use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::pricing::BillingPricingResolution;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VirtualBillingRule {
    pub id: String,
    pub name: String,
    pub task_type: String,
    pub expression: String,
    pub variables: BTreeMap<String, Value>,
    pub dimension_mappings: BTreeMap<String, Value>,
    pub scope: String,
}

pub struct DefaultBillingRuleGenerator;

impl DefaultBillingRuleGenerator {
    /// Builds the default rule for one usage's effective pricing.
    ///
    /// `task_type` identifies the billed modality: a per-second video table
    /// only replaces token pricing for an actual video task, so chat and image
    /// calls on the same model keep their token/image prices.
    pub fn generate_for_pricing(
        global_model_name: &str,
        pricing: &BillingPricingResolution,
        task_type: &str,
    ) -> Option<VirtualBillingRule> {
        let pricing_config = pricing.tiered_pricing.as_ref();
        let tiers = pricing_config
            .and_then(|value| value.get("tiers"))
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let explicit_image_output_price_default =
            explicit_image_output_price_default(pricing_config);
        let image_output_price_default = explicit_image_output_price_default.unwrap_or(0.0);
        let has_image_output_matrix = explicit_image_output_price_entries(pricing_config)
            .is_some_and(|entries| !entries.is_empty());
        let has_image_output_ranges = explicit_image_output_price_ranges(pricing_config)
            .is_some_and(|ranges| !ranges.is_empty());
        let has_image_output_pricing = has_image_output_matrix
            || has_image_output_ranges
            || explicit_image_output_price_default.is_some();
        let video_pricing = pricing.video_pricing.as_ref();
        // A per-second table on a multimodal model must not turn ordinary chat
        // or image usage into zero-rate token billing. Only a task the gateway
        // actually routed as video uses the seconds price.
        let per_second_video = per_second_video_billing_applies(video_pricing, task_type, None);

        if tiers.is_empty()
            && pricing.price_per_request.is_none()
            && !has_image_output_pricing
            && !per_second_video
        {
            return None;
        }

        let first_tier = tiers.first().cloned().unwrap_or_else(|| json!({}));
        // Per-second video pricing replaces token pricing rather than adding to
        // it, so every token rate is zeroed here, cache rates included.
        // Enforcing it at rule level means a stale token price in the config
        // cannot double-charge alongside the rendered seconds.
        let (base_input_price, base_output_price) = if per_second_video {
            (0.0, 0.0)
        } else {
            (
                tier_value(&first_tier, "input_price_per_1m", 0.0),
                tier_value(&first_tier, "output_price_per_1m", 0.0),
            )
        };
        let (base_cache_creation_price, base_cache_read_price) = if per_second_video {
            (0.0, 0.0)
        } else {
            (
                tier_value_with_fallback(&first_tier, "cache_creation_price_per_1m", 1.25),
                tier_value_with_fallback(&first_tier, "cache_read_price_per_1m", 0.1),
            )
        };
        let base_request_price = pricing.price_per_request.unwrap_or(0.0);

        let mut variables = BTreeMap::new();
        variables.insert("input_price_per_1m".to_string(), json!(base_input_price));
        variables.insert("output_price_per_1m".to_string(), json!(base_output_price));
        variables.insert(
            "cache_creation_price_per_1m".to_string(),
            json!(base_cache_creation_price),
        );
        variables.insert(
            "cache_creation_ephemeral_5m_price_per_1m".to_string(),
            json!(base_cache_creation_price),
        );
        variables.insert(
            "cache_creation_ephemeral_1h_price_per_1m".to_string(),
            json!(base_cache_creation_price),
        );
        variables.insert(
            "cache_read_price_per_1m".to_string(),
            json!(base_cache_read_price),
        );
        variables.insert("price_per_request".to_string(), json!(base_request_price));
        variables.insert(
            "image_output_price_per_image".to_string(),
            json!(image_output_price_default),
        );

        let mut dimension_mappings = BTreeMap::new();
        for (name, key, default) in [
            ("input_tokens", "input_tokens", json!(0)),
            ("output_tokens", "output_tokens", json!(0)),
            ("cache_creation_tokens", "cache_creation_tokens", json!(0)),
            (
                "cache_creation_ephemeral_5m_tokens",
                "cache_creation_ephemeral_5m_tokens",
                json!(0),
            ),
            (
                "cache_creation_ephemeral_1h_tokens",
                "cache_creation_ephemeral_1h_tokens",
                json!(0),
            ),
            (
                "cache_creation_uncategorized_tokens",
                "cache_creation_uncategorized_tokens",
                json!(0),
            ),
            ("cache_read_tokens", "cache_read_tokens", json!(0)),
            ("request_count", "request_count", json!(1)),
            ("image_count", "image_count", json!(0)),
            ("image_count_unmetered", "image_count_unmetered", json!(0)),
            ("image_price_key", "image_price_key", json!("default")),
            (
                "image_output_price_per_image",
                "image_output_price_per_image",
                json!(image_output_price_default),
            ),
        ] {
            dimension_mappings.insert(
                name.to_string(),
                json!({
                    "source": "dimension",
                    "key": key,
                    "required": false,
                    "allow_zero": true,
                    "default": default,
                }),
            );
        }

        for (name, expression) in [
            ("input_cost", "input_tokens * input_price_per_1m / 1000000"),
            (
                "output_cost",
                "output_tokens * output_price_per_1m / 1000000",
            ),
            (
                "cache_creation_uncategorized_cost",
                "cache_creation_uncategorized_tokens * cache_creation_price_per_1m / 1000000",
            ),
            (
                "cache_creation_ephemeral_5m_cost",
                "cache_creation_ephemeral_5m_tokens * cache_creation_ephemeral_5m_price_per_1m / 1000000",
            ),
            (
                "cache_creation_ephemeral_1h_cost",
                "cache_creation_ephemeral_1h_tokens * cache_creation_ephemeral_1h_price_per_1m / 1000000",
            ),
            (
                "cache_read_cost",
                "cache_read_tokens * cache_read_price_per_1m / 1000000",
            ),
            (
                "image_output_cost",
                "image_count_unmetered * image_output_price_per_image",
            ),
            (
                "video_cost",
                "video_seconds_unmetered * video_price_per_second",
            ),
            ("request_cost", "request_count * price_per_request"),
        ] {
            dimension_mappings.insert(
                name.to_string(),
                json!({
                    "source": "computed",
                    "expression": expression,
                    "required": false,
                    "default": 0,
                }),
            );
        }

        if !tiers.is_empty() {
            dimension_mappings.insert(
                "input_price_per_1m".to_string(),
                json!({
                    "source": "tiered",
                    "tier_key": "total_input_context",
                    "allow_zero": true,
                    "tiers": token_tier_entries(
                        &tiers,
                        per_second_video,
                        "input_price_per_1m",
                        None,
                        false,
                    ),
                    "default": base_input_price,
                }),
            );
            dimension_mappings.insert(
                "output_price_per_1m".to_string(),
                json!({
                    "source": "tiered",
                    "tier_key": "total_input_context",
                    "allow_zero": true,
                    "tiers": token_tier_entries(
                        &tiers,
                        per_second_video,
                        "output_price_per_1m",
                        None,
                        false,
                    ),
                    "default": base_output_price,
                }),
            );
            dimension_mappings.insert(
                "cache_creation_price_per_1m".to_string(),
                json!({
                    "source": "tiered",
                    "tier_key": "total_input_context",
                    "allow_zero": true,
                    "ttl_key": "cache_ttl_minutes",
                    "ttl_value_key": "cache_creation_price_per_1m",
                    "tiers": token_tier_entries(
                        &tiers,
                        per_second_video,
                        "cache_creation_price_per_1m",
                        Some(1.25),
                        true,
                    ),
                    "default": base_cache_creation_price,
                }),
            );
            dimension_mappings.insert(
                "cache_creation_ephemeral_5m_price_per_1m".to_string(),
                json!({
                    "source": "tiered",
                    "tier_key": "total_input_context",
                    "allow_zero": true,
                    "ttl_key": "cache_creation_ephemeral_5m_ttl_minutes",
                    "ttl_value_key": "cache_creation_price_per_1m",
                    "tiers": token_tier_entries(
                        &tiers,
                        per_second_video,
                        "cache_creation_price_per_1m",
                        Some(1.25),
                        true,
                    ),
                    "default": base_cache_creation_price,
                }),
            );
            dimension_mappings.insert(
                "cache_creation_ephemeral_1h_price_per_1m".to_string(),
                json!({
                    "source": "tiered",
                    "tier_key": "total_input_context",
                    "allow_zero": true,
                    "ttl_key": "cache_creation_ephemeral_1h_ttl_minutes",
                    "ttl_value_key": "cache_creation_price_per_1m",
                    "tiers": token_tier_entries(
                        &tiers,
                        per_second_video,
                        "cache_creation_price_per_1m",
                        Some(1.25),
                        true,
                    ),
                    "default": base_cache_creation_price,
                }),
            );
            dimension_mappings.insert(
                "cache_read_price_per_1m".to_string(),
                json!({
                    "source": "tiered",
                    "tier_key": "total_input_context",
                    "allow_zero": true,
                    "ttl_key": "cache_ttl_minutes",
                    "ttl_value_key": "cache_read_price_per_1m",
                    "tiers": token_tier_entries(
                        &tiers,
                        per_second_video,
                        "cache_read_price_per_1m",
                        Some(0.1),
                        true,
                    ),
                    "default": base_cache_read_price,
                }),
            );
        }

        Some(VirtualBillingRule {
            id: "__default__".to_string(),
            name: format!("Default rule for {global_model_name}"),
            task_type: normalize_task_type(task_type).to_string(),
            expression: "input_cost + output_cost + cache_creation_uncategorized_cost + cache_creation_ephemeral_5m_cost + cache_creation_ephemeral_1h_cost + cache_read_cost + image_output_cost + request_cost + video_cost".to_string(),
            variables,
            dimension_mappings,
            scope: "default".to_string(),
        })
    }
}

pub fn normalize_task_type(task_type: &str) -> &str {
    if task_type.trim().eq_ignore_ascii_case("cli") {
        "chat"
    } else {
        task_type.trim()
    }
}

fn tier_value(tier: &Value, key: &str, default: f64) -> f64 {
    tier.get(key).and_then(Value::as_f64).unwrap_or(default)
}

fn tier_value_with_fallback(tier: &Value, key: &str, default_multiplier: f64) -> f64 {
    if let Some(value) = tier.get(key).and_then(Value::as_f64) {
        return value;
    }
    tier.get("input_price_per_1m")
        .and_then(Value::as_f64)
        .map(|value| value * default_multiplier)
        .unwrap_or(0.0)
}

fn build_tier_entries(
    tiers: &[Value],
    key: &str,
    default_multiplier: Option<f64>,
    include_cache_ttl_pricing: bool,
) -> Vec<Value> {
    tiers
        .iter()
        .map(|tier| {
            let mut value = serde_json::Map::new();
            value.insert(
                "up_to".to_string(),
                tier.get("up_to").cloned().unwrap_or(Value::Null),
            );
            let resolved = match default_multiplier {
                Some(multiplier) => Value::from(tier_value_with_fallback(tier, key, multiplier)),
                None => Value::from(tier_value(tier, key, 0.0)),
            };
            value.insert("value".to_string(), resolved);
            if include_cache_ttl_pricing {
                if let Some(ttl_pricing) = tier.get("cache_ttl_pricing").cloned() {
                    value.insert("cache_ttl_pricing".to_string(), ttl_pricing);
                }
            }
            Value::Object(value)
        })
        .collect()
}

/// Builds a token price tier table, except under per-second billing where the
/// table must be empty so a stale configured tier cannot re-introduce a charge
/// on top of the rendered seconds.
fn token_tier_entries(
    tiers: &[Value],
    per_second_video: bool,
    key: &str,
    default_multiplier: Option<f64>,
    include_cache_ttl_pricing: bool,
) -> Vec<Value> {
    if per_second_video {
        Vec::new()
    } else {
        build_tier_entries(tiers, key, default_multiplier, include_cache_ttl_pricing)
    }
}

pub(crate) fn explicit_image_output_price_entries(
    pricing_config: Option<&Value>,
) -> Option<BTreeMap<String, Value>> {
    let pricing_config = pricing_config?;
    let mut entries = BTreeMap::new();
    for key in [
        "image_output_prices",
        "image_output_price_per_image",
        "image_output_price_matrix",
        "image_prices",
    ] {
        if let Some(value) = pricing_config.get(key) {
            collect_image_output_price_entries(value, &mut entries);
        }
    }
    Some(entries)
}

pub(crate) fn explicit_image_output_price_ranges(
    pricing_config: Option<&Value>,
) -> Option<Vec<Value>> {
    let pricing_config = pricing_config?;
    let Some(value) = pricing_config.get("image_output_price_ranges") else {
        return Some(Vec::new());
    };

    let mut ranges = Vec::new();
    match value {
        Value::Array(items) => {
            for item in items {
                let Some(object) = item.as_object() else {
                    continue;
                };
                let mut range = serde_json::Map::new();
                if let Some(up_to_pixels) = object
                    .get("up_to_pixels")
                    .or_else(|| object.get("up_to"))
                    .or_else(|| object.get("max_pixels"))
                {
                    range.insert("up_to_pixels".to_string(), up_to_pixels.clone());
                }
                if let Some(label) = object.get("label").cloned() {
                    range.insert("label".to_string(), label);
                }
                if let Some(prices) = object.get("prices") {
                    range.insert("prices".to_string(), prices.clone());
                } else {
                    let mut prices = serde_json::Map::new();
                    for quality in ["low", "medium", "high"] {
                        if let Some(price) = object.get(quality).and_then(Value::as_f64) {
                            prices.insert(quality.to_string(), json!(price));
                        }
                    }
                    if prices.is_empty() {
                        if let Some(price) = object
                            .get("price_per_image")
                            .or_else(|| object.get("price"))
                            .or_else(|| object.get("value"))
                            .and_then(Value::as_f64)
                        {
                            prices.insert("default".to_string(), json!(price));
                        }
                    }
                    if !prices.is_empty() {
                        range.insert("prices".to_string(), Value::Object(prices));
                    }
                }
                if !range.is_empty() {
                    ranges.push(Value::Object(range));
                }
            }
        }
        Value::Object(object) => {
            for (key, item) in object {
                let Some(entry) = item.as_object() else {
                    continue;
                };
                let mut range = serde_json::Map::new();
                if let Some(up_to_pixels) = entry
                    .get("up_to_pixels")
                    .or_else(|| entry.get("up_to"))
                    .or_else(|| entry.get("max_pixels"))
                {
                    range.insert("up_to_pixels".to_string(), up_to_pixels.clone());
                } else if let Ok(parsed) = key.parse::<u64>() {
                    range.insert("up_to_pixels".to_string(), json!(parsed));
                }
                if let Some(label) = entry.get("label").cloned() {
                    range.insert("label".to_string(), label);
                }
                if let Some(prices) = entry.get("prices") {
                    range.insert("prices".to_string(), prices.clone());
                }
                if !range.is_empty() {
                    ranges.push(Value::Object(range));
                }
            }
        }
        _ => {}
    }

    Some(ranges)
}

pub(crate) fn explicit_image_output_price_default(pricing_config: Option<&Value>) -> Option<f64> {
    let pricing_config = pricing_config?;
    pricing_config
        .get("image_output_price_default")
        .or_else(|| pricing_config.get("image_price_default"))
        .or_else(|| {
            pricing_config
                .get("image_output_prices")
                .and_then(|value| value.get("default"))
        })
        .and_then(Value::as_f64)
}

/// Config key holding the per-second video price table, keyed by resolution.
const VIDEO_PER_SECOND_TABLE_KEY: &str = "price_per_second_by_resolution";

#[derive(Debug, Clone, Copy, Default)]
pub(crate) struct VideoPricingState {
    /// Whether per-second pricing is configured with at least one resolution row.
    pub(crate) per_second_enabled: bool,
}

pub(crate) fn video_pricing_state(video_pricing: Option<&Value>) -> VideoPricingState {
    let per_second_enabled = video_pricing
        .and_then(|value| value.get(VIDEO_PER_SECOND_TABLE_KEY))
        .and_then(Value::as_object)
        .is_some_and(|table| !table.is_empty());
    VideoPricingState { per_second_enabled }
}

/// Whether this billing input is an actual video task rather than ordinary
/// chat or image usage that happens to share a model with a video price table.
///
/// `BillingUsageInput.task_type` is the canonical modality: the gateway derives
/// it from the request type, and event enrichment rewrites it for image usage.
/// The API format endpoint kind is a fallback for projections that lost the
/// request type; a duration alone never makes a request video.
pub(crate) fn usage_is_video(task_type: &str, api_format: Option<&str>) -> bool {
    normalize_task_type(task_type).eq_ignore_ascii_case("video")
        || api_format
            .and_then(|value| value.split_once(':'))
            .map(|(_, kind)| kind.trim())
            .is_some_and(|kind| kind.eq_ignore_ascii_case("video"))
}

/// Per-second pricing replaces token pricing only for an actual video task on
/// a model with a configured resolution table. Chat and image calls keep their
/// token and image prices even when the same model also offers video.
pub(crate) fn per_second_video_billing_applies(
    video_pricing: Option<&Value>,
    task_type: &str,
    api_format: Option<&str>,
) -> bool {
    video_pricing_state(video_pricing).per_second_enabled && usage_is_video(task_type, api_format)
}

/// Resolves the per-second price for the rendered resolution.
///
/// A resolution the operator never listed resolves to nothing rather than
/// inventing a price, so an unconfigured video stays unbilled by seconds.
pub(crate) fn resolve_video_price_per_second(
    video_pricing: Option<&Value>,
    resolution: Option<&str>,
) -> f64 {
    let Some(video_pricing) = video_pricing else {
        return 0.0;
    };
    let key = normalize_video_resolution_key(resolution.unwrap_or_default());
    if key.is_empty() {
        return 0.0;
    }
    video_pricing
        .get(VIDEO_PER_SECOND_TABLE_KEY)
        .and_then(Value::as_object)
        .and_then(|table| {
            table
                .iter()
                .find(|(candidate, _)| normalize_video_resolution_key(candidate) == key)
        })
        .and_then(|(_, entry)| entry.as_f64())
        .filter(|price| price.is_finite() && *price > 0.0)
        .unwrap_or(0.0)
}

/// Normalizes a resolution key so config and provider spellings match.
///
/// Must stay aligned with the admin UI's `normalizeResolutionKey`: providers
/// report either a tier (`720p`) or pixels (`1280x720`), and a pixel pair is
/// ordered smallest-first so portrait and landscape share one price entry.
pub(crate) fn normalize_video_resolution_key(value: &str) -> String {
    let normalized = value
        .trim()
        .to_ascii_lowercase()
        .replace('×', "x")
        .chars()
        .filter(|ch| !ch.is_whitespace())
        .collect::<String>();
    let Some((width, height)) = normalized.split_once('x') else {
        return normalized;
    };
    match (width.parse::<u64>(), height.parse::<u64>()) {
        (Ok(width), Ok(height)) => {
            let (smaller, larger) = if width <= height {
                (width, height)
            } else {
                (height, width)
            };
            format!("{smaller}x{larger}")
        }
        _ => normalized,
    }
}

fn collect_image_output_price_entries(value: &Value, entries: &mut BTreeMap<String, Value>) {
    if let Some(object) = value.as_object() {
        for (key, value) in object {
            if key.eq_ignore_ascii_case("default") {
                continue;
            }
            if let Some(price) = value.as_f64() {
                entries.insert(normalize_image_price_key(key), json!(price));
                continue;
            }
            let Some(nested) = value.as_object() else {
                continue;
            };
            let key_is_quality = matches_quality_key(key);
            for (nested_key, nested_value) in nested {
                let Some(price) = nested_value.as_f64() else {
                    continue;
                };
                let (size, quality) = if key_is_quality {
                    (nested_key.as_str(), key.as_str())
                } else {
                    (key.as_str(), nested_key.as_str())
                };
                entries.insert(image_price_key(size, quality), json!(price));
            }
        }
        return;
    }

    if let Some(items) = value.as_array() {
        for item in items.iter().filter_map(Value::as_object) {
            let Some(size) = item.get("size").and_then(Value::as_str) else {
                continue;
            };
            let quality = item
                .get("quality")
                .and_then(Value::as_str)
                .unwrap_or("medium");
            let Some(price) = item
                .get("price_per_image")
                .or_else(|| item.get("price"))
                .or_else(|| item.get("cost"))
                .and_then(Value::as_f64)
            else {
                continue;
            };
            entries.insert(image_price_key(size, quality), json!(price));
        }
    }
}

fn normalize_image_price_key(value: &str) -> String {
    if let Some((size, quality)) = value.split_once(':').or_else(|| value.split_once('|')) {
        return image_price_key(size, quality);
    }
    value.trim().to_ascii_lowercase().replace(' ', "")
}

fn image_price_key(size: &str, quality: &str) -> String {
    format!(
        "{}:{}",
        normalize_image_size(size),
        normalize_image_quality(quality)
    )
}

fn normalize_image_size(value: &str) -> String {
    value.trim().to_ascii_lowercase().replace(' ', "")
}

fn normalize_image_quality(value: &str) -> String {
    value.trim().to_ascii_lowercase()
}

fn matches_quality_key(value: &str) -> bool {
    matches!(
        normalize_image_quality(value).as_str(),
        "low" | "medium" | "high"
    )
}

#[cfg(test)]
mod video_pricing_tests {
    use super::*;
    use serde_json::json;

    fn video_config() -> Value {
        json!({
            "price_per_second_by_resolution": {
                "480p": 1.0,
                "720p": 2.0,
                "1080p": 3.0,
                "1280x720": 2.5
            }
        })
    }

    #[test]
    fn resolution_keys_normalize_across_provider_spellings() {
        for value in ["720p", "720P", " 720p ", "  720P"] {
            assert_eq!(normalize_video_resolution_key(value), "720p", "{value}");
        }
        // A pixel pair is ordered smallest-first so portrait and landscape
        // share one configured price.
        for value in ["1280x720", "720x1280", "1280X720", "1280×720", "1280 x 720"] {
            assert_eq!(normalize_video_resolution_key(value), "720x1280", "{value}");
        }
    }

    #[test]
    fn tier_and_pixel_spellings_both_resolve_a_price() {
        let config = video_config();
        assert_eq!(
            resolve_video_price_per_second(Some(&config), Some("720p")),
            2.0
        );
        assert_eq!(
            resolve_video_price_per_second(Some(&config), Some("720P")),
            2.0
        );
        // `1280x720` is stored landscape but normalizes to `720x1280`, so both
        // orientations hit the same entry.
        assert_eq!(
            resolve_video_price_per_second(Some(&config), Some("1280x720")),
            2.5
        );
        assert_eq!(
            resolve_video_price_per_second(Some(&config), Some("720x1280")),
            2.5
        );
    }

    #[test]
    fn unknown_or_missing_resolution_prices_at_zero() {
        let config = video_config();
        assert_eq!(
            resolve_video_price_per_second(Some(&config), Some("8k")),
            0.0
        );
        assert_eq!(resolve_video_price_per_second(Some(&config), None), 0.0);
        assert_eq!(
            resolve_video_price_per_second(Some(&config), Some("   ")),
            0.0
        );
        assert_eq!(resolve_video_price_per_second(None, Some("720p")), 0.0);
    }

    #[test]
    fn an_empty_or_malformed_table_never_resolves_a_price() {
        assert!(!video_pricing_state(Some(&json!({}))).per_second_enabled);
        assert!(!video_pricing_state(None).per_second_enabled);
        let config = json!({
            "price_per_second_by_resolution": {"720p": "2.0", "1080p": -3.0}
        });
        assert!(video_pricing_state(Some(&config)).per_second_enabled);
        // The table is configured, but neither malformed value may become a
        // price or a negative credit.
        assert_eq!(
            resolve_video_price_per_second(Some(&config), Some("720p")),
            0.0
        );
        assert_eq!(
            resolve_video_price_per_second(Some(&config), Some("1080p")),
            0.0
        );
    }

    #[test]
    fn per_second_mode_zeroes_every_token_price_and_drops_token_tiers() {
        let pricing = BillingPricingResolution {
            tiered_pricing: Some(json!({
                "tiers": [{
                    "up_to": null,
                    "input_price_per_1m": 3.0,
                    "output_price_per_1m": 15.0,
                    "cache_creation_price_per_1m": 3.75,
                    "cache_read_price_per_1m": 0.3,
                    "cache_ttl_pricing": [{
                        "ttl_minutes": 60,
                        "cache_creation_price_per_1m": 6.0,
                        "cache_read_price_per_1m": 1.0
                    }]
                }]
            })),
            video_pricing: Some(video_config()),
            ..Default::default()
        };
        let rule = DefaultBillingRuleGenerator::generate_for_pricing("seedance", &pricing, "video")
            .expect("per-second video pricing must generate a rule");

        // Enforced at rule level so a stale token or cache price in the config
        // cannot double-charge alongside the per-second price.
        for key in [
            "input_price_per_1m",
            "output_price_per_1m",
            "cache_creation_price_per_1m",
            "cache_creation_ephemeral_5m_price_per_1m",
            "cache_creation_ephemeral_1h_price_per_1m",
            "cache_read_price_per_1m",
        ] {
            assert_eq!(
                rule.variables.get(key),
                Some(&json!(0.0)),
                "{key} must not keep a token rate"
            );
            assert_eq!(
                rule.dimension_mappings
                    .get(key)
                    .and_then(|value| value.get("tiers"))
                    .and_then(Value::as_array)
                    .map(Vec::len),
                Some(0),
                "{key} must not resolve a stale token tier"
            );
        }
        assert!(rule.expression.contains("video_cost"));
        assert_eq!(
            rule.dimension_mappings
                .get("video_cost")
                .and_then(|value| value.get("expression"))
                .and_then(Value::as_str),
            Some("video_seconds_unmetered * video_price_per_second")
        );
    }

    #[test]
    fn video_table_keeps_token_prices_for_chat_and_image_usage() {
        let pricing = BillingPricingResolution {
            tiered_pricing: Some(json!({
                "tiers": [{
                    "up_to": null,
                    "input_price_per_1m": 3.0,
                    "output_price_per_1m": 15.0,
                    "cache_creation_price_per_1m": 3.75,
                    "cache_read_price_per_1m": 0.3
                }],
                "image_output_price_default": 0.04
            })),
            price_per_request: Some(0.02),
            video_pricing: Some(video_config()),
            ..Default::default()
        };
        for task_type in ["chat", "image"] {
            let rule =
                DefaultBillingRuleGenerator::generate_for_pricing("seedance", &pricing, task_type)
                    .expect("ordinary usage on a video-capable model must still bill");

            assert_eq!(
                rule.variables.get("input_price_per_1m"),
                Some(&json!(3.0)),
                "{task_type} input price"
            );
            assert_eq!(
                rule.variables.get("output_price_per_1m"),
                Some(&json!(15.0)),
                "{task_type} output price"
            );
            assert_eq!(
                rule.variables.get("cache_creation_price_per_1m"),
                Some(&json!(3.75)),
                "{task_type} cache creation price"
            );
            assert_eq!(
                rule.variables.get("cache_read_price_per_1m"),
                Some(&json!(0.3)),
                "{task_type} cache read price"
            );
            for key in [
                "input_price_per_1m",
                "output_price_per_1m",
                "cache_creation_price_per_1m",
                "cache_read_price_per_1m",
            ] {
                assert_eq!(
                    rule.dimension_mappings
                        .get(key)
                        .and_then(|value| value.get("tiers"))
                        .and_then(Value::as_array)
                        .map(Vec::len),
                    Some(1),
                    "{task_type} {key} keeps its configured tier"
                );
            }
        }
    }

    #[test]
    fn video_modality_comes_from_task_type_or_endpoint_kind() {
        assert!(usage_is_video("video", Some("openai:video")));
        assert!(usage_is_video("VIDEO", Some("openai:chat")));
        assert!(usage_is_video("chat", Some("openai:video")));
        assert!(!usage_is_video("chat", Some("openai:chat")));
        assert!(!usage_is_video("image", Some("openai:image")));
        assert!(!usage_is_video("chat", None));
    }

    #[test]
    fn token_pricing_is_unchanged_without_video_config() {
        let pricing = BillingPricingResolution {
            tiered_pricing: Some(json!({
                "tiers": [{
                    "up_to": null,
                    "input_price_per_1m": 3.0,
                    "output_price_per_1m": 15.0
                }]
            })),
            ..Default::default()
        };
        let rule = DefaultBillingRuleGenerator::generate_for_pricing("gpt-5", &pricing, "chat")
            .expect("token pricing must still generate a rule");

        assert_eq!(rule.variables.get("input_price_per_1m"), Some(&json!(3.0)));
        assert_eq!(
            rule.variables.get("output_price_per_1m"),
            Some(&json!(15.0))
        );
        assert_eq!(
            rule.dimension_mappings
                .get("output_price_per_1m")
                .and_then(|value| value.get("tiers"))
                .and_then(Value::as_array)
                .map(Vec::len),
            Some(1)
        );
        assert!(rule.expression.contains("video_cost"));
    }

    #[test]
    fn per_second_pricing_alone_is_enough_to_generate_a_rule() {
        let pricing = BillingPricingResolution {
            video_pricing: Some(video_config()),
            ..Default::default()
        };
        assert!(
            DefaultBillingRuleGenerator::generate_for_pricing("seedance", &pricing, "video")
                .is_some(),
            "a model priced only by rendered seconds must still bill"
        );
    }

    #[test]
    fn no_pricing_at_all_generates_no_rule() {
        assert!(DefaultBillingRuleGenerator::generate_for_pricing(
            "seedance",
            &BillingPricingResolution::default(),
            "video",
        )
        .is_none());
    }
}
