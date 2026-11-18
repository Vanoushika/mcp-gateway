"""Tests for call analytics: per-tool latency and error rates."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mcpgateway.analytics import compute_analytics
from mcpgateway.models import CallRecord


def _record(tool: str, server: str, duration: float, is_error: bool = False):
    return CallRecord(
        id=f"{tool}-{duration}",
        tool_name=tool,
        server=server,
        arguments={},
        result={},
        is_error=is_error,
        duration_ms=duration,
        created_at=datetime.now(timezone.utc),
    )


def test_empty_records_give_zero_totals():
    analytics = compute_analytics([])
    assert analytics.total_calls == 0
    assert analytics.total_errors == 0
    assert analytics.overall_error_rate == 0.0
    assert analytics.tools == []


def test_per_tool_counts_and_error_rate():
    records = [
        _record("echo", "local", 10.0),
        _record("echo", "local", 20.0),
        _record("echo", "local", 30.0, is_error=True),
        _record("calculator", "local", 5.0),
    ]
    analytics = compute_analytics(records)
    assert analytics.total_calls == 4
    assert analytics.total_errors == 1
    assert analytics.overall_error_rate == pytest.approx(0.25)

    echo = next(t for t in analytics.tools if t.tool_name == "echo")
    assert echo.calls == 3
    assert echo.errors == 1
    assert echo.error_rate == pytest.approx(1 / 3)
    assert echo.server == "local"

    calc = next(t for t in analytics.tools if t.tool_name == "calculator")
    assert calc.calls == 1
    assert calc.errors == 0
    assert calc.error_rate == 0.0


def test_latency_mean_and_percentiles():
    records = [_record("echo", "local", float(ms)) for ms in (10, 20, 30, 40)]
    analytics = compute_analytics(records)
    echo = analytics.tools[0]
    assert echo.mean_latency_ms == pytest.approx(25.0)
    assert echo.p50_latency_ms == pytest.approx(20.0)
    assert echo.p95_latency_ms == pytest.approx(40.0)


def test_percentiles_with_a_single_call():
    analytics = compute_analytics([_record("echo", "local", 7.5)])
    echo = analytics.tools[0]
    assert echo.mean_latency_ms == pytest.approx(7.5)
    assert echo.p50_latency_ms == pytest.approx(7.5)
    assert echo.p95_latency_ms == pytest.approx(7.5)


def test_tools_sorted_by_name():
    records = [
        _record("weather", "weather-svc", 12.0),
        _record("echo", "local", 3.0),
        _record("calculator", "local", 4.0),
    ]
    analytics = compute_analytics(records)
    assert [t.tool_name for t in analytics.tools] == [
        "calculator",
        "echo",
        "weather",
    ]
