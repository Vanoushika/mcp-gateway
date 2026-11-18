"""Tests for the tool registry."""

import pytest

from mcpgateway.models import ServerRegistration
from mcpgateway.registry import RegistryError, ToolRegistry
from mcpgateway.tools import ToolError


def test_local_server_registered_by_default():
    registry = ToolRegistry()
    names = [server.name for server in registry.list_servers()]
    assert names == ["local"]


def test_list_tools_advertises_three_tools():
    registry = ToolRegistry()
    names = sorted(tool.name for tool in registry.list_tools())
    assert names == ["calculator", "echo", "kb_search"]


def test_call_routes_to_local_tool():
    registry = ToolRegistry()
    result = registry.call_tool("echo", {"text": "ping"})
    assert result.content[0]["text"] == "ping"


def test_call_unknown_tool_raises():
    registry = ToolRegistry()
    with pytest.raises(RegistryError, match="unknown tool"):
        registry.call_tool("nope", {})


def test_call_tool_error_propagates():
    registry = ToolRegistry()
    with pytest.raises(ToolError):
        registry.call_tool("calculator", {"expression": "1/0"})


def test_duplicate_server_rejected():
    registry = ToolRegistry()
    with pytest.raises(RegistryError, match="already registered"):
        registry.register_server(ServerRegistration(name="local", kind="local"))


def test_http_server_registers_on_day_two(remote_registry):
    names = [server.name for server in remote_registry.list_servers()]
    assert names == ["local", "weather-svc"]
    server = remote_registry.get_server("weather-svc")
    assert server is not None
    assert server.status == "healthy"


def test_unknown_server_kind_rejected():
    registry = ToolRegistry()
    with pytest.raises(RegistryError, match="unknown server kind"):
        registry.register_server(ServerRegistration(name="weird", kind="grpc"))
