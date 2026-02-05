from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.services.antigravity.client import load_code_assist
from src.services.antigravity.constants import DAILY_BASE_URL, PROD_BASE_URL


@pytest.mark.asyncio
async def test_load_code_assist_falls_back_to_daily() -> None:
    resp1 = httpx.Response(500, json={"error": {"message": "boom"}})
    resp2 = httpx.Response(200, json={"cloudaicompanionProject": "project-1"})

    client = SimpleNamespace(post=AsyncMock(side_effect=[resp1, resp2]))

    with patch(
        "src.clients.http_client.HTTPClientPool.get_proxy_client",
        AsyncMock(return_value=client),
    ):
        data = await load_code_assist("tok", proxy_config=None, timeout_seconds=1.0)

    assert data["cloudaicompanionProject"] == "project-1"
    assert client.post.await_count == 2
    assert client.post.call_args_list[0].args[0] == f"{PROD_BASE_URL}/v1internal:loadCodeAssist"
    assert client.post.call_args_list[1].args[0] == f"{DAILY_BASE_URL}/v1internal:loadCodeAssist"


@pytest.mark.asyncio
async def test_load_code_assist_requires_token() -> None:
    with pytest.raises(ValueError):
        await load_code_assist("", proxy_config=None)

