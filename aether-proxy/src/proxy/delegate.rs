use std::collections::HashMap;
use std::collections::HashSet;
use std::sync::Arc;
use std::time::Instant;

use futures_util::TryStreamExt;
use http_body_util::{BodyExt, Full, Limited, StreamBody};
use hyper::body::{Frame, Incoming};
use hyper::{Request, Response};
use serde::Deserialize;
use tracing::{debug, warn};
use url::Url;

use super::BoxBody;
use crate::auth;
use crate::config::Config;
use crate::proxy::target_filter::{self, DnsCache};

/// Delegation request payload sent by Aether.
#[derive(Debug, Deserialize)]
struct DelegateRequest {
    method: String,
    url: String,
    headers: HashMap<String, String>,
    body: Option<String>,
    /// Accepted but not used on the proxy side — Aether controls timeouts.
    #[allow(dead_code)]
    timeout: Option<u64>,
}

/// Handle delegation requests: Aether sends a full request description,
/// and the proxy issues the actual upstream HTTP call using its own TLS stack.
///
/// Endpoint: POST /_aether/delegate
pub async fn handle_delegate(
    req: Request<Incoming>,
    config: Arc<Config>,
    allowed_ports: &HashSet<u16>,
    timestamp_tolerance: u64,
    dns_cache: &DnsCache,
    http_client: &reqwest::Client,
) -> Response<BoxBody> {
    let total_start = Instant::now();

    // Authenticate via Authorization header (same HMAC scheme as Proxy-Authorization)
    let auth_header = req
        .headers()
        .get("authorization")
        .and_then(|v| v.to_str().ok());

    if let Err(e) = auth::validate_proxy_auth(auth_header, &config, timestamp_tolerance) {
        warn!(error = %e, "delegate auth failed");
        return error_response(401, "authentication_failed", &e.to_string());
    }
    let auth_ms = total_start.elapsed().as_millis() as u64;

    // Read and parse request body (limit to 10 MB to prevent OOM)
    const MAX_BODY: usize = 10 * 1024 * 1024;
    let body_read_start = Instant::now();
    let body_bytes = match Limited::new(req.into_body(), MAX_BODY).collect().await {
        Ok(collected) => collected.to_bytes(),
        Err(e) => {
            warn!(error = %e, "failed to read delegate request body");
            return error_response(413, "payload_too_large", "request body exceeds 10MB limit");
        }
    };
    let body_read_ms = body_read_start.elapsed().as_millis() as u64;
    let body_size = body_bytes.len() as u64;

    let body_parse_start = Instant::now();
    let delegate_req: DelegateRequest = match serde_json::from_slice(&body_bytes) {
        Ok(r) => r,
        Err(e) => {
            warn!(error = %e, "invalid delegate request JSON");
            return error_response(400, "bad_request", &format!("invalid JSON: {}", e));
        }
    };
    let body_parse_ms = body_parse_start.elapsed().as_millis() as u64;

    // Target filter: validate the upstream URL against allowed ports and private IP checks
    let parsed_url = match Url::parse(&delegate_req.url) {
        Ok(u) => u,
        Err(e) => {
            warn!(url = %delegate_req.url, error = %e, "invalid delegate target URL");
            return error_response(400, "bad_request", &format!("invalid URL: {}", e));
        }
    };

    let host = match parsed_url.host_str() {
        Some(h) => h.to_string(),
        None => {
            warn!(url = %delegate_req.url, "delegate target URL missing host");
            return error_response(400, "bad_request", "URL missing host");
        }
    };

    let port = parsed_url.port_or_known_default().unwrap_or(443);

    let dns_start = Instant::now();
    if let Err(e) = target_filter::validate_target(&host, port, allowed_ports, dns_cache).await {
        warn!(host = %host, port, error = %e, "delegate target rejected");
        return error_response(403, "target_not_allowed", &e.to_string());
    }
    let dns_ms = dns_start.elapsed().as_millis() as u64;

    debug!(
        method = %delegate_req.method,
        url = %delegate_req.url,
        "delegate request"
    );

    // Build upstream request
    let method = match delegate_req.method.parse::<reqwest::Method>() {
        Ok(m) => m,
        Err(e) => {
            warn!(error = %e, method = %delegate_req.method, "invalid HTTP method");
            return error_response(400, "bad_request", &format!("invalid method: {}", e));
        }
    };

    let mut upstream_req = http_client.request(method, &delegate_req.url);

    // NOTE: We intentionally do NOT set a per-request timeout here.
    // reqwest's `.timeout()` caps the *entire* request including body streaming,
    // which would truncate long-lived SSE streams. The delegate_client already
    // has a configured connect_timeout for connection establishment, and Aether controls
    // first-byte / idle timeouts on its own side via asyncio.

    // Set headers (skip `host` — reqwest sets it from the URL automatically,
    // and a duplicate Host header can confuse certain upstreams)
    for (name, value) in &delegate_req.headers {
        if name.eq_ignore_ascii_case("host") {
            continue;
        }
        upstream_req = upstream_req.header(name.as_str(), value.as_str());
    }

    // Set body
    if let Some(body) = delegate_req.body {
        upstream_req = upstream_req.body(body);
    }

    // Send upstream request
    let upstream_start = Instant::now();
    let upstream_resp = match upstream_req.send().await {
        Ok(resp) => resp,
        Err(e) => {
            warn!(url = %delegate_req.url, error = %e, "delegate upstream request failed");
            // Sanitize: strip URL details from error message to avoid leaking
            // API keys or paths that may appear in query strings / paths.
            let safe_detail = sanitize_upstream_error(&e.to_string());
            if e.is_timeout() {
                return error_response(504, "upstream_timeout", &safe_detail);
            }
            return error_response(502, "upstream_connection_failed", &safe_detail);
        }
    };
    let upstream_ms = upstream_start.elapsed().as_millis() as u64;

    // Build response: pass through upstream status + headers, stream body back
    let status = upstream_resp.status().as_u16();
    let upstream_headers = upstream_resp.headers().clone();

    let total_ms = total_start.elapsed().as_millis() as u64;

    debug!(
        url = %delegate_req.url,
        status,
        dns_ms,
        upstream_ms,
        total_ms,
        "delegate upstream response"
    );

    // Inject proxy timing header for Aether to parse
    let timing = serde_json::json!({
        "auth_ms": auth_ms,
        "body_read_ms": body_read_ms,
        "body_parse_ms": body_parse_ms,
        "body_size": body_size,
        "dns_ms": dns_ms,
        "upstream_ms": upstream_ms,
        "total_ms": total_ms,
    });

    // Stream the response body
    let body_stream = upstream_resp
        .bytes_stream()
        .map_ok(Frame::data)
        .map_err(|e| -> Box<dyn std::error::Error + Send + Sync> { Box::new(e) });

    let stream_body: BoxBody = StreamBody::new(body_stream).boxed();

    let mut builder = Response::builder().status(status);
    for (name, value) in upstream_headers.iter() {
        builder = builder.header(name, value);
    }
    builder = builder.header("X-Proxy-Timing", timing.to_string());

    builder.body(stream_body).unwrap_or_else(|_| {
        Response::builder()
            .status(500)
            .body(super::empty_box_body())
            .unwrap()
    })
}

// ── Sanitisation ─────────────────────────────────────────────────────────────

/// Strip full URLs from error messages to prevent leaking upstream API keys,
/// paths, or query parameters in the delegate error response.
///
/// Replaces `https://api.example.com/v1/chat?key=xxx` with `api.example.com`.
fn sanitize_upstream_error(msg: &str) -> String {
    // Simple regex-free approach: find "https://..." or "http://..." spans and
    // replace them with just the host portion.
    let mut result = msg.to_string();
    for scheme in &["https://", "http://"] {
        while let Some(start) = result.find(scheme) {
            let after_scheme = start + scheme.len();
            // Host ends at '/', '?', '#', ' ', or end of string
            let host_end = result[after_scheme..]
                .find(['/', '?', '#', ' '])
                .map(|i| after_scheme + i)
                .unwrap_or(result.len());
            let host = &result[after_scheme..host_end];
            result = format!("{}{}{}", &result[..start], host, &result[host_end..]);
        }
    }
    result
}

// ── Error response helpers ───────────────────────────────────────────────────

fn error_response(status: u16, error: &str, detail: &str) -> Response<BoxBody> {
    let body = serde_json::json!({
        "error": error,
        "detail": detail,
    });
    let body_bytes = bytes::Bytes::from(body.to_string());

    Response::builder()
        .status(status)
        .header("Content-Type", "application/json")
        .header("X-Delegate-Error", "true")
        .body(
            Full::new(body_bytes)
                .map_err(|e| -> Box<dyn std::error::Error + Send + Sync> { match e {} })
                .boxed(),
        )
        .unwrap()
}
