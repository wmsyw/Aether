//! Dedicated WebSocket writer task.
//!
//! All frame writes go through an mpsc channel to a single writer task,
//! avoiding contention on the WebSocket sink.

use futures_util::SinkExt;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tokio_tungstenite::tungstenite::Message;
use tracing::{debug, error};

use super::protocol::Frame;

/// Sender half — cloned by stream handlers and heartbeat.
pub type FrameSender = mpsc::Sender<Frame>;

/// Spawn the writer task. Returns the sender and a JoinHandle for cleanup.
pub fn spawn_writer<S>(mut sink: S) -> (FrameSender, JoinHandle<()>)
where
    S: SinkExt<Message, Error = tokio_tungstenite::tungstenite::Error> + Unpin + Send + 'static,
{
    let (tx, mut rx) = mpsc::channel::<Frame>(256);

    let handle = tokio::spawn(async move {
        while let Some(frame) = rx.recv().await {
            let data = frame.encode();
            if let Err(e) = sink.send(Message::Binary(data.into())).await {
                error!(error = %e, "failed to write frame to WebSocket");
                break;
            }
        }
        debug!("writer task exiting");
        let _ = sink.close().await;
    });

    (tx, handle)
}
