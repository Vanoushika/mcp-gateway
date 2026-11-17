"""API-key auth for the gateway.

When the ``MCP_GATEWAY_API_KEY`` environment variable is set, every
route except ``/health`` requires it in the ``X-API-Key`` header.
When it is unset the gateway runs open; that is for local development
only, and the server logs a warning at startup.
"""

from __future__ import annotations

import os

from fastapi import Header, HTTPException


def api_key_configured() -> bool:
    return bool(os.environ.get("MCP_GATEWAY_API_KEY"))


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.environ.get("MCP_GATEWAY_API_KEY")
    if not expected:
        return
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="missing or invalid API key")
