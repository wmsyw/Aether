import pytest

from src.services.proxy_node.hub_config import reset_hub_config_cache
from src.services.proxy_node.hub_transport import HubTunnelTransport
from src.services.proxy_node.tunnel_protocol import Frame, MsgType
from src.services.proxy_node.tunnel_transport import TunnelTransport, create_tunnel_transport


def test_create_tunnel_transport_uses_legacy_transport_when_hub_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCKER_CONTAINER", "false")
    monkeypatch.setattr("src.services.proxy_node.hub_config.os.path.exists", lambda _: False)
    reset_hub_config_cache()

    transport = create_tunnel_transport("node-1", timeout=12.0)
    assert isinstance(transport, TunnelTransport)


def test_create_tunnel_transport_uses_hub_transport_when_hub_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCKER_CONTAINER", "true")
    monkeypatch.setattr("src.services.proxy_node.hub_config.os.path.exists", lambda _: False)
    reset_hub_config_cache()

    transport = create_tunnel_transport("node-1", timeout=12.0)
    assert isinstance(transport, HubTunnelTransport)


def test_tunnel_protocol_supports_node_status_msg_type() -> None:
    raw = Frame(0, MsgType.NODE_STATUS, 0, b'{"node_id":"n1","connected":true}').encode()
    decoded = Frame.decode(raw)
    assert decoded.msg_type == MsgType.NODE_STATUS
