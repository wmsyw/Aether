//! Tunnel heartbeat: sends metrics over the tunnel, processes ACKs.

use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use bytes::Bytes;
use tokio::sync::watch;
use tracing::{debug, warn};

use crate::config::Config;
use crate::registration::client::RemoteConfig;
use crate::runtime;
use crate::state::ServerContext;

use super::protocol::{Frame, MsgType};
use super::writer::FrameSender;

/// Handle for the dispatcher to forward HeartbeatAck frames.
#[derive(Clone)]
pub struct HeartbeatHandle {
    ack_tx: tokio::sync::mpsc::Sender<Bytes>,
}

impl HeartbeatHandle {
    pub async fn on_ack(&self, payload: Bytes) {
        let _ = self.ack_tx.send(payload).await;
    }
}

/// Create a no-op heartbeat handle that silently discards ACKs.
/// Used for non-primary tunnel connections (conn_idx > 0) to avoid
/// resetting shared atomic metrics via `swap(0)`.
pub fn spawn_noop() -> HeartbeatHandle {
    let (ack_tx, _) = tokio::sync::mpsc::channel::<Bytes>(1);
    // receiver is immediately dropped; on_ack() calls will silently fail
    HeartbeatHandle { ack_tx }
}

/// Spawn the heartbeat task. Returns a handle for forwarding ACKs.
pub fn spawn(
    config: Arc<Config>,
    server: Arc<ServerContext>,
    frame_tx: FrameSender,
    mut shutdown: watch::Receiver<bool>,
) -> HeartbeatHandle {
    let (ack_tx, mut ack_rx) = tokio::sync::mpsc::channel::<Bytes>(4);
    let interval = Duration::from_secs(config.heartbeat_interval);

    tokio::spawn(async move {
        let mut ticker = tokio::time::interval(interval);
        ticker.tick().await; // Skip first immediate tick

        loop {
            tokio::select! {
                _ = ticker.tick() => {
                    let payload = build_heartbeat_payload(&server);
                    let frame = Frame::control(MsgType::HeartbeatData, payload);
                    if frame_tx.send(frame).await.is_err() {
                        break; // Writer closed
                    }
                    debug!("sent heartbeat data");
                }
                Some(ack_payload) = ack_rx.recv() => {
                    handle_ack(&server, &ack_payload);
                }
                _ = shutdown.changed() => {
                    debug!("heartbeat task shutting down");
                    break;
                }
            }
        }
    });

    HeartbeatHandle { ack_tx }
}

fn build_heartbeat_payload(server: &ServerContext) -> Bytes {
    let node_id = server.node_id.read().unwrap().clone();

    let interval_requests = server.metrics.total_requests.swap(0, Ordering::Relaxed);
    let interval_latency_ns = server.metrics.total_latency_ns.swap(0, Ordering::Relaxed);
    let avg_latency_ms = if interval_requests > 0 {
        Some(interval_latency_ns as f64 / interval_requests as f64 / 1_000_000.0)
    } else {
        None
    };

    let payload = serde_json::json!({
        "node_id": node_id,
        "active_connections": server.active_connections.load(Ordering::Relaxed),
        "total_requests": interval_requests,
        "avg_latency_ms": avg_latency_ms,
    });

    Bytes::from(serde_json::to_vec(&payload).unwrap_or_default())
}

fn handle_ack(server: &ServerContext, payload: &[u8]) {
    if payload.is_empty() {
        return;
    }

    #[derive(serde::Deserialize)]
    struct AckPayload {
        #[serde(default)]
        remote_config: Option<RemoteConfig>,
        #[serde(default)]
        config_version: u64,
    }

    match serde_json::from_slice::<AckPayload>(payload) {
        Ok(ack) => {
            if let Some(ref rc) = ack.remote_config {
                runtime::apply_remote_config(&server.dynamic, rc, ack.config_version);
            }
        }
        Err(e) => {
            warn!(error = %e, "failed to parse heartbeat ACK");
        }
    }
}
