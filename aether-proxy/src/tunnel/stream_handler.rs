//! Per-stream request handler.
//!
//! Receives request frames, executes the upstream HTTP request,
//! and sends response frames back through the writer channel.

use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::{Duration, Instant};

use bytes::Bytes;
use futures_util::StreamExt;
use tokio::sync::mpsc;
use tracing::{debug, warn};

use crate::state::{AppState, ServerContext};
use crate::target_filter;

use super::protocol::{flags, Frame, MsgType, RequestMeta, ResponseMeta};
use super::writer::FrameSender;

/// Maximum response body chunk size per frame (32 KB).
const MAX_CHUNK_SIZE: usize = 32 * 1024;

/// Handle a single stream: receive body, execute upstream, send response.
pub async fn handle_stream(
    state: Arc<AppState>,
    server: Arc<ServerContext>,
    stream_id: u32,
    meta: RequestMeta,
    mut body_rx: mpsc::Receiver<Frame>,
    frame_tx: FrameSender,
) {
    let start = Instant::now();
    server.active_connections.fetch_add(1, Ordering::Relaxed);

    handle_stream_inner(&state, &server, stream_id, meta, &mut body_rx, &frame_tx).await;

    server.active_connections.fetch_sub(1, Ordering::Relaxed);
    server.metrics.record_request(start.elapsed());
}

async fn handle_stream_inner(
    state: &AppState,
    server: &ServerContext,
    stream_id: u32,
    meta: RequestMeta,
    body_rx: &mut mpsc::Receiver<Frame>,
    frame_tx: &FrameSender,
) {
    // Collect request body
    let mut body_parts: Vec<Bytes> = Vec::new();
    let mut body_done = false;

    // Drain body frames
    while !body_done {
        match body_rx.recv().await {
            Some(frame) => {
                if frame.msg_type == MsgType::RequestBody {
                    let payload = if frame.is_gzip() {
                        match decompress_gzip(&frame.payload) {
                            Ok(d) => d,
                            Err(e) => {
                                send_error(
                                    frame_tx,
                                    stream_id,
                                    &format!("gzip decompress failed: {e}"),
                                )
                                .await;
                                return;
                            }
                        }
                    } else {
                        frame.payload.clone()
                    };
                    if !payload.is_empty() {
                        body_parts.push(payload);
                    }
                    if frame.is_end_stream() {
                        body_done = true;
                    }
                } else if frame.msg_type == MsgType::StreamEnd
                    || frame.msg_type == MsgType::StreamError
                {
                    body_done = true;
                    if frame.msg_type == MsgType::StreamError {
                        return; // Client cancelled
                    }
                }
            }
            None => return, // Channel closed
        }
    }

    let body: Bytes = if body_parts.is_empty() {
        Bytes::new()
    } else if body_parts.len() == 1 {
        body_parts.into_iter().next().unwrap()
    } else {
        let total: usize = body_parts.iter().map(|b| b.len()).sum();
        let mut combined = Vec::with_capacity(total);
        for part in &body_parts {
            combined.extend_from_slice(part);
        }
        Bytes::from(combined)
    };

    // Validate target
    let target_url = match url::Url::parse(&meta.url) {
        Ok(u) => u,
        Err(e) => {
            send_error(frame_tx, stream_id, &format!("invalid URL: {e}")).await;
            return;
        }
    };

    let host = match target_url.host_str() {
        Some(h) => h.to_string(),
        None => {
            send_error(frame_tx, stream_id, "missing host in URL").await;
            return;
        }
    };
    let port = target_url.port_or_known_default().unwrap_or(443);

    // DNS + target validation (dns_cache is populated as a side effect)
    let dns_start = Instant::now();
    {
        let allowed_ports = server.dynamic.read().unwrap().allowed_ports.clone();
        if let Err(e) =
            target_filter::validate_target(&host, port, &allowed_ports, &state.dns_cache).await
        {
            send_error(frame_tx, stream_id, &format!("target blocked: {e}")).await;
            return;
        }
    }
    let dns_ms = dns_start.elapsed().as_millis() as u64;

    // Execute upstream request
    let client = &state.reqwest_client;
    let timeout = Duration::from_secs(meta.timeout);

    let method: reqwest::Method = meta.method.parse().unwrap_or(reqwest::Method::GET);
    let mut req = client.request(method, &meta.url);
    for (k, v) in &meta.headers {
        req = req.header(k.as_str(), v.as_str());
    }
    let body_size = body.len();
    if !body.is_empty() {
        req = req.body(body);
    }
    req = req.timeout(timeout);

    let upstream_start = Instant::now();
    let response = match req.send().await {
        Ok(r) => r,
        Err(e) => {
            let msg = if e.is_timeout() {
                "upstream timeout".to_string()
            } else if e.is_connect() {
                format!("upstream connect error: {e}")
            } else {
                format!("upstream error: {e}")
            };
            send_error(frame_tx, stream_id, &msg).await;
            return;
        }
    };

    // Send RESPONSE_HEADERS
    let status = response.status().as_u16();
    let ttfb_ms = upstream_start.elapsed().as_millis() as u64;
    let mut resp_headers: Vec<(String, String)> = Vec::new();
    for (k, v) in response.headers() {
        if let Ok(vs) = v.to_str() {
            resp_headers.push((k.as_str().to_string(), vs.to_string()));
        }
    }
    // Inject proxy timing (same format as delegate mode)
    let timing = serde_json::json!({
        "dns_ms": dns_ms,
        "ttfb_ms": ttfb_ms,
        "upstream_ms": ttfb_ms,
        "upstream_processing_ms": ttfb_ms.saturating_sub(dns_ms),
        "body_size": body_size,
        "mode": "tunnel",
    });
    resp_headers.push(("x-proxy-timing".to_string(), timing.to_string()));
    let resp_meta = ResponseMeta {
        status,
        headers: resp_headers,
    };
    let meta_json = serde_json::to_vec(&resp_meta).unwrap_or_default();
    let _ = frame_tx
        .send(Frame::new(
            stream_id,
            MsgType::ResponseHeaders,
            0,
            meta_json,
        ))
        .await;

    // Stream response body
    let mut stream = response.bytes_stream();
    while let Some(chunk_result) = stream.next().await {
        match chunk_result {
            Ok(chunk) => {
                if chunk.len() <= MAX_CHUNK_SIZE {
                    // 大多数 chunk 无需分割，直接零拷贝发送
                    let _ = frame_tx
                        .send(Frame::new(stream_id, MsgType::ResponseBody, 0, chunk))
                        .await;
                } else {
                    // 超大 chunk 按 MAX_CHUNK_SIZE 分割（使用 Bytes::slice 避免拷贝）
                    let mut offset = 0;
                    while offset < chunk.len() {
                        let end = (offset + MAX_CHUNK_SIZE).min(chunk.len());
                        let slice = chunk.slice(offset..end);
                        let _ = frame_tx
                            .send(Frame::new(stream_id, MsgType::ResponseBody, 0, slice))
                            .await;
                        offset = end;
                    }
                }
            }
            Err(e) => {
                warn!(stream_id, error = %e, "upstream body read error");
                send_error(frame_tx, stream_id, &format!("body read error: {e}")).await;
                return;
            }
        }
    }

    // Send STREAM_END
    let _ = frame_tx
        .send(Frame::new(
            stream_id,
            MsgType::StreamEnd,
            flags::END_STREAM,
            Bytes::new(),
        ))
        .await;

    debug!(stream_id, status, "stream completed");
}

async fn send_error(tx: &FrameSender, stream_id: u32, msg: &str) {
    let _ = tx
        .send(Frame::new(
            stream_id,
            MsgType::StreamError,
            0,
            Bytes::from(msg.to_string()),
        ))
        .await;
}

fn decompress_gzip(data: &[u8]) -> Result<Bytes, std::io::Error> {
    use flate2::read::GzDecoder;
    use std::io::Read;
    let mut decoder = GzDecoder::new(data);
    let mut buf = Vec::new();
    decoder.read_to_end(&mut buf)?;
    Ok(Bytes::from(buf))
}
