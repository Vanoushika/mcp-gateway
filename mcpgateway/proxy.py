"""Proxy client for remote MCP servers over HTTP.

A remote server speaks the same JSON-RPC 2.0 subset the gateway
itself serves: ``initialize``, ``ping``, ``tools/list`` and
``tools/call`` over one POST endpoint. The client sends an
``initialize`` handshake once, lazily, before the first real call —
real MCP servers expect it — and then forwards tool calls verbatim.

Any transport failure, bad HTTP status, invalid JSON or remote
protocol error raises :class:`ProxyError`. The registry turns that
into a failed tool call (``isError: true``), not a protocol error,
because the gateway itself worked and the remote tool did not.
"""

from __future__ import annotations

from typing import Any

import httpx

from .models import ToolCallResult, ToolDefinition

PROTOCOL_VERSION = "2025-03-26"


class ProxyError(ValueError):
    """The remote MCP server could not be reached or answered badly."""


class HttpMcpClient:
    """One remote MCP server, reached over HTTP JSON-RPC."""

    def __init__(
        self,
        url: str,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = url
        # trust_env=False: the gateway dials its configured MCP servers
        # directly and must never route them through an egress proxy.
        # It also keeps construction from crashing on proxy env vars
        # httpx cannot parse (for example unbracketed IPv6 entries in
        # NO_PROXY), which would otherwise raise InvalidURL here.
        self._client = httpx.Client(
            timeout=timeout, transport=transport, trust_env=False
        )
        self._initialized = False

    def _request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        }
        try:
            response = self._client.post(self.url, json=payload)
        except httpx.HTTPError as exc:
            raise ProxyError(f"could not reach {self.url}: {exc}") from exc
        if response.status_code != 200:
            raise ProxyError(
                f"remote server returned HTTP {response.status_code}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ProxyError("remote server returned invalid JSON") from exc
        error = data.get("error")
        if error is not None:
            raise ProxyError(f"remote server error: {error}")
        return data.get("result")

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        result = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcp-gateway", "version": "0.1.0"},
            },
        )
        if not isinstance(result, dict) or "protocolVersion" not in result:
            raise ProxyError("remote server did not answer initialize")
        self._initialized = True

    def ping(self) -> bool:
        """True when the remote server answers a ping, False otherwise."""
        try:
            self._request("ping")
            return True
        except ProxyError:
            return False

    def list_tools(self) -> list[ToolDefinition]:
        self._ensure_initialized()
        result = self._request("tools/list")
        if not isinstance(result, dict) or not isinstance(
            result.get("tools"), list
        ):
            raise ProxyError("remote server returned a bad tools/list result")
        tools = []
        for item in result["tools"]:
            tools.append(ToolDefinition.model_validate(item))
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolCallResult:
        self._ensure_initialized()
        result = self._request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        if not isinstance(result, dict):
            raise ProxyError("remote server returned a bad tools/call result")
        return ToolCallResult.model_validate(result)
