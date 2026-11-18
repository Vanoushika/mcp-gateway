"""Tool registry: which server owns which tool, and how to call it.

Day 2 adds remote servers. A server of kind ``http`` is a remote MCP
server reached through :class:`mcpgateway.proxy.HttpMcpClient`; its
tools are fetched at registration and cached for 60 seconds, then
refreshed lazily. A server that cannot be reached at registration is
still registered — with status ``unreachable`` and no tools — so a
temporarily-down server is not lost; its tools appear after the next
successful health check.

Every call passes through the policy store first: a disabled tool is
refused, and a tool over its per-minute limit is refused, before any
server is contacted.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from .models import ServerRegistration, ToolCallResult, ToolDefinition, ToolPolicy
from .policies import PolicyError, PolicyStore
from .proxy import HttpMcpClient, ProxyError
from .tools import LOCAL_TOOLS, ToolError

logger = logging.getLogger(__name__)

REMOTE_TOOL_CACHE_TTL_SECONDS = 60.0


class RegistryError(ValueError):
    """The registry cannot do what was asked (unknown tool, bad server)."""


class ToolRegistry:
    """Owns server registrations and routes tool calls to them."""

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._servers: dict[str, ServerRegistration] = {}
        self._clients: dict[str, HttpMcpClient] = {}
        self._remote_tools: dict[str, list[ToolDefinition]] = {}
        self._tools_fetched_at: dict[str, float] = {}
        self._transport = transport
        self.policies = PolicyStore()
        self.register_server(
            ServerRegistration(
                name="local",
                kind="local",
                description="Built-in tools running inside the gateway.",
                status="healthy",
            )
        )

    def register_server(self, server: ServerRegistration) -> ServerRegistration:
        if server.name in self._servers:
            raise RegistryError(f"server {server.name!r} is already registered")
        if server.kind == "local":
            server.status = "healthy"
        elif server.kind == "http":
            if not server.url:
                raise RegistryError("an http server requires a url")
            server.status = "unknown"
        else:
            raise RegistryError(f"unknown server kind {server.kind!r}")
        self._servers[server.name] = server
        if server.kind == "http":
            assert server.url is not None
            self._clients[server.name] = HttpMcpClient(
                server.url,
                timeout=server.timeout_seconds,
                transport=self._transport,
            )
            self._refresh_remote_tools(server.name)
        return server

    def list_servers(self) -> list[ServerRegistration]:
        return list(self._servers.values())

    def get_server(self, name: str) -> ServerRegistration | None:
        return self._servers.get(name)

    def _refresh_remote_tools(self, server_name: str) -> None:
        """Fetch a remote server's tools; mark it unreachable on failure."""
        server = self._servers[server_name]
        client = self._clients[server_name]
        try:
            tools = client.list_tools()
        except (ProxyError, ValueError) as exc:
            logger.warning("could not fetch tools from %r: %s", server_name, exc)
            server.status = "unreachable"
            self._remote_tools.pop(server_name, None)
            return
        for tool in tools:
            tool.server = server_name
        self._remote_tools[server_name] = tools
        self._tools_fetched_at[server_name] = time.monotonic()
        server.status = "healthy"

    def _remote_tools_for(self, server_name: str) -> list[ToolDefinition]:
        fetched_at = self._tools_fetched_at.get(server_name)
        if (
            fetched_at is None
            or time.monotonic() - fetched_at > REMOTE_TOOL_CACHE_TTL_SECONDS
        ):
            self._refresh_remote_tools(server_name)
        return self._remote_tools.get(server_name, [])

    def list_tools(self) -> list[ToolDefinition]:
        tools = []
        for definition, _ in LOCAL_TOOLS.values():
            tools.append(definition)
        for server_name, server in self._servers.items():
            if server.kind == "http":
                tools.extend(self._remote_tools_for(server_name))
        return tools

    def tool_server(self, name: str) -> str:
        """Which server owns a tool name, or raise RegistryError."""
        if name in LOCAL_TOOLS:
            return "local"
        for server_name, server in self._servers.items():
            if server.kind != "http":
                continue
            if any(tool.name == name for tool in self._remote_tools_for(server_name)):
                return server_name
        raise RegistryError(f"unknown tool {name!r}")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolCallResult:
        try:
            self.policies.enforce(name)
        except PolicyError as exc:
            raise ToolError(str(exc)) from exc
        server_name = self.tool_server(name)
        if server_name == "local":
            entry = LOCAL_TOOLS[name]
            _, fn = entry
            try:
                return fn(arguments)
            except ToolError:
                raise
            except Exception as exc:  # defensive: a tool bug is a failed call
                raise ToolError(f"tool {name!r} failed: {exc}") from exc
        client = self._clients[server_name]
        try:
            return client.call_tool(name, arguments)
        except (ProxyError, ValueError) as exc:
            raise ToolError(f"remote tool {name!r} failed: {exc}") from exc

    def check_server_health(self, name: str) -> ServerRegistration:
        """Ping one server and record the result. Returns the registration."""
        server = self._servers.get(name)
        if server is None:
            raise RegistryError(f"unknown server {name!r}")
        if server.kind == "local":
            server.status = "healthy"
        else:
            healthy = self._clients[name].ping()
            server.status = "healthy" if healthy else "unreachable"
            if healthy:
                self._refresh_remote_tools(name)
        server.last_checked_at = datetime.now(timezone.utc)
        return server

    def check_all_health(self) -> list[ServerRegistration]:
        """Ping every registered server; returns the updated list."""
        return [
            self.check_server_health(name)
            for name in list(self._servers)
            if self._servers[name].kind == "http"
        ]

    def set_policy(self, policy: ToolPolicy) -> ToolPolicy:
        return self.policies.set_policy(policy)

    def list_policies(self) -> list[ToolPolicy]:
        return self.policies.list_policies()
