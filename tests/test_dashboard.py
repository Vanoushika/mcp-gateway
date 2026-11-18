"""Tests for the HTML dashboard rendering."""

from __future__ import annotations

from datetime import datetime, timezone

from mcpgateway.analytics import compute_analytics
from mcpgateway.dashboard import render_dashboard
from mcpgateway.models import CallRecord


def _record(tool: str, duration: float, is_error: bool = False):
    return CallRecord(
        id=f"{tool}-{duration}",
        tool_name=tool,
        server="local",
        arguments={},
        result={},
        is_error=is_error,
        duration_ms=duration,
        created_at=datetime(2026, 11, 16, 17, 0, tzinfo=timezone.utc),
    )


def test_dashboard_shows_tool_table_and_calls():
    records = [
        _record("calculator", 5.0),
        _record("calculator", 15.0, is_error=True),
        _record("echo", 2.0),
    ]
    analytics = compute_analytics(records)
    page = render_dashboard(analytics, records)

    assert "mcp-gateway dashboard" in page
    assert "calculator" in page
    assert "echo" in page
    assert "3 calls recorded" in page
    assert "1 errors" in page
    assert "Per-tool analytics" in page
    assert "Recent calls" in page
    assert "error" in page  # the failed calculator call is marked


def test_dashboard_with_no_calls_says_so():
    page = render_dashboard(compute_analytics([]), [])
    assert "0 calls recorded" in page
    assert "No calls recorded yet." in page


def test_dashboard_escapes_tool_names():
    records = [_record("<script>alert(1)</script>", 1.0)]
    page = render_dashboard(compute_analytics(records), records)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
