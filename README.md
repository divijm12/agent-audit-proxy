# Agent Audit Proxy

**A spending limit, an emergency stop and a tamper-evident flight recorder for AI agents.**
It sits between your agents and Claude / their tools, enforces your rules on every call, and
hands you a report of exactly what they did.

![Dashboard: per-agent spend bars, STOP button, live audit trail](docs/img/dashboard.jpg)

> **Live demo: [agent-audit-proxy-demo.fly.dev/dashboard](https://agent-audit-proxy-demo.fly.dev/dashboard)**
> A pretend Claude and three pretend agents, no real money. Press STOP, watch them get blocked,
> export the report. Resets every 5 minutes (the first visit may take a few seconds to wake it).

## The problem

An agent is a loop: ask the model what to do, do it, repeat. Left alone, that loop can
spend $50 overnight re-asking the same question, or run `rm -rf` because a web page told
it to. Enterprise buyers now ask AI startups two questions before signing: *what stops your
agents going rogue?* and *can you prove what they did?*

## What it does

| Job | How |
|---|---|
| **Spending limit** | Every Claude call goes through a proxy that prices it from the real token usage and refuses the next call once an agent's budget can't cover it. |
| **Permission rules** | Every tool call, whether through MCP or asked for directly in Claude's reply, is checked against one `guardrails.yaml`: **allow**, **deny** (with a reason the agent sees), or **ask a human**. |
| **Kill switch** | One button (or `shugo halt`) freezes all model and tool calls at once and cuts off replies already streaming. |
| **Audit log + report** | Every decision is appended to a SHA-256 hash-chained log. One click exports a 72-hour incident report with an integrity check. |

## How it works

```
                      ┌──────────────────────────────┐
  agent ──── MCP ────▶│ tool guard (shugo serve)     │──▶ MCP tool servers
    │                 │ rules · approvals · STOP     │
    │                 └───────────────┬──────────────┘
    │                                 ▼ writes
    │                       one hash-chained audit log ◀── dashboard · 72h report
    │                                 ▲ writes
    │                 ┌───────────────┴──────────────┐
    └─ ANTHROPIC_ ───▶│ spend proxy (shugo spend)    │──▶ api.anthropic.com
       BASE_URL       │ STOP · budget · price · rules│
                      │ on tool_use in replies       │
                      └──────────────────────────────┘
```

An agent changes one setting (`ANTHROPIC_BASE_URL`) and names itself with an `x-agent-id`
header. No code changes. Its own API key passes through; the proxy never stores it.

## Numbers

From [`evals/RESULTS.md`](evals/RESULTS.md) (fake Claude, $0: `.venv/bin/python evals/run_evals.py`) and
one real-API run ([`evals/real_test_result.json`](evals/real_test_result.json), $0.098:
`evals/real_claude_test.py`, which caps itself at $0.30 whatever the proxy does).

| Eval | Target | Result |
|---|---|---|
| **Real Claude Haiku 4.5**: runaway agent, $0.10 budget | stop at budget | **stopped at $0.098** after 11 real calls; the proxy's ledger matched the actual bill to the cent |
| Runaway agent (fake Claude): $0.50 budget, loop worth $50 | stop at budget | **stopped at $0.48** (16 calls). Growing-cost loop: $0.48 |
| Dangerous tool calls blocked (20 attacks × plain + streaming) | 100% | **40 / 40** |
| Harmless tool calls wrongly blocked (10 × 2) | 0% | **0 / 20** |
| Log tampering caught (7 attack types) | all | **7 / 7** with a saved chain head (5 / 7 by the chain alone) |
| Latency added per call, p50 / p95 | < 20 ms | **1.3 / 1.5 ms**; first streamed byte **0.7 / 0.9 ms** |

## Try it

```bash
git clone https://github.com/divijm12/agent-audit-proxy && cd agent-audit-proxy
uv sync --extra dev
.venv/bin/shugo spend demo                              # live demo at :8787/dashboard
.venv/bin/python examples/phase2/run_demo.py            # a runaway agent hits its budget
```

Real agents: `shugo spend serve -c spend.yaml`, then `ANTHROPIC_BASE_URL=http://127.0.0.1:8787`.
Walkthroughs in [`examples/`](examples/); deployment (Fly.io, login) in [`docs/deploy.md`](docs/deploy.md).

## Cost

- **To run:** one small machine. The demo scales to zero on Fly.io when nobody's looking.
- **Per call:** ~1.3 ms of added latency; no extra model calls.
- **Pricing table:** Anthropic's published per-token rates, including cache reads/writes
  ([`prices.yaml`](src/shugo/spend/prices.yaml)). Unknown models are refused by default rather than guessed.

## Failure modes and trade-offs

- **Budgets are enforced before a call, but costs are only known after.** The proxy estimates
  the next call from the agent's previous one. That's exact for loops, but an agent's very first call,
  or a call much pricier than the last, can overshoot by that difference. Budgets are lifetime
  totals (no daily reset yet).
- **It only sees what passes through it.** If an agent's own code deletes a file without
  Claude asking for it, no proxy can see that.
- **Regex rules can be dodged; allow-lists can't.** The red-team policy allows a short list of
  safe actions and denies the rest. The same person wrote the policy and the attacks, so 40/40
  shows the mechanism works; it doesn't prove a determined attacker can't find a gap.
- **The hash chain is tamper-*evident*, not tamper-proof.** Without a secret key, someone who
  can edit the file can recompute every later hash or cut entries off the end. Saving the chain
  head elsewhere (`shugo audit verify --anchor`) catches both.
- **Blocked tool calls are rewritten into text.** Claude reads the reason and adapts. The newest models
  (e.g. Opus 5.5) may reject a conversation whose history was edited; use `on_deny: error` for those.
- **Single machine.** The spend ledger is SQLite; don't scale it horizontally.

## How it compares

LiteLLM, Portkey, Helicone and Bifrost give per-key budgets, logging and routing across many
providers. Anthropic's Console has monthly spend limits per workspace, but not per agent. [agentguard](https://github.com/agentwares/agentguard)
(TypeScript, Sept 2026) covers similar ground for MCP. This project's angle: one STOP button for
**both** model and tool calls, rules applied to tool calls inside Claude's replies (not just MCP),
per-agent budgets that stop a loop *before* it crosses the line, and an incident report with a
verifiable log. It's Anthropic-only for now.

## On compliance

Illinois' AI Safety Measures Act (SB 315, signed July 2026) gives **frontier model developers**
72 hours to report a critical safety incident. It doesn't cover companies building on those
models, but buyers are starting to ask them the same question. The export is modeled on that
timeline; it is not a regulatory filing. Notes and sources: [`docs/illinois-sb315.md`](docs/illinois-sb315.md).

## Credits

Built on [shugo](https://github.com/aritraghosh01/shugo) by aritraghosh01 (MIT): the MCP tool
guard, policy engine, approvals and hash-chained log. Its original README is in
[`docs/shugo-README.md`](docs/shugo-README.md). Fixes found here were sent upstream
([#13](https://github.com/aritraghosh01/shugo/pull/13), [#14](https://github.com/aritraghosh01/shugo/pull/14)).
Spend limits inspired by [costfuse](https://github.com/costfuse/costfuse). MIT licensed.
