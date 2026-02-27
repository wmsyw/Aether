pub mod client;
pub mod dispatcher;
pub mod heartbeat;
pub mod protocol;
pub mod stream_handler;
pub mod writer;

use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;
use std::time::Duration;

use tokio::sync::watch;
use tracing::{error, info};

use crate::state::{AppState, ServerContext};

/// Minimum connection duration (seconds) to consider a session "stable".
/// If a connection lasts shorter than this, the backoff counter is NOT reset,
/// preventing rapid reconnect loops on persistently bad networks.
const MIN_STABLE_DURATION: Duration = Duration::from_secs(30);

/// Run the tunnel mode main loop (connect, dispatch, reconnect).
///
/// `conn_idx` identifies which connection in the pool this is (0-based).
/// Only connection 0 sends heartbeats to avoid resetting shared metrics.
pub async fn run(
    state: &Arc<AppState>,
    server: &Arc<ServerContext>,
    conn_idx: usize,
    mut shutdown: watch::Receiver<bool>,
) {
    info!(server = %server.server_label, conn = conn_idx, "starting tunnel");

    // Per-connection reconnect counter (avoids N connections interfering
    // with each other's backoff via the shared ServerContext field).
    let reconnect_attempts = AtomicU32::new(0);

    loop {
        let connect_start = tokio::time::Instant::now();

        match client::connect_and_run(state, server, conn_idx, &mut shutdown).await {
            Ok(client::TunnelOutcome::Shutdown) => {
                info!(server = %server.server_label, conn = conn_idx, "tunnel shut down gracefully");
                return;
            }
            Ok(client::TunnelOutcome::Disconnected) => {
                let duration = connect_start.elapsed();
                if duration >= MIN_STABLE_DURATION {
                    // Stable session -- reset backoff for quick reconnect
                    reconnect_attempts.store(0, Ordering::Release);
                    info!(
                        server = %server.server_label,
                        conn = conn_idx,
                        duration_secs = duration.as_secs(),
                        "tunnel disconnected after stable session"
                    );
                } else {
                    // Short-lived session -- keep backoff increasing
                    info!(
                        server = %server.server_label,
                        conn = conn_idx,
                        duration_secs = duration.as_secs(),
                        "tunnel disconnected quickly, increasing backoff"
                    );
                }
            }
            Err(e) => {
                // Connection failed -- keep backoff increasing
                error!(server = %server.server_label, conn = conn_idx, error = %e, "tunnel connection lost");
            }
        }

        if *shutdown.borrow() {
            info!(server = %server.server_label, conn = conn_idx, "shutdown requested, not reconnecting");
            return;
        }

        let delay = client::next_reconnect_delay(state, &reconnect_attempts);
        info!(server = %server.server_label, conn = conn_idx, delay_ms = delay.as_millis(), "reconnecting tunnel");

        tokio::select! {
            _ = tokio::time::sleep(delay) => {}
            _ = shutdown.changed() => {
                info!(server = %server.server_label, conn = conn_idx, "shutdown requested during reconnect wait");
                return;
            }
        }
    }
}
