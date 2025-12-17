"""
Provider Query API 端点
用于查询提供商的模型列表等信息
"""

import asyncio
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from src.core.crypto import crypto_service
from src.core.logger import logger
from src.database.database import get_db
from src.models.database import Provider, ProviderEndpoint, User
from src.utils.auth_utils import get_current_user

router = APIRouter(prefix="/api/admin/provider-query", tags=["Provider Query"])


# ============ Request/Response Models ============


class ModelsQueryRequest(BaseModel):
    """模型列表查询请求"""

    provider_id: str
    api_key_id: Optional[str] = None


# ============ API Endpoints ============


async def _fetch_openai_models(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    api_format: str,
    extra_headers: Optional[dict] = None,
) -> tuple[list, Optional[str]]:
    """获取 OpenAI 格式的模型列表

    Returns:
        tuple[list, Optional[str]]: (模型列表, 错误信息)
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    if extra_headers:
        # 防止 extra_headers 覆盖 Authorization
        safe_headers = {k: v for k, v in extra_headers.items() if k.lower() != "authorization"}
        headers.update(safe_headers)

    # 构建 /v1/models URL
    if base_url.endswith("/v1"):
        models_url = f"{base_url}/models"
    else:
        models_url = f"{base_url}/v1/models"

    try:
        response = await client.get(models_url, headers=headers)
        logger.debug(f"OpenAI models request to {models_url}: status={response.status_code}")
        if response.status_code == 200:
            data = response.json()
            models = []
            if "data" in data:
                models = data["data"]
            elif isinstance(data, list):
                models = data
            # 为每个模型添加 api_format 字段
            for m in models:
                m["api_format"] = api_format
            return models, None
        else:
            # 记录详细的错误信息
            error_body = response.text[:500] if response.text else "(empty)"
            error_msg = f"HTTP {response.status_code}: {error_body}"
            logger.warning(f"OpenAI models request to {models_url} failed: {error_msg}")
            return [], error_msg
    except Exception as e:
        error_msg = f"Request error: {str(e)}"
        logger.warning(f"Failed to fetch models from {models_url}: {e}")
        return [], error_msg


async def _fetch_claude_models(
    client: httpx.AsyncClient, base_url: str, api_key: str, api_format: str
) -> tuple[list, Optional[str]]:
    """获取 Claude 格式的模型列表

    Returns:
        tuple[list, Optional[str]]: (模型列表, 错误信息)
    """
    headers = {
        "x-api-key": api_key,
        "Authorization": f"Bearer {api_key}",
        "anthropic-version": "2023-06-01",
    }

    # 构建 /v1/models URL
    if base_url.endswith("/v1"):
        models_url = f"{base_url}/models"
    else:
        models_url = f"{base_url}/v1/models"

    try:
        response = await client.get(models_url, headers=headers)
        logger.debug(f"Claude models request to {models_url}: status={response.status_code}")
        if response.status_code == 200:
            data = response.json()
            models = []
            if "data" in data:
                models = data["data"]
            elif isinstance(data, list):
                models = data
            # 为每个模型添加 api_format 字段
            for m in models:
                m["api_format"] = api_format
            return models, None
        else:
            error_body = response.text[:500] if response.text else "(empty)"
            error_msg = f"HTTP {response.status_code}: {error_body}"
            logger.warning(f"Claude models request to {models_url} failed: {error_msg}")
            return [], error_msg
    except Exception as e:
        error_msg = f"Request error: {str(e)}"
        logger.warning(f"Failed to fetch Claude models from {models_url}: {e}")
        return [], error_msg


async def _fetch_gemini_models(
    client: httpx.AsyncClient, base_url: str, api_key: str, api_format: str
) -> tuple[list, Optional[str]]:
    """获取 Gemini 格式的模型列表

    Returns:
        tuple[list, Optional[str]]: (模型列表, 错误信息)
    """
    # 兼容 base_url 已包含 /v1beta 的情况
    base_url_clean = base_url.rstrip("/")
    if base_url_clean.endswith("/v1beta"):
        models_url = f"{base_url_clean}/models?key={api_key}"
    else:
        models_url = f"{base_url_clean}/v1beta/models?key={api_key}"

    try:
        response = await client.get(models_url)
        logger.debug(f"Gemini models request to {models_url}: status={response.status_code}")
        if response.status_code == 200:
            data = response.json()
            if "models" in data:
                # 转换为统一格式
                return [
                    {
                        "id": m.get("name", "").replace("models/", ""),
                        "owned_by": "google",
                        "display_name": m.get("displayName", ""),
                        "api_format": api_format,
                    }
                    for m in data["models"]
                ], None
            return [], None
        else:
            error_body = response.text[:500] if response.text else "(empty)"
            error_msg = f"HTTP {response.status_code}: {error_body}"
            logger.warning(f"Gemini models request to {models_url} failed: {error_msg}")
            return [], error_msg
    except Exception as e:
        error_msg = f"Request error: {str(e)}"
        logger.warning(f"Failed to fetch Gemini models from {models_url}: {e}")
        return [], error_msg


@router.post("/models")
async def query_available_models(
    request: ModelsQueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    查询提供商可用模型

    遍历所有活跃端点，根据端点的 API 格式选择正确的请求方式：
    - OPENAI/OPENAI_CLI: /v1/models (Bearer token)
    - CLAUDE/CLAUDE_CLI: /v1/models (x-api-key)
    - GEMINI/GEMINI_CLI: /v1beta/models (URL key parameter)

    Args:
        request: 查询请求

    Returns:
        所有端点的模型列表（合并）
    """
    # 获取提供商及其端点
    provider = (
        db.query(Provider)
        .options(joinedload(Provider.endpoints).joinedload(ProviderEndpoint.api_keys))
        .filter(Provider.id == request.provider_id)
        .first()
    )

    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    # 收集所有活跃端点的配置
    endpoint_configs: list[dict] = []

    if request.api_key_id:
        # 指定了特定的 API Key，只使用该 Key 对应的端点
        for endpoint in provider.endpoints:
            for api_key in endpoint.api_keys:
                if api_key.id == request.api_key_id:
                    try:
                        api_key_value = crypto_service.decrypt(api_key.api_key)
                    except Exception as e:
                        logger.error(f"Failed to decrypt API key: {e}")
                        raise HTTPException(status_code=500, detail="Failed to decrypt API key")
                    endpoint_configs.append({
                        "api_key": api_key_value,
                        "base_url": endpoint.base_url,
                        "api_format": endpoint.api_format,
                        "extra_headers": endpoint.headers,
                    })
                    break
            if endpoint_configs:
                break

        if not endpoint_configs:
            raise HTTPException(status_code=404, detail="API Key not found")
    else:
        # 遍历所有活跃端点，每个端点取第一个可用的 Key
        for endpoint in provider.endpoints:
            if not endpoint.is_active or not endpoint.api_keys:
                continue

            # 找第一个可用的 Key
            for api_key in endpoint.api_keys:
                if api_key.is_active:
                    try:
                        api_key_value = crypto_service.decrypt(api_key.api_key)
                    except Exception as e:
                        logger.error(f"Failed to decrypt API key: {e}")
                        continue  # 尝试下一个 Key
                    endpoint_configs.append({
                        "api_key": api_key_value,
                        "base_url": endpoint.base_url,
                        "api_format": endpoint.api_format,
                        "extra_headers": endpoint.headers,
                    })
                    break  # 只取第一个可用的 Key

        if not endpoint_configs:
            raise HTTPException(status_code=400, detail="No active API Key found for this provider")

    # 并发请求所有端点的模型列表
    all_models: list = []
    errors: list[str] = []

    async def fetch_endpoint_models(
        client: httpx.AsyncClient, config: dict
    ) -> tuple[list, Optional[str]]:
        base_url = config["base_url"]
        if not base_url:
            return [], None
        base_url = base_url.rstrip("/")
        api_format = config["api_format"]
        api_key_value = config["api_key"]
        extra_headers = config["extra_headers"]

        try:
            if api_format in ["CLAUDE", "CLAUDE_CLI"]:
                return await _fetch_claude_models(client, base_url, api_key_value, api_format)
            elif api_format in ["GEMINI", "GEMINI_CLI"]:
                return await _fetch_gemini_models(client, base_url, api_key_value, api_format)
            else:
                return await _fetch_openai_models(
                    client, base_url, api_key_value, api_format, extra_headers
                )
        except Exception as e:
            logger.error(f"Error fetching models from {api_format} endpoint: {e}")
            return [], f"{api_format}: {str(e)}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        results = await asyncio.gather(
            *[fetch_endpoint_models(client, c) for c in endpoint_configs]
        )
        for models, error in results:
            all_models.extend(models)
            if error:
                errors.append(error)

    # 按 model id 去重（保留第一个）
    seen_ids: set[str] = set()
    unique_models: list = []
    for model in all_models:
        model_id = model.get("id")
        if model_id and model_id not in seen_ids:
            seen_ids.add(model_id)
            unique_models.append(model)

    error = "; ".join(errors) if errors else None
    if not unique_models and not error:
        error = "No models returned from any endpoint"

    return {
        "success": len(unique_models) > 0,
        "data": {"models": unique_models, "error": error},
        "provider": {
            "id": provider.id,
            "name": provider.name,
            "display_name": provider.display_name,
        },
    }
