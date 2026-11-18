"""Tests for the remote MCP proxy client."""

import json

import httpx
import pytest

from conftest import fake_mcp_handler
from mcpgateway.proxy import HttpMcpClient, ProxyError


def _client(transport):
    return HttpMcpClient("http://fake-remote/mcp", transport=transport)


def test_ping_ok(fake_remote_transport):
    assert _client(fake_remote_transport).ping() is True


def test_ping_false_when_server_errors():
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    assert _client(httpx.MockTransport(handler)).ping() is False


def test_list_tools_returns_remote_tools(fake_remote_transport):
    tools = _client(fake_remote_transport).list_tools()
    names = sorted(tool.name for tool in tools)
    assert names == ["translate", "weather"]


def test_call_tool_returns_result(fake_remote_transport):
    result = _client(fake_remote_transport).call_tool(
        "weather", {"city": "Frisco"}
    )
    assert result.is_error is False
    assert "Frisco" in result.content[0]["text"]


def test_call_unknown_remote_tool_raises(fake_remote_transport):
    with pytest.raises(ProxyError, match="unknown tool"):
        _client(fake_remote_transport).call_tool("nope", {})


def test_initialize_is_sent_before_first_call(fake_remote_transport):
    seen = []

    def spy(request):
        seen.append(json.loads(request.content)["method"])
        return fake_mcp_handler(request)

    client = _client(httpx.MockTransport(spy))
    client.list_tools()
    assert seen[0] == "initialize"
    assert seen[1] == "tools/list"
    # Second call does not re-initialize.
    client.ping()
    assert seen.count("initialize") == 1


def test_http_500_raises_proxy_error():
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(ProxyError, match="HTTP 500"):
        _client(httpx.MockTransport(handler)).list_tools()


def test_invalid_json_raises_proxy_error():
    def handler(request):
        return httpx.Response(200, content=b"not json")

    with pytest.raises(ProxyError, match="invalid JSON"):
        _client(httpx.MockTransport(handler)).list_tools()


def test_connection_failure_raises_proxy_error():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    transport = httpx.MockTransport(handler)
    assert _client(transport).ping() is False
    with pytest.raises(ProxyError, match="could not reach"):
        _client(transport).list_tools()


def test_client_constructs_without_a_transport():
    """Regression: plain construction must not crash on the sandbox's
    proxy env vars (unbracketed IPv6 entries in NO_PROXY make httpx
    raise InvalidURL when trust_env is left on). The call itself then
    fails cleanly as a ProxyError, not a construction crash."""
    client = HttpMcpClient("http://127.0.0.1:1/mcp", timeout=1.0)
    assert client.ping() is False
    with pytest.raises(ProxyError, match="could not reach"):
        client.list_tools()
