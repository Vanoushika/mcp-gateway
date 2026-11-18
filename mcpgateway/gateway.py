"""JSON-RPC 2.0 dispatcher for the MCP Streamable HTTP transport.

Day 1 implements the smallest useful subset of the Model Context
Protocol over a single ``POST /mcp`` endpoint:

- ``initialize``: protocol handshake, returns server info.
- ``notifications/initialized``: client notification, no response.
- ``ping``: liveness check.
- ``tools/list``: every tool the gateway can route to.
- ``tools/call``: run one tool and return its content blocks.

Protocol errors use the standard JSON-RPC codes (-32600, -32601,
-32602). A tool that runs and fails is not a protocol error: it comes
back as a result with ``isError: true``, the MCP convention.
"""

from __future__ import annotations

import time
from typing import Any

from . import __version__
from .models import JsonRpcRequest, JsonRpcResponse, ToolCallResult
from .registry import RegistryError, ToolRegistry
from .store import Store
from .tools import ToolError

PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "mcp-gateway"


def _error_response(
    request_id: str | int | None, code: int, message: str
) -> JsonRpcResponse:
    return JsonRpcResponse(
        id=request_id, error={"code": code, "message": message}
    )


class Gateway:
    """Routes JSON-RPC requests to the registry and logs every call."""

    def __init__(
        self, registry: ToolRegistry | None = None, store: Store | None = None
    ) -> None:
        self.registry = registry or ToolRegistry()
        self.store = store or Store()

    def handle(self, payload: dict[str, Any]) -> JsonRpcResponse | None:
        """Dispatch one JSON-RPC request.

        Returns ``None`` for notifications, which get no response.
        """
        request_id = payload.get("id")
        method = payload.get("method")
        if payload.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return _error_response(request_id, -32600, "invalid Request object")
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            return _error_response(request_id, -32602, "params must be an object")

        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return JsonRpcResponse(
                id=request_id,
                result={
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": __version__},
                },
            )
        if method == "ping":
            return JsonRpcResponse(id=request_id, result={})
        if method == "tools/list":
            tools = [tool.model_dump() for tool in self.registry.list_tools()]
            return JsonRpcResponse(id=request_id, result={"tools": tools})
        if method == "tools/call":
            return self._handle_tool_call(request_id, params)
        return _error_response(request_id, -32601, f"method not found: {method}")

    def _handle_tool_call(
        self, request_id: str | int | None, params: dict[str, Any]
    ) -> JsonRpcResponse:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not name:
            return _error_response(
                request_id, -32602, "tools/call requires a string 'name'"
            )
        if not isinstance(arguments, dict):
            return _error_response(
                request_id, -32602, "tools/call 'arguments' must be an object"
            )
        started = time.perf_counter()
        try:
            server = self.registry.tool_server(name)
        except RegistryError as exc:
            return _error_response(request_id, -32602, str(exc))
        try:
            result = self.registry.call_tool(name, arguments)
        except RegistryError as exc:
            return _error_response(request_id, -32602, str(exc))
        except ToolError as exc:
            result = ToolCallResult(
                content=[{"type": "text", "text": str(exc)}], is_error=True
            )
        duration_ms = (time.perf_counter() - started) * 1000
        self.store.record_call(
            tool_name=name,
            server=server,
            arguments=arguments,
            result=result.model_dump(),
            is_error=result.is_error,
            duration_ms=duration_ms,
        )
        return JsonRpcResponse(id=request_id, result=result.model_dump())


def parse_request(payload: Any) -> JsonRpcRequest:
    """Validate the raw JSON body into a request model."""
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    return JsonRpcRequest.model_validate(payload)
