# Agent Audit Proxy — build plan

Source: the 9-day roadmap PDF (Phases 1–5). This file records where we deviate
from it and why. Decided with the project owner on 2026-09-22.

## Architecture (option a)

```
                      ┌─────────────────────────────┐
  agent ── MCP ──────▶│ shugo (tool guard)          │──▶ MCP tool servers
    │                 │ policy · approvals · halt   │
    │                 └──────────────┬──────────────┘
    │                                │ writes
    │                                ▼
    │                     one hash-chained audit log  ◀── dashboard + 72h export
    │                                ▲ writes
    │                 ┌──────────────┴──────────────┐
    └── HTTP ────────▶│ spend proxy (new, FastAPI)  │──▶ api.anthropic.com
      ANTHROPIC_      │ /v1/messages passthrough    │
      BASE_URL        │ budget · halt · cost        │
                      └─────────────────────────────┘
```

shugo only sees tool calls, never model calls, so it cannot know what anything
costs. The spend proxy fills that gap. Both share the kill switch (shugo's `HALT`
file) and write to the same audit log.

## Changes from the PDF

| PDF says | We do | Why |
|---|---|---|
| Single FastAPI app in `app/` handling everything | shugo (`src/shugo/`) for tools + a new spend proxy for model calls | shugo is an MCP stdio guard, not an HTTP server |
| LiteLLM, OpenAI + Anthropic | Anthropic only, plain passthrough; OpenAI is "coming soon" | One less dependency; the demo uses Claude |
| `/v1/messages (OpenAI-compatible)` | `/v1/messages`, Anthropic format | `/v1/messages` *is* Anthropic's endpoint; OpenAI's is `/v1/chat/completions` |
| Price table with gpt-6-sol, mimo | Claude models only (from Anthropic's published prices) | Anthropic-only scope |
| Audit row stores `args_hash` | shugo stores redacted args (`args_redacted`) + SHA-256 chain; model-call rows add `agent_id`, `usage`, `cost_usd`, `spent_usd` | Keep shugo's format; never log prompts or API keys |
| `app/budget.py`, `app/main.py`, `config.yaml` | `src/shugo/spend/` (`budget.py`, `server.py`, `pricing.py`, `prices.yaml`) + `spend.yaml` | Lives inside the shugo package so it shares the kill switch, audit log and CLI |
| `args_match: "rm -rf"` substring rule | Needs building — shugo only matches args by exact equality | Required for the 20-prompt red-team eval |
| "Illinois 72-hour export" framed as a legal requirement | Incident-style report modeled on the 72h format | SB 315 covers frontier developers, not deployers — see `illinois-sb315.md` |
| GitHub fork | Private repo carrying shugo's full history (`upstream` remote) | GitHub forks of public repos can't be private; flip to public / re-fork once the README has real numbers |

## Phases

1. **Done (2026-09-22).** shugo runs locally; `examples/phase1/` sends allow / deny /
   escalate calls through it; audit log verifies; tampering is detected. Fixed two
   upstream issues on the way (see LEARNING_LOG.md).
2. **Done (2026-09-22). Spend proxy + budget.** `shugo spend serve`: FastAPI
   `/v1/messages` passthrough (streaming bytes relayed untouched; usage read from
   `message_start` / `message_delta`), SQLite ledger per agent, pre-flight budget
   check with in-flight reservations, cost rows in the shared audit log (now safe
   for multiple writer processes). `examples/phase2/`: a runaway SDK agent with a
   $0.10 budget is stopped at $0.09. Fake upstream only — no paid calls.

   How a call is judged: kill switch (403 `permission_error`) → model must be in
   the price table (403) → budget (402 `billing_error`) → forward → settle real cost.

   Known limits: the first call of an agent can overshoot its budget (no cost
   history yet); a call that costs much more than the previous one can overshoot
   by the difference; server-tool fees (web search) and fast-mode pricing aren't
   counted; budgets are lifetime totals (no daily reset yet).
3. **Done (2026-09-23). Dashboard + kill switch UI.** `GET /dashboard` on the
   spend proxy: plain HTML + `fetch()`, refreshed every 1.5s. STOP/RESUME toggles
   the shared `HALT` file (freezes tool calls and model calls, cuts open streams);
   every STOP/RESUME, from the button or `shugo halt`, is an audit entry.
   Per-agent spend bars turn red when an agent can't afford its next call; last
   50 audit rows. Buttons need an `x-shugo-dashboard` header so other websites
   can't press them through your browser. Local only until Phase 5 adds a login.
   Checked in a real browser, not just tests.
4. **Export + evals.** Also: apply tool rules to `tool_use` blocks in Claude's
   replies (agents that define tools in the API request, not via MCP, currently
   bypass shugo; the red-team eval needs this). `/export?hours=72` markdown report; runaway, policy
   (incl. `args_match`), and tamper evals; proxy-overhead p50/p95.
5. **Deploy + README.** Login in front of the dashboard before it's reachable
   from the internet. Dockerfile, Fly.io; README with real numbers; **one real
   Claude Haiku 4.5 run capped at $0.30 total** (agent budget set below that, e.g. $0.10) to prove the budget stop; then make the repo public.
