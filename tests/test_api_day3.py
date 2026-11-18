"""Tests for the Day 3 API surface: /analytics and /analytics/html."""

import os

import pytest
from fastapi.testclient import TestClient

import mcpgateway.main as main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/api-day3.db")
    monkeypatch.delenv("MCP_GATEWAY_API_KEY", raising=False)
    import importlib

    importlib.reload(main)
    with TestClient(main.app) as test_client:
        yield test_client


def _call(client, name, arguments):
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200
    return response


def test_analytics_json_after_calls(client):
    _call(client, "calculator", {"expression": "2+3*4"})
    _call(client, "calculator", {"expression": "1/0"})
    _call(client, "echo", {"text": "hi"})

    response = client.get("/analytics")
    assert response.status_code == 200
    body = response.json()
    assert body["total_calls"] == 3
    assert body["total_errors"] == 1

    calc = next(t for t in body["tools"] if t["tool_name"] == "calculator")
    assert calc["calls"] == 2
    assert calc["errors"] == 1
    assert calc["error_rate"] == pytest.approx(0.5)
    assert calc["mean_latency_ms"] >= 0
    assert calc["p95_latency_ms"] >= calc["p50_latency_ms"]

    echo = next(t for t in body["tools"] if t["tool_name"] == "echo")
    assert echo["calls"] == 1
    assert echo["errors"] == 0


def test_analytics_json_with_no_calls(client):
    response = client.get("/analytics")
    assert response.status_code == 200
    assert response.json() == {
        "total_calls": 0,
        "total_errors": 0,
        "overall_error_rate": 0.0,
        "tools": [],
    }


def test_analytics_html_dashboard(client):
    _call(client, "echo", {"text": "hello"})
    _call(client, "calculator", {"expression": "1/0"})

    response = client.get("/analytics/html")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "mcp-gateway dashboard" in response.text
    assert "Per-tool analytics" in response.text
    assert "calculator" in response.text
    assert "echo" in response.text
    assert "2 calls recorded" in response.text
    assert "error" in response.text


def test_analytics_requires_api_key_when_configured(client, monkeypatch):
    monkeypatch.setenv("MCP_GATEWAY_API_KEY", "secret-key")
    # The app reads the key at request time, so no reload is needed.
    unauthenticated = client.get("/analytics")
    assert unauthenticated.status_code == 401
    authenticated = client.get(
        "/analytics", headers={"X-API-Key": "secret-key"}
    )
    assert authenticated.status_code == 200
