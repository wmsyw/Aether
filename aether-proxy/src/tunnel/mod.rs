pub mod client;
pub mod dispatcher;
pub mod heartbeat;
pub mod protocol;
pub mod stream_handler;
pub mod writer;

use std::sync::Arc;
use std::time::Duration;

use tokio::sync::watch;
use tracing::{error, info};

use crate::state::{AppState, ServerContext};

/// Fixed reconnect delay -- short enough for fast recovery, long enough to
/// avoid CPU spin when the network is completely down.
const RECONNECT_DELAY: Duration = Duration::from_secs(1);

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

    loop {
        match client::connect_and_run(state, server, conn_idx, &mut shutdown).await {
            Ok(client::TunnelOutcome::Shutdown) => {
                info!(server = %server.server_label, conn = conn_idx, "tunnel shut down gracefully");
                return;
            }
            Ok(client::TunnelOutcome::Disconnected) => {
                info!(server = %server.server_label, conn = conn_idx, "tunnel disconnected, reconnecting");
            }
            Err(e) => {
                error!(server = %server.server_label, conn = conn_idx, error = %e, "tunnel connection error, reconnecting");
            }
        }

        if *shutdown.borrow() {
            info!(server = %server.server_label, conn = conn_idx, "shutdown requested, not reconnecting");
            return;
        }

        tokio::select! {
            _ = tokio::time::sleep(RECONNECT_DELAY) => {}
            _ = shutdown.changed() => {
                info!(server = %server.server_label, conn = conn_idx, "shutdown requested during reconnect wait");
                return;
            }
        }
    }
}
