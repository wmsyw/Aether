from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from src.core.logger import logger
from src.services.auth.oauth.base import OAuthProviderBase
from src.services.auth.oauth.models import OAuthFlowError, OAuthToken, OAuthUserInfo

if TYPE_CHECKING:
    from src.models.database import OAuthProvider


class GitHubOAuthProvider(OAuthProviderBase):
    """GitHub OAuth App provider."""

    provider_type = "github"
    display_name = "GitHub"

    allowed_domains = ("github.com", "api.github.com")

    authorization_url = "https://github.com/login/oauth/authorize"
    token_url = "https://github.com/login/oauth/access_token"
    userinfo_url = "https://api.github.com/user"
    emails_url = "https://api.github.com/user/emails"

    default_scopes = ("read:user", "user:email")

    @staticmethod
    def _build_api_headers(access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "Aether",
        }

    async def exchange_code(self, config: OAuthProvider, code: str) -> OAuthToken:
        client_secret = config.get_client_secret()
        redirect_uri = config.redirect_uri
        client_id = config.client_id
        if not client_secret:
            raise OAuthFlowError("provider_unavailable", "client_secret 未配置")
        if not redirect_uri or not client_id:
            raise OAuthFlowError("provider_unavailable", "redirect_uri/client_id 未配置")

        url = self.get_effective_token_url(config)
        resp = await self._http_post_form(
            url,
            data={
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={
                "Accept": "application/json",
                "User-Agent": "Aether",
            },
        )

        if resp.status_code >= 400:
            detail = ""
            try:
                payload = resp.json()
                detail = str(payload.get("error_description") or payload.get("error") or "")
            except Exception:
                detail = ""
            logger.warning("GitHub token 兑换失败: status={} detail={}", resp.status_code, detail)
            raise OAuthFlowError(
                "token_exchange_failed", detail or f"status={resp.status_code}"
            )

        data = resp.json()
        access_token = data.get("access_token")
        if not access_token:
            raise OAuthFlowError("token_exchange_failed", "missing access_token")

        return OAuthToken(
            access_token=str(access_token),
            token_type=str(data.get("token_type") or "bearer"),
            refresh_token=(str(data["refresh_token"]) if data.get("refresh_token") else None),
            expires_in=(int(data["expires_in"]) if data.get("expires_in") is not None else None),
            scope=(str(data["scope"]) if data.get("scope") else None),
            raw=data,
        )

    async def get_user_info(self, config: OAuthProvider, access_token: str) -> OAuthUserInfo:
        headers = self._build_api_headers(access_token)
        userinfo_url = self.get_effective_userinfo_url(config)
        resp = await self._http_get(userinfo_url, headers=headers)

        if resp.status_code >= 400:
            logger.warning("GitHub userinfo 获取失败: status={}", resp.status_code)
            raise OAuthFlowError("userinfo_fetch_failed", f"status={resp.status_code}")

        data: dict[str, Any] = resp.json()
        provider_user_id = data.get("id")
        if provider_user_id is None:
            raise OAuthFlowError("userinfo_fetch_failed", "missing user id")

        email, email_verified, emails_payload = await self._fetch_email_info(
            config,
            access_token,
            fallback_email=data.get("email"),
        )

        raw: dict[str, Any] = {"profile": data}
        if emails_payload is not None:
            raw["emails"] = emails_payload

        return OAuthUserInfo(
            id=str(provider_user_id),
            username=(str(data["login"]) if data.get("login") else None),
            email=email,
            email_verified=email_verified,
            raw=raw,
        )

    async def _fetch_email_info(
        self,
        config: OAuthProvider,
        access_token: str,
        *,
        fallback_email: Any,
    ) -> tuple[str | None, bool | None, list[dict[str, Any]] | None]:
        email = (
            str(fallback_email).lower()
            if isinstance(fallback_email, str) and fallback_email
            else None
        )
        email_verified: bool | None = None
        emails_payload: list[dict[str, Any]] | None = None

        emails_url = self._derive_emails_url(config)
        try:
            resp = await self._http_get(emails_url, headers=self._build_api_headers(access_token))
            if resp.status_code >= 400:
                logger.info("GitHub emails 接口不可用: status={}", resp.status_code)
                return email, email_verified, emails_payload

            payload = resp.json()
            if not isinstance(payload, list):
                return email, email_verified, emails_payload
            emails_payload = [item for item in payload if isinstance(item, dict)]
        except httpx.HTTPError as exc:
            logger.info("GitHub emails 接口请求失败: {}", exc)
            return email, email_verified, emails_payload

        chosen = self._pick_best_email(emails_payload)
        if not chosen:
            return email, email_verified, emails_payload

        chosen_email = chosen.get("email")
        if isinstance(chosen_email, str) and chosen_email:
            email = chosen_email.lower()
        verified_value = chosen.get("verified")
        email_verified = bool(verified_value) if verified_value is not None else email_verified
        return email, email_verified, emails_payload

    def _derive_emails_url(self, config: OAuthProvider) -> str:
        userinfo_url = self.get_effective_userinfo_url(config).rstrip("/")
        if userinfo_url.endswith("/user"):
            return f"{userinfo_url}/emails"
        return self.emails_url

    @staticmethod
    def _pick_best_email(emails: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not emails:
            return None

        for item in emails:
            if item.get("primary") and item.get("email"):
                return item
        for item in emails:
            if item.get("verified") and item.get("email"):
                return item
        for item in emails:
            if item.get("email"):
                return item
        return None
