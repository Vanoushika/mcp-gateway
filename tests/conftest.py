"""Shared fixtures: every test gets a fresh temp database."""

from __future__ import annotations

import json

import httpx
import pytest

from mcpgateway.gateway import Gateway
from mcpgateway.registry import ToolRegistry
from mcpgateway.store import Store


@pytest.fixture()
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path}/test.db")


@pytest.fixture()
def gateway(store):
    return Gateway(registry=ToolRegistry(), store=store)


FAKE_REMOTE_TOOLS = [
    {
        "name": "weather",
        "description": "Current weather for a city.",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
    {
        "name": "translate",
        "description": "Translate text to another language.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "language": {"type": "string"},
            },
            "required": ["text", "language"],
        },
    },
]


def fake_mcp_handler(request: httpx.Request) -> httpx.Response:
    """A tiny in-memory MCP server, for proxy tests.

    Speaks the same JSON-RPC subset as the gateway: initialize, ping,
    tools/list and tools/call for ``weather`` and ``translate``.
    """
    payload = json.loads(request.content)
    method = payload.get("method")
    params = payload.get("params") or {}
    request_id = payload.get("id")

    def reply(result=None, error=None):
        body = {"jsonrpc": "2.0", "id": request_id}
        if error is not None:
            body["error"] = error
        else:
            body["result"] = result
        return httpx.Response(200, json=body)

    if method == "initialize":
        return reply(
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-remote", "version": "1.0"},
            }
        )
    if method == "ping":
        return reply({})
    if method == "tools/list":
        return reply({"tools": FAKE_REMOTE_TOOLS})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name == "weather":
            city = arguments.get("city", "unknown")
            return reply(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": f"sunny, 21C in {city}",
                        }
                    ],
                    "is_error": False,
                }
            )
        if name == "translate":
            return reply(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": f"[{arguments.get('language')}] "
                            f"{arguments.get('text')}",
                        }
                    ],
                    "is_error": False,
                }
            )
        return reply(
            error={"code": -32602, "message": f"unknown tool {name!r}"}
        )
    return reply(error={"code": -32601, "message": f"method not found: {method}"})


@pytest.fixture()
def fake_remote_transport():
    return httpx.MockTransport(fake_mcp_handler)


@pytest.fixture()
def remote_registry(fake_remote_transport):
    """A registry with one healthy remote server ('weather-svc')."""
    registry = ToolRegistry(transport=fake_remote_transport)
    from mcpgateway.models import ServerRegistration

    registry.register_server(
        ServerRegistration(
            name="weather-svc",
            kind="http",
            url="http://fake-remote/mcp",
            description="Fake remote weather server for tests.",
        )
    )
    return registry
