"""
Passkey/WebAuthn 认证服务

使用 pywebauthn 库实现 WebAuthn 注册和认证流程。
"""

from __future__ import annotations

import base64
import json
import secrets
import uuid
from collections.abc import Awaitable
from datetime import datetime, timezone
from typing import Any, cast

from redis.asyncio import Redis
from sqlalchemy.orm import Session

from src.clients.redis_client import get_redis_client
from src.config import config
from src.core.logger import logger
from src.models.database import User, UserPasskeyCredential


def _as_str(value: object) -> str:
    return cast(str, value)


def _as_bool(value: object) -> bool:
    return cast(bool, value)


class PasskeyServiceError(Exception):
    """Passkey 服务错误"""

    def __init__(self, message: str, code: str = "passkey_error"):
        self.message = message
        self.code = code
        super().__init__(self.message)


class PasskeyService:
    """Passkey/WebAuthn 认证服务"""

    _challenge_ttl_seconds = 300
    _challenge_key_prefix = "passkey:challenge:"
    _max_active_credentials_per_user = 10
    _consume_challenge_script = """
    local value = redis.call("GET", KEYS[1])
    if value then
        redis.call("DEL", KEYS[1])
    end
    return value
    """

    @classmethod
    def _generate_challenge_id(cls) -> str:
        """生成挑战 ID"""
        return str(uuid.uuid4())

    @classmethod
    def _challenge_key(cls, challenge_id: str) -> str:
        return f"{cls._challenge_key_prefix}{challenge_id}"

    @classmethod
    async def _get_redis(cls) -> Redis:
        try:
            redis_client = await get_redis_client(require_redis=True)
        except Exception as exc:
            logger.error(f"Passkey Redis 初始化失败: {exc}")
            raise PasskeyServiceError(
                "Passkey 服务暂不可用，请稍后重试", "redis_unavailable"
            ) from exc

        if redis_client is None:
            raise PasskeyServiceError(
                "Passkey 服务暂不可用，请稍后重试", "redis_unavailable"
            )

        return redis_client

    @classmethod
    async def _store_challenge(cls, challenge_id: str, data: dict[str, Any]) -> None:
        """存储挑战数据。"""
        redis_client = await cls._get_redis()
        await redis_client.setex(
            cls._challenge_key(challenge_id),
            cls._challenge_ttl_seconds,
            json.dumps(data),
        )

    @classmethod
    async def _consume_challenge(cls, challenge_id: str) -> dict[str, Any] | None:
        """原子消费挑战数据。"""
        if not challenge_id:
            return None

        redis_client = await cls._get_redis()
        raw = await cast(
            Awaitable[str | None],
            redis_client.eval(
                cls._consume_challenge_script,
                1,
                cls._challenge_key(challenge_id),
            ),
        )
        if not raw:
            return None

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"Passkey 挑战数据解析失败: challenge_id={challenge_id}")
            return None

        return parsed

    @classmethod
    def _count_active_credentials(cls, db: Session, user_id: str) -> int:
        return (
            db.query(UserPasskeyCredential)
            .filter(
                UserPasskeyCredential.user_id == user_id,
                UserPasskeyCredential.is_active == True,
            )
            .count()
        )

    @classmethod
    def _get_rp_config(cls) -> dict[str, str]:
        """获取 Relying Party 配置"""
        # 使用配置的 RP ID，如果没有则尝试从 CORS 源推断
        rp_id = config.passkey_rp_id
        if not rp_id:
            # 尝试从 CORS 源列表中提取域名
            if config.cors_origins and config.cors_origins != ["*"]:
                rp_id = config.cors_origins[0].split("//")[-1].split(":")[0]
            else:
                rp_id = "localhost"
        return {
            "id": rp_id,
            "name": config.passkey_rp_name or "Aether",
        }

    @classmethod
    def _base64url_encode(cls, data: bytes) -> str:
        """Base64URL 编码"""
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    @classmethod
    def _base64url_decode(cls, data: str) -> bytes:
        """Base64URL 解码"""
        padding = 4 - len(data) % 4
        if padding != 4:
            data += "=" * padding
        return base64.urlsafe_b64decode(data)

    @classmethod
    async def begin_registration(
        cls,
        db: Session,
        user: User,
        device_name: str | None = None,
    ) -> dict[str, Any]:
        """
        开始 Passkey 注册流程

        Args:
            db: 数据库会话
            user: 当前用户
            device_name: 设备名称

        Returns:
            包含 challenge_id 和 publicKeyCredentialCreationOptions 的字典
        """
        try:
            from webauthn import generate_registration_options  # pyright: ignore[reportMissingImports]
            from webauthn.helpers import bytes_to_base64url  # pyright: ignore[reportMissingImports]
        except ImportError:
            raise PasskeyServiceError("pywebauthn 库未安装", "library_not_installed")

        user_id = _as_str(user.id)
        active_credentials = cls._count_active_credentials(db, user_id)
        if active_credentials >= cls._max_active_credentials_per_user:
            raise PasskeyServiceError(
                f"最多只能保留 {cls._max_active_credentials_per_user} 个启用中的 Passkey，请先删除或停用旧设备",
                "credential_limit_exceeded",
            )

        rp = cls._get_rp_config()

        # 生成用户 ID（使用用户 UUID 的字节表示）
        user_id_bytes = user_id.encode("utf-8")

        # 生成挑战
        challenge_bytes = secrets.token_bytes(32)

        # 生成注册选项
        options = generate_registration_options(
            rp_id=rp["id"],
            rp_name=rp["name"],
            user_id=user_id_bytes,
            user_name=user.email or user.username,
            user_display_name=user.username,
            challenge=challenge_bytes,
            timeout=120000,  # 2分钟超时
            attestation="none",  # 不需要 attestation
            authenticator_selection={
                "authenticator_attachment": None,  # 允许所有类型
                "resident_key": "preferred",  # 优先使用 discoverable credentials
                "user_verification": "required",  # 强制用户验证
            },
        )

        # 存储挑战
        challenge_id = cls._generate_challenge_id()
        await cls._store_challenge(
            challenge_id,
            {
                "user_id": user_id,
                "challenge": bytes_to_base64url(options.challenge),
                "device_name": device_name,
            },
        )

        # 转换为前端可用的格式
        options_dict = {
            "rp": {"id": options.rp.id, "name": options.rp.name},
            "user": {
                "id": bytes_to_base64url(options.user.id),
                "name": options.user.name,
                "displayName": options.user.display_name,
            },
            "challenge": bytes_to_base64url(options.challenge),
            "pubKeyCredParams": [
                {"type": param.type, "alg": param.alg}
                for param in options.pub_key_cred_params
            ],
            "timeout": options.timeout,
            "attestation": options.attestation,
            "authenticatorSelection": {
                "authenticatorAttachment": options.authenticator_selection.authenticator_attachment,
                "residentKey": options.authenticator_selection.resident_key,
                "userVerification": options.authenticator_selection.user_verification,
            },
            "excludeCredentials": [
                {
                    "id": bytes_to_base64url(cred.id),
                    "type": cred.type,
                    "transports": list(cred.transports) if cred.transports else [],
                }
                for cred in (options.exclude_credentials or [])
            ],
        }

        logger.info(f"Passkey 注册开始: user_id={user.id}, challenge_id={challenge_id}")

        return {
            "challenge_id": challenge_id,
            "public_key_credential_creation_options": options_dict,
        }

    @classmethod
    async def complete_registration(
        cls,
        db: Session,
        challenge_id: str,
        credential: dict[str, Any],
        device_name: str | None = None,
    ) -> UserPasskeyCredential:
        """
        完成 Passkey 注册流程

        Args:
            db: 数据库会话
            challenge_id: 挑战 ID
            credential: 客户端返回的凭证数据
            device_name: 设备名称

        Returns:
            创建的 UserPasskeyCredential 对象
        """
        try:
            from webauthn import verify_registration_response  # pyright: ignore[reportMissingImports]
            from webauthn.helpers import base64url_to_bytes, bytes_to_base64url  # pyright: ignore[reportMissingImports]
        except ImportError:
            raise PasskeyServiceError("pywebauthn 库未安装", "library_not_installed")

        # 获取挑战数据
        challenge_data = await cls._consume_challenge(challenge_id)
        if not challenge_data:
            raise PasskeyServiceError("挑战已过期或无效", "invalid_challenge")

        user_id = challenge_data["user_id"]
        expected_challenge = challenge_data["challenge"]
        stored_device_name = challenge_data.get("device_name")

        active_credentials = cls._count_active_credentials(db, user_id)
        if active_credentials >= cls._max_active_credentials_per_user:
            raise PasskeyServiceError(
                f"最多只能保留 {cls._max_active_credentials_per_user} 个启用中的 Passkey，请先删除或停用旧设备",
                "credential_limit_exceeded",
            )

        rp = cls._get_rp_config()

        try:
            # 验证注册响应
            verification = verify_registration_response(
                credential=credential,
                expected_challenge=base64url_to_bytes(expected_challenge),
                expected_origin=config.passkey_origin or f"https://{rp['id']}",
                expected_rp_id=rp["id"],
                require_user_verification=True,
            )
        except Exception as e:
            logger.error(f"Passkey 注册验证失败: {e}")
            raise PasskeyServiceError(f"凭证验证失败: {str(e)}", "verification_failed")

        # 检查凭证 ID 是否已存在
        existing = (
            db.query(UserPasskeyCredential)
            .filter(UserPasskeyCredential.credential_id == verification.credential_id)
            .first()
        )
        if existing:
            raise PasskeyServiceError("该凭证已注册", "credential_exists")

        # 创建设备名称
        final_device_name = device_name or stored_device_name or "Passkey 设备"

        # 获取传输方式
        transports = (
            list(verification.credential.transports)
            if verification.credential.transports
            else []
        )

        # 创建凭证记录
        passkey_credential = UserPasskeyCredential(
            user_id=user_id,
            credential_id=verification.credential_id,
            public_key=bytes_to_base64url(verification.credential_public_key),
            sign_count=verification.sign_count,
            device_name=final_device_name,
            device_type="security_key"
            if verification.credential.authenticator_attachment == "cross-platform"
            else "platform",
            backed_up=verification.credential.backup_eligible or False,
            transports=transports,
            aaguid=str(verification.aaguid) if verification.aaguid else None,
            is_active=True,
        )

        db.add(passkey_credential)
        db.flush()

        logger.info(
            f"Passkey 注册成功: user_id={user_id}, credential_id={passkey_credential.id}"
        )

        return passkey_credential

    @classmethod
    async def begin_authentication(
        cls,
        db: Session,
        email: str | None = None,
    ) -> dict[str, Any]:
        """
        开始 Passkey 认证流程

        Args:
            db: 数据库会话
            email: 用户邮箱（可选，用于提示）

        Returns:
            包含 challenge_id 和 publicKeyCredentialRequestOptions 的字典
        """
        try:
            from webauthn import generate_authentication_options  # pyright: ignore[reportMissingImports]
            from webauthn.helpers import bytes_to_base64url  # pyright: ignore[reportMissingImports]
        except ImportError:
            raise PasskeyServiceError("pywebauthn 库未安装", "library_not_installed")

        rp = cls._get_rp_config()

        # 生成挑战
        challenge_bytes = secrets.token_bytes(32)

        # 获取用户的凭证列表（如果提供了邮箱）
        allow_credentials = []
        if email:
            user = db.query(User).filter(User.email == email).first()
            if user:
                credentials = (
                    db.query(UserPasskeyCredential)
                    .filter(
                        UserPasskeyCredential.user_id == user.id,
                        UserPasskeyCredential.is_active == True,
                    )
                    .all()
                )
                allow_credentials = [
                    {
                        "id": cred.credential_id,
                        "type": "public-key",
                        "transports": cred.transports or [],
                    }
                    for cred in credentials
                ]

        # 生成认证选项
        options = generate_authentication_options(
            rp_id=rp["id"],
            challenge=challenge_bytes,
            timeout=120000,  # 2分钟超时
            user_verification="required",
            allow_credentials=allow_credentials if allow_credentials else None,
        )

        # 存储挑战
        challenge_id = cls._generate_challenge_id()
        await cls._store_challenge(
            challenge_id,
            {
                "challenge": bytes_to_base64url(options.challenge),
                "email": email,
            },
        )

        # 转换为前端可用的格式
        options_dict = {
            "challenge": bytes_to_base64url(options.challenge),
            "timeout": options.timeout,
            "rpId": options.rp_id,
            "userVerification": options.user_verification,
            "allowCredentials": [
                {
                    "id": cred["id"],
                    "type": cred["type"],
                    "transports": cred["transports"],
                }
                for cred in (allow_credentials or [])
            ],
        }

        logger.info(f"Passkey 认证开始: challenge_id={challenge_id}, email={email}")

        return {
            "challenge_id": challenge_id,
            "public_key_credential_request_options": options_dict,
        }

    @classmethod
    async def complete_authentication(
        cls,
        db: Session,
        challenge_id: str,
        credential: dict[str, Any],
    ) -> User:
        """
        完成 Passkey 认证流程

        Args:
            db: 数据库会话
            challenge_id: 挑战 ID
            credential: 客户端返回的凭证数据

        Returns:
            认证成功的 User 对象
        """
        try:
            from webauthn import verify_authentication_response  # pyright: ignore[reportMissingImports]
            from webauthn.helpers import base64url_to_bytes  # pyright: ignore[reportMissingImports]
        except ImportError:
            raise PasskeyServiceError("pywebauthn 库未安装", "library_not_installed")

        # 获取挑战数据
        challenge_data = await cls._consume_challenge(challenge_id)
        if not challenge_data:
            raise PasskeyServiceError("挑战已过期或无效", "invalid_challenge")

        expected_challenge = challenge_data["challenge"]
        rp = cls._get_rp_config()

        # 从凭证中获取 credential_id
        credential_id = credential.get("id")
        if not credential_id:
            raise PasskeyServiceError("凭证 ID 缺失", "missing_credential_id")

        # 查找凭证
        passkey_credential = (
            db.query(UserPasskeyCredential)
            .filter(
                UserPasskeyCredential.credential_id == credential_id,
                UserPasskeyCredential.is_active == True,
            )
            .first()
        )

        if not passkey_credential:
            raise PasskeyServiceError("凭证不存在或已禁用", "credential_not_found")

        try:
            # 验证认证响应
            verification = verify_authentication_response(
                credential=credential,
                expected_challenge=base64url_to_bytes(expected_challenge),
                expected_origin=config.passkey_origin or f"https://{rp['id']}",
                expected_rp_id=rp["id"],
                credential_public_key=base64url_to_bytes(passkey_credential.public_key),
                credential_current_sign_count=passkey_credential.sign_count,
                require_user_verification=True,
            )
        except Exception as e:
            logger.error(f"Passkey 认证验证失败: {e}")
            raise PasskeyServiceError(f"认证验证失败: {str(e)}", "verification_failed")

        # 更新签名计数器
        passkey_credential.sign_count = verification.new_sign_count  # pyright: ignore[reportAttributeAccessIssue]
        passkey_credential.last_used_at = datetime.now(timezone.utc)  # pyright: ignore[reportAttributeAccessIssue]

        # 获取用户
        user = db.query(User).filter(User.id == passkey_credential.user_id).first()
        if not user:
            raise PasskeyServiceError("用户不存在", "user_not_found")

        if not _as_bool(user.is_active):
            raise PasskeyServiceError("用户已禁用", "user_inactive")

        db.flush()

        logger.info(
            f"Passkey 认证成功: user_id={user.id}, credential_id={passkey_credential.id}"
        )

        return user

    @classmethod
    def get_user_credentials(
        cls, db: Session, user_id: str
    ) -> list[UserPasskeyCredential]:
        """
        获取用户的所有 Passkey 凭证

        Args:
            db: 数据库会话
            user_id: 用户 ID

        Returns:
            凭证列表
        """
        return (
            db.query(UserPasskeyCredential)
            .filter(UserPasskeyCredential.user_id == user_id)
            .order_by(UserPasskeyCredential.created_at.desc())
            .all()
        )

    @classmethod
    def get_credential_by_id(
        cls, db: Session, credential_id: str, user_id: str
    ) -> UserPasskeyCredential | None:
        """
        根据 ID 获取凭证

        Args:
            db: 数据库会话
            credential_id: 凭证 ID
            user_id: 用户 ID

        Returns:
            凭证对象或 None
        """
        return (
            db.query(UserPasskeyCredential)
            .filter(
                UserPasskeyCredential.id == credential_id,
                UserPasskeyCredential.user_id == user_id,
            )
            .first()
        )

    @classmethod
    def update_credential(
        cls,
        db: Session,
        credential_id: str,
        user_id: str,
        device_name: str | None = None,
        is_active: bool | None = None,
    ) -> UserPasskeyCredential:
        """
        更新凭证信息

        Args:
            db: 数据库会话
            credential_id: 凭证 ID
            user_id: 用户 ID
            device_name: 新的设备名称
            is_active: 新的激活状态

        Returns:
            更新后的凭证对象
        """
        credential = cls.get_credential_by_id(db, credential_id, user_id)
        if not credential:
            raise PasskeyServiceError("凭证不存在", "credential_not_found")

        if device_name is not None:
            credential.device_name = device_name  # pyright: ignore[reportAttributeAccessIssue]

        if is_active is not None:
            credential.is_active = is_active  # pyright: ignore[reportAttributeAccessIssue]

        db.commit()

        logger.info(
            f"Passkey 凭证更新: credential_id={credential_id}, user_id={user_id}"
        )

        return credential

    @classmethod
    def delete_credential(cls, db: Session, credential_id: str, user_id: str) -> None:
        """
        删除凭证

        Args:
            db: 数据库会话
            credential_id: 凭证 ID
            user_id: 用户 ID
        """
        credential = cls.get_credential_by_id(db, credential_id, user_id)
        if not credential:
            raise PasskeyServiceError("凭证不存在", "credential_not_found")

        db.delete(credential)
        db.commit()

        logger.info(
            f"Passkey 凭证删除: credential_id={credential_id}, user_id={user_id}"
        )

    @classmethod
    def get_settings(cls) -> dict[str, Any]:
        """
        获取 Passkey 设置

        Returns:
            设置字典
        """
        rp = cls._get_rp_config()
        return {
            "enabled": True,
            "rp_id": rp["id"],
            "rp_name": rp["name"],
        }
