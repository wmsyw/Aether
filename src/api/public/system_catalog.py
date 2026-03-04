"""
System Catalog / 健康检查相关端点

这些是系统工具端点，不需要复杂的 Adapter 抽象。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session, load_only, selectinload

from src.api.handlers.base.request_builder import (
    PassthroughRequestBuilder,
    build_test_request_body,
    get_provider_auth,
)
from src.clients.redis_client import get_redis_client
from src.core.logger import logger
from src.database import get_db
from src.database.database import get_pool_status
from src.models.database import GlobalModel, Model, Provider, ProviderAPIKey, ProviderEndpoint
from src.services.provider.transport import build_provider_url
from src.utils.ssl_utils import get_ssl_context

router = APIRouter(tags=["System Catalog"])


# ============== 辅助函数 ==============


def _as_bool(value: str | None, default: bool) -> bool:
    """将字符串转换为布尔值"""
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _serialize_provider(
    provider: Provider,
    include_models: bool,
    include_endpoints: bool,
) -> dict[str, Any]:
    """序列化 Provider 对象"""
    provider_data: dict[str, Any] = {
        "id": provider.id,
        "name": provider.name,
        "is_active": provider.is_active,
        "provider_priority": provider.provider_priority,
    }

    if include_endpoints:
        provider_data["endpoints"] = [
            {
                "id": endpoint.id,
                "base_url": endpoint.base_url,
                "api_format": endpoint.api_format if endpoint.api_format else None,
                "is_active": endpoint.is_active,
            }
            for endpoint in provider.endpoints or []
        ]

    if include_models:
        provider_data["models"] = [
            {
                "id": model.id,
                "name": (
                    model.global_model.name if model.global_model else model.provider_model_name
                ),
                "display_name": (
                    model.global_model.display_name
                    if model.global_model
                    else model.provider_model_name
                ),
                "is_active": model.is_active,
                "supports_streaming": model.supports_streaming,
            }
            for model in provider.models or []
            if model.is_active
        ]

    return provider_data


def _select_provider(db: Session, provider_name: str | None) -> Provider | None:
    """选择 Provider（按 provider_priority 优先级选择）"""
    query = db.query(Provider).filter(Provider.is_active.is_(True))
    if provider_name:
        provider = query.filter(Provider.name == provider_name).first()
        if provider:
            return provider

    # 按优先级选择（provider_priority 最小的优先）
    return query.order_by(Provider.provider_priority.asc()).first()


# ============== 端点 ==============


@router.get("/v1/health")
async def service_health(db: Session = Depends(get_db)) -> Any:
    """返回服务健康状态与依赖信息"""
    active_providers = (
        db.query(func.count(Provider.id)).filter(Provider.is_active.is_(True)).scalar() or 0
    )
    active_models = db.query(func.count(Model.id)).filter(Model.is_active.is_(True)).scalar() or 0

    redis_info: dict[str, Any] = {"status": "unknown"}
    try:
        redis = await get_redis_client()
        if redis:
            await redis.ping()
            redis_info = {"status": "ok"}
        else:
            redis_info = {"status": "degraded", "message": "Redis client not initialized"}
    except Exception as exc:
        redis_info = {"status": "error", "message": str(exc)}

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "active_providers": active_providers,
            "active_models": active_models,
        },
        "dependencies": {
            "database": {"status": "ok"},
            "redis": redis_info,
        },
    }


@router.get("/health")
async def health_check() -> Any:
    """简单健康检查端点（无需认证）"""
    try:
        pool_status = get_pool_status()
        pool_health = {
            "checked_out": pool_status["checked_out"],
            "pool_size": pool_status["pool_size"],
            "overflow": pool_status["overflow"],
            "max_capacity": pool_status["max_capacity"],
            "usage_rate": (
                f"{(pool_status['checked_out'] / pool_status['max_capacity'] * 100):.1f}%"
                if pool_status["max_capacity"] > 0
                else "0.0%"
            ),
        }
    except Exception as e:
        pool_health = {"error": str(e)}

    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database_pool": pool_health,
    }


@router.get("/")
async def root(db: Session = Depends(get_db)) -> Any:
    """Root endpoint - 服务信息概览"""
    # 按优先级选择最高优先级的提供商
    top_provider = (
        db.query(Provider)
        .options(load_only(Provider.id, Provider.name, Provider.provider_priority))
        .filter(Provider.is_active.is_(True))
        .order_by(Provider.provider_priority.asc())
        .first()
    )
    active_providers = (
        db.query(func.count(Provider.id)).filter(Provider.is_active.is_(True)).scalar() or 0
    )

    return {
        "message": "AI Proxy with Modular Architecture v4.0.0",
        "status": "running",
        "current_provider": top_provider.name if top_provider else "None",
        "available_providers": active_providers,
        "config": {},
        "endpoints": {
            "messages": "/v1/messages",
            "count_tokens": "/v1/messages/count_tokens",
            "health": "/v1/health",
            "providers": "/v1/providers",
            "test_connection": "/v1/test-connection",
        },
    }


@router.get("/v1/providers")
async def list_providers(
    db: Session = Depends(get_db),
    include_models: bool = Query(False),
    include_endpoints: bool = Query(False),
    active_only: bool = Query(True),
) -> Any:
    """列出所有 Provider"""
    load_options = [
        load_only(Provider.id, Provider.name, Provider.is_active, Provider.provider_priority)
    ]
    if include_models:
        load_options.append(
            selectinload(Provider.models)
            .load_only(
                Model.id,
                Model.provider_model_name,
                Model.is_active,
                Model.supports_streaming,
                Model.global_model_id,
            )
            .selectinload(Model.global_model)
            .load_only(GlobalModel.id, GlobalModel.name, GlobalModel.display_name)
        )
    if include_endpoints:
        load_options.append(
            selectinload(Provider.endpoints).load_only(
                ProviderEndpoint.id,
                ProviderEndpoint.base_url,
                ProviderEndpoint.api_format,
                ProviderEndpoint.is_active,
            )
        )

    base_query = db.query(Provider)
    if load_options:
        base_query = base_query.options(*load_options)
    if active_only:
        base_query = base_query.filter(Provider.is_active.is_(True))
    base_query = base_query.order_by(Provider.provider_priority.asc(), Provider.name.asc())

    providers = base_query.all()
    return {
        "providers": [
            _serialize_provider(provider, include_models, include_endpoints)
            for provider in providers
        ]
    }


@router.get("/v1/providers/{provider_identifier}")
async def provider_detail(
    provider_identifier: str,
    db: Session = Depends(get_db),
    include_models: bool = Query(False),
    include_endpoints: bool = Query(False),
) -> Any:
    """获取单个 Provider 详情"""
    load_options = [
        load_only(Provider.id, Provider.name, Provider.is_active, Provider.provider_priority)
    ]
    if include_models:
        load_options.append(
            selectinload(Provider.models)
            .load_only(
                Model.id,
                Model.provider_model_name,
                Model.is_active,
                Model.supports_streaming,
                Model.global_model_id,
            )
            .selectinload(Model.global_model)
            .load_only(GlobalModel.id, GlobalModel.name, GlobalModel.display_name)
        )
    if include_endpoints:
        load_options.append(
            selectinload(Provider.endpoints).load_only(
                ProviderEndpoint.id,
                ProviderEndpoint.base_url,
                ProviderEndpoint.api_format,
                ProviderEndpoint.is_active,
            )
        )

    base_query = db.query(Provider)
    if load_options:
        base_query = base_query.options(*load_options)

    provider = base_query.filter(
        (Provider.id == provider_identifier) | (Provider.name == provider_identifier)
    ).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    return _serialize_provider(provider, include_models, include_endpoints)


@router.get("/v1/test-connection")
@router.get("/test-connection")
async def test_connection(
    request: Request,
    db: Session = Depends(get_db),
    provider: str | None = Query(None),
    model: str = Query("claude-3-haiku-20240307"),
    api_format: str | None = Query(None),
) -> Any:
    """测试 Provider 连接"""
    selected_provider = _select_provider(db, provider)
    if not selected_provider:
        raise HTTPException(status_code=503, detail="No active provider available")

    # Determine endpoint format: prefer explicit api_format; otherwise use the provider's first active endpoint.
    active_endpoints: list[ProviderEndpoint] = [
        ep for ep in (selected_provider.endpoints or []) if getattr(ep, "is_active", False)
    ]
    if not active_endpoints:
        raise HTTPException(status_code=503, detail="Provider has no active endpoints")

    if api_format:
        endpoint = next(
            (ep for ep in active_endpoints if (ep.api_format or "") == api_format),
            None,
        )
        if not endpoint:
            raise HTTPException(
                status_code=400,
                detail=f"Provider has no active endpoint for api_format={api_format}",
            )
        format_value = api_format
    else:
        endpoint = active_endpoints[0]
        format_value = endpoint.api_format or "claude:chat"

    # Pick an active ProviderAPIKey that supports this format (best-effort).
    active_keys: list[ProviderAPIKey] = [
        k for k in (selected_provider.api_keys or []) if getattr(k, "is_active", False)
    ]
    if not active_keys:
        raise HTTPException(status_code=503, detail="Provider has no active api keys")

    def _key_supports_format(k: ProviderAPIKey) -> bool:
        formats = getattr(k, "api_formats", None)
        # None => supports all formats; [] => supports none
        if formats is None:
            return True
        if isinstance(formats, list):
            return str(format_value) in {str(x) for x in formats}
        # unexpected type: be permissive
        return True

    key = next((k for k in active_keys if _key_supports_format(k)), active_keys[0])

    # Build a safe test request body in the endpoint's format (via format conversion registry).
    payload = build_test_request_body(
        format_value,
        request_data={
            "model": model,
            "messages": [{"role": "user", "content": "Health check"}],
            "max_tokens": 5,
        },
    )

    try:
        # 获取认证信息（处理 Service Account 等异步认证场景）
        auth_info = await get_provider_auth(endpoint, key)

        request_builder = PassthroughRequestBuilder()
        provider_payload, provider_headers = request_builder.build(
            payload,
            {},
            endpoint,
            key,
            is_stream=False,
            pre_computed_auth=auth_info.as_tuple() if auth_info else None,
        )

        url = build_provider_url(
            endpoint,
            query_params=dict(request.query_params),
            path_params={"model": model},
            is_stream=False,
            key=key,
            decrypted_auth_config=auth_info.decrypted_auth_config if auth_info else None,
        )

        async with httpx.AsyncClient(timeout=30.0, verify=get_ssl_context()) as client:
            resp = await client.post(url, json=provider_payload, headers=provider_headers)
            resp.raise_for_status()
            response = resp.json()

        return {
            "status": "success",
            "provider": selected_provider.name,
            "endpoint_id": getattr(endpoint, "id", None),
            "api_format": format_value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "response_id": response.get("id", "unknown"),
        }
    except Exception as exc:
        logger.error(f"API connectivity test failed: {exc}")
        raise HTTPException(status_code=503, detail=str(exc))
