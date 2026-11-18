"""HTML dashboard — a single self-contained page, no JavaScript.

Shows the per-tool analytics table and the most recent calls, so an
operator can see gateway health in a browser without a separate
frontend. All values are escaped; nothing here runs code.
"""

from __future__ import annotations

import html

from .analytics import GatewayAnalytics
from .models import CallRecord


def _tool_rows(analytics: GatewayAnalytics) -> str:
    if not analytics.tools:
        return (
            '<tr><td colspan="7">No calls recorded yet.</td></tr>'
        )
    rows = []
    for tool in analytics.tools:
        rows.append(
            "<tr>"
            f"<td>{html.escape(tool.tool_name)}</td>"
            f"<td>{html.escape(tool.server)}</td>"
            f"<td>{tool.calls}</td>"
            f"<td>{tool.errors}</td>"
            f"<td>{tool.error_rate:.1%}</td>"
            f"<td>{tool.mean_latency_ms:.1f}</td>"
            f"<td>{tool.p95_latency_ms:.1f}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _call_rows(records: list[CallRecord]) -> str:
    if not records:
        return '<tr><td colspan="5">No calls recorded yet.</td></tr>'
    rows = []
    for record in records:
        status = "error" if record.is_error else "ok"
        rows.append(
            "<tr>"
            f"<td>{html.escape(record.created_at.isoformat())}</td>"
            f"<td>{html.escape(record.tool_name)}</td>"
            f"<td>{html.escape(record.server)}</td>"
            f"<td>{status}</td>"
            f"<td>{record.duration_ms:.1f}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def render_dashboard(
    analytics: GatewayAnalytics, recent_calls: list[CallRecord]
) -> str:
    """Render the full dashboard page for the given analytics."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>mcp-gateway dashboard</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2em; color: #222; }}
table {{ border-collapse: collapse; margin: 1em 0; }}
th, td {{ border: 1px solid #ccc; padding: 0.4em 0.8em; text-align: left; }}
th {{ background: #f0f0f0; }}
</style>
</head>
<body>
<h1>mcp-gateway dashboard</h1>
<p>{analytics.total_calls} calls recorded, {analytics.total_errors} errors
({analytics.overall_error_rate:.1%} error rate).</p>
<h2>Per-tool analytics</h2>
<table>
<tr><th>Tool</th><th>Server</th><th>Calls</th><th>Errors</th>
<th>Error rate</th><th>Mean latency (ms)</th><th>p95 latency (ms)</th></tr>
{_tool_rows(analytics)}
</table>
<h2>Recent calls</h2>
<table>
<tr><th>Time (UTC)</th><th>Tool</th><th>Server</th><th>Status</th>
<th>Duration (ms)</th></tr>
{_call_rows(recent_calls)}
</table>
</body>
</html>
"""
