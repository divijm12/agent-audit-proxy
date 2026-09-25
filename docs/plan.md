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
4. **Done (2026-09-24). Export + evals.**
   - Incident report: `GET /export?hours=72`, dashboard button, `shugo audit report`.
     Markdown with integrity check (PASS/FAIL + chain head), totals, per-agent,
     kill-switch timeline, blocked actions, full trail.
   - Way-B gap closed: `tool_policy` in spend.yaml applies guardrails.yaml rules to
     `tool_use` blocks in Claude's replies (rewrite blocked calls to an explanation,
     or refuse the reply; escalate waits for a human). Policy gained `args_regex`.
   - `shugo audit verify --anchor` catches tail truncation and full rewrites.
   - Evals (`evals/run_evals.py` → `evals/RESULTS.md`): runaway stopped at $0.48 of
     $0.50 (vs $50 unsupervised); 40/40 attack checks blocked, 0/20 harmless blocked;
     tamper 5/7 by chain alone, 7/7 with anchor; latency added p50 1.3 ms / p95 1.5 ms.
   - Found on the way: stream relay forwarded compressed bytes without their header
     (fixed: relay decoded bytes).
   - README still to be rewritten with these numbers (Phase 5).
5. **In progress. Deploy + README.**
   - Done (2026-09-24): README rewritten as a product spec (problem, diagram, eval
     numbers, cost, failure modes, comparison; shugo's README kept in
     docs/shugo-README.md). Login for internet-facing use (dashboard password,
     agent token; `serve` refuses a public host without one). `shugo spend demo`:
     self-contained live demo (fake Claude, looping agents, resets). Dockerfile
     (demo by default) + fly.toml + docs/deploy.md; image steps checked locally
     without Docker.
   - Done (2026-09-25): live demo deployed to https://agent-audit-proxy-demo.fly.dev
     (one machine, scales to zero; STOP/RESUME, export and HTTPS redirect checked live).
   - Done (2026-09-25): the one real-API test. Claude Haiku 4.5, agent budget $0.10,
     script hard cap $0.30: 11 real calls, stopped by the proxy at $0.09807; the proxy's
     ledger equalled the script's independent total; audit chain OK. Total spent: $0.098.
   - Waiting on the owner: make the repo public; demo video.
