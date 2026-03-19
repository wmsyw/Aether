from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from src.services.user.apikey import ApiKeyService


def test_normalize_custom_key_accepts_trimmed_valid_key() -> None:
    assert ApiKeyService._normalize_custom_key("  sk-12345678901  ") == "sk-12345678901"


def test_normalize_custom_key_requires_sk_prefix() -> None:
    with pytest.raises(ValueError, match='必须以 "sk-" 开头'):
        ApiKeyService._normalize_custom_key("abc-12345678901")


def test_normalize_custom_key_requires_length_greater_than_ten() -> None:
    with pytest.raises(ValueError, match="长度必须大于 10 位"):
        ApiKeyService._normalize_custom_key("sk-1234567")


def test_create_api_key_rejects_duplicate_custom_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = object()
    monkeypatch.setattr(
        "src.services.user.apikey.crypto_service.encrypt", lambda value: value
    )

    with pytest.raises(ValueError, match="API Key 已存在"):
        ApiKeyService.create_api_key(
            db=db,
            user_id="user-1",
            key="sk-12345678901",
        )


def test_create_api_key_uses_manual_key_when_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    monkeypatch.setattr(
        "src.services.user.apikey.crypto_service.encrypt", lambda value: f"enc::{value}"
    )

    api_key, plain_key = ApiKeyService.create_api_key(
        db=db,
        user_id="user-1",
        name="Manual",
        key="sk-12345678901",
    )

    assert plain_key == "sk-12345678901"
    assert api_key.key_encrypted == "enc::sk-12345678901"
    assert db.add.called
    assert db.commit.called
    assert db.refresh.called


def test_create_api_key_translates_commit_uniqueness_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    db.commit.side_effect = IntegrityError("insert into api_keys", {}, Exception("dup"))
    monkeypatch.setattr(
        "src.services.user.apikey.crypto_service.encrypt", lambda value: f"enc::{value}"
    )

    with pytest.raises(ValueError, match="API Key 已存在"):
        ApiKeyService.create_api_key(
            db=db,
            user_id="user-1",
            key="sk-12345678901",
        )

    assert db.rollback.called
