"""Command line interface for mcp-gateway.

Usage:
  python -m mcpgateway.cli serve [--host 127.0.0.1] [--port 8000]
  python -m mcpgateway.cli tools
  python -m mcpgateway.cli call calculator --args '{"expression": "2+3*4"}'
  python -m mcpgateway.cli calls [--limit 20]
  python -m mcpgateway.cli analytics
  python -m mcpgateway.cli servers
  python -m mcpgateway.cli check <server-name>
"""

from __future__ import annotations

import argparse
import json
import sys

import uvicorn

from .analytics import compute_analytics
from .gateway import Gateway
from .registry import RegistryError
from .tools import ToolError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcp-gateway", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Run the gateway HTTP server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    sub.add_parser("tools", help="List the tools the gateway can route to")
    call = sub.add_parser("call", help="Call one tool through the gateway")
    call.add_argument("name")
    call.add_argument("--args", default="{}", help="JSON object of arguments")
    calls = sub.add_parser("calls", help="Show recent call history")
    calls.add_argument("--limit", type=int, default=20)
    sub.add_parser(
        "analytics", help="Show per-tool latency and error rates"
    )
    sub.add_parser("servers", help="List registered servers with health status")
    check = sub.add_parser("check", help="Ping one server and show its status")
    check.add_argument("name")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    gateway = Gateway()
    if args.command == "serve":
        uvicorn.run(
            "mcpgateway.main:app", host=args.host, port=args.port, log_level="info"
        )
        return 0
    if args.command == "tools":
        for tool in gateway.registry.list_tools():
            print(f"{tool.name} [{tool.server}]: {tool.description}")
        return 0
    if args.command == "call":
        try:
            arguments = json.loads(args.args)
        except json.JSONDecodeError as exc:
            print(f"invalid --args JSON: {exc}", file=sys.stderr)
            return 2
        if not isinstance(arguments, dict):
            print("--args must be a JSON object", file=sys.stderr)
            return 2
        try:
            result = gateway.registry.call_tool(args.name, arguments)
        except (RegistryError, ToolError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result.model_dump(), indent=2))
        return 0
    if args.command == "calls":
        for record in gateway.store.list_calls(args.limit):
            status = "error" if record.is_error else "ok"
            print(
                f"{record.created_at.isoformat()} {record.tool_name} "
                f"{status} {record.duration_ms:.1f}ms"
            )
        return 0
    if args.command == "analytics":
        analytics = compute_analytics(gateway.store.list_calls(10000))
        print(
            f"{analytics.total_calls} calls, {analytics.total_errors} errors "
            f"({analytics.overall_error_rate:.1%} error rate)"
        )
        for tool in analytics.tools:
            print(
                f"{tool.tool_name} [{tool.server}]: {tool.calls} calls, "
                f"{tool.errors} errors ({tool.error_rate:.1%}), "
                f"mean {tool.mean_latency_ms:.1f}ms, "
                f"p95 {tool.p95_latency_ms:.1f}ms"
            )
        return 0
    if args.command == "servers":
        for server in gateway.registry.list_servers():
            checked = (
                server.last_checked_at.isoformat()
                if server.last_checked_at
                else "never"
            )
            print(
                f"{server.name} [{server.kind}] {server.status} "
                f"(last checked {checked})"
            )
        return 0
    if args.command == "check":
        try:
            server = gateway.registry.check_server_health(args.name)
        except RegistryError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"{server.name}: {server.status}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
