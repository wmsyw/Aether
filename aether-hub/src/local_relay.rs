use std::io;
use std::net::SocketAddr;
use std::time::Duration;

use async_stream::stream;
use axum::body::{Body, Bytes};
use axum::extract::{ConnectInfo, Path, State};
use axum::http::{HeaderMap, HeaderName, HeaderValue, Response, StatusCode};
use axum::response::IntoResponse;
use tracing::warn;

use crate::hub::LocalBodyEvent;
use crate::protocol;
use crate::AppState;

pub const TUNNEL_ERROR_HEADER: &str = "x-aether-tunnel-error";

struct StreamGuard {
    hub: std::sync::Arc<crate::hub::HubRouter>,
    stream_id: u64,
    finished: bool,
}

impl Drop for StreamGuard {
    fn drop(&mut self) {
        if !self.finished {
            self.hub
                .cancel_local_stream(self.stream_id, "local relay client dropped");
        }
    }
}

pub async fn relay_request(
    Path(node_id): Path<String>,
    State(state): State<AppState>,
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
    body: Bytes,
) -> impl IntoResponse {
    if !addr.ip().is_loopback() {
        return tunnel_error_response(
            StatusCode::FORBIDDEN,
            "forbidden",
            "local relay only accepts loopback requests",
        );
    }

    let (meta, request_body) = match decode_envelope(body) {
        Ok(value) => value,
        Err(error) => {
            return tunnel_error_response(StatusCode::BAD_REQUEST, "bad_request", &error);
        }
    };

    let stream = match state.hub.open_local_stream(&node_id, &meta, request_body) {
        Ok(stream) => stream,
        Err(error) => {
            return tunnel_error_response(StatusCode::SERVICE_UNAVAILABLE, "connect", &error);
        }
    };
    let request_guard = StreamGuard {
        hub: state.hub.clone(),
        stream_id: stream.id,
        finished: false,
    };

    let wait_timeout = Duration::from_secs(meta.timeout.clamp(5, 300));
    let response_head = match stream.wait_headers(wait_timeout).await {
        Ok(response) => response,
        Err(error) => {
            state.hub.cancel_local_stream(stream.id, &error);
            return tunnel_error_response(StatusCode::GATEWAY_TIMEOUT, "timeout", &error);
        }
    };

    let Some(mut body_rx) = stream.take_body_receiver() else {
        state
            .hub
            .cancel_local_stream(stream.id, "missing relay response body receiver");
        return tunnel_error_response(
            StatusCode::BAD_GATEWAY,
            "relay",
            "missing relay response body receiver",
        );
    };

    let hub = state.hub.clone();
    let stream_id = stream.id;
    let body_stream = stream! {
        let mut guard = request_guard;
        guard.hub = hub;
        guard.stream_id = stream_id;
        while let Some(event) = body_rx.recv().await {
            match event {
                LocalBodyEvent::Chunk(chunk) => yield Ok::<Bytes, io::Error>(chunk),
                LocalBodyEvent::End => {
                    guard.finished = true;
                    break;
                }
                LocalBodyEvent::Error(error) => {
                    guard.finished = true;
                    yield Err(io::Error::other(error));
                    break;
                }
            }
        }
        guard.finished = true;
    };

    let mut builder = Response::builder().status(response_head.status);
    if let Some(headers) = builder.headers_mut() {
        append_headers(headers, &response_head.headers);
    }
    match builder.body(Body::from_stream(body_stream)) {
        Ok(response) => response,
        Err(error) => {
            warn!(error = %error, "failed to build relay response");
            tunnel_error_response(
                StatusCode::BAD_GATEWAY,
                "relay",
                "failed to build relay response",
            )
        }
    }
}

fn decode_envelope(body: Bytes) -> Result<(protocol::RequestMeta, Bytes), String> {
    if body.len() < 4 {
        return Err("relay envelope too short".to_string());
    }
    let meta_len = u32::from_be_bytes([body[0], body[1], body[2], body[3]]) as usize;
    let meta_end = 4usize
        .checked_add(meta_len)
        .ok_or_else(|| "relay envelope length overflow".to_string())?;
    if body.len() < meta_end {
        return Err("relay envelope metadata truncated".to_string());
    }
    let meta = serde_json::from_slice::<protocol::RequestMeta>(&body[4..meta_end])
        .map_err(|e| format!("invalid relay metadata: {e}"))?;
    Ok((meta, body.slice(meta_end..)))
}

fn append_headers(target: &mut HeaderMap, headers: &[(String, String)]) {
    for (name, value) in headers {
        let Ok(name) = HeaderName::from_bytes(name.as_bytes()) else {
            continue;
        };
        let Ok(value) = HeaderValue::from_str(value) else {
            continue;
        };
        target.append(name, value);
    }
}

fn tunnel_error_response(status: StatusCode, kind: &str, message: &str) -> Response<Body> {
    let mut builder = Response::builder().status(status);
    if let Some(headers) = builder.headers_mut() {
        headers.insert(
            HeaderName::from_static(TUNNEL_ERROR_HEADER),
            HeaderValue::from_str(kind).unwrap_or_else(|_| HeaderValue::from_static("relay")),
        );
        headers.insert(
            axum::http::header::CONTENT_TYPE,
            HeaderValue::from_static("text/plain; charset=utf-8"),
        );
    }
    builder
        .body(Body::from(message.to_string()))
        .unwrap_or_else(|_| Response::new(Body::from("relay error")))
}
