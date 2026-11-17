"""Call analytics — latency and error rates per tool.

Pure functions over the call records the store already keeps, so the
numbers on the dashboard are exactly the numbers the gateway logged.
Percentiles use the nearest-rank method, the same definition most
monitoring tools use for p50/p95.
"""

from __future__ import annotations

from pydantic import BaseModel

from .models import CallRecord


class ToolAnalytics(BaseModel):
    """Aggregated stats for one tool."""

    tool_name: str
    server: str
    calls: int
    errors: int
    error_rate: float
    mean_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float


class GatewayAnalytics(BaseModel):
    """Overall stats plus one row per tool."""

    total_calls: int
    total_errors: int
    overall_error_rate: float
    tools: list[ToolAnalytics]


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    rank = max(1, int(-(-pct * len(sorted_values) // 100)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


def compute_analytics(records: list[CallRecord]) -> GatewayAnalytics:
    """Aggregate a list of call records into per-tool stats.

    A tool is keyed by name; the server shown is the one that ran the
    most recent call, since a tool name belongs to one server in
    practice and the latest call is the freshest evidence.
    """
    by_tool: dict[str, list[CallRecord]] = {}
    for record in records:
        by_tool.setdefault(record.tool_name, []).append(record)

    tools: list[ToolAnalytics] = []
    for name in sorted(by_tool):
        rows = by_tool[name]
        latencies = sorted(row.duration_ms for row in rows)
        errors = sum(1 for row in rows if row.is_error)
        tools.append(
            ToolAnalytics(
                tool_name=name,
                server=rows[0].server,
                calls=len(rows),
                errors=errors,
                error_rate=errors / len(rows) if rows else 0.0,
                mean_latency_ms=(
                    sum(latencies) / len(latencies) if latencies else 0.0
                ),
                p50_latency_ms=_percentile(latencies, 50),
                p95_latency_ms=_percentile(latencies, 95),
            )
        )

    total_errors = sum(1 for record in records if record.is_error)
    return GatewayAnalytics(
        total_calls=len(records),
        total_errors=total_errors,
        overall_error_rate=(
            total_errors / len(records) if records else 0.0
        ),
        tools=tools,
    )
