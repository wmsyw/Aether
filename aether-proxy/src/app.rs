//! Application lifecycle: initialization, task orchestration, and shutdown.

use std::sync::atomic::{AtomicU32, AtomicU64};
use std::sync::{Arc, RwLock};
use std::time::Duration;

use tokio::signal;
use tokio::sync::watch;
use tracing::{error, info, warn};

use crate::config::{Config, ServerEntry};
use crate::net;
use crate::registration::client::AetherClient;
use crate::runtime::{self, DynamicConfig};
use crate::state::{AppState, ProxyMetrics, ServerContext};
use crate::{hardware, target_filter, tunnel};

/// Run the full application lifecycle after config has been parsed.
pub async fn run(mut config: Config, servers: Vec<ServerEntry>) -> anyhow::Result<()> {
    init_tracing(&config);

    info!(
        version = env!("CARGO_PKG_VERSION"),
        node_name = %config.node_name,
        server_count = servers.len(),
        "aether-proxy starting (tunnel mode)"
    );

    // Resolve public IP (best-effort for region info)
    let public_ip = match &config.public_ip {
        Some(ip) => ip.clone(),
        None => net::detect_public_ip()
            .await
            .unwrap_or_else(|_| "0.0.0.0".to_string()),
    };

    // Auto-detect region if not configured
    if config.node_region.is_none() {
        if let Some(region) = net::detect_region(&public_ip).await {
            config.node_region = Some(region);
        }
    }

    // Collect hardware info (once at startup, sent during registration)
    let hw_info = hardware::collect();

    // Auto-detect tunnel_max_streams from hardware if not explicitly set
    if config.tunnel_max_streams.is_none() {
        let auto = (hw_info.estimated_max_concurrency / 10).clamp(64, 1024) as u32;
        config.tunnel_max_streams = Some(auto);
        info!(
            tunnel_max_streams = auto,
            "auto-detected tunnel_max_streams from hardware"
        );
    }

    info!(
        max_concurrency = hw_info.estimated_max_concurrency,
        "hardware info collected"
    );

    let dns_cache = Arc::new(target_filter::DnsCache::new(
        Duration::from_secs(config.dns_cache_ttl_secs),
        config.dns_cache_capacity,
    ));

    // Build reqwest client for tunnel upstream requests (shared).
    let reqwest_client = reqwest::Client::builder()
        .pool_max_idle_per_host(config.upstream_pool_max_idle_per_host)
        .pool_idle_timeout(Duration::from_secs(config.upstream_pool_idle_timeout_secs))
        .connect_timeout(Duration::from_secs(config.upstream_connect_timeout_secs))
        .tcp_nodelay(config.upstream_tcp_nodelay)
        .build()
        .expect("failed to build reqwest client");

    // Register with each Aether server and build per-server contexts
    let mut server_contexts: Vec<Arc<ServerContext>> = Vec::new();
    for (i, entry) in servers.iter().enumerate() {
        let label = if servers.len() == 1 {
            "server".to_string()
        } else {
            format!("server-{}", i)
        };
        let node_name = entry
            .node_name
            .clone()
            .unwrap_or_else(|| config.node_name.clone());
        let client = Arc::new(AetherClient::new(
            &config,
            &entry.aether_url,
            &entry.management_token,
        ));
        match client
            .register(&config, &node_name, &public_ip, Some(&hw_info))
            .await
        {
            Ok(node_id) => {
                info!(server = %label, node_id = %node_id, url = %entry.aether_url, node_name = %node_name, "registered");
                server_contexts.push(Arc::new(ServerContext {
                    server_label: label,
                    aether_url: entry.aether_url.clone(),
                    management_token: entry.management_token.clone(),
                    node_name,
                    node_id: Arc::new(RwLock::new(node_id)),
                    aether_client: client,
                    dynamic: Arc::new(RwLock::new(DynamicConfig::from_config(&config))),
                    active_connections: Arc::new(AtomicU64::new(0)),
                    metrics: Arc::new(ProxyMetrics::new()),
                    reconnect_attempts: AtomicU32::new(0),
                }));
            }
            Err(e) => {
                warn!(
                    server = %label,
                    url = %entry.aether_url,
                    error = %e,
                    "registration failed, skipping server"
                );
            }
        }
    }

    if server_contexts.is_empty() {
        anyhow::bail!("no servers registered successfully");
    }

    // Build shared application state
    let state = Arc::new(AppState {
        config: Arc::new(config),
        dns_cache,
        reqwest_client,
    });

    // Shutdown signal channel
    let (shutdown_tx, shutdown_rx) = watch::channel(false);

    info!(
        active_servers = server_contexts.len(),
        "running in tunnel mode"
    );

    // Spawn one tunnel task per server
    let mut tunnel_handles = Vec::new();
    for server in &server_contexts {
        let s = Arc::clone(&state);
        let srv = Arc::clone(server);
        let rx = shutdown_rx.clone();
        tunnel_handles.push(tokio::spawn(async move {
            tunnel::run(&s, &srv, rx).await;
        }));
    }

    // Wait for shutdown signal
    wait_for_shutdown().await;
    info!("shutdown signal received, cleaning up...");
    let _ = shutdown_tx.send(true);

    // Graceful unregister from all servers
    for server in &server_contexts {
        let node_id = server.node_id.read().unwrap().clone();
        if let Err(e) = server.aether_client.unregister(&node_id).await {
            error!(
                server = %server.server_label,
                error = %e,
                "unregister failed during shutdown"
            );
        }
    }

    // Wait for all tunnel tasks
    for h in tunnel_handles {
        let _ = h.await;
    }

    info!("aether-proxy stopped");
    Ok(())
}

fn init_tracing(config: &Config) {
    use tracing_subscriber::prelude::*;
    use tracing_subscriber::{reload, EnvFilter};

    let filter = EnvFilter::try_new(&config.log_level).unwrap_or_else(|_| EnvFilter::new("info"));

    let (filter_layer, reload_handle) = reload::Layer::new(filter);

    runtime::set_log_reloader(Box::new(move |level: &str| {
        if let Ok(new_filter) = EnvFilter::try_new(level) {
            let _ = reload_handle.modify(|f| *f = new_filter);
        }
    }));

    if config.log_json {
        tracing_subscriber::registry()
            .with(filter_layer)
            .with(tracing_subscriber::fmt::layer().json())
            .init();
    } else {
        tracing_subscriber::registry()
            .with(filter_layer)
            .with(tracing_subscriber::fmt::layer())
            .init();
    }
}

async fn wait_for_shutdown() {
    let ctrl_c = async {
        signal::ctrl_c()
            .await
            .expect("failed to install Ctrl+C handler");
    };

    #[cfg(unix)]
    let terminate = async {
        signal::unix::signal(signal::unix::SignalKind::terminate())
            .expect("failed to install SIGTERM handler")
            .recv()
            .await;
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }
}
