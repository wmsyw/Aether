from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from webauthn.helpers import bytes_to_base64url

from src.services.auth.passkey_service import PasskeyService


@pytest.mark.asyncio
async def test_complete_registration_normalizes_credential_id_for_query_and_storage() -> (
    None
):
    raw_credential_id = bytes.fromhex("10f5330360")
    expected_credential_id = bytes_to_base64url(raw_credential_id)

    duplicate_query = MagicMock()
    duplicate_query.filter.return_value.first.return_value = None

    db = MagicMock()
    db.query.return_value = duplicate_query

    parsed_credential = SimpleNamespace(
        response=SimpleNamespace(transports=["internal"]),
        authenticator_attachment="platform",
    )
    verification = SimpleNamespace(
        credential_id=raw_credential_id,
        credential_public_key=b"public-key",
        sign_count=1,
        credential_backed_up=True,
        aaguid=None,
    )

    with (
        patch(
            "src.services.auth.passkey_service.PasskeyService._consume_challenge",
            new=AsyncMock(
                return_value={
                    "user_id": "user-1",
                    "challenge": bytes_to_base64url(b"challenge-bytes"),
                    "device_name": "MacBook Pro",
                }
            ),
        ),
        patch(
            "src.services.auth.passkey_service.PasskeyService._count_active_credentials",
            return_value=0,
        ),
        patch(
            "src.services.auth.passkey_service.parse_registration_credential_json",
            return_value=parsed_credential,
        ),
        patch("webauthn.verify_registration_response", return_value=verification),
    ):
        credential = await PasskeyService.complete_registration(
            db=db,
            challenge_id="challenge-1",
            credential={"id": expected_credential_id},
        )

    duplicate_filter_expression = duplicate_query.filter.call_args.args[0]
    stored_credential_id = cast(str, credential.__dict__["credential_id"])

    assert duplicate_filter_expression.right.value == expected_credential_id
    assert stored_credential_id == expected_credential_id
    db.add.assert_called_once_with(credential)
    db.flush.assert_called_once()
