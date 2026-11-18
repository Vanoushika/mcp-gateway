"""Tests for per-tool call policies and the rate limiter."""

import pytest

from mcpgateway.models import ToolPolicy
from mcpgateway.policies import PolicyError, PolicyStore, RateLimiter
from mcpgateway.tools import ToolError


def test_no_policy_means_no_enforcement():
    store = PolicyStore()
    store.enforce("echo")  # must not raise


def test_disabled_tool_is_refused():
    store = PolicyStore()
    store.set_policy(ToolPolicy(tool_name="echo", enabled=False))
    with pytest.raises(PolicyError, match="disabled by policy"):
        store.enforce("echo")


def test_rate_limit_allows_up_to_the_limit_then_refuses():
    limiter = RateLimiter()
    limiter.check("echo", 2)
    limiter.check("echo", 2)
    with pytest.raises(PolicyError, match="rate limit exceeded"):
        limiter.check("echo", 2)


def test_rate_limit_is_per_tool():
    limiter = RateLimiter()
    limiter.check("echo", 1)
    limiter.check("calculator", 1)  # a different tool is unaffected
    with pytest.raises(PolicyError, match="rate limit exceeded"):
        limiter.check("echo", 1)


def test_rate_limit_window_expires(monkeypatch):
    import mcpgateway.policies as policies

    now = [1000.0]
    monkeypatch.setattr(policies.time, "monotonic", lambda: now[0])
    limiter = RateLimiter()
    limiter.check("echo", 1)
    with pytest.raises(PolicyError, match="rate limit exceeded"):
        limiter.check("echo", 1)
    now[0] += 61  # past the one-minute window
    limiter.check("echo", 1)  # allowed again


def test_no_limit_when_calls_per_minute_is_none():
    limiter = RateLimiter()
    for _ in range(100):
        limiter.check("echo", None)


def test_policy_round_trip_through_store():
    store = PolicyStore()
    store.set_policy(ToolPolicy(tool_name="echo", calls_per_minute=5))
    policy = store.get_policy("echo")
    assert policy is not None
    assert policy.calls_per_minute == 5
    assert policy.enabled is True
    assert [p.tool_name for p in store.list_policies()] == ["echo"]


def test_clearing_a_limit_resets_the_counter(remote_registry):
    remote_registry.set_policy(
        ToolPolicy(tool_name="weather", calls_per_minute=1)
    )
    remote_registry.call_tool("weather", {"city": "Frisco"})
    with pytest.raises(ToolError, match="rate limit exceeded"):
        remote_registry.call_tool("weather", {"city": "Frisco"})
    remote_registry.set_policy(ToolPolicy(tool_name="weather"))
    result = remote_registry.call_tool("weather", {"city": "Frisco"})
    assert "Frisco" in result.content[0]["text"]


def test_registry_enforces_disabled_tool(remote_registry):
    remote_registry.set_policy(
        ToolPolicy(tool_name="weather", enabled=False)
    )
    with pytest.raises(ToolError, match="disabled by policy"):
        remote_registry.call_tool("weather", {"city": "Frisco"})


def test_registry_enforces_rate_limit_on_local_tool():
    from mcpgateway.registry import ToolRegistry

    registry = ToolRegistry()
    registry.set_policy(ToolPolicy(tool_name="echo", calls_per_minute=1))
    registry.call_tool("echo", {"text": "one"})
    with pytest.raises(ToolError, match="rate limit exceeded"):
        registry.call_tool("echo", {"text": "two"})
