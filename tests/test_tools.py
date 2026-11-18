"""Tests for the built-in local tools."""

import pytest

from mcpgateway.tools import ToolError, calculator_tool, echo_tool, kb_search_tool


def test_echo_returns_text():
    result = echo_tool({"text": "hello"})
    assert result.content == [{"type": "text", "text": "hello"}]
    assert result.is_error is False


def test_echo_rejects_non_string():
    with pytest.raises(ToolError):
        echo_tool({"text": 42})


def test_calculator_respects_precedence():
    result = calculator_tool({"expression": "2+3*4"})
    assert result.content[0]["text"] == "14.0"


def test_calculator_handles_parens_and_power():
    result = calculator_tool({"expression": "(2+3)**2"})
    assert result.content[0]["text"] == "25.0"


def test_calculator_rejects_division_by_zero():
    with pytest.raises(ToolError, match="division by zero"):
        calculator_tool({"expression": "1/0"})


def test_calculator_rejects_names_and_calls():
    with pytest.raises(ToolError):
        calculator_tool({"expression": "__import__('os').system('id')"})
    with pytest.raises(ToolError):
        calculator_tool({"expression": "os.getcwd()"})


def test_calculator_rejects_syntax_errors():
    with pytest.raises(ToolError):
        calculator_tool({"expression": "2 +"})


def test_kb_search_finds_auth_doc():
    result = kb_search_tool({"query": "API key header"})
    text = result.content[0]["text"]
    assert "auth" in text
    assert "X-API-Key" in text


def test_kb_search_no_match_is_honest():
    result = kb_search_tool({"query": "quantum banana"})
    assert result.content[0]["text"] == "No matching documents found."


def test_kb_search_top_k_limits_results():
    result = kb_search_tool({"query": "gateway tools", "top_k": 1})
    assert result.content[0]["text"].count("[") == 1


def test_kb_search_rejects_bad_top_k():
    with pytest.raises(ToolError):
        kb_search_tool({"query": "gateway", "top_k": 0})
