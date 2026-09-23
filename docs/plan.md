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
| Audit row stores `args_hash` | shugo stores redacted args (`args_redacted`) + SHA-256 chain | Keep shugo's format; add cost fields for model-call rows |
| `args_match: "rm -rf"` substring rule | Needs building — shugo only matches args by exact equality | Required for the 20-prompt red-team eval |
| "Illinois 72-hour export" framed as a legal requirement | Incident-style report modeled on the 72h format | SB 315 covers frontier developers, not deployers — see `illinois-sb315.md` |
| GitHub fork | Private repo carrying shugo's full history (`upstream` remote) | GitHub forks of public repos can't be private; flip to public / re-fork once the README has real numbers |

## Phases

1. **Done (2026-09-22).** shugo runs locally; `examples/phase1/` sends allow / deny /
   escalate calls through it; audit log verifies; tampering is detected. Fixed two
   upstream issues on the way (see LEARNING_LOG.md).
2. **Spend proxy + budget.** FastAPI `/v1/messages` passthrough (streaming via
   SSE, usage read from `message_start` / `message_delta`), per-agent spend table,
   pre-flight budget check, cost rows in the shared audit log. Tested against a
   fake Anthropic upstream — no paid calls.
3. **Dashboard + kill switch UI.** One HTML page: STOP/RESUME (toggles `HALT`,
   closes open streams), per-agent spend bars, last 50 audit rows.
4. **Export + evals.** `/export?hours=72` markdown report; runaway, policy
   (incl. `args_match`), and tamper evals; proxy-overhead p50/p95.
5. **Deploy + README.** Dockerfile, Fly.io; README with real numbers; **one real
   Claude Haiku 4.5 run capped at $0.30 total** (agent budget set below that, e.g. $0.10) to prove the budget stop; then make the repo public.
