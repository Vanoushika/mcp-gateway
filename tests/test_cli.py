"""Tests for the command line interface."""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_cli_tools_lists_all_tools():
    proc = subprocess.run(
        [sys.executable, "-m", "mcpgateway.cli", "tools"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0
    assert "echo" in proc.stdout
    assert "calculator" in proc.stdout
    assert "kb_search" in proc.stdout


def test_cli_call_calculator():
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcpgateway.cli",
            "call",
            "calculator",
            "--args",
            '{"expression": "2+3*4"}',
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0
    assert "14.0" in proc.stdout


def test_cli_analytics_reports_zero_calls():
    proc = subprocess.run(
        [sys.executable, "-m", "mcpgateway.cli", "analytics"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "DATABASE_URL": "sqlite:///:memory:"},
    )
    assert proc.returncode == 0
    assert "0 calls" in proc.stdout


def test_cli_call_unknown_tool_exits_nonzero():
    proc = subprocess.run(
        [sys.executable, "-m", "mcpgateway.cli", "call", "nope"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0


def test_cli_servers_lists_local_as_healthy():
    proc = subprocess.run(
        [sys.executable, "-m", "mcpgateway.cli", "servers"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0
    assert "local [local] healthy" in proc.stdout


def test_cli_check_local_is_healthy():
    proc = subprocess.run(
        [sys.executable, "-m", "mcpgateway.cli", "check", "local"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0
    assert "local: healthy" in proc.stdout


def test_cli_check_unknown_server_exits_nonzero():
    proc = subprocess.run(
        [sys.executable, "-m", "mcpgateway.cli", "check", "nope"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0
    assert "unknown server" in proc.stderr
