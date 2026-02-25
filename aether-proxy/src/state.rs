//! Shared application state passed to all subsystems.

use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};
use std::sync::{Arc, RwLock};
use std::time::Duration;

use crate::config::Config;
use crate::registration::client::AetherClient;
use crate::runtime::SharedDynamicConfig;
use crate::target_filter::DnsCache;

/// Central application state shared across all servers/tunnels.
pub struct AppState {
    pub config: Arc<Config>,
    /// DNS cache for upstream target resolution (shared).
    pub dns_cache: Arc<DnsCache>,
    /// Reqwest client for tunnel upstream requests (shared).
    pub reqwest_client: reqwest::Client,
}

/// Per-server state: one instance per Aether server connection.
pub struct ServerContext {
    /// Human-readable label for logging (e.g. "server-0").
    pub server_label: String,
    /// Aether server URL for this connection.
    pub aether_url: String,
    /// Management token for this server.
    pub management_token: String,
    /// Resolved node name (per-server override or global fallback).
    pub node_name: String,
    /// Node ID assigned by this Aether server.
    pub node_id: Arc<RwLock<String>>,
    /// API client for this server.
    pub aether_client: Arc<AetherClient>,
    /// Dynamic config from this server's heartbeat ACKs.
    pub dynamic: SharedDynamicConfig,
    /// Per-server active connection count.
    pub active_connections: Arc<AtomicU64>,
    /// Per-server request/latency metrics.
    pub metrics: Arc<ProxyMetrics>,
    /// Reconnect attempt counter (reset on successful connection).
    pub reconnect_attempts: AtomicU32,
}

/// Aggregate metrics for reporting to Aether.
pub struct ProxyMetrics {
    pub total_requests: AtomicU64,
    pub total_latency_ns: AtomicU64,
}

impl ProxyMetrics {
    pub fn new() -> Self {
        Self {
            total_requests: AtomicU64::new(0),
            total_latency_ns: AtomicU64::new(0),
        }
    }

    pub fn record_request(&self, elapsed: Duration) {
        let nanos = u64::try_from(elapsed.as_nanos()).unwrap_or(u64::MAX);
        self.total_requests.fetch_add(1, Ordering::Relaxed);
        self.total_latency_ns.fetch_add(nanos, Ordering::Relaxed);
    }
}
