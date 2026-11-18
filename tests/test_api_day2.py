"""Tests for the Day 2 API surface: health checks and policies."""

import importlib

import pytest
from fastapi.testclient import TestClient

import mcpgateway.main as main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/api2.db")
    monkeypatch.delenv("MCP_GATEWAY_API_KEY", raising=False)
    importlib.reload(main)
    with TestClient(main.app) as test_client:
        yield test_client


def _register_unreachable(client):
    response = client.post(
        "/servers",
        json={"name": "remote", "kind": "http", "url": "http://127.0.0.1:1/mcp"},
    )
    assert response.status_code == 201
    return response.json()


def test_servers_endpoint_shows_health_status(client):
    _register_unreachable(client)
    response = client.get("/servers")
    assert response.status_code == 200
    by_name = {s["name"]: s for s in response.json()["servers"]}
    assert by_name["local"]["status"] == "healthy"
    assert by_name["remote"]["status"] == "unreachable"
    assert by_name["remote"]["last_checked_at"] is None


def test_health_check_endpoint_updates_status(client):
    _register_unreachable(client)
    response = client.post("/servers/remote/health-check")
    assert response.status_code == 200
    assert response.json()["status"] == "unreachable"
    assert response.json()["last_checked_at"] is not None


def test_health_check_unknown_server_404(client):
    response = client.post("/servers/nope/health-check")
    assert response.status_code == 404


def test_policies_round_trip(client):
    response = client.post(
        "/policies",
        json={"tool_name": "echo", "calls_per_minute": 5, "enabled": True},
    )
    assert response.status_code == 201
    listed = client.get("/policies")
    assert listed.status_code == 200
    assert listed.json()["policies"][0]["calls_per_minute"] == 5


def _mcp_call(client, request_id, name, arguments):
    return client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )


def test_rate_limit_enforced_over_http(client):
    client.post(
        "/policies", json={"tool_name": "echo", "calls_per_minute": 1}
    )
    first = _mcp_call(client, 1, "echo", {"text": "one"})
    assert first.json()["result"]["is_error"] is False
    second = _mcp_call(client, 2, "echo", {"text": "two"})
    assert second.json()["result"]["is_error"] is True
    assert "rate limit exceeded" in second.json()["result"]["content"][0]["text"]
    # Clearing the limit lets the tool run again.
    client.post("/policies", json={"tool_name": "echo", "calls_per_minute": None})
    third = _mcp_call(client, 3, "echo", {"text": "three"})
    assert third.json()["result"]["is_error"] is False


def test_disabled_tool_refused_over_http(client):
    client.post("/policies", json={"tool_name": "calculator", "enabled": False})
    response = _mcp_call(client, 1, "calculator", {"expression": "1+1"})
    assert response.json()["result"]["is_error"] is True
    assert "disabled by policy" in response.json()["result"]["content"][0]["text"]
    client.post("/policies", json={"tool_name": "calculator", "enabled": True})
    again = _mcp_call(client, 2, "calculator", {"expression": "1+1"})
    assert again.json()["result"]["content"][0]["text"] == "2.0"
