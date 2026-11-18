"""Tests for the FastAPI surface, including API-key auth."""

import os

import pytest
from fastapi.testclient import TestClient

import mcpgateway.main as main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/api.db")
    monkeypatch.delenv("MCP_GATEWAY_API_KEY", raising=False)
    import importlib

    importlib.reload(main)
    with TestClient(main.app) as test_client:
        yield test_client


def test_health_is_open(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "mcp-gateway"


def test_mcp_initialize_over_http(client):
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "mcp-gateway"


def test_mcp_tools_call_over_http_and_call_history(client):
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"text": "hello"}},
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["content"][0]["text"] == "hello"
    history = client.get("/calls")
    assert history.status_code == 200
    assert len(history.json()["calls"]) == 1
    assert history.json()["calls"][0]["tool_name"] == "echo"


def test_mcp_notification_returns_202(client):
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert response.status_code == 202


def test_mcp_parse_error_returns_400(client):
    response = client.post("/mcp", content="{not json", headers={"Content-Type": "application/json"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32700


def test_tools_endpoint_lists_tools(client):
    response = client.get("/tools")
    assert response.status_code == 200
    assert len(response.json()["tools"]) == 3


def test_register_http_server_accepted(client):
    # No server listens on port 1, so registration succeeds but the
    # server is marked unreachable until it answers a health check.
    response = client.post(
        "/servers",
        json={"name": "remote", "kind": "http", "url": "http://127.0.0.1:1/mcp"},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "unreachable"


def test_get_unknown_call_404(client):
    response = client.get("/calls/does-not-exist")
    assert response.status_code == 404


def test_auth_required_when_key_set(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/auth.db")
    monkeypatch.setenv("MCP_GATEWAY_API_KEY", "secret-key")
    import importlib

    importlib.reload(main)
    with TestClient(main.app) as authed:
        assert authed.get("/health").status_code == 200
        assert authed.get("/tools").status_code == 401
        assert authed.get("/tools", headers={"X-API-Key": "wrong"}).status_code == 401
        ok = authed.get("/tools", headers={"X-API-Key": "secret-key"})
        assert ok.status_code == 200
