"""FastAPI app — one governed entry point for agent tools.

Endpoints:
  GET  /health            service health (no auth)
  POST /mcp              MCP Streamable HTTP: JSON-RPC 2.0 requests
  GET  /tools            tools the gateway can route to
  GET  /servers          registered servers, with health status
  POST /servers          register a server (local or remote http)
  POST /servers/{name}/health-check   ping one server now
  GET  /policies         per-tool call policies
  POST /policies         set a per-tool policy (rate limit, disable)
  GET  /calls            recent tool-call history
  GET  /calls/{id}       one call record
  GET  /analytics        per-tool latency and error rates (JSON)
  GET  /analytics/html   the same analytics as a dashboard page

A background thread pings every registered remote server every
MCP_GATEWAY_HEALTH_INTERVAL_SECONDS (default 60) and refreshes its
status and tool list, so /servers always shows a recent verdict.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import __version__
from .analytics import compute_analytics
from .auth import api_key_configured, require_api_key
from .dashboard import render_dashboard
from .gateway import Gateway, parse_request
from .models import ServerRegistration, ToolPolicy
from .registry import RegistryError
from .store import Store

logger = logging.getLogger(__name__)


def _health_interval_seconds() -> float:
    try:
        return float(os.environ.get("MCP_GATEWAY_HEALTH_INTERVAL_SECONDS", "60"))
    except ValueError:
        return 60.0


def _health_loop(gateway: Gateway, stop: threading.Event) -> None:
    interval = _health_interval_seconds()
    while not stop.wait(interval):
        try:
            gateway.registry.check_all_health()
        except Exception as exc:  # a failed check must not kill the loop
            logger.warning("periodic health check failed: %s", exc)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not api_key_configured():
        logger.warning(
            "MCP_GATEWAY_API_KEY is not set: the gateway is running open. "
            "Set it before exposing this service."
        )
    stop = threading.Event()
    thread = threading.Thread(
        target=_health_loop, args=(gateway, stop), daemon=True
    )
    thread.start()
    try:
        yield
    finally:
        stop.set()


app = FastAPI(
    title="MCP Gateway",
    description="One governed entry point for agent tools: routing, "
    "API-key auth and call logging for MCP servers.",
    version=__version__,
    lifespan=lifespan,
)

store = Store()
gateway = Gateway(store=store)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "mcp-gateway", "version": __version__}


@app.post("/mcp")
async def mcp_endpoint(
    request: Request, _auth: None = Depends(require_api_key)
) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "parse error"},
            },
        )
    try:
        parsed = parse_request(payload)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": payload.get("id") if isinstance(payload, dict) else None,
                "error": {"code": -32600, "message": str(exc)},
            },
        )
    response = await asyncio.to_thread(
        gateway.handle, parsed.model_dump(exclude_none=False)
    )
    if response is None:
        return JSONResponse(status_code=202, content={})
    return JSONResponse(
        status_code=200, content=response.model_dump(exclude_none=True)
    )


@app.get("/tools", dependencies=[Depends(require_api_key)])
def list_tools() -> dict[str, Any]:
    return {"tools": [tool.model_dump() for tool in gateway.registry.list_tools()]}


@app.get("/servers", dependencies=[Depends(require_api_key)])
def list_servers() -> dict[str, Any]:
    return {
        "servers": [
            server.model_dump() for server in gateway.registry.list_servers()
        ]
    }


@app.post("/servers", status_code=201, dependencies=[Depends(require_api_key)])
def register_server(server: ServerRegistration) -> ServerRegistration:
    try:
        return gateway.registry.register_server(server)
    except RegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/servers/{name}/health-check", dependencies=[Depends(require_api_key)]
)
def health_check_server(name: str) -> ServerRegistration:
    try:
        return gateway.registry.check_server_health(name)
    except RegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/policies", dependencies=[Depends(require_api_key)])
def list_policies() -> dict[str, Any]:
    return {
        "policies": [
            policy.model_dump() for policy in gateway.registry.list_policies()
        ]
    }


@app.post("/policies", status_code=201, dependencies=[Depends(require_api_key)])
def set_policy(policy: ToolPolicy) -> ToolPolicy:
    return gateway.registry.set_policy(policy)


@app.get("/calls", dependencies=[Depends(require_api_key)])
def list_calls(limit: int = 50) -> dict[str, Any]:
    return {"calls": [call.model_dump(mode="json") for call in store.list_calls(limit)]}


@app.get("/calls/{call_id}", dependencies=[Depends(require_api_key)])
def get_call(call_id: str) -> dict[str, Any]:
    record = store.get_call(call_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"call {call_id!r} not found")
    return record.model_dump(mode="json")


@app.get("/analytics", dependencies=[Depends(require_api_key)])
def get_analytics() -> dict[str, Any]:
    records = store.list_calls(limit=10000)
    return compute_analytics(records).model_dump(mode="json")


@app.get(
    "/analytics/html",
    response_class=HTMLResponse,
    dependencies=[Depends(require_api_key)],
)
def get_analytics_html() -> str:
    records = store.list_calls(limit=10000)
    analytics = compute_analytics(records)
    return render_dashboard(analytics, records[:20])
