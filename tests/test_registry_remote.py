"""Tests for remote (http) server registration, routing and health."""

import httpx
import pytest

from mcpgateway.gateway import Gateway
from mcpgateway.models import ServerRegistration
from mcpgateway.registry import RegistryError, ToolRegistry
from mcpgateway.tools import ToolError


def test_http_server_registers_and_advertises_remote_tools(remote_registry):
    names = sorted(tool.name for tool in remote_registry.list_tools())
    assert names == ["calculator", "echo", "kb_search", "translate", "weather"]
    weather = [t for t in remote_registry.list_tools() if t.name == "weather"][0]
    assert weather.server == "weather-svc"


def test_http_server_without_url_is_rejected():
    registry = ToolRegistry()
    with pytest.raises(RegistryError, match="requires a url"):
        registry.register_server(ServerRegistration(name="remote", kind="http"))


def test_tool_call_routes_to_remote_server(remote_registry):
    result = remote_registry.call_tool("weather", {"city": "Frisco"})
    assert result.is_error is False
    assert "sunny, 21C in Frisco" in result.content[0]["text"]


def test_tool_server_reports_the_remote_owner(remote_registry):
    assert remote_registry.tool_server("weather") == "weather-svc"
    assert remote_registry.tool_server("echo") == "local"


def test_unreachable_server_registers_with_no_tools():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    registry = ToolRegistry(transport=httpx.MockTransport(handler))
    server = registry.register_server(
        ServerRegistration(
            name="down", kind="http", url="http://down:9/mcp"
        )
    )
    assert server.status == "unreachable"
    assert "weather" not in [t.name for t in registry.list_tools()]


def test_health_check_marks_healthy_server(remote_registry):
    server = remote_registry.check_server_health("weather-svc")
    assert server.status == "healthy"
    assert server.last_checked_at is not None


def test_health_check_marks_unreachable_server():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    registry = ToolRegistry(transport=httpx.MockTransport(handler))
    registry.register_server(
        ServerRegistration(name="down", kind="http", url="http://down:9/mcp")
    )
    server = registry.check_server_health("down")
    assert server.status == "unreachable"
    assert server.last_checked_at is not None


def test_health_check_unknown_server_raises(remote_registry):
    with pytest.raises(RegistryError, match="unknown server"):
        remote_registry.check_server_health("nope")


def test_check_all_health_only_touches_remote_servers(remote_registry):
    checked = remote_registry.check_all_health()
    assert [s.name for s in checked] == ["weather-svc"]
    assert checked[0].status == "healthy"


def test_local_server_health_check_is_healthy(remote_registry):
    server = remote_registry.check_server_health("local")
    assert server.status == "healthy"


def test_unknown_tool_is_a_protocol_error(remote_registry, store):
    gateway = Gateway(registry=remote_registry, store=store)
    response = gateway.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "nope-remote", "arguments": {}},
        }
    )
    assert response is not None
    assert response.error is not None  # unknown tool: protocol error
    assert response.error["code"] == -32602


def test_gateway_logs_remote_server_name(remote_registry, store):
    gateway = Gateway(registry=remote_registry, store=store)
    response = gateway.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "weather", "arguments": {"city": "Frisco"}},
        }
    )
    assert response is not None and response.error is None
    calls = store.list_calls()
    assert len(calls) == 1
    assert calls[0].server == "weather-svc"
    assert calls[0].tool_name == "weather"


def test_remote_tool_error_comes_back_as_is_error(store):
    """A remote tool that fails at call time is a failed call, not a
    protocol error: the gateway answers with isError true."""
    import json

    from conftest import fake_mcp_handler

    def flaky(request):
        payload = json.loads(request.content)
        if payload.get("method") == "tools/call":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "error": {"code": -32000, "message": "weather service down"},
                },
            )
        return fake_mcp_handler(request)

    registry = ToolRegistry(transport=httpx.MockTransport(flaky))
    registry.register_server(
        ServerRegistration(
            name="flaky", kind="http", url="http://flaky/mcp"
        )
    )
    assert "weather" in [t.name for t in registry.list_tools()]
    gateway = Gateway(registry=registry, store=store)
    response = gateway.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "weather", "arguments": {"city": "Frisco"}},
        }
    )
    assert response is not None
    assert response.error is None  # not a protocol error
    assert response.result["is_error"] is True
    assert "weather service down" in response.result["content"][0]["text"]
    calls = store.list_calls()
    assert len(calls) == 1
    assert calls[0].server == "flaky"
    assert calls[0].is_error is True
