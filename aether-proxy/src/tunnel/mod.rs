pub mod client;
pub mod dispatcher;
pub mod heartbeat;
pub mod protocol;
pub mod stream_handler;
pub mod writer;

use std::sync::Arc;

use tokio::sync::watch;
use tracing::{error, info};

use crate::state::{AppState, ServerContext};

/// Run the tunnel mode main loop (connect, dispatch, reconnect).
pub async fn run(
    state: &Arc<AppState>,
    server: &Arc<ServerContext>,
    mut shutdown: watch::Receiver<bool>,
) {
    info!(server = %server.server_label, "starting tunnel");

    loop {
        match client::connect_and_run(state, server, &mut shutdown).await {
            Ok(client::TunnelOutcome::Shutdown) => {
                info!(server = %server.server_label, "tunnel shut down gracefully");
                return;
            }
            Ok(client::TunnelOutcome::Disconnected) => {
                info!(server = %server.server_label, "tunnel disconnected, will reconnect");
            }
            Err(e) => {
                error!(server = %server.server_label, error = %e, "tunnel connection lost");
            }
        }

        if *shutdown.borrow() {
            info!(server = %server.server_label, "shutdown requested, not reconnecting");
            return;
        }

        let delay = client::next_reconnect_delay(state, server);
        info!(server = %server.server_label, delay_ms = delay.as_millis(), "reconnecting tunnel");

        tokio::select! {
            _ = tokio::time::sleep(delay) => {}
            _ = shutdown.changed() => {
                info!(server = %server.server_label, "shutdown requested during reconnect wait");
                return;
            }
        }
    }
}
