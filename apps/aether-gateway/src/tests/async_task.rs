use aether_crypto::{encrypt_python_fernet_plaintext, DEVELOPMENT_ENCRYPTION_KEY};
use aether_data::repository::billing::InMemoryBillingReadRepository;
use aether_data::repository::provider_catalog::InMemoryProviderCatalogReadRepository;
use aether_data::repository::settlement::InMemorySettlementRepository;
use aether_data::repository::usage::InMemoryUsageReadRepository;
use aether_data::repository::video_tasks::InMemoryVideoTaskRepository;
use aether_data::repository::wallet::{InMemoryWalletRepository, StoredWalletSnapshot};
use aether_data_contracts::repository::billing::StoredBillingModelContext;
use aether_data_contracts::repository::provider_catalog::{
    StoredProviderCatalogEndpoint, StoredProviderCatalogKey, StoredProviderCatalogProvider,
};
use aether_data_contracts::repository::usage::UsageReadRepository;
use aether_data_contracts::repository::video_tasks::{
    UpsertVideoTask, VideoTaskLookupKey, VideoTaskReadRepository, VideoTaskStatus,
    VideoTaskWriteRepository,
};
use aether_data_contracts::repository::wallet::{WalletLookupKey, WalletReadRepository};
use std::collections::BTreeMap;

use super::{
    any, authenticated_operational_client, build_state_with_execution_runtime_override, json,
    start_authenticated_operational_server, start_server, to_bytes, AppState, Arc, Body, Bytes,
    HeaderValue, Json, Mutex, Request, Response, Router, StatusCode,
};

fn sample_video_task(
    id: &str,
    status: VideoTaskStatus,
    created_at_unix_ms: u64,
    model: &str,
    user_id: &str,
    client_api_format: &str,
) -> UpsertVideoTask {
    UpsertVideoTask {
        id: id.to_string(),
        short_id: Some(format!("short-{id}")),
        request_id: format!("request-{id}"),
        user_id: Some(user_id.to_string()),
        api_key_id: Some(format!("api-key-{id}")),
        username: Some(format!("user-{user_id}")),
        api_key_name: Some("primary".to_string()),
        external_task_id: Some(format!("ext-{id}")),
        provider_id: Some("provider-1".to_string()),
        endpoint_id: Some("endpoint-1".to_string()),
        key_id: Some("provider-key-1".to_string()),
        client_api_format: Some(client_api_format.to_string()),
        provider_api_format: Some(client_api_format.to_string()),
        format_converted: false,
        model: Some(model.to_string()),
        prompt: Some(format!("prompt-{id}")),
        original_request_body: Some(json!({"prompt": format!("prompt-{id}")})),
        duration_seconds: Some(4),
        resolution: Some("720p".to_string()),
        aspect_ratio: Some("16:9".to_string()),
        size: Some("1280x720".to_string()),
        status,
        progress_percent: if matches!(status, VideoTaskStatus::Completed) {
            100
        } else {
            50
        },
        progress_message: Some("ok".to_string()),
        retry_count: 0,
        poll_interval_seconds: 10,
        next_poll_at_unix_secs: if status.is_active() {
            Some(created_at_unix_ms.saturating_add(10))
        } else {
            None
        },
        poll_count: 0,
        max_poll_count: 360,
        created_at_unix_ms,
        submitted_at_unix_secs: Some(created_at_unix_ms),
        completed_at_unix_secs: if matches!(status, VideoTaskStatus::Completed) {
            Some(created_at_unix_ms.saturating_add(30))
        } else {
            None
        },
        updated_at_unix_secs: created_at_unix_ms.saturating_add(5),
        error_code: None,
        error_message: None,
        video_url: None,
        request_metadata: None,
    }
}

fn bound_provider_api_key(provider_id: &str, key_id: &str, plaintext: &str) -> String {
    let purpose = format!(
        "provider-catalog-credential-bound-v2\0provider-id-bytes={}\0{provider_id}\0key-id-bytes={}\0{key_id}\0field=api-key",
        provider_id.len(),
        key_id.len(),
    );
    let protected = format!("{purpose}\0{plaintext}");
    let ciphertext = encrypt_python_fernet_plaintext(DEVELOPMENT_ENCRYPTION_KEY, &protected)
        .expect("bound provider api key should encrypt");
    format!("aether-provider-catalog-credential-v2:aether-runtime-secret-v1:{ciphertext}")
}

fn video_provider_catalog_repository(
    provider_id: &str,
    provider_type: &str,
    endpoint_id: &str,
    api_format: &str,
    endpoint_base_url: &str,
    key_id: &str,
    upstream_api_key: &str,
) -> Arc<InMemoryProviderCatalogReadRepository> {
    let provider = StoredProviderCatalogProvider::new(
        provider_id.to_string(),
        format!("video-{provider_type}"),
        Some("https://example.com".to_string()),
        provider_type.to_string(),
    )
    .expect("provider should build")
    .with_transport_fields(
        true,
        false,
        false,
        None,
        Some(2),
        None,
        Some(20.0),
        None,
        None,
    );
    let endpoint = StoredProviderCatalogEndpoint::new(
        endpoint_id.to_string(),
        provider_id.to_string(),
        api_format.to_string(),
        Some(provider_type.to_string()),
        Some("video".to_string()),
        true,
    )
    .expect("endpoint should build")
    .with_transport_fields(
        endpoint_base_url.to_string(),
        None,
        None,
        Some(2),
        None,
        None,
        None,
        None,
    )
    .expect("endpoint transport should build");
    let key = StoredProviderCatalogKey::new(
        key_id.to_string(),
        provider_id.to_string(),
        "primary".to_string(),
        "api_key".to_string(),
        None,
        true,
    )
    .expect("key should build")
    .with_transport_fields(
        Some(json!([api_format])),
        bound_provider_api_key(provider_id, key_id, upstream_api_key),
        None,
        None,
        Some(json!({api_format: 1})),
        None,
        None,
        None,
        None,
    )
    .expect("key transport should build");
    Arc::new(InMemoryProviderCatalogReadRepository::seed(
        vec![provider],
        vec![endpoint],
        vec![key],
    ))
}

#[tokio::test]
async fn gateway_lists_video_tasks_via_internal_async_task_endpoint() {
    let repository = Arc::new(InMemoryVideoTaskRepository::default());
    repository
        .upsert(sample_video_task(
            "task-1",
            VideoTaskStatus::Completed,
            100,
            "sora-2",
            "user-1",
            "openai:video",
        ))
        .await
        .expect("upsert should succeed");
    repository
        .upsert(sample_video_task(
            "task-2",
            VideoTaskStatus::Processing,
            200,
            "sora-2",
            "user-1",
            "openai:video",
        ))
        .await
        .expect("upsert should succeed");
    repository
        .upsert(sample_video_task(
            "task-3",
            VideoTaskStatus::Completed,
            300,
            "veo-3",
            "user-2",
            "gemini:video",
        ))
        .await
        .expect("upsert should succeed");

    let state = AppState::new()
        .expect("gateway state should build")
        .with_video_task_data_repository_for_tests(repository);
    let (gateway_url, gateway_handle, access_token) =
        start_authenticated_operational_server(state).await;
    let client = authenticated_operational_client(&access_token);

    let response = client
        .get(format!(
            "{gateway_url}/_gateway/async-tasks/video-tasks?status=completed&page=1&page_size=1"
        ))
        .send()
        .await
        .expect("request should succeed");

    assert_eq!(response.status(), StatusCode::OK);
    let body: serde_json::Value = response.json().await.expect("body should parse");
    assert_eq!(body["total"], 2);
    assert_eq!(body["page"], 1);
    assert_eq!(body["page_size"], 1);
    assert_eq!(body["pages"], 2);
    assert_eq!(body["items"].as_array().map(Vec::len), Some(1));
    assert_eq!(body["items"][0]["id"], "task-3");

    gateway_handle.abort();
}

#[tokio::test]
async fn gateway_exposes_video_task_stats_via_internal_async_task_endpoint() {
    let repository = Arc::new(InMemoryVideoTaskRepository::default());
    let now_unix_secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("time should be monotonic")
        .as_secs();
    repository
        .upsert(sample_video_task(
            "task-1",
            VideoTaskStatus::Completed,
            now_unix_secs,
            "sora-2",
            "user-1",
            "openai:video",
        ))
        .await
        .expect("upsert should succeed");
    repository
        .upsert(sample_video_task(
            "task-2",
            VideoTaskStatus::Processing,
            now_unix_secs.saturating_sub(86_400),
            "veo-3",
            "user-2",
            "gemini:video",
        ))
        .await
        .expect("upsert should succeed");

    let state = AppState::new()
        .expect("gateway state should build")
        .with_video_task_data_repository_for_tests(repository);
    let (gateway_url, gateway_handle, access_token) =
        start_authenticated_operational_server(state).await;
    let client = authenticated_operational_client(&access_token);

    let response = client
        .get(format!(
            "{gateway_url}/_gateway/async-tasks/video-tasks/stats"
        ))
        .send()
        .await
        .expect("request should succeed");

    assert_eq!(response.status(), StatusCode::OK);
    let body: serde_json::Value = response.json().await.expect("body should parse");
    assert_eq!(body["total"], 2);
    assert_eq!(body["by_status"]["completed"], 1);
    assert_eq!(body["by_status"]["processing"], 1);
    assert_eq!(body["by_model"]["sora-2"], 1);
    assert_eq!(body["by_model"]["veo-3"], 1);
    assert_eq!(body["today_count"], 1);
    assert_eq!(body["processing_count"], 1);

    gateway_handle.abort();
}

#[tokio::test]
async fn gateway_reads_video_task_detail_via_internal_async_task_endpoint() {
    let repository = Arc::new(InMemoryVideoTaskRepository::default());
    repository
        .upsert(sample_video_task(
            "task-1",
            VideoTaskStatus::Completed,
            100,
            "sora-2",
            "user-1",
            "openai:video",
        ))
        .await
        .expect("upsert should succeed");

    let state = AppState::new()
        .expect("gateway state should build")
        .with_video_task_data_repository_for_tests(repository);
    let (gateway_url, gateway_handle, access_token) =
        start_authenticated_operational_server(state).await;
    let client = authenticated_operational_client(&access_token);

    let response = client
        .get(format!(
            "{gateway_url}/_gateway/async-tasks/video-tasks/task-1"
        ))
        .send()
        .await
        .expect("request should succeed");

    assert_eq!(response.status(), StatusCode::OK);
    let body: serde_json::Value = response.json().await.expect("body should parse");
    assert_eq!(body["id"], "task-1");
    assert_eq!(body["request_id"], "request-task-1");
    assert_eq!(body["model"], "sora-2");
    assert_eq!(body["status"], "Completed");

    gateway_handle.abort();
}

#[tokio::test]
async fn gateway_redirects_persisted_openai_video_url_from_authenticated_internal_endpoint() {
    let repository = Arc::new(InMemoryVideoTaskRepository::default());
    let mut task = sample_video_task(
        "task-redirect",
        VideoTaskStatus::Completed,
        100,
        "sora-2",
        "user-1",
        "openai:video",
    );
    task.video_url = Some("https://8.8.8.8/video-task-redirect.mp4".to_string());
    let stored = repository
        .upsert(task)
        .await
        .expect("upsert should succeed");
    assert_eq!(
        stored.video_url.as_deref(),
        Some("https://8.8.8.8/video-task-redirect.mp4")
    );

    let state = AppState::new()
        .expect("gateway state should build")
        .with_video_task_data_repository_for_tests(repository);
    let (gateway_url, gateway_handle, access_token) =
        start_authenticated_operational_server(state).await;

    let client = super::authenticated_operational_client_with_builder(
        reqwest::Client::builder().redirect(reqwest::redirect::Policy::none()),
        &access_token,
    );
    let response = client
        .get(format!(
            "{gateway_url}/_gateway/async-tasks/video-tasks/task-redirect/video"
        ))
        .send()
        .await
        .expect("request should succeed");

    assert_eq!(response.status(), StatusCode::TEMPORARY_REDIRECT);
    assert_eq!(
        response
            .headers()
            .get("location")
            .and_then(|value| value.to_str().ok()),
        stored.video_url.as_deref()
    );

    gateway_handle.abort();
}

#[tokio::test]
async fn gateway_rejects_private_gemini_video_target_without_sending_provider_key() {
    let seen_api_key = Arc::new(Mutex::new(None::<String>));
    let seen_api_key_clone = Arc::clone(&seen_api_key);

    let upstream = Router::new().route(
        "/generativelanguage.googleapis.com/v1beta/files/video-task-123:download",
        any(move |request: Request| {
            let seen_api_key_inner = Arc::clone(&seen_api_key_clone);
            async move {
                *seen_api_key_inner.lock().expect("mutex should lock") = request
                    .headers()
                    .get("x-goog-api-key")
                    .and_then(|value| value.to_str().ok())
                    .map(ToOwned::to_owned);
                let mut response = Response::builder()
                    .status(StatusCode::OK)
                    .body(Body::from("proxied-video-bytes"))
                    .expect("response should build");
                response.headers_mut().insert(
                    http::header::CONTENT_TYPE,
                    HeaderValue::from_static("video/mp4"),
                );
                response
            }
        }),
    );
    let (upstream_url, upstream_handle) = start_server(upstream).await;

    let repository = Arc::new(InMemoryVideoTaskRepository::default());
    let mut task = sample_video_task(
        "task-proxy",
        VideoTaskStatus::Completed,
        100,
        "veo-3",
        "user-1",
        "gemini:video",
    );
    task.provider_id = Some("provider-gemini-video-1".to_string());
    task.endpoint_id = Some("endpoint-gemini-video-1".to_string());
    task.key_id = Some("key-gemini-video-1".to_string());
    task.video_url = Some(format!(
        "{upstream_url}/generativelanguage.googleapis.com/v1beta/files/video-task-123:download"
    ));
    repository
        .upsert(task)
        .await
        .expect("upsert should succeed");

    let provider_catalog_repository = Arc::new(InMemoryProviderCatalogReadRepository::seed(
        vec![StoredProviderCatalogProvider::new(
            "provider-gemini-video-1".to_string(),
            "gemini".to_string(),
            Some("https://ai.google.dev".to_string()),
            "custom".to_string(),
        )
        .expect("provider should build")
        .with_transport_fields(
            true,
            false,
            false,
            None,
            Some(2),
            None,
            Some(20.0),
            None,
            None,
        )],
        vec![StoredProviderCatalogEndpoint::new(
            "endpoint-gemini-video-1".to_string(),
            "provider-gemini-video-1".to_string(),
            "gemini:video".to_string(),
            Some("gemini".to_string()),
            Some("video".to_string()),
            true,
        )
        .expect("endpoint should build")
        .with_transport_fields(
            upstream_url.clone(),
            None,
            None,
            Some(2),
            None,
            None,
            None,
            None,
        )
        .expect("endpoint transport should build")],
        vec![StoredProviderCatalogKey::new(
            "key-gemini-video-1".to_string(),
            "provider-gemini-video-1".to_string(),
            "primary".to_string(),
            "api_key".to_string(),
            None,
            true,
        )
        .expect("key should build")
        .with_transport_fields(
            Some(json!(["gemini:video"])),
            bound_provider_api_key(
                "provider-gemini-video-1",
                "key-gemini-video-1",
                "gemini-upstream-secret",
            ),
            None,
            None,
            Some(json!({"gemini:video": 1})),
            None,
            None,
            None,
            None,
        )
        .expect("key transport should build")],
    ));

    let state = AppState::new()
        .expect("gateway state should build")
        .with_data_state_for_tests(
        crate::data::GatewayDataState::with_video_task_repository_and_provider_transport_for_tests(
            repository,
            provider_catalog_repository,
            DEVELOPMENT_ENCRYPTION_KEY,
        ),
    );
    let (gateway_url, gateway_handle, access_token) =
        start_authenticated_operational_server(state).await;
    let client = authenticated_operational_client(&access_token);

    let response = client
        .get(format!(
            "{gateway_url}/_gateway/async-tasks/video-tasks/task-proxy/video"
        ))
        .send()
        .await
        .expect("request should succeed");

    assert_eq!(response.status(), StatusCode::BAD_GATEWAY);
    assert_eq!(
        seen_api_key.lock().expect("mutex should lock").as_deref(),
        None
    );

    gateway_handle.abort();
    upstream_handle.abort();
}

#[tokio::test]
async fn gateway_cancels_openai_video_task_via_internal_async_task_endpoint() {
    #[derive(Debug, Clone, PartialEq, Eq)]
    struct SeenExecutionRuntimeSyncRequest {
        method: String,
        url: String,
        authorization: String,
    }

    let seen_execution_runtime = Arc::new(Mutex::new(None::<SeenExecutionRuntimeSyncRequest>));
    let seen_execution_runtime_clone = Arc::clone(&seen_execution_runtime);
    let execution_runtime = Router::new().route(
        "/v1/execute/sync",
        any(move |request: Request| {
            let seen_execution_runtime_inner = Arc::clone(&seen_execution_runtime_clone);
            async move {
                let (_parts, body) = request.into_parts();
                let raw_body = to_bytes(body, usize::MAX).await.expect("body should read");
                let payload: serde_json::Value =
                    serde_json::from_slice(&raw_body).expect("payload should parse");
                *seen_execution_runtime_inner
                    .lock()
                    .expect("mutex should lock") = Some(SeenExecutionRuntimeSyncRequest {
                    method: payload
                        .get("method")
                        .and_then(|value| value.as_str())
                        .unwrap_or_default()
                        .to_string(),
                    url: payload
                        .get("url")
                        .and_then(|value| value.as_str())
                        .unwrap_or_default()
                        .to_string(),
                    authorization: payload
                        .get("headers")
                        .and_then(|value| value.get("authorization"))
                        .and_then(|value| value.as_str())
                        .unwrap_or_default()
                        .to_string(),
                });
                Json(json!({
                    "request_id": "cancel-openai-task-1",
                    "status_code": 204,
                    "headers": {},
                    "telemetry": {
                        "elapsed_ms": 11
                    }
                }))
            }
        }),
    );

    let repository = Arc::new(InMemoryVideoTaskRepository::default());
    let mut task = sample_video_task(
        "task-openai-cancel",
        VideoTaskStatus::Processing,
        100,
        "sora-2",
        "user-1",
        "openai:video",
    );
    task.external_task_id = Some("ext-video-task-123".to_string());
    task.request_metadata = Some(json!({
        "rust_local_snapshot": {
            "OpenAi": {
                "local_task_id": "task-openai-cancel",
                "upstream_task_id": "ext-video-task-123",
                "created_at_unix_ms": 100,
                "user_id": "user-1",
                "api_key_id": "api-key-task-openai-cancel",
                "model": "sora-2",
                "prompt": "prompt-task-openai-cancel",
                "size": "1280x720",
                "seconds": "4",
                "remixed_from_video_id": null,
                "status": "Processing",
                "progress_percent": 50,
                "completed_at_unix_secs": null,
                "expires_at_unix_secs": null,
                "error_code": null,
                "error_message": null,
                "video_url": null,
                "persistence": {
                    "request_id": "request-task-openai-cancel",
                    "username": "user-user-1",
                    "api_key_name": "primary",
                    "client_api_format": "openai:video",
                    "provider_api_format": "openai:video",
                    "original_request_body": {
                        "prompt": "prompt-task-openai-cancel"
                    },
                    "format_converted": false
                },
                "transport": {
                    "upstream_base_url": "https://api.openai.example/v1",
                    "provider_name": "openai-video",
                    "provider_id": "provider-1",
                    "endpoint_id": "endpoint-1",
                    "key_id": "provider-key-1",
                    "headers": {
                        "authorization": "Bearer sk-upstream-openai-video",
                        "content-type": "application/json"
                    },
                    "content_type": "application/json",
                    "model_name": "sora-2-upstream",
                    "proxy": null,
                    "transport_profile": null,
                    "timeouts": null
                }
            }
        }
    }));
    repository
        .upsert(task)
        .await
        .expect("upsert should succeed");

    let provider_catalog_repository = video_provider_catalog_repository(
        "provider-1",
        "openai",
        "endpoint-1",
        "openai:video",
        "https://api.openai.example/v1",
        "provider-key-1",
        "sk-upstream-openai-video",
    );
    let (execution_runtime_url, execution_runtime_handle) = start_server(execution_runtime).await;
    let state = build_state_with_execution_runtime_override(execution_runtime_url)
        .with_data_state_for_tests(
        crate::data::GatewayDataState::with_video_task_repository_and_provider_transport_for_tests(
            Arc::clone(&repository),
            provider_catalog_repository,
            DEVELOPMENT_ENCRYPTION_KEY,
        ),
    );
    let (gateway_url, gateway_handle, access_token) =
        start_authenticated_operational_server(state).await;
    let client = authenticated_operational_client(&access_token);

    let response = client
        .post(format!(
            "{gateway_url}/_gateway/async-tasks/video-tasks/task-openai-cancel/cancel"
        ))
        .send()
        .await
        .expect("request should succeed");

    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response
            .json::<serde_json::Value>()
            .await
            .expect("body should parse"),
        json!({
            "id": "task-openai-cancel",
            "status": "cancelled",
            "message": "Task cancelled successfully",
        })
    );

    let seen_execution_runtime_request = seen_execution_runtime
        .lock()
        .expect("mutex should lock")
        .clone()
        .expect("execution runtime should be called");
    assert_eq!(seen_execution_runtime_request.method, "DELETE");
    assert_eq!(
        seen_execution_runtime_request.url,
        "https://api.openai.example/v1/videos/ext-video-task-123"
    );
    assert_eq!(
        seen_execution_runtime_request.authorization,
        "Bearer sk-upstream-openai-video"
    );

    let detail = client
        .get(format!(
            "{gateway_url}/_gateway/async-tasks/video-tasks/task-openai-cancel"
        ))
        .send()
        .await
        .expect("detail request should succeed");
    assert_eq!(detail.status(), StatusCode::OK);
    let detail_json: serde_json::Value = detail.json().await.expect("detail should parse");
    assert_eq!(detail_json["status"], "Cancelled");
    assert!(detail_json["next_poll_at_unix_secs"].is_null());
    assert!(detail_json["original_request_body"].is_null());
    assert!(detail_json["progress_message"].is_null());
    assert!(detail_json["error_message"].is_null());
    assert!(detail_json["request_metadata"].is_null());

    gateway_handle.abort();
    execution_runtime_handle.abort();
}

#[tokio::test]
async fn gateway_cancels_openai_video_task_via_internal_async_task_endpoint_without_execution_runtime_override(
) {
    #[derive(Debug, Clone, PartialEq, Eq)]
    struct SeenUpstreamDeleteRequest {
        method: String,
        path: String,
        authorization: String,
    }

    let seen_upstream = Arc::new(Mutex::new(None::<SeenUpstreamDeleteRequest>));
    let seen_upstream_clone = Arc::clone(&seen_upstream);
    let upstream = Router::new().route(
        "/v1/videos/ext-video-task-123",
        any(move |request: Request| {
            let seen_upstream_inner = Arc::clone(&seen_upstream_clone);
            async move {
                *seen_upstream_inner.lock().expect("mutex should lock") =
                    Some(SeenUpstreamDeleteRequest {
                        method: request.method().as_str().to_string(),
                        path: request.uri().path().to_string(),
                        authorization: request
                            .headers()
                            .get(http::header::AUTHORIZATION)
                            .and_then(|value| value.to_str().ok())
                            .unwrap_or_default()
                            .to_string(),
                    });
                StatusCode::NO_CONTENT
            }
        }),
    );

    let repository = Arc::new(InMemoryVideoTaskRepository::default());
    let mut task = sample_video_task(
        "task-openai-cancel-direct",
        VideoTaskStatus::Processing,
        100,
        "sora-2",
        "user-1",
        "openai:video",
    );
    task.external_task_id = Some("ext-video-task-123".to_string());
    let (upstream_url, upstream_handle) = start_server(upstream).await;
    let upstream_api_root = format!("{upstream_url}/v1");
    task.request_metadata = Some(json!({
        "rust_local_snapshot": {
            "OpenAi": {
                "local_task_id": "task-openai-cancel-direct",
                "upstream_task_id": "ext-video-task-123",
                "created_at_unix_ms": 100,
                "user_id": "user-1",
                "api_key_id": "api-key-task-openai-cancel",
                "model": "sora-2",
                "prompt": "prompt-task-openai-cancel",
                "size": "1280x720",
                "seconds": "4",
                "remixed_from_video_id": null,
                "status": "Processing",
                "progress_percent": 50,
                "completed_at_unix_secs": null,
                "expires_at_unix_secs": null,
                "error_code": null,
                "error_message": null,
                "video_url": null,
                "persistence": {
                    "request_id": "request-task-openai-cancel-direct",
                    "username": "user-user-1",
                    "api_key_name": "primary",
                    "client_api_format": "openai:video",
                    "provider_api_format": "openai:video",
                    "original_request_body": {
                        "prompt": "prompt-task-openai-cancel"
                    },
                    "format_converted": false
                },
                "transport": {
                    "upstream_base_url": upstream_api_root,
                    "provider_name": "openai-video",
                    "provider_id": "provider-1",
                    "endpoint_id": "endpoint-1",
                    "key_id": "provider-key-1",
                    "headers": {
                        "authorization": "Bearer sk-upstream-openai-video",
                        "content-type": "application/json"
                    },
                    "content_type": "application/json",
                    "model_name": "sora-2-upstream",
                    "proxy": null,
                    "transport_profile": null,
                    "timeouts": null
                }
            }
        }
    }));
    repository
        .upsert(task)
        .await
        .expect("upsert should succeed");

    let provider_catalog_repository = video_provider_catalog_repository(
        "provider-1",
        "openai",
        "endpoint-1",
        "openai:video",
        &upstream_api_root,
        "provider-key-1",
        "sk-upstream-openai-video",
    );
    let state = AppState::new()
        .expect("gateway state should build")
        .with_data_state_for_tests(
        crate::data::GatewayDataState::with_video_task_repository_and_provider_transport_for_tests(
            Arc::clone(&repository),
            provider_catalog_repository,
            DEVELOPMENT_ENCRYPTION_KEY,
        ),
    );
    let (gateway_url, gateway_handle, access_token) =
        start_authenticated_operational_server(state).await;
    let client = authenticated_operational_client(&access_token);

    let response = client
        .post(format!(
            "{gateway_url}/_gateway/async-tasks/video-tasks/task-openai-cancel-direct/cancel"
        ))
        .send()
        .await
        .expect("request should succeed");

    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response
            .json::<serde_json::Value>()
            .await
            .expect("body should parse"),
        json!({
            "id": "task-openai-cancel-direct",
            "status": "cancelled",
            "message": "Task cancelled successfully",
        })
    );

    assert_eq!(
        seen_upstream.lock().expect("mutex should lock").clone(),
        Some(SeenUpstreamDeleteRequest {
            method: "DELETE".to_string(),
            path: "/v1/videos/ext-video-task-123".to_string(),
            authorization: "Bearer sk-upstream-openai-video".to_string(),
        })
    );

    let detail = client
        .get(format!(
            "{gateway_url}/_gateway/async-tasks/video-tasks/task-openai-cancel-direct"
        ))
        .send()
        .await
        .expect("detail request should succeed");
    assert_eq!(detail.status(), StatusCode::OK);
    let detail_json: serde_json::Value = detail.json().await.expect("detail should parse");
    assert_eq!(detail_json["status"], "Cancelled");
    assert!(detail_json["next_poll_at_unix_secs"].is_null());
    assert!(detail_json["original_request_body"].is_null());
    assert!(detail_json["progress_message"].is_null());
    assert!(detail_json["error_message"].is_null());
    assert!(detail_json["request_metadata"].is_null());

    gateway_handle.abort();
    upstream_handle.abort();
}

#[tokio::test]
async fn gateway_rejects_terminal_video_task_cancel_via_internal_async_task_endpoint() {
    let repository = Arc::new(InMemoryVideoTaskRepository::default());
    repository
        .upsert(sample_video_task(
            "task-cancelled-already",
            VideoTaskStatus::Completed,
            100,
            "sora-2",
            "user-1",
            "openai:video",
        ))
        .await
        .expect("upsert should succeed");

    let state = AppState::new()
        .expect("gateway state should build")
        .with_video_task_data_repository_for_tests(repository);
    let (gateway_url, gateway_handle, access_token) =
        start_authenticated_operational_server(state).await;
    let client = authenticated_operational_client(&access_token);

    let response = client
        .post(format!(
            "{gateway_url}/_gateway/async-tasks/video-tasks/task-cancelled-already/cancel"
        ))
        .send()
        .await
        .expect("request should succeed");

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    assert_eq!(
        response
            .json::<serde_json::Value>()
            .await
            .expect("body should parse"),
        json!({
            "error": {
                "message": "Cannot cancel task with status: completed",
            }
        })
    );

    gateway_handle.abort();
}

#[tokio::test]
async fn user_scoped_video_task_cancel_rechecks_owner_before_side_effects() {
    let repository = Arc::new(InMemoryVideoTaskRepository::default());
    repository
        .upsert(sample_video_task(
            "task-owner-bound-cancel",
            VideoTaskStatus::Processing,
            100,
            "sora-2",
            "user-owner",
            "openai:video",
        ))
        .await
        .expect("upsert should succeed");
    let state = AppState::new()
        .expect("gateway state should build")
        .with_video_task_data_repository_for_tests(Arc::clone(&repository));

    let error = crate::async_task::cancel_video_task_record_for_user(
        &state,
        "task-owner-bound-cancel",
        "user-foreign",
    )
    .await
    .expect_err("a non-owner cancellation must be hidden as not found");

    assert!(matches!(
        error,
        crate::async_task::CancelVideoTaskError::NotFound
    ));
    let stored = repository
        .find(VideoTaskLookupKey::Id("task-owner-bound-cancel"))
        .await
        .expect("task lookup should succeed")
        .expect("task should remain present");
    assert_eq!(stored.status, VideoTaskStatus::Processing);
}

struct VideoRefreshSettlementFixture {
    state: AppState,
    usage_repository: Arc<InMemoryUsageReadRepository>,
    wallet_repository: Arc<InMemoryWalletRepository>,
    task_repository: Arc<InMemoryVideoTaskRepository>,
    upstream_base_url: String,
    upstream_handle: tokio::task::JoinHandle<()>,
    task_id: String,
    request_id: String,
    api_key_id: String,
}

impl Drop for VideoRefreshSettlementFixture {
    fn drop(&mut self) {
        self.upstream_handle.abort();
    }
}

// Production mints reservation tokens as canonical UUIDs, and the persistence
// metadata projection only retains that admitted shape.
const VIDEO_REFRESH_RESERVATION_TOKEN: &str = "550e8400-e29b-41d4-a716-446655440000";

fn video_refresh_billing_context() -> StoredBillingModelContext {
    StoredBillingModelContext::new(
        "provider-1".to_string(),
        Some("pay_as_you_go".to_string()),
        Some("provider-key-1".to_string()),
        None,
        None,
        "global-model-video-1".to_string(),
        "sora-2".to_string(),
        Some(json!({
            "billing": {
                "video": { "price_per_second_by_resolution": { "720p": 2.0 } }
            }
        })),
        None,
        None,
        Some("model-video-1".to_string()),
        Some("sora-2".to_string()),
        None,
        None,
        None,
    )
    .expect("video billing context should build")
}

fn video_refresh_wallet_repository() -> Arc<InMemoryWalletRepository> {
    Arc::new(InMemoryWalletRepository::seed(vec![
        StoredWalletSnapshot::new(
            "wallet-video-1".to_string(),
            Some("user-1".to_string()),
            None,
            100.0,
            0.0,
            "finite".to_string(),
            "USD".to_string(),
            "active".to_string(),
            0.0,
            0.0,
            0.0,
            0.0,
            100,
        )
        .expect("wallet should build"),
    ]))
}

async fn video_refresh_settlement_fixture(
    task_id: &str,
    provider_body: serde_json::Value,
) -> VideoRefreshSettlementFixture {
    // Read refreshes go through the direct sync transport, so the fixture needs
    // a real loopback upstream rather than the executor-only test override.
    let upstream = Router::new().fallback(any(move |_request: Request| {
        let provider_body = provider_body.clone();
        async move { Json(provider_body) }
    }));
    let (upstream_base_url, upstream_handle) = start_server(upstream).await;
    let request_id = format!("request-{task_id}");
    let api_key_id = format!("api-key-{task_id}");
    let usage_repository = Arc::new(InMemoryUsageReadRepository::default());
    let wallet_repository = video_refresh_wallet_repository();
    let task_repository = Arc::new(InMemoryVideoTaskRepository::default());
    let data_state = crate::data::GatewayDataState::with_usage_billing_and_wallet_for_tests(
        Arc::clone(&usage_repository),
        Arc::new(InMemoryBillingReadRepository::seed(vec![
            video_refresh_billing_context(),
        ])),
        Arc::clone(&wallet_repository),
    )
    .with_settlement_writer_for_tests(Arc::new(
        InMemorySettlementRepository::from_wallet_repository(Arc::clone(&wallet_repository)),
    ))
    .attach_video_task_repository_for_tests(Arc::clone(&task_repository));
    let state = AppState::new()
        .expect("gateway state should build")
        .with_data_state_for_tests(data_state)
        .with_video_task_truth_source_mode(
            crate::video_tasks::VideoTaskTruthSourceMode::RustAuthoritative,
        )
        .with_usage_runtime_for_tests(crate::usage::UsageRuntimeConfig {
            enabled: true,
            ..Default::default()
        });

    VideoRefreshSettlementFixture {
        state,
        usage_repository,
        wallet_repository,
        task_repository,
        upstream_base_url,
        upstream_handle,
        task_id: task_id.to_string(),
        request_id,
        api_key_id,
    }
}

fn video_refresh_snapshot(
    fixture: &VideoRefreshSettlementFixture,
) -> crate::video_tasks::LocalVideoTaskSnapshot {
    crate::video_tasks::LocalVideoTaskSnapshot::OpenAi(crate::video_tasks::OpenAiVideoTaskSeed {
        local_short_id: Some(format!("short-{}", fixture.task_id)),
        native_response: None,
        xai_provider: false,
        local_task_id: fixture.task_id.clone(),
        upstream_task_id: format!("ext-{}", fixture.task_id),
        created_at_unix_ms: 100,
        user_id: Some("user-1".to_string()),
        api_key_id: Some(fixture.api_key_id.clone()),
        model: Some("sora-2".to_string()),
        prompt: Some("hello".to_string()),
        size: Some("1280x720".to_string()),
        seconds: Some("4".to_string()),
        remixed_from_video_id: None,
        status: crate::video_tasks::LocalVideoTaskStatus::Processing,
        progress_percent: 50,
        completed_at_unix_secs: None,
        expires_at_unix_secs: None,
        error_code: None,
        error_message: None,
        video_url: None,
        persistence: crate::video_tasks::LocalVideoTaskPersistence {
            request_id: fixture.request_id.clone(),
            username: Some("user-1".to_string()),
            api_key_name: Some("primary".to_string()),
            client_api_format: "openai:video".to_string(),
            provider_api_format: "openai:video".to_string(),
            original_request_body: json!({
                "prompt": "hello",
                "seconds": "4",
                "resolution": "720p",
                "size": "1280x720"
            }),
            format_converted: false,
        },
        transport: crate::video_tasks::LocalVideoTaskTransport {
            upstream_base_url: format!("{}/v1", fixture.upstream_base_url),
            provider_name: Some("provider".to_string()),
            provider_id: "provider-1".to_string(),
            endpoint_id: "endpoint-1".to_string(),
            key_id: "provider-key-1".to_string(),
            headers: BTreeMap::new(),
            content_type: Some("application/json".to_string()),
            model_name: Some("sora-2".to_string()),
            proxy: None,
            transport_profile: None,
            timeouts: None,
        },
    })
}

async fn seed_refreshable_openai_video_task(fixture: &VideoRefreshSettlementFixture) {
    fixture
        .task_repository
        .upsert(sample_video_task(
            &fixture.task_id,
            VideoTaskStatus::Processing,
            100,
            "sora-2",
            "user-1",
            "openai:video",
        ))
        .await
        .expect("video task upsert should succeed");
    fixture
        .state
        .video_tasks
        .record_snapshot(video_refresh_snapshot(fixture));
}

fn video_refresh_usage_plan(request_id: &str) -> aether_contracts::ExecutionPlan {
    aether_contracts::ExecutionPlan {
        request_id: request_id.to_string(),
        candidate_id: None,
        provider_name: Some("provider".to_string()),
        provider_id: "provider-1".to_string(),
        endpoint_id: "endpoint-1".to_string(),
        key_id: "provider-key-1".to_string(),
        method: "POST".to_string(),
        url: "https://api.openai.example/v1/videos".to_string(),
        headers: BTreeMap::new(),
        content_type: Some("application/json".to_string()),
        content_encoding: None,
        body: aether_contracts::RequestBody {
            json_body: None,
            body_bytes_b64: None,
            body_ref: None,
        },
        stream: false,
        client_api_format: "openai:video".to_string(),
        provider_api_format: "openai:video".to_string(),
        model_name: Some("sora-2".to_string()),
        proxy: None,
        transport_profile: None,
        timeouts: None,
    }
}

fn video_refresh_usage_context(fixture: &VideoRefreshSettlementFixture) -> serde_json::Value {
    json!({
        "trace_id": fixture.request_id,
        "request_id": fixture.request_id,
        "user_id": "user-1",
        "api_key_id": fixture.api_key_id,
        "model": "sora-2",
        "provider_name": "provider",
        "plan_usage_reservation_token": VIDEO_REFRESH_RESERVATION_TOKEN,
        "routing_group_billing_multiplier": 2.0
    })
}

async fn seed_deferred_video_create_usage(fixture: &VideoRefreshSettlementFixture) {
    let plan = video_refresh_usage_plan(&fixture.request_id);
    let context = video_refresh_usage_context(fixture);
    let pending = aether_usage_runtime::build_pending_usage_record(
        &plan,
        Some(&context),
        crate::clock::current_unix_secs(),
    )
    .expect("deferred create usage should build");
    fixture
        .state
        .data
        .upsert_usage(pending)
        .await
        .expect("deferred create usage should persist")
        .expect("usage writer should store the pending row");
}

async fn video_refresh_wallet_balance(fixture: &VideoRefreshSettlementFixture) -> f64 {
    fixture
        .wallet_repository
        .find(WalletLookupKey::UserId("user-1"))
        .await
        .expect("wallet lookup should succeed")
        .expect("wallet should exist")
        .balance
}

async fn video_refresh_usage_row(
    fixture: &VideoRefreshSettlementFixture,
) -> aether_data_contracts::repository::usage::StoredRequestUsageAudit {
    fixture
        .usage_repository
        .find_by_request_id(&fixture.request_id)
        .await
        .expect("usage lookup should succeed")
        .expect("usage row should exist")
}

async fn prepared_openai_read_refresh_plan(
    fixture: &VideoRefreshSettlementFixture,
) -> crate::video_tasks::LocalVideoTaskReadRefreshPlan {
    let refresh_path = format!("/v1/videos/{}", fixture.task_id);
    fixture
        .state
        .video_tasks
        .prepare_read_refresh_sync_plan_for_user(
            Some("openai"),
            &refresh_path,
            "user-1",
            "trace-video-read-refresh",
        )
        .expect("read refresh plan should build")
}

#[tokio::test]
async fn gateway_video_read_refresh_finalizes_deferred_create_usage_exactly_once() {
    let fixture = video_refresh_settlement_fixture(
        "task-refresh-finalize",
        json!({
            "id": "ext-task-refresh-finalize",
            "status": "completed",
            "video": { "url": "https://cdn.example/video.mp4" },
            "seconds": 4,
            "progress": 100
        }),
    )
    .await;
    seed_refreshable_openai_video_task(&fixture).await;
    seed_deferred_video_create_usage(&fixture).await;
    let refresh_plan = prepared_openai_read_refresh_plan(&fixture).await;

    assert!(fixture
        .state
        .execute_video_task_refresh_plan(&refresh_plan)
        .await
        .expect("read refresh should succeed"));

    let stored = fixture
        .task_repository
        .find(VideoTaskLookupKey::Id(&fixture.task_id))
        .await
        .expect("task lookup should succeed")
        .expect("task should exist");
    assert_eq!(stored.status, VideoTaskStatus::Completed);

    let usage = video_refresh_usage_row(&fixture).await;
    assert_eq!(usage.status, "completed");
    // Four seconds at 2.0/s is billed once; the pending row supplied the
    // reservation identity the settlement must keep using.
    assert_eq!(usage.total_cost_usd, 8.0);
    let metadata = usage
        .request_metadata
        .as_ref()
        .expect("settled usage should keep request metadata");
    assert_eq!(
        metadata["plan_usage_reservation_token"],
        json!(VIDEO_REFRESH_RESERVATION_TOKEN)
    );
    assert_eq!(metadata["routing_group_billing_multiplier"], json!(2.0));
    assert_eq!(video_refresh_wallet_balance(&fixture).await, 84.0);

    // Replaying the same client read stays terminal and must not charge again.
    assert!(fixture
        .state
        .execute_video_task_refresh_plan(&refresh_plan)
        .await
        .expect("replayed read refresh should succeed"));
    let replayed = video_refresh_usage_row(&fixture).await;
    assert_eq!(replayed.status, "completed");
    assert_eq!(replayed.total_cost_usd, 8.0);
    assert_eq!(video_refresh_wallet_balance(&fixture).await, 84.0);
    let now_unix_secs = crate::clock::current_unix_secs();
    assert!(
        fixture
            .state
            .claim_due_video_tasks(now_unix_secs, now_unix_secs.saturating_add(30), 8)
            .await
            .expect("poller claim should succeed")
            .is_empty(),
        "terminal tasks must not be claimable by the settlement poller"
    );
}

#[tokio::test]
async fn gateway_video_read_refresh_settles_failed_and_cancelled_tasks_as_void() {
    for provider_status in ["failed", "cancelled"] {
        let fixture = video_refresh_settlement_fixture(
            &format!("task-refresh-{provider_status}"),
            json!({
                "id": format!("ext-task-refresh-{provider_status}"),
                "status": provider_status,
                "error": { "code": "generation_failed" }
            }),
        )
        .await;
        seed_refreshable_openai_video_task(&fixture).await;
        seed_deferred_video_create_usage(&fixture).await;
        let refresh_plan = prepared_openai_read_refresh_plan(&fixture).await;

        assert!(fixture
            .state
            .execute_video_task_refresh_plan(&refresh_plan)
            .await
            .expect("read refresh should succeed"));

        let stored = fixture
            .task_repository
            .find(VideoTaskLookupKey::Id(&fixture.task_id))
            .await
            .expect("task lookup should succeed")
            .expect("task should exist");
        assert_eq!(
            stored.status,
            if provider_status == "failed" {
                VideoTaskStatus::Failed
            } else {
                VideoTaskStatus::Cancelled
            }
        );

        let usage = video_refresh_usage_row(&fixture).await;
        assert_eq!(usage.status, provider_status);
        assert_eq!(usage.total_cost_usd, 0.0);
        let metadata = usage
            .request_metadata
            .as_ref()
            .expect("void usage should keep request metadata");
        assert_eq!(
            metadata["plan_usage_reservation_token"],
            json!(VIDEO_REFRESH_RESERVATION_TOKEN)
        );
        // A failed or cancelled task must never pick up a seconds fee, and the
        // deferred reservation must not stay pending.
        assert_eq!(video_refresh_wallet_balance(&fixture).await, 100.0);

        assert!(fixture
            .state
            .execute_video_task_refresh_plan(&refresh_plan)
            .await
            .expect("replayed read refresh should succeed"));
        assert_eq!(video_refresh_usage_row(&fixture).await.total_cost_usd, 0.0);
        assert_eq!(video_refresh_wallet_balance(&fixture).await, 100.0);
    }
}

#[tokio::test]
async fn gateway_video_create_terminal_snapshot_finalizes_deferred_admission_after_order() {
    let fixture = video_refresh_settlement_fixture("task-create-terminal", json!({})).await;
    let stored = fixture
        .task_repository
        .upsert(sample_video_task(
            &fixture.task_id,
            VideoTaskStatus::Completed,
            100,
            "sora-2",
            "user-1",
            "openai:video",
        ))
        .await
        .expect("terminal create task upsert should succeed");

    // The create path enqueues the deferred pending usage row before it stores
    // the initial snapshot; an upstream that reports a terminal state in the
    // create response must settle only after that admission row lands.
    let plan = video_refresh_usage_plan(&fixture.request_id);
    let context = video_refresh_usage_context(&fixture);
    let report = crate::usage::GatewaySyncReportRequest {
        trace_id: fixture.request_id.clone(),
        report_kind: "openai_video_create_sync_success".to_string(),
        report_context: Some(context.clone()),
        status_code: 200,
        headers: BTreeMap::new(),
        body_json: Some(json!({
            "id": format!("ext-{}", fixture.task_id),
            "status": "completed"
        })),
        client_body_json: None,
        body_base64: None,
        telemetry: None,
    };
    fixture
        .state
        .usage_runtime
        .record_sync_terminal(
            fixture.state.usage_lifecycle_data_state().as_ref(),
            aether_usage_runtime::build_terminal_usage_context_seed(&plan, Some(&context)),
            aether_usage_runtime::build_sync_terminal_usage_payload_seed(&report),
        )
        .await;
    crate::async_task::finalize_video_task_if_terminal(&fixture.state, &stored).await;

    let usage = video_refresh_usage_row(&fixture).await;
    assert_eq!(usage.status, "completed");
    assert_eq!(usage.total_cost_usd, 8.0);
    let metadata = usage
        .request_metadata
        .as_ref()
        .expect("initially terminal create should settle the admission row");
    assert_eq!(
        metadata["plan_usage_reservation_token"],
        json!(VIDEO_REFRESH_RESERVATION_TOKEN)
    );
    assert_eq!(metadata["routing_group_billing_multiplier"], json!(2.0));
    assert_eq!(video_refresh_wallet_balance(&fixture).await, 84.0);

    crate::async_task::finalize_video_task_if_terminal(&fixture.state, &stored).await;
    assert_eq!(video_refresh_usage_row(&fixture).await.total_cost_usd, 8.0);
    assert_eq!(video_refresh_wallet_balance(&fixture).await, 84.0);
}
