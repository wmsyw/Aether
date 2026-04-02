from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.api.oauth.admin import OAuthProviderUpsertRequest


def test_oauth_upsert_request_allows_blank_core_fields_when_disabled() -> None:
    req = OAuthProviderUpsertRequest.model_validate(
        {
            "display_name": "GitHub",
            "client_id": "",
            "client_secret": None,
            "authorization_url_override": None,
            "token_url_override": None,
            "userinfo_url_override": None,
            "scopes": None,
            "redirect_uri": "",
            "frontend_callback_url": "",
            "attribute_mapping": None,
            "extra_config": None,
            "is_enabled": False,
            "force": False,
        }
    )

    assert req.client_id == ""
    assert req.redirect_uri == ""
    assert req.frontend_callback_url == ""
    assert req.is_enabled is False


def test_oauth_upsert_request_rejects_blank_core_fields_when_enabled() -> None:
    with pytest.raises(ValidationError):
        OAuthProviderUpsertRequest.model_validate(
            {
                "display_name": "GitHub",
                "client_id": "",
                "client_secret": None,
                "authorization_url_override": None,
                "token_url_override": None,
                "userinfo_url_override": None,
                "scopes": None,
                "redirect_uri": "",
                "frontend_callback_url": "",
                "attribute_mapping": None,
                "extra_config": None,
                "is_enabled": True,
                "force": False,
            }
        )
