"""
Passkey/WebAuthn 认证路由

提供 Passkey 注册、认证和凭证管理 API 端点。
"""

from __future__ import annotations


from abc import ABC
from datetime import datetime, timezone
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from src.api.base.adapter import ApiAdapter, ApiMode
from src.api.auth.session_tokens import issue_session_bound_tokens
from src.api.base.authenticated_adapter import AuthenticatedApiAdapter
from src.api.base.context import ApiRequestContext
from src.api.base.pipeline import get_pipeline
from src.core.logger import logger
from src.database import get_db
from src.models.api import (
    PasskeyAuthSettingsResponse,
    PasskeyCredentialResponse,
    PasskeyLoginBeginResponse,
    PasskeyLoginCompleteResponse,
    PasskeyRegistrationBeginResponse,
    PasskeyRegistrationCompleteResponse,
)
from src.models.database import AuditEventType, User
from src.services.auth.passkey_service import PasskeyService, PasskeyServiceError
from src.services.auth.refresh_cookie import set_refresh_token_cookie
from src.services.cache.user_cache import UserCacheService
from src.services.rate_limit.ip_limiter import IPRateLimiter
from src.services.system.audit import AuditService
from src.utils.request_utils import get_client_ip, get_user_agent

router = APIRouter(prefix="/api/auth/passkey", tags=["Passkey Authentication"])
pipeline = get_pipeline()


async def _enforce_passkey_rate_limit(
    request: Request, *, endpoint_type: str, detail_prefix: str
) -> None:
    client_ip = get_client_ip(request)
    allowed, remaining, reset_after = await IPRateLimiter.check_limit(
        client_ip, endpoint_type
    )
    if allowed:
        return

    logger.warning(
        "{}超过速率限制: IP={}, 剩余={}", detail_prefix, client_ip, remaining
    )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"{detail_prefix}过于频繁，请在 {reset_after} 秒后重试",
    )


def _require_authenticated_user(context: ApiRequestContext) -> User:
    user = context.user
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户未登录",
        )
    return cast(User, user)


def _as_str(value: object) -> str:
    return cast(str, value)


def _as_optional_str(value: object) -> str | None:
    return cast(str | None, value)


def _as_bool(value: object) -> bool:
    return cast(bool, value)


def _serialize_passkey_credential(credential: Any) -> dict[str, Any]:
    return PasskeyCredentialResponse(
        id=_as_str(credential.id),
        device_name=_as_optional_str(credential.device_name),
        device_type=_as_optional_str(credential.device_type),
        backed_up=_as_bool(credential.backed_up),
        transports=cast(list[str] | None, credential.transports),
        aaguid=_as_optional_str(credential.aaguid),
        is_active=_as_bool(credential.is_active),
        last_used_at=credential.last_used_at,
        created_at=credential.created_at,
    ).model_dump()


class PasskeyPublicAdapter(ApiAdapter, ABC):
    """公开 Passkey 适配器"""

    mode = ApiMode.PUBLIC

    def authorize(self, context: ApiRequestContext) -> None:
        return None


class PasskeyAuthenticatedAdapter(AuthenticatedApiAdapter, ABC):
    """需要认证的 Passkey 适配器"""

    pass


@router.get("/settings", response_model=PasskeyAuthSettingsResponse)
async def get_passkey_settings(request: Request, db: Session = Depends(get_db)) -> Any:
    """
    获取 Passkey 认证设置

    返回 Passkey 的 RP ID 和名称，供前端初始化 WebAuthn 使用。
    此接口为公开接口，无需认证。
    """
    adapter = PasskeySettingsAdapter()
    return await pipeline.run(
        adapter=adapter, http_request=request, db=db, mode=adapter.mode
    )


class PasskeySettingsAdapter(PasskeyPublicAdapter):
    """Passkey 设置适配器"""

    async def handle(self, context: ApiRequestContext) -> Any:
        """获取 Passkey 设置"""
        settings = PasskeyService.get_settings()
        return PasskeyAuthSettingsResponse(**settings).model_dump()


@router.post("/register/begin", response_model=PasskeyRegistrationBeginResponse)
async def passkey_register_begin(
    request: Request, db: Session = Depends(get_db)
) -> Any:
    """
    开始 Passkey 注册流程

    返回 WebAuthn 注册选项，供前端调用 navigator.credentials.create() 使用。
    需要用户已登录（认证适配器）。
    """
    adapter = PasskeyRegisterBeginAdapter()
    return await pipeline.run(
        adapter=adapter, http_request=request, db=db, mode=adapter.mode
    )


class PasskeyRegisterBeginAdapter(PasskeyAuthenticatedAdapter):
    """Passkey 注册开始适配器"""

    async def handle(self, context: ApiRequestContext) -> Any:
        """开始 Passkey 注册"""
        await _enforce_passkey_rate_limit(
            context.request,
            endpoint_type="register",
            detail_prefix="Passkey 注册请求",
        )

        user = _require_authenticated_user(context)
        payload = context.ensure_json_body()
        device_name = payload.get("device_name") if payload else None

        try:
            result = await PasskeyService.begin_registration(
                db=context.db,
                user=user,
                device_name=device_name,
            )
            return PasskeyRegistrationBeginResponse(**result).model_dump()
        except PasskeyServiceError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=e.message
            )


@router.post("/register/complete", response_model=PasskeyRegistrationCompleteResponse)
async def passkey_register_complete(
    request: Request, db: Session = Depends(get_db)
) -> Any:
    """
    完成 Passkey 注册流程

    接收前端返回的凭证数据，验证并存储到数据库。
    需要用户已登录（认证适配器）。
    """
    adapter = PasskeyRegisterCompleteAdapter()
    return await pipeline.run(
        adapter=adapter, http_request=request, db=db, mode=adapter.mode
    )


class PasskeyRegisterCompleteAdapter(PasskeyAuthenticatedAdapter):
    """Passkey 注册完成适配器"""

    async def handle(self, context: ApiRequestContext) -> Any:
        """完成 Passkey 注册"""
        await _enforce_passkey_rate_limit(
            context.request,
            endpoint_type="register",
            detail_prefix="Passkey 注册请求",
        )

        user = _require_authenticated_user(context)
        payload = context.ensure_json_body()

        if not payload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="请求体不能为空"
            )

        challenge_id = payload.get("challenge_id")
        credential = payload.get("credential")
        device_name = payload.get("device_name")

        if not challenge_id or not credential:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="缺少 challenge_id 或 credential",
            )

        try:
            passkey_credential = await PasskeyService.complete_registration(
                db=context.db,
                challenge_id=challenge_id,
                credential=credential,
                device_name=device_name,
            )

            user_id = _as_str(user.id)
            user_email = _as_optional_str(user.email)
            user_username = _as_str(user.username)

            _ = AuditService.log_event(
                db=context.db,
                event_type=AuditEventType.PASSKEY_REGISTERED,
                description=f"用户 {user_email or user_username} 注册了 Passkey 凭证",
                user_id=user_id,
                ip_address=get_client_ip(context.request),
                user_agent=get_user_agent(context.request),
                metadata={
                    "credential_id": _as_str(passkey_credential.id),
                    "device_name": _as_optional_str(passkey_credential.device_name),
                },
            )
            context.db.commit()
            context.request.state.tx_committed_by_route = True

            return PasskeyRegistrationCompleteResponse(
                success=True,
                credential_id=_as_str(passkey_credential.id),
                message="Passkey 注册成功",
            ).model_dump()
        except PasskeyServiceError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=e.message
            )


@router.post("/login/begin", response_model=PasskeyLoginBeginResponse)
async def passkey_login_begin(request: Request, db: Session = Depends(get_db)) -> Any:
    """
    开始 Passkey 登录流程

    返回 WebAuthn 登录选项，供前端调用 navigator.credentials.get() 使用。
    此接口为公开接口，无需认证。
    """
    adapter = PasskeyLoginBeginAdapter()
    return await pipeline.run(
        adapter=adapter, http_request=request, db=db, mode=adapter.mode
    )


class PasskeyLoginBeginAdapter(PasskeyPublicAdapter):
    """Passkey 登录开始适配器"""

    async def handle(self, context: ApiRequestContext) -> Any:
        """开始 Passkey 登录"""
        await _enforce_passkey_rate_limit(
            context.request,
            endpoint_type="login",
            detail_prefix="Passkey 登录请求",
        )

        payload = context.ensure_json_body()
        email = payload.get("email") if payload else None

        try:
            result = await PasskeyService.begin_authentication(
                db=context.db,
                email=email,
            )
            return PasskeyLoginBeginResponse(**result).model_dump()
        except PasskeyServiceError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=e.message
            )


@router.post(
    "/login/complete",
    response_model=PasskeyLoginCompleteResponse,
    response_model_exclude_none=True,
)
async def passkey_login_complete(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> Any:
    """
    完成 Passkey 登录流程

    接收前端返回的凭证数据，验证后返回 JWT Token。
    此接口为公开接口，无需认证。
    """
    adapter = PasskeyLoginCompleteAdapter()
    result = await pipeline.run(
        adapter=adapter, http_request=request, db=db, mode=adapter.mode
    )
    refresh_token = (
        result.pop("_refresh_token", None) if isinstance(result, dict) else None
    )
    if refresh_token:
        set_refresh_token_cookie(response, refresh_token)
    return result


class PasskeyLoginCompleteAdapter(PasskeyPublicAdapter):
    """Passkey 登录完成适配器"""

    async def handle(self, context: ApiRequestContext) -> Any:
        """完成 Passkey 登录"""
        await _enforce_passkey_rate_limit(
            context.request,
            endpoint_type="login",
            detail_prefix="Passkey 登录请求",
        )

        payload = context.ensure_json_body()

        if not payload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="请求体不能为空"
            )

        challenge_id = payload.get("challenge_id")
        credential = payload.get("credential")

        if not challenge_id or not credential:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="缺少 challenge_id 或 credential",
            )

        try:
            user = await PasskeyService.complete_authentication(
                db=context.db,
                challenge_id=challenge_id,
                credential=credential,
            )

            user_id = _as_str(user.id)
            user_email = _as_optional_str(user.email)
            user_username = _as_str(user.username)

            access_token, refresh_token = issue_session_bound_tokens(
                db=context.db,
                user=user,
                request=context.request,
            )

            _ = AuditService.log_event(
                db=context.db,
                event_type=AuditEventType.PASSKEY_LOGIN_SUCCESS,
                description=f"用户 {user_email or user_username} 使用 Passkey 登录成功",
                user_id=user_id,
                ip_address=get_client_ip(context.request),
                user_agent=get_user_agent(context.request),
            )
            user.last_login_at = datetime.now(timezone.utc)  # pyright: ignore[reportAttributeAccessIssue]
            context.db.commit()
            context.request.state.tx_committed_by_route = True
            await UserCacheService.invalidate_user_cache(user_id, user_email)

            logger.info(f"Passkey 登录成功: user_id={user_id}")

            response = PasskeyLoginCompleteResponse(
                access_token=access_token,
                token_type="bearer",
                expires_in=86400,
                user_id=user_id,
                email=user_email,
                username=user_username,
                role=_as_str(user.role.value),
            ).model_dump()
            response["_refresh_token"] = refresh_token
            return response
        except PasskeyServiceError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=e.message
            )


@router.get("/credentials")
async def list_passkey_credentials(
    request: Request, db: Session = Depends(get_db)
) -> Any:
    """
    获取当前用户的 Passkey 凭证列表

    返回用户注册的所有 Passkey 凭证信息。
    需要用户已登录（认证适配器）。
    """
    adapter = PasskeyListCredentialsAdapter()
    return await pipeline.run(
        adapter=adapter, http_request=request, db=db, mode=adapter.mode
    )


class PasskeyListCredentialsAdapter(PasskeyAuthenticatedAdapter):
    """Passkey 凭证列表适配器"""

    async def handle(self, context: ApiRequestContext) -> Any:
        """获取用户凭证列表"""
        user = _require_authenticated_user(context)

        credentials = PasskeyService.get_user_credentials(context.db, _as_str(user.id))

        return [_serialize_passkey_credential(cred) for cred in credentials]


@router.patch("/credentials/{credential_id}")
async def update_passkey_credential(
    credential_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Any:
    """
    更新 Passkey 凭证信息

    可以更新设备名称或激活状态。
    需要用户已登录（认证适配器）。
    """
    adapter = PasskeyUpdateCredentialAdapter()
    return await pipeline.run(
        adapter=adapter, http_request=request, db=db, mode=adapter.mode
    )


class PasskeyUpdateCredentialAdapter(PasskeyAuthenticatedAdapter):
    """Passkey 更新凭证适配器"""

    async def handle(self, context: ApiRequestContext) -> Any:
        """更新凭证信息"""
        user = _require_authenticated_user(context)
        payload = context.ensure_json_body()

        if not payload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="请求体不能为空"
            )

        # 从 URL 路径获取 credential_id
        credential_id = context.request.path_params.get("credential_id")
        if not credential_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="缺少凭证 ID"
            )

        device_name = payload.get("device_name")
        is_active = payload.get("is_active")

        try:
            credential = PasskeyService.update_credential(
                db=context.db,
                credential_id=credential_id,
                user_id=_as_str(user.id),
                device_name=device_name,
                is_active=is_active,
            )

            return _serialize_passkey_credential(credential)
        except PasskeyServiceError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=e.message
            )


@router.delete("/credentials/{credential_id}")
async def delete_passkey_credential(
    credential_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Any:
    """
    删除 Passkey 凭证

    从数据库中删除指定的 Passkey 凭证。
    需要用户已登录（认证适配器）。
    """
    adapter = PasskeyDeleteCredentialAdapter()
    return await pipeline.run(
        adapter=adapter, http_request=request, db=db, mode=adapter.mode
    )


class PasskeyDeleteCredentialAdapter(PasskeyAuthenticatedAdapter):
    """Passkey 删除凭证适配器"""

    async def handle(self, context: ApiRequestContext) -> Any:
        """删除凭证"""
        user = _require_authenticated_user(context)

        # 从 URL 路径获取 credential_id
        credential_id = context.request.path_params.get("credential_id")
        if not credential_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="缺少凭证 ID"
            )

        try:
            PasskeyService.delete_credential(
                db=context.db,
                credential_id=credential_id,
                user_id=_as_str(user.id),
            )

            return {"success": True, "message": "凭证已删除"}
        except PasskeyServiceError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=e.message
            )
