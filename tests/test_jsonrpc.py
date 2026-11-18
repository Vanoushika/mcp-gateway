"""Tests for the JSON-RPC dispatcher (the MCP surface)."""


def test_initialize_handshake(gateway):
    response = gateway.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )
    assert response is not None
    assert response.error is None
    assert response.result["protocolVersion"] == "2025-03-26"
    assert response.result["serverInfo"]["name"] == "mcp-gateway"
    assert "tools" in response.result["capabilities"]


def test_initialized_notification_returns_none(gateway):
    response = gateway.handle(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert response is None


def test_ping(gateway):
    response = gateway.handle({"jsonrpc": "2.0", "id": "x", "method": "ping"})
    assert response is not None and response.error is None
    assert response.result == {}


def test_tools_list(gateway):
    response = gateway.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    )
    names = sorted(tool["name"] for tool in response.result["tools"])
    assert names == ["calculator", "echo", "kb_search"]


def test_tools_call_success_and_logged(gateway, store):
    response = gateway.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "calculator", "arguments": {"expression": "2+3*4"}},
        }
    )
    assert response.error is None
    assert response.result["content"][0]["text"] == "14.0"
    assert response.result["is_error"] is False
    calls = store.list_calls()
    assert len(calls) == 1
    assert calls[0].tool_name == "calculator"
    assert calls[0].is_error is False


def test_tools_call_failure_is_error_result_not_protocol_error(gateway):
    response = gateway.handle(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "calculator", "arguments": {"expression": "1/0"}},
        }
    )
    assert response.error is None
    assert response.result["is_error"] is True
    assert "division by zero" in response.result["content"][0]["text"]


def test_tools_call_unknown_tool_is_protocol_error(gateway):
    response = gateway.handle(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "nope", "arguments": {}},
        }
    )
    assert response.result is None
    assert response.error["code"] == -32602


def test_unknown_method(gateway):
    response = gateway.handle(
        {"jsonrpc": "2.0", "id": 6, "method": "resources/list"}
    )
    assert response.error["code"] == -32601


def test_invalid_request_object(gateway):
    response = gateway.handle({"id": 7, "method": "ping"})
    assert response.error["code"] == -32600


def test_missing_tool_name(gateway):
    response = gateway.handle(
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {}}
    )
    assert response.error["code"] == -32602
