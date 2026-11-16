# mcp-gateway

One governed entry point for agent tools: routing, API-key auth and call
logging for MCP servers. Clients speak the Model Context Protocol to the
gateway; the gateway routes each tool call to the server that owns it and
records what ran, how long it took, and whether it failed.

## Why this exists

MCP has become the standard way agents reach tools. The protocol crossed
97 million monthly SDK downloads, more than 10,000 public MCP servers are
live on GitHub, and OpenAI, Google, Microsoft and AWS have all adopted it.
Teams now run several MCP servers at once and need one governed place to
reach them: a single endpoint, one credential to manage, one log of every
call. That is what this gateway is. It is built with Python and FastAPI
only, no extra framework, and it speaks the MCP Streamable HTTP transport
(JSON-RPC 2.0 over `POST /mcp`).

Sources checked 12 November 2026:

- https://dev.to/max_quimby/agents-still-cant-talk-to-each-other-550g
  (MCP at 97M monthly SDK downloads; agent-to-agent plumbing still
  fragmented, which is the gap a gateway sits in)
- https://library.mikesailab.com/bookmarks/ai-stack-radar/2026-11-11/
  (MCP gateways listed as a current category; evals and observability
  alongside)
- https://ai.dosa.dev/best/mcp-servers-for-ai-coding
  (November 2026 roundup; governed, self-hosted entry points for coding
  agents are the direction of travel)

## Build schedule

This project is built in three sessions, 30 / 30 / 40:

- **Day 1 (30%) — done 12 Nov 2026:** scaffold, core models, tool
  registry, JSON-RPC dispatcher for the MCP subset, API-key auth, call
  logging to SQLite (PostgreSQL-ready), three built-in local tools
  (`echo`, `calculator`, `kb_search`), FastAPI surface, CLI, tests.
- **Day 2 (30%) — done 13 Nov 2026:** proxying to remote MCP servers
  over HTTP (JSON-RPC client, `initialize` handshake, `tools/list` and
  `tools/call` forwarded), per-tool rate limits and enable/disable
  policies, server health checks (on demand and periodic in the
  background).
- **Day 3 (40%) — done 16 Nov 2026:** call analytics (latency and
  error rates per tool), HTML dashboard, CI gating, Dockerfile
  verification (not possible — no container runtime here), publish
  held on the repo still not existing (see below).

## Quickstart

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # set MCP_GATEWAY_API_KEY to require an API key
.venv/bin/python -m mcpgateway.cli serve        # http://127.0.0.1:8000
.venv/bin/python -m mcpgateway.cli tools
.venv/bin/python -m mcpgateway.cli call calculator --args '{"expression": "2+3*4"}'
```

## The MCP surface

`POST /mcp` accepts one JSON-RPC 2.0 object. Methods:

| Method | What it does |
| --- | --- |
| `initialize` | Protocol handshake, returns server info |
| `notifications/initialized` | Client notification, no response (HTTP 202) |
| `ping` | Liveness check |
| `tools/list` | Every tool the gateway can route to, local and remote |
| `tools/call` | Run one tool, returns MCP content blocks |

Protocol errors use the standard codes (`-32600`, `-32601`, `-32602`).
A tool that runs and fails is not a protocol error: it comes back as a
result with `isError: true`, the MCP convention.

```bash
curl -X POST http://127.0.0.1:8000/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"calculator","arguments":{"expression":"2+3*4"}}}'
# {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"14.0"}],"is_error":false}}
```

## REST surface

- `GET /health` — no auth, service health.
- `GET /tools` — tools the gateway can route to, local and remote.
- `GET /servers`, `POST /servers` — server registry. `POST /servers`
  accepts `local` and `http` servers; an `http` server that cannot be
  reached is registered with status `unreachable` and no tools, and its
  tools appear after the next successful health check.
- `POST /servers/{name}/health-check` — ping one server now, returns
  its updated status. A background thread also pings every remote
  server every `MCP_GATEWAY_HEALTH_INTERVAL_SECONDS` (default 60).
- `GET /policies`, `POST /policies` — per-tool policies: a
  `calls_per_minute` limit, or `enabled: false` to switch a tool off.
  Policies are enforced before the tool runs, on the MCP endpoint and
  the CLI alike.
- `GET /calls`, `GET /calls/{id}` — call history with durations. The
  logged `server` is the server that actually ran the tool.
- `GET /analytics` — per-tool stats as JSON: calls, errors, error
  rate, mean, p50 and p95 latency in milliseconds, plus overall totals.
- `GET /analytics/html` — the same analytics as a self-contained
  dashboard page (no JavaScript), with the 20 most recent calls.
- `mcp-gateway analytics` — the same per-tool summary on the CLI.

Server registrations and policies live in memory and reset when the
gateway restarts; the call log is the only persisted state.

When `MCP_GATEWAY_API_KEY` is set, every route except `/health`
requires it in the `X-API-Key` header. Without it the gateway runs
open, for local development only.

## Architecture

```
mcpgateway/
  models.py    Pydantic models: tools, servers, policies, calls, JSON-RPC
  tools.py     Built-in local tools (echo, calculator, kb_search)
  proxy.py     HTTP client for remote MCP servers (JSON-RPC over POST)
  policies.py  Per-tool policies: rate limiter and policy store
  registry.py  Server registry, routes tool names to their server
  gateway.py   JSON-RPC dispatcher, logs every call
  auth.py      API-key check
  store.py     SQLAlchemy store (SQLite default, DATABASE_URL override)
  analytics.py Per-tool latency and error-rate aggregates
  dashboard.py Self-contained HTML dashboard (no JavaScript)
  main.py      FastAPI app: /mcp, /tools, /servers, /policies, /calls, /analytics
  cli.py       serve / tools / call / calls / analytics / servers / check
scripts/self_check.py  Dogfoods the CLI and the live API (7 checks)
.github/workflows/ci.yml  pytest + self-check on every push/PR
```

## Day 1 results (actually observed, 12 Nov 2026)

- Full test suite: **41 passed, 0 failed** (pytest, fully offline).
- Live HTTP smoke test: `/health` ok; `initialize` handshake returned
  protocol version `2025-03-26`; `tools/call` on `calculator` returned
  `14.0` for `2+3*4`; `kb_search` for "API key header" returned the auth
  doc first; `GET /calls` showed both calls logged with no errors.
- CLI: `tools` lists all three tools; `call echo` returns the text.
- Auth: tested with a key set, missing and wrong keys get 401, the
  right key gets 200.
- Calculator safety: `__import__('os').system('id')` and `os.getcwd()`
  are rejected, division by zero reports a clean tool error.
- Dockerfile is included but the image build was **not** verified: no
  container runtime (Docker / Podman) is available in this environment.
- Repo creation through the GitHub connector failed as before
  (403 "Resource not accessible by integration"), so the repo does not
  exist yet. The one step waiting on Anoushika: create the empty public
  repo `mcp-gateway` on github.com/new (no README ticked), then the
  project is pushed on Day 3.

## Day 2 results (actually observed, 13 Nov 2026)

- Full test suite: **83 passed, 0 failed** (pytest, fully offline;
  was 41 after Day 1). The new tests use an in-memory fake remote MCP
  server (MockTransport) with `weather` and `translate` tools.
- Live HTTP smoke test, gateway plus a real fake remote server on
  separate ports: registering the remote server returned 201; after a
  health check its status flipped `unreachable` → `healthy` and its
  tools appeared in `tools/list`; `tools/call` on `weather` returned
  "sunny, 21C in Frisco" and the call log recorded it under server
  `weather-svc`. A remote tool that fails at call time comes back as a
  failed call (`isError: true`), not a protocol error.
- Policies live: with `echo` limited to 1 call per minute the first
  call succeeded and the second came back `isError: true` ("rate limit
  exceeded"); with `calculator` disabled the call was refused
  ("disabled by policy"); clearing the limit and re-enabling restored
  both tools. The CLI `servers` and `check` commands work.
- One real bug found and fixed during the run: `httpx.Client()`
  crashes at construction in this environment because the sandbox's
  `NO_PROXY` contains unbracketed IPv6 entries httpx cannot parse
  (`InvalidURL: Invalid port: ':1]'`). The proxy client now builds its
  client with `trust_env=False`, so it dials configured MCP servers
  directly and never reads proxy env vars; a regression test covers
  plain construction.
- Honest limits: server registrations and policies live in memory and
  reset on restart; remote tool lists are cached for 60 seconds; the
  proxy speaks the same JSON-RPC subset as the gateway (a remote
  server with a different transport, e.g. stdio, is out of scope).
- Publish still waits on Day 3 (Mon 16 Nov): the repo `mcp-gateway`
  does not exist on GitHub yet (checked 13 Nov), and the
  `llm-eval-harness` `.github/workflows/ci.yml` is still missing —
  Anoushika's manual upload of that one file is still outstanding.

## Day 3 results (actually observed, 16 Nov 2026)

- Full test suite: **96 passed, 0 failed** (pytest, fully offline;
  was 83 after Day 2). The 13 new tests cover analytics
  (counts, error rates, mean/p50/p95, including the empty and
  single-call cases), the dashboard (table content, empty state, HTML
  escaping of tool names), the new API endpoints, and the CLI
  `analytics` command.
- Self-check script `scripts/self_check.py`: **7/7 checks held** —
  pytest, CLI `tools` / `call` / `analytics` (verified against two
  seeded calls: 2 calls, 1 error shown), and the live API
  (`/mcp` call returns 14.0, `/analytics` shows the call,
  `/analytics/html` renders the dashboard). The script runs the
  gateway over real HTTP on a throwaway database.
- Live HTTP smoke test (gateway on a throwaway database): 4 calls —
  `calculator` 2+3\*4 → 14.0, 10/2 → 5.0, 1/0 → clean tool error;
  `echo` → hello. `GET /analytics` reported 4 calls, 1 error (25%
  overall); calculator 3 calls, 1 error (33.3%), mean 0.08 ms,
  p95 0.12 ms; echo 1 call, 0 errors. `GET /analytics/html`
  returned a 1,372-byte dashboard page with the per-tool table.
- One environment quirk found and fixed while writing the
  self-check: `httpx.Client()` crashes at construction when the
  sandbox proxy vars are set (same unbracketed-IPv6 `NO_PROXY`
  problem as Day 2). The self-check client now uses
  `trust_env=False`, matching the proxy fix.
- CI workflow `.github/workflows/ci.yml` added: pytest, then the
  self-check, on every push and pull request to `main`.
- Dockerfile build **not** verified again: no container runtime
  (Docker / Podman) is available in this environment. The Dockerfile
  is unchanged from Day 1.
- **Publish held:** repo creation through the GitHub connector
  failed again today (403 "Resource not accessible by integration",
  same limit as Nov 6 / Nov 9 / Nov 12), and the repo still does not
  exist (checked 16 Nov). The project is code-complete at 100% —
  35 files ready to push — but it stays local until Anoushika
  creates the empty public repo `mcp-gateway` on github.com/new
  (no README ticked) and selects it at
  https://github.com/apps/meta-muse-ai/installations/new so the App
  can write to it. Then rosie pushes the files (file by file, the
  route that worked for `llm-eval-harness`) and verifies by reading
  the repo back.
- Honest limits, unchanged: server registrations and policies live
  in memory and reset on restart; `/analytics` reads the most
  recent 10,000 logged calls; the dashboard shows the 20 most
  recent calls.

## Stack

Python 3.12, FastAPI, Pydantic, SQLAlchemy, pytest, Docker. No other
frameworks, and no skills beyond the author's verified stack.
