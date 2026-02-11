use base64::Engine;
use hmac::{Hmac, Mac};
use sha2::Sha256;
use subtle::ConstantTimeEq;

use crate::config::Config;

type HmacSha256 = Hmac<Sha256>;

#[derive(Debug)]
pub enum AuthError {
    MissingHeader,
    InvalidBasicAuth,
    InvalidUsername,
    InvalidPasswordFormat,
    TimestampParseError,
    TimestampExpired,
    SignatureMismatch,
}

impl std::fmt::Display for AuthError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::MissingHeader => write!(f, "missing Proxy-Authorization header"),
            Self::InvalidBasicAuth => write!(f, "invalid Basic auth encoding"),
            Self::InvalidUsername => write!(f, "username must be 'hmac'"),
            Self::InvalidPasswordFormat => {
                write!(f, "password format must be 'timestamp.signature'")
            }
            Self::TimestampParseError => write!(f, "invalid timestamp"),
            Self::TimestampExpired => write!(f, "timestamp outside tolerance window"),
            Self::SignatureMismatch => write!(f, "HMAC signature mismatch"),
        }
    }
}

/// Validate Proxy-Authorization header.
///
/// Expected format: `Basic base64(hmac:{timestamp}.{signature})`
/// where signature = hex(HMAC-SHA256(hmac_key, "{timestamp}"))
///
/// The signature no longer includes `node_id`, eliminating race conditions
/// during re-registration where the Aether server's cached `node_id` could
/// differ from the proxy's freshly assigned `node_id`.
///
/// `timestamp_tolerance` is accepted separately so the caller can supply
/// the value from [`DynamicConfig`](crate::runtime::DynamicConfig) (which
/// may be updated remotely).
pub fn validate_proxy_auth(
    proxy_auth_header: Option<&str>,
    config: &Config,
    timestamp_tolerance: u64,
) -> Result<(), AuthError> {
    let header = proxy_auth_header.ok_or(AuthError::MissingHeader)?;

    let encoded = header
        .strip_prefix("Basic ")
        .or_else(|| header.strip_prefix("basic "))
        .ok_or(AuthError::InvalidBasicAuth)?;

    let decoded_bytes = base64::engine::general_purpose::STANDARD
        .decode(encoded.trim())
        .map_err(|_| AuthError::InvalidBasicAuth)?;

    let decoded = String::from_utf8(decoded_bytes).map_err(|_| AuthError::InvalidBasicAuth)?;

    // format: hmac:{timestamp}.{signature}
    let (username, password) = decoded.split_once(':').ok_or(AuthError::InvalidBasicAuth)?;

    if username != "hmac" {
        return Err(AuthError::InvalidUsername);
    }

    let (timestamp_str, signature_hex) = password
        .split_once('.')
        .ok_or(AuthError::InvalidPasswordFormat)?;

    // Validate timestamp window
    let timestamp: u64 = timestamp_str
        .parse()
        .map_err(|_| AuthError::TimestampParseError)?;

    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("system clock before epoch")
        .as_secs();

    let diff = now.abs_diff(timestamp);

    if diff > timestamp_tolerance {
        return Err(AuthError::TimestampExpired);
    }

    // Recompute signature: HMAC-SHA256(key, timestamp)
    let mut mac =
        HmacSha256::new_from_slice(config.hmac_key.as_bytes()).expect("HMAC accepts any key size");
    mac.update(timestamp_str.as_bytes());
    let expected = mac.finalize().into_bytes();
    let expected_hex = hex::encode(expected);

    // Constant-time comparison
    let sig_bytes = signature_hex.as_bytes();
    let exp_bytes = expected_hex.as_bytes();

    if sig_bytes.len() != exp_bytes.len() || sig_bytes.ct_eq(exp_bytes).unwrap_u8() != 1 {
        return Err(AuthError::SignatureMismatch);
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_config() -> Config {
        Config {
            aether_url: String::new(),
            management_token: String::new(),
            hmac_key: "test-hmac-key".to_string(),
            listen_port: 18080,
            public_ip: None,
            node_name: "test".to_string(),
            node_region: None,
            heartbeat_interval: 30,
            allowed_ports: vec![80, 443],
            timestamp_tolerance: 300,
            aether_request_timeout_secs: 10,
            aether_connect_timeout_secs: 10,
            aether_pool_max_idle_per_host: 8,
            aether_pool_idle_timeout_secs: 90,
            aether_tcp_keepalive_secs: 60,
            aether_tcp_nodelay: true,
            aether_http2: true,
            aether_retry_max_attempts: 3,
            aether_retry_base_delay_ms: 200,
            aether_retry_max_delay_ms: 2000,
            max_concurrent_connections: None,
            connect_timeout_secs: 30,
            tls_handshake_timeout_secs: 10,
            dns_cache_ttl_secs: 60,
            dns_cache_capacity: 1024,
            delegate_connect_timeout_secs: 30,
            delegate_pool_max_idle_per_host: 64,
            delegate_pool_idle_timeout_secs: 300,
            delegate_tcp_keepalive_secs: 60,
            delegate_tcp_nodelay: true,
            log_level: "info".to_string(),
            log_json: false,
            enable_tls: false,
            tls_cert: String::new(),
            tls_key: String::new(),
        }
    }

    fn make_valid_auth(config: &Config) -> String {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let mut mac = HmacSha256::new_from_slice(config.hmac_key.as_bytes()).unwrap();
        mac.update(now.to_string().as_bytes());
        let sig = hex::encode(mac.finalize().into_bytes());
        let cred = format!("hmac:{}.{}", now, sig);
        let encoded = base64::engine::general_purpose::STANDARD.encode(cred);
        format!("Basic {}", encoded)
    }

    #[test]
    fn test_valid_auth() {
        let config = make_config();
        let header = make_valid_auth(&config);
        assert!(validate_proxy_auth(Some(&header), &config, config.timestamp_tolerance).is_ok());
    }

    #[test]
    fn test_missing_header() {
        let config = make_config();
        assert!(matches!(
            validate_proxy_auth(None, &config, config.timestamp_tolerance),
            Err(AuthError::MissingHeader)
        ));
    }

    #[test]
    fn test_wrong_username() {
        let cred = "user:12345.abc";
        let encoded = base64::engine::general_purpose::STANDARD.encode(cred);
        let header = format!("Basic {}", encoded);
        let config = make_config();
        assert!(matches!(
            validate_proxy_auth(Some(&header), &config, config.timestamp_tolerance),
            Err(AuthError::InvalidUsername)
        ));
    }
}
