"""Data models for mcp-gateway.

A server is a source of tools (Day 1: local Python tools only).
A tool is a named function with a JSON Schema describing its arguments.
Every tool call is recorded so the gateway can show what ran, how long
it took, and whether it failed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    """One callable tool, as advertised to MCP clients."""

    name: str
    description: str
    input_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    server: str = "local"


class ServerRegistration(BaseModel):
    """A registered tool server.

    ``kind`` is ``local`` for tools implemented in this codebase, or
    ``http`` for a remote MCP server proxied over JSON-RPC. ``status``
    is ``healthy`` for the in-process local server, ``unknown`` for a
    remote server that has not been checked yet, and ``healthy`` /
    ``unreachable`` after a health check.
    """

    name: str
    kind: str = "local"
    url: str | None = None
    description: str = ""
    status: str = "unknown"
    last_checked_at: datetime | None = None
    timeout_seconds: float = 10.0


class ToolPolicy(BaseModel):
    """Per-tool call policy: rate limit and enable/disable.

    ``calls_per_minute`` of ``None`` means no rate limit. A disabled
    tool is rejected before it runs. Policies live in memory and are
    set through the API; they reset when the gateway restarts.
    """

    tool_name: str
    calls_per_minute: int | None = None
    enabled: bool = True


class ToolCallRequest(BaseModel):
    """Arguments for one tool call."""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallResult(BaseModel):
    """The outcome of one tool call, in MCP content-block shape."""

    content: list[dict[str, Any]]
    is_error: bool = False


class CallRecord(BaseModel):
    """One logged gateway call, for the call history."""

    id: str
    tool_name: str
    server: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    is_error: bool
    duration_ms: float
    created_at: datetime


class JsonRpcRequest(BaseModel):
    """A single JSON-RPC 2.0 request object (batches are not supported yet)."""

    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] | None = None


class JsonRpcResponse(BaseModel):
    """A single JSON-RPC 2.0 response object."""

    jsonrpc: str = "2.0"
    id: str | int | None = None
    result: Any = None
    error: dict[str, Any] | None = None
