import pytest

from src.api.handlers.claude.adapter import ClaudeChatAdapter


@pytest.mark.asyncio
async def test_check_endpoint_accepts_base_url_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_run_endpoint_check(**kwargs):
        captured.update(kwargs)
        return {"status_code": 200, "headers": {}, "response_time_ms": 1, "request_id": "test"}

    monkeypatch.setattr(
        "src.api.handlers.base.endpoint_checker.run_endpoint_check",
        fake_run_endpoint_check,
    )

    await ClaudeChatAdapter.check_endpoint(
        client=None,
        base_url={"base_url": "https://api.anthropic.com"},
        api_key="test-key",
        request_data={
            "model": "claude-sonnet-4-5-20250929",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 32,
            "stream": False,
        },
    )

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert isinstance(captured["json_body"], dict)


@pytest.mark.asyncio
async def test_check_endpoint_accepts_url_key_in_base_url_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_run_endpoint_check(**kwargs):
        captured.update(kwargs)
        return {"status_code": 200, "headers": {}, "response_time_ms": 1, "request_id": "test"}

    monkeypatch.setattr(
        "src.api.handlers.base.endpoint_checker.run_endpoint_check",
        fake_run_endpoint_check,
    )

    await ClaudeChatAdapter.check_endpoint(
        client=None,
        base_url={"url": "https://api.anthropic.com/v1"},
        api_key="test-key",
        request_data={
            "model": "claude-sonnet-4-5-20250929",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 32,
            "stream": False,
        },
    )

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
