from __future__ import annotations

import gzip
import json

from src.services.proxy_node.resolver import build_post_kwargs, build_stream_kwargs


class TestProxyResolverCompression:
    def test_build_post_kwargs_compresses_when_client_sent_gzip(self) -> None:
        payload = {"message": "hello", "tokens": [1, 2, 3]}
        kwargs = build_post_kwargs(
            None,
            url="https://example.com/v1/messages",
            headers={"Content-Type": "application/json"},
            payload=payload,
            timeout=10.0,
            client_content_encoding="gzip",
        )

        assert kwargs["headers"]["Content-Encoding"] == "gzip"
        assert json.loads(gzip.decompress(kwargs["content"]).decode("utf-8")) == payload

    def test_build_post_kwargs_keeps_plain_body_without_client_gzip(self) -> None:
        payload = {"message": "plain"}
        kwargs = build_post_kwargs(
            None,
            url="https://example.com/v1/messages",
            headers={"Content-Type": "application/json"},
            payload=payload,
            timeout=10.0,
            client_content_encoding=None,
        )

        assert "Content-Encoding" not in kwargs["headers"]
        assert json.loads(kwargs["content"].decode("utf-8")) == payload

    def test_build_stream_kwargs_drops_stale_content_encoding_header(self) -> None:
        kwargs = build_stream_kwargs(
            None,
            url="https://example.com/v1/messages",
            headers={"content-encoding": "gzip", "Content-Type": "application/json"},
            payload={"message": "no-gzip"},
            timeout=10.0,
            client_content_encoding=None,
        )

        assert all(key.lower() != "content-encoding" for key in kwargs["headers"])
