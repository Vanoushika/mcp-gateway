"""Built-in local tools.

Day 1 ships three small tools implemented in plain Python, so the
gateway can be exercised end to end with no external service:

- ``echo``: returns the text it is given (connectivity smoke test).
- ``calculator``: evaluates arithmetic safely, no ``eval``.
- ``kb_search``: keyword search over a small built-in document set,
  the same shape as the retrieval step in a RAG support desk.

Each tool is a function taking a dict of arguments and returning a
``ToolCallResult``. Argument validation errors raise ``ToolError``,
which the gateway reports as a failed call (``isError: true``) rather
than a protocol error.
"""

from __future__ import annotations

import ast
import operator
from typing import Any, Callable

from .models import ToolCallResult, ToolDefinition

DOCS = [
    {
        "id": "gateway-overview",
        "title": "What the gateway does",
        "text": "The gateway is the single entry point for agent tools. "
        "Clients call tools through the gateway, which checks the API key, "
        "routes the call to the owning server, and logs the result.",
    },
    {
        "id": "auth",
        "title": "Authentication",
        "text": "When MCP_GATEWAY_API_KEY is set, every gateway request must "
        "carry it in the X-API-Key header. Without a key the gateway runs "
        "open, which is for local development only.",
    },
    {
        "id": "rate-limits",
        "title": "Rate limits",
        "text": "Per-tool rate limits are set through POST /policies: "
        "a calls_per_minute limit, or enabled false to switch a tool "
        "off. Limits are enforced before the tool runs.",
    },
    {
        "id": "local-tools",
        "title": "Local tools",
        "text": "Local tools run inside the gateway process: echo, calculator "
        "and kb_search. Remote MCP servers are proxied from Day 2 onward.",
    },
    {
        "id": "password-reset",
        "title": "Password reset help",
        "text": "To reset a password, use the forgot-password link on the "
        "sign-in page. The link expires after one hour and can be used once.",
    },
]


class ToolError(ValueError):
    """A tool ran but failed (bad arguments, bad expression, no match)."""


def _text_result(text: str) -> ToolCallResult:
    return ToolCallResult(content=[{"type": "text", "text": text}])


def echo_tool(arguments: dict[str, Any]) -> ToolCallResult:
    text = arguments.get("text")
    if not isinstance(text, str):
        raise ToolError("echo requires a string argument 'text'")
    return _text_result(text)


_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_ALLOWED_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](
            _eval_node(node.left), _eval_node(node.right)
        )
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return _ALLOWED_UNARY[type(node.op)](_eval_node(node.operand))
    raise ToolError(f"unsupported expression element: {type(node).__name__}")


def calculator_tool(arguments: dict[str, Any]) -> ToolCallResult:
    expression = arguments.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        raise ToolError("calculator requires a string argument 'expression'")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ToolError(f"could not parse expression: {exc}") from exc
    try:
        value = _eval_node(tree)
    except ToolError:
        raise
    except ZeroDivisionError as exc:
        raise ToolError("division by zero") from exc
    return _text_result(str(value))


def kb_search_tool(arguments: dict[str, Any]) -> ToolCallResult:
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ToolError("kb_search requires a string argument 'query'")
    top_k = arguments.get("top_k", 3)
    if not isinstance(top_k, int) or top_k < 1:
        raise ToolError("kb_search 'top_k' must be a positive integer")
    terms = query.lower().split()
    scored = []
    for doc in DOCS:
        haystack = f"{doc['title']} {doc['text']}".lower()
        score = sum(1 for term in terms if term in haystack)
        if score:
            scored.append((score, doc))
    scored.sort(key=lambda item: item[0], reverse=True)
    lines = []
    for score, doc in scored[:top_k]:
        lines.append(f"[{doc['id']}] {doc['title']} (score {score})\n{doc['text']}")
    if not lines:
        return _text_result("No matching documents found.")
    return _text_result("\n\n".join(lines))


ToolFn = Callable[[dict[str, Any]], ToolCallResult]

LOCAL_TOOLS: dict[str, tuple[ToolDefinition, ToolFn]] = {
    "echo": (
        ToolDefinition(
            name="echo",
            description="Return the given text unchanged. Connectivity smoke test.",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        ),
        echo_tool,
    ),
    "calculator": (
        ToolDefinition(
            name="calculator",
            description="Evaluate an arithmetic expression (+, -, *, /, %, **).",
            input_schema={
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
        ),
        calculator_tool,
    ),
    "kb_search": (
        ToolDefinition(
            name="kb_search",
            description="Keyword search over the built-in help documents.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "default": 3},
                },
                "required": ["query"],
            },
        ),
        kb_search_tool,
    ),
}
