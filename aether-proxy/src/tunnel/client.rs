//! WebSocket tunnel client: connect, authenticate, and run the tunnel.

use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use tokio::sync::watch;
use tokio_tungstenite::tungstenite::client::IntoClientRequest;
use tokio_tungstenite::tungstenite::http;
use tracing::{debug, info};

use crate::state::{AppState, ServerContext};

use super::{dispatcher, heartbeat, writer};

/// Outcome of a tunnel session.
pub enum TunnelOutcome {
    /// Graceful shutdown requested by the local process.
    Shutdown,
    /// Remote side disconnected or connection lost — should reconnect.
    Disconnected,
}

/// Connect to Aether's WebSocket tunnel endpoint and run until disconnected.
pub async fn connect_and_run(
    state: &Arc<AppState>,
    server: &Arc<ServerContext>,
    shutdown: &mut watch::Receiver<bool>,
) -> Result<TunnelOutcome, anyhow::Error> {
    let ws_url = build_tunnel_url(server);
    info!(url = %ws_url, "connecting tunnel");

    // Build WebSocket request with auth headers
    let mut request = ws_url.into_client_request()?;
    let headers = request.headers_mut();
    headers.insert(
        "Authorization",
        http::HeaderValue::from_str(&format!("Bearer {}", server.management_token))?,
    );
    let node_id = server.node_id.read().unwrap().clone();
    headers.insert("X-Node-Id", http::HeaderValue::from_str(&node_id)?);
    headers.insert(
        "X-Node-Name",
        http::HeaderValue::from_str(&server.node_name)?,
    );

    // Connect
    let (ws_stream, _response) = tokio_tungstenite::connect_async(request).await?;
    info!("tunnel connected");

    // Reset reconnect counter on success
    server.reconnect_attempts.store(0, Ordering::Relaxed);

    // Split into read/write halves
    let (ws_sink, ws_read) = futures_util::StreamExt::split(ws_stream);

    // Spawn writer task
    let (frame_tx, writer_handle) = writer::spawn_writer(ws_sink);

    // Spawn heartbeat task
    let hb_handle = heartbeat::spawn(
        Arc::clone(&state.config),
        Arc::clone(server),
        frame_tx.clone(),
        shutdown.clone(),
    );

    // Run dispatcher (blocks until disconnect or shutdown)
    let state_clone = Arc::clone(state);
    let server_clone = Arc::clone(server);
    let outcome = tokio::select! {
        result = dispatcher::run(state_clone, server_clone, ws_read, frame_tx.clone(), hb_handle) => {
            match result {
                Ok(()) => TunnelOutcome::Disconnected,
                Err(e) => return Err(e),
            }
        }
        _ = shutdown.changed() => {
            debug!("shutdown during tunnel dispatch");
            TunnelOutcome::Shutdown
        }
    };

    // Drop our sender; the writer will exit once all stream handler clones
    // are also dropped (i.e. after they finish their in-flight work).
    drop(frame_tx);

    // Wait for the writer task to finish with a generous timeout — the
    // dispatcher already waits up to 30s for stream handlers, so 35s here
    // covers that plus a small margin.
    let _ = tokio::time::timeout(Duration::from_secs(35), writer_handle).await;

    info!("tunnel disconnected");
    Ok(outcome)
}

/// Calculate next reconnect delay with exponential backoff + jitter.
pub fn next_reconnect_delay(state: &Arc<AppState>, server: &Arc<ServerContext>) -> Duration {
    let attempt = server.reconnect_attempts.fetch_add(1, Ordering::Relaxed);
    let base_ms = state.config.tunnel_reconnect_base_ms;
    let max_ms = state.config.tunnel_reconnect_max_ms;

    let delay_ms = base_ms.saturating_mul(1u64 << attempt.min(10)).min(max_ms);

    let jitter = (delay_ms / 4).max(1);
    let jitter_ms = rand_u64() % jitter;

    Duration::from_millis(delay_ms + jitter_ms)
}

fn build_tunnel_url(server: &ServerContext) -> String {
    let base = server.aether_url.trim_end_matches('/');
    let ws_base = if base.starts_with("https://") {
        base.replacen("https://", "wss://", 1)
    } else if base.starts_with("http://") {
        base.replacen("http://", "ws://", 1)
    } else {
        format!("wss://{}", base)
    };
    format!("{}/api/internal/proxy-tunnel", ws_base)
}

/// Simple pseudo-random u64 (no external crate needed).
fn rand_u64() -> u64 {
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::time::{SystemTime, UNIX_EPOCH};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let seed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos() as u64;
    let cnt = COUNTER.fetch_add(1, Ordering::Relaxed);
    let mut x = seed ^ cnt;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    x
}
