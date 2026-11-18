"""Self-check: the gateway exercises its own public paths, end to end.

Dogfoods what a user would actually rely on:

1. The pytest suite (the gateway's own tests of its tools, registry,
   proxy, policies, analytics and API).
2. The CLI: ``tools`` lists the built-in tools, ``call`` runs the
   calculator, ``analytics`` reports the calls just made.
3. The live API over HTTP: a tool call through ``POST /mcp`` shows up
   in ``GET /analytics`` and in the ``GET /analytics/html`` dashboard.

Everything here runs fully offline against a throwaway database; no
API key is used. Run it with:
    python scripts/self_check.py
It is also a step in .github/workflows/ci.yml.

Exit code 0 means every self-check held; 1 means something regressed.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from mcpgateway.cli import main as cli_main  # noqa: E402
from mcpgateway.gateway import Gateway  # noqa: E402
from mcpgateway.store import Store  # noqa: E402


def _run_pytest() -> tuple[int, int]:
    """Run pytest and return (passed, failed) counts from its last line."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q"],
        cwd=ROOT, capture_output=True, text=True,
    )
    passed = failed = 0
    for line in proc.stdout.splitlines():
        if "passed" in line or "failed" in line:
            for part in line.split(","):
                part = part.strip()
                if part.endswith(" passed"):
                    passed = int(part.split()[0])
                elif part.endswith(" failed"):
                    failed = int(part.split()[0])
    return passed, failed


def _cli_checks(tmp_db: Path) -> tuple[bool, bool, bool]:
    """CLI tools / call / analytics against a throwaway database.

    The analytics check seeds two real calls through the gateway's
    JSON-RPC handler (the only path that logs calls) and then asserts
    the CLI analytics output actually reports them.
    """
    import io
    import os
    from contextlib import redirect_stdout

    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_db}"
    gateway = Gateway(store=Store())
    for expression in ("2+3*4", "1/0"):
        gateway.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "calculator",
                    "arguments": {"expression": expression},
                },
            }
        )

    tools_exit = cli_main(["tools"])
    call_exit = cli_main(
        ["call", "calculator", "--args", '{"expression": "2+3*4"}']
    )
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        analytics_exit = cli_main(["analytics"])
    analytics_output = buffer.getvalue()
    analytics_ok = (
        analytics_exit == 0
        and "2 calls" in analytics_output
        and "calculator" in analytics_output
        and "1 errors" in analytics_output
    )
    return tools_exit == 0, call_exit == 0, analytics_ok


def _api_checks(tmp_db: Path) -> tuple[bool, bool, bool]:
    """Live HTTP: a tool call must appear in /analytics and the dashboard."""
    import os

    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_db}"
    # Import after the env var is set so the app binds the throwaway db.
    import mcpgateway.main as main_module
    import importlib

    importlib.reload(main_module)
    config = uvicorn.Config(
        main_module.app, host="127.0.0.1", port=18081, log_level="error"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    try:
        # trust_env=False: the sandbox NO_PROXY holds unbracketed IPv6
        # entries httpx cannot parse at construction time.
        with httpx.Client(
            base_url="http://127.0.0.1:18081", timeout=10, trust_env=False
        ) as client:
            for _ in range(50):
                try:
                    resp = client.get("/health")
                    if resp.status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                import time

                time.sleep(0.1)
            else:
                return False, False, False

            call = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "calculator",
                        "arguments": {"expression": "2+3*4"},
                    },
                },
            )
            call_ok = (
                call.status_code == 200
                and call.json()["result"]["content"][0]["text"] == "14.0"
            )

            analytics = client.get("/analytics")
            analytics_ok = False
            if analytics.status_code == 200:
                body = analytics.json()
                analytics_ok = body["total_calls"] >= 1 and any(
                    tool["tool_name"] == "calculator"
                    and tool["calls"] >= 1
                    for tool in body["tools"]
                )

            dashboard = client.get("/analytics/html")
            dashboard_ok = (
                dashboard.status_code == 200
                and "calculator" in dashboard.text
                and "Per-tool analytics" in dashboard.text
            )
            return call_ok, analytics_ok, dashboard_ok
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    passed, failed = _run_pytest()
    checks.append(("pytest suite", failed == 0 and passed > 0,
                   f"{passed} passed, {failed} failed"))

    with tempfile.TemporaryDirectory() as tmp:
        tmp_db = Path(tmp) / "selfcheck.db"
        tools_ok, call_ok, analytics_ok = _cli_checks(tmp_db)
        checks.append(("CLI tools lists the built-in tools",
                       tools_ok, "exit 0" if tools_ok else "non-zero exit"))
        checks.append(("CLI call runs the calculator",
                       call_ok, "exit 0" if call_ok else "non-zero exit"))
        checks.append(("CLI analytics reports the seeded calls",
                       analytics_ok,
                       "2 calls, 1 error shown" if analytics_ok else "output missing the calls"))

    with tempfile.TemporaryDirectory() as tmp:
        tmp_db = Path(tmp) / "selfcheck-api.db"
        api_call, api_analytics, api_dashboard = _api_checks(tmp_db)
        checks.append(("live /mcp tool call returns 14.0",
                       api_call, "14.0 returned" if api_call else "call failed"))
        checks.append(("live /analytics shows the calculator call",
                       api_analytics,
                       "call present" if api_analytics else "call missing"))
        checks.append(("live /analytics/html renders the dashboard",
                       api_dashboard,
                       "dashboard rendered" if api_dashboard else "dashboard missing"))

    print("\nSelf-check — mcp-gateway exercising itself")
    print("=" * 48)
    all_ok = True
    for name, ok, detail in checks:
        mark = "PASS" if ok else "FAIL"
        all_ok = all_ok and ok
        print(f"  [{mark}] {name} — {detail}")
    print(f"\nResult: {sum(1 for _, ok, _ in checks if ok)}/{len(checks)} checks held")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
