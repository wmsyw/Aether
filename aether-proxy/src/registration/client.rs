use std::time::{Duration, SystemTime, UNIX_EPOCH};

use reqwest::{Client, StatusCode};
use serde::{Deserialize, Serialize};
use tokio::time::sleep;
use tracing::{debug, error, info, warn};

use crate::config::Config;
use crate::hardware::HardwareInfo;

/// Heartbeat-specific error that distinguishes "node not found" (needs
/// re-registration) from transient / other failures.
#[derive(Debug)]
pub enum HeartbeatError {
    /// HTTP 404 – the node_id is no longer known to Aether.
    NodeNotFound(String),
    /// Any other failure (network, 5xx, etc.).
    Other(anyhow::Error),
}

impl std::fmt::Display for HeartbeatError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NodeNotFound(msg) => write!(f, "node not found: {}", msg),
            Self::Other(e) => write!(f, "{}", e),
        }
    }
}

#[derive(Debug, Serialize)]
struct RegisterRequest {
    name: String,
    ip: String,
    port: u16,
    #[serde(skip_serializing_if = "Option::is_none")]
    region: Option<String>,
    heartbeat_interval: u64,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    tls_enabled: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    tls_cert_fingerprint: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    hardware_info: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    estimated_max_concurrency: Option<u64>,
}

#[derive(Debug, Deserialize)]
pub struct RegisterResponse {
    pub node_id: String,
}

#[derive(Debug, Serialize)]
struct HeartbeatRequest {
    node_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    active_connections: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    total_requests: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    avg_latency_ms: Option<f64>,
}

/// Remote configuration pushed by the Aether management backend.
#[derive(Debug, Clone, Deserialize)]
pub struct RemoteConfig {
    pub node_name: Option<String>,
    pub allowed_ports: Option<Vec<u16>>,
    pub log_level: Option<String>,
    pub heartbeat_interval: Option<u64>,
    pub timestamp_tolerance: Option<u64>,
}

/// Parsed heartbeat response from Aether.
#[derive(Debug, Deserialize)]
struct HeartbeatResponseBody {
    #[serde(default)]
    node: Option<HeartbeatNodeInfo>,
}

#[derive(Debug, Deserialize)]
struct HeartbeatNodeInfo {
    #[serde(default)]
    remote_config: Option<RemoteConfig>,
    #[serde(default)]
    config_version: Option<u64>,
}

/// Heartbeat result returned to the caller.
#[derive(Debug)]
pub struct HeartbeatResult {
    pub remote_config: Option<RemoteConfig>,
    pub config_version: u64,
}

#[derive(Debug, Serialize)]
struct UnregisterRequest {
    node_id: String,
}

/// Aether API client for proxy node lifecycle management.
pub struct AetherClient {
    http: Client,
    base_url: String,
    token: String,
    retry_max_attempts: u32,
    retry_base_delay: Duration,
    retry_max_delay: Duration,
}

impl AetherClient {
    pub fn new(config: &Config) -> Self {
        let mut builder = Client::builder()
            .timeout(Duration::from_secs(config.aether_request_timeout_secs))
            .connect_timeout(Duration::from_secs(config.aether_connect_timeout_secs))
            .pool_max_idle_per_host(config.aether_pool_max_idle_per_host)
            .pool_idle_timeout(Duration::from_secs(config.aether_pool_idle_timeout_secs))
            .tcp_nodelay(config.aether_tcp_nodelay);

        if config.aether_tcp_keepalive_secs > 0 {
            builder =
                builder.tcp_keepalive(Some(Duration::from_secs(config.aether_tcp_keepalive_secs)));
        } else {
            builder = builder.tcp_keepalive(None);
        }

        if config.aether_http2 {
            builder = builder.http2_adaptive_window(true);
        }

        let http = builder.build().expect("failed to create HTTP client");

        let retry_base_delay = Duration::from_millis(config.aether_retry_base_delay_ms);
        let retry_max_delay =
            Duration::from_millis(config.aether_retry_max_delay_ms).max(retry_base_delay);

        Self {
            http,
            base_url: config.aether_url.trim_end_matches('/').to_string(),
            token: config.management_token.clone(),
            retry_max_attempts: config.aether_retry_max_attempts.max(1),
            retry_base_delay,
            retry_max_delay,
        }
    }

    /// Register this node with Aether (idempotent upsert by ip:port).
    ///
    /// Returns the stable node_id assigned by Aether.
    pub async fn register(
        &self,
        config: &Config,
        public_ip: &str,
        tls_enabled: bool,
        tls_cert_fingerprint: Option<&str>,
        hw: Option<&HardwareInfo>,
    ) -> anyhow::Result<String> {
        let url = format!("{}/api/admin/proxy-nodes/register", self.base_url);
        let body = RegisterRequest {
            name: config.node_name.clone(),
            ip: public_ip.to_string(),
            port: config.listen_port,
            region: config.node_region.clone(),
            heartbeat_interval: config.heartbeat_interval,
            tls_enabled,
            tls_cert_fingerprint: tls_cert_fingerprint.map(|s| s.to_string()),
            hardware_info: hw.and_then(|h| serde_json::to_value(h).ok()),
            estimated_max_concurrency: hw.map(|h| h.estimated_max_concurrency),
        };

        info!(
            url = %url,
            name = %body.name,
            ip = %body.ip,
            port = body.port,
            "registering with Aether"
        );

        let resp = self
            .send_with_retry(
                || {
                    self.http
                        .post(&url)
                        .header("Authorization", format!("Bearer {}", self.token))
                        .json(&body)
                },
                "register",
            )
            .await?;

        let status = resp.status();
        if !status.is_success() {
            let text = resp.text().await.unwrap_or_default();
            anyhow::bail!("register failed (HTTP {}): {}", status, text);
        }

        let data: RegisterResponse = resp.json().await?;
        info!(node_id = %data.node_id, "registered successfully");
        Ok(data.node_id)
    }

    /// Send heartbeat to Aether.
    ///
    /// On success, returns any remote config included in the response.
    /// Returns [`HeartbeatError::NodeNotFound`] on HTTP 404 so the caller
    /// can trigger re-registration.
    pub async fn heartbeat(
        &self,
        node_id: &str,
        active_connections: Option<i64>,
        total_requests: Option<i64>,
        avg_latency_ms: Option<f64>,
    ) -> Result<HeartbeatResult, HeartbeatError> {
        let url = format!("{}/api/admin/proxy-nodes/heartbeat", self.base_url);
        let body = HeartbeatRequest {
            node_id: node_id.to_string(),
            active_connections,
            total_requests,
            avg_latency_ms,
        };

        debug!(node_id = %node_id, "sending heartbeat");

        let resp = self
            .send_with_retry(
                || {
                    self.http
                        .post(&url)
                        .header("Authorization", format!("Bearer {}", self.token))
                        .json(&body)
                },
                "heartbeat",
            )
            .await
            .map_err(|e| HeartbeatError::Other(e.into()))?;

        let status = resp.status();
        if !status.is_success() {
            let text = resp.text().await.unwrap_or_default();
            warn!(status = %status, body = %text, "heartbeat failed");
            if status == StatusCode::NOT_FOUND {
                return Err(HeartbeatError::NodeNotFound(text));
            }
            return Err(HeartbeatError::Other(anyhow::anyhow!(
                "heartbeat failed (HTTP {}): {}",
                status,
                text
            )));
        }

        // Parse remote config from response (best-effort)
        let result = match resp.json::<HeartbeatResponseBody>().await {
            Ok(body) => {
                let (remote_config, config_version) = match body.node {
                    Some(node) => (node.remote_config, node.config_version.unwrap_or(0)),
                    None => (None, 0),
                };
                HeartbeatResult {
                    remote_config,
                    config_version,
                }
            }
            Err(e) => {
                debug!(error = %e, "failed to parse heartbeat response body");
                HeartbeatResult {
                    remote_config: None,
                    config_version: 0,
                }
            }
        };

        debug!(node_id = %node_id, config_version = result.config_version, "heartbeat ok");
        Ok(result)
    }

    /// Unregister this node from Aether (graceful shutdown).
    pub async fn unregister(&self, node_id: &str) -> anyhow::Result<()> {
        let url = format!("{}/api/admin/proxy-nodes/unregister", self.base_url);
        let body = UnregisterRequest {
            node_id: node_id.to_string(),
        };

        info!(node_id = %node_id, "unregistering from Aether");

        let resp = self
            .send_with_retry(
                || {
                    self.http
                        .post(&url)
                        .header("Authorization", format!("Bearer {}", self.token))
                        .json(&body)
                },
                "unregister",
            )
            .await;

        match resp {
            Ok(r) if r.status().is_success() => {
                info!(node_id = %node_id, "unregistered successfully");
                Ok(())
            }
            Ok(r) => {
                let text = r.text().await.unwrap_or_default();
                error!(body = %text, "unregister failed");
                anyhow::bail!("unregister failed: {}", text);
            }
            Err(e) => {
                // Best-effort during shutdown
                error!(error = %e, "unregister request failed");
                anyhow::bail!("unregister request failed: {}", e);
            }
        }
    }

    async fn send_with_retry<F>(
        &self,
        mut make_req: F,
        label: &str,
    ) -> Result<reqwest::Response, reqwest::Error>
    where
        F: FnMut() -> reqwest::RequestBuilder,
    {
        let mut attempt: u32 = 0;
        let mut delay = self.retry_base_delay;

        loop {
            attempt = attempt.saturating_add(1);
            let resp = make_req().send().await;
            match resp {
                Ok(resp) => {
                    if should_retry_status(resp.status()) && attempt < self.retry_max_attempts {
                        let sleep_for = jitter_delay(delay);
                        debug!(
                            attempt,
                            status = %resp.status(),
                            sleep_ms = sleep_for.as_millis(),
                            label,
                            "Aether request retrying"
                        );
                        sleep(sleep_for).await;
                        let next_delay = delay.checked_mul(2).unwrap_or(self.retry_max_delay);
                        delay = std::cmp::min(next_delay, self.retry_max_delay);
                        continue;
                    }
                    return Ok(resp);
                }
                Err(e) => {
                    if attempt < self.retry_max_attempts {
                        let sleep_for = jitter_delay(delay);
                        debug!(
                            attempt,
                            error = %e,
                            sleep_ms = sleep_for.as_millis(),
                            label,
                            "Aether request retrying"
                        );
                        sleep(sleep_for).await;
                        let next_delay = delay.checked_mul(2).unwrap_or(self.retry_max_delay);
                        delay = std::cmp::min(next_delay, self.retry_max_delay);
                        continue;
                    }
                    return Err(e);
                }
            }
        }
    }
}

fn should_retry_status(status: StatusCode) -> bool {
    status.is_server_error()
        || status == StatusCode::TOO_MANY_REQUESTS
        || status == StatusCode::REQUEST_TIMEOUT
}

fn jitter_delay(base: Duration) -> Duration {
    if base.is_zero() {
        return base;
    }
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.subsec_nanos() as u64)
        .unwrap_or(0);
    let jitter_ms = nanos % 100;
    base + Duration::from_millis(jitter_ms)
}
