//! Frame dispatcher: reads incoming WebSocket frames and routes them.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use bytes::Bytes;
use futures_util::StreamExt;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tokio_tungstenite::tungstenite::Message;
use tracing::{debug, error, warn};

use crate::state::{AppState, ServerContext};

use super::heartbeat::HeartbeatHandle;
use super::protocol::{Frame, MsgType, RequestMeta};
use super::stream_handler;
use super::writer::FrameSender;

/// Run the dispatcher loop, reading from the WebSocket stream.
pub async fn run<S>(
    state: Arc<AppState>,
    server: Arc<ServerContext>,
    mut ws_stream: S,
    frame_tx: FrameSender,
    heartbeat: HeartbeatHandle,
) -> Result<(), anyhow::Error>
where
    S: StreamExt<Item = Result<Message, tokio_tungstenite::tungstenite::Error>>
        + Unpin
        + Send
        + 'static,
{
    // Active streams: stream_id -> body sender
    let mut streams: HashMap<u32, mpsc::Sender<Frame>> = HashMap::new();
    // Track spawned stream handlers so we can wait for them on shutdown
    let mut handler_handles: Vec<JoinHandle<()>> = Vec::new();
    let max_streams = state.config.tunnel_max_streams.unwrap_or(128) as usize;

    let read_err = loop {
        let msg_result = match ws_stream.next().await {
            Some(r) => r,
            None => break None, // stream ended
        };

        let msg = match msg_result {
            Ok(m) => m,
            Err(e) => {
                error!(error = %e, "WebSocket read error");
                break Some(e);
            }
        };

        let data = match msg {
            Message::Binary(data) => Bytes::from(data),
            Message::Ping(_) => continue,
            Message::Pong(_) => continue,
            Message::Close(_) => {
                debug!("received WebSocket close");
                break None;
            }
            _ => continue,
        };

        let frame = match Frame::decode(data) {
            Ok(f) => f,
            Err(e) => {
                warn!(error = %e, "failed to decode frame");
                continue;
            }
        };

        match frame.msg_type {
            MsgType::RequestHeaders => {
                // Parse request metadata
                let meta: RequestMeta = match serde_json::from_slice(&frame.payload) {
                    Ok(m) => m,
                    Err(e) => {
                        warn!(stream_id = frame.stream_id, error = %e, "invalid request metadata");
                        let _ = frame_tx
                            .send(Frame::new(
                                frame.stream_id,
                                MsgType::StreamError,
                                0,
                                Bytes::from(format!("invalid request metadata: {e}")),
                            ))
                            .await;
                        continue;
                    }
                };

                if streams.len() >= max_streams {
                    warn!(
                        stream_id = frame.stream_id,
                        "max concurrent streams reached"
                    );
                    let _ = frame_tx
                        .send(Frame::new(
                            frame.stream_id,
                            MsgType::StreamError,
                            0,
                            Bytes::from("max concurrent streams reached"),
                        ))
                        .await;
                    continue;
                }

                // Create body channel and spawn handler
                let (body_tx, body_rx) = mpsc::channel::<Frame>(16);
                streams.insert(frame.stream_id, body_tx);

                let state_clone = Arc::clone(&state);
                let server_clone = Arc::clone(&server);
                let tx_clone = frame_tx.clone();
                let sid = frame.stream_id;
                let handle = tokio::spawn(async move {
                    stream_handler::handle_stream(
                        state_clone,
                        server_clone,
                        sid,
                        meta,
                        body_rx,
                        tx_clone,
                    )
                    .await;
                });
                handler_handles.push(handle);

                debug!(stream_id = frame.stream_id, "new stream started");
            }

            MsgType::RequestBody => {
                if let Some(tx) = streams.get(&frame.stream_id) {
                    let is_end = frame.is_end_stream();
                    let sid = frame.stream_id;
                    let _ = tx.send(frame).await;
                    if is_end {
                        streams.remove(&sid);
                    }
                }
            }

            MsgType::StreamEnd | MsgType::StreamError => {
                // Client-side cancellation or end
                streams.remove(&frame.stream_id);
            }

            MsgType::Ping => {
                let _ = frame_tx
                    .send(Frame::control(MsgType::Pong, frame.payload))
                    .await;
            }

            MsgType::HeartbeatAck => {
                heartbeat.on_ack(frame.payload).await;
            }

            MsgType::GoAway => {
                debug!("received GOAWAY");
                break None;
            }

            _ => {
                debug!(msg_type = ?frame.msg_type, "ignoring unexpected frame type");
            }
        }

        // Periodically clean up finished handles to avoid unbounded growth
        if handler_handles.len() > max_streams {
            handler_handles.retain(|h| !h.is_finished());
        }
    };

    // Drop body senders so stream handlers waiting on body_rx will unblock
    streams.clear();

    // Wait for active stream handlers to finish so their frame_tx clones
    // are dropped before the writer closes the sink.
    drain_handlers(handler_handles).await;

    match read_err {
        Some(e) => Err(e.into()),
        None => Ok(()),
    }
}

/// Wait for all active stream handlers to finish (with a timeout).
async fn drain_handlers(handles: Vec<JoinHandle<()>>) {
    if handles.is_empty() {
        return;
    }
    let count = handles.len();
    debug!(count, "waiting for active stream handlers to finish");
    let _ = tokio::time::timeout(Duration::from_secs(30), async {
        for h in handles {
            let _ = h.await;
        }
    })
    .await;
}
