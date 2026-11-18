"""Per-tool call policies: rate limits and enable/disable.

A policy is enforced before a tool runs, wherever the call comes
from (the MCP endpoint or the CLI), so a limit cannot be bypassed by
switching entry points. Rate limiting is a sliding one-minute window
kept in memory; policies reset when the gateway restarts.
"""

from __future__ import annotations

import time
from collections import deque

from .models import ToolPolicy


class PolicyError(ValueError):
    """A call was refused by policy (disabled tool, rate limit)."""


class RateLimiter:
    """Sliding-window counter: at most N calls per tool per minute."""

    def __init__(self) -> None:
        self._calls: dict[str, deque[float]] = {}

    def check(self, tool_name: str, calls_per_minute: int | None) -> None:
        if calls_per_minute is None:
            return
        now = time.monotonic()
        window = self._calls.setdefault(tool_name, deque())
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= calls_per_minute:
            raise PolicyError(
                f"rate limit exceeded for tool {tool_name!r}: "
                f"{calls_per_minute} calls per minute"
            )
        window.append(now)

    def reset(self, tool_name: str | None = None) -> None:
        if tool_name is None:
            self._calls.clear()
        else:
            self._calls.pop(tool_name, None)


class PolicyStore:
    """Holds the policy for each tool and enforces it."""

    def __init__(self) -> None:
        self._policies: dict[str, ToolPolicy] = {}
        self._limiter = RateLimiter()

    def set_policy(self, policy: ToolPolicy) -> ToolPolicy:
        self._policies[policy.tool_name] = policy
        if policy.calls_per_minute is None:
            self._limiter.reset(policy.tool_name)
        return policy

    def get_policy(self, tool_name: str) -> ToolPolicy | None:
        return self._policies.get(tool_name)

    def list_policies(self) -> list[ToolPolicy]:
        return list(self._policies.values())

    def enforce(self, tool_name: str) -> None:
        """Refuse the call when the tool is disabled or over its limit."""
        policy = self._policies.get(tool_name)
        if policy is None:
            return
        if not policy.enabled:
            raise PolicyError(f"tool {tool_name!r} is disabled by policy")
        self._limiter.check(tool_name, policy.calls_per_minute)
