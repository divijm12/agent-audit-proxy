# Learning Log

A running, plain-language record of what we built, why, and what it taught us.
Newest entries at the bottom.

---

## Phase 1 — Getting shugo running (2026-09-22)

### The big idea in one paragraph

An AI agent is just a program that asks a model what to do, then *does* it by
calling **tools** — read a file, run a shell command, open a pull request. The
risk lives in those tool calls. A **guardrail proxy** is a middleman: the agent
thinks it's talking to its tools, but it's actually talking to the proxy, which
checks each call against rules before passing it on. Because the proxy is in the
middle, the agent's code doesn't change at all.

### What is MCP?

The **Model Context Protocol** is a standard way for agents to talk to tools. A
tool provider runs an "MCP server"; the agent (Claude Code, Cursor, …) is the
"MCP client". shugo pretends to be an MCP server to the agent and acts as an MCP
client to the real tool servers. It talks over **stdio** — the agent starts shugo
as a child process and they exchange JSON messages through stdin/stdout. That's
why there's no URL or port.

### The code, by job

All the real code lives in `src/shugo/` (~2,000 lines).

| When you… | Look at | What it does |
|---|---|---|
| start the guard | `proxy.py` | The heart. Lists every upstream tool (renamed `server__tool`), and on each call: kill switch → policy → maybe ask a human → write audit row → forward or refuse. |
| talk to real tool servers | `upstream.py`, `router.py` | Launches each tool server and splits `demo__read_file` back into server `demo` + tool `read_file`. |
| decide allow/deny | `policy/` | `models.py` = the YAML shape; `loader.py` reads it; `engine.py` walks the rules top to bottom, first match wins, default deny. |
| ask a human | `approval/` | "Escalate" writes a request file to `~/.shugo/pending/`; a person approves it in a terminal UI or a small web page. No answer in time → the rule's `on_timeout` applies. |
| record what happened | `audit/log.py`, `audit/verify.py` | Appends one JSON line per decision, each carrying the previous line's hash. |
| prove it to an auditor | `evidence/` | Builds a report mapping rules to standards (OWASP, NIST, EU AI Act, ISO 42001). |
| type a command | `cli.py`, `commands/` | `shugo serve / init / validate / explain / audit / halt / approve / evidence`. |

### Hash chains, the one concept to really get

Each audit line stores `prev_hash` (the previous line's fingerprint) and
`this_hash` (a SHA-256 fingerprint of this line *including* `prev_hash`). Change
one character in an old line and its fingerprint no longer matches — and neither
does every line after it. We tested this: flipping one `deny` to `allow` made
`shugo audit verify` fail and point at line 2. This is "tamper-*evident*": it
can't stop someone editing the file, but it can't be edited without being caught.

### The kill switch is just a file

`shugo halt` creates `~/.shugo/HALT`. Every tool call checks whether that file
exists before doing anything else. Simple on purpose — no database, and any
process (including our future spend proxy and dashboard) can flip it.

### What went wrong, and what it taught us

1. **A real bug in shugo.** Allowed calls to our demo tools failed with
   *"outputSchema defined but no structured output returned."* Modern MCP tools
   describe what they return (an `outputSchema`) and send a structured copy of the
   answer. shugo passed the description along but threw the structured copy away,
   so the MCP library rejected the response. Fix: forward the tool's result
   untouched. **Lesson:** a proxy must pass through everything it doesn't
   deliberately change — the parts you drop are the parts you'll forget about.
   We wrote a failing test first, then the fix (`test_allow_path_preserves_structured_content`).
2. **A test that broke on its own.** One test hardcoded July 2026 dates and asked
   for "the last 30 days". Correct in July, broken by September. **Lesson:** tests
   that depend on today's date should compute dates relative to now.
3. **An environment gotcha.** Our shell sets `FORCE_COLOR`, which makes the CLI
   print color codes, which broke a test that compared text. (Fixed properly in
   the CI entry below.)

### What shugo *can't* do (and why Phase 2 exists)

shugo sees tool calls, never model calls. It has no idea how many tokens an agent
used or what it cost. So a spending limit can't live inside shugo — it needs a
second, small proxy in front of the Anthropic API. See `docs/plan.md`.

---

## CI — why GitHub emailed "workflow run failed" (2026-09-22)

**CI** ("continuous integration") is GitHub re-running the test suite on fresh
Linux, macOS and Windows machines every time we push. It came with shugo in
`.github/workflows/ci.yml`. Our first push failed on all 9 machines.

1. **It never got as far as testing.** The setup step caches downloads keyed on
   a `uv.lock` file (the exact version of every dependency), and shugo never
   committed one — so setup crashed. shugo's own CI had been red since July 30
   for the same reason. The workflow also installed packages into the wrong
   Python and skipped the test plugins. Fix: commit `uv.lock`, then
   `uv sync --locked --extra dev` builds an identical environment on every
   machine. **Lesson:** a lock file is what makes "works on my machine" also
   work on theirs.
2. **Then only Linux failed.** A test checked the CLI printed `2 entries`, but
   the CLI wraps long lines to fit the terminal, and on Linux the temp-folder
   path was just long enough to wrap between "2" and "entries". Same test that
   broke locally on color codes. Fix: the test now strips color codes and line
   breaks before comparing. **Lesson:** test what a command *means*, not exactly
   how it's laid out on screen — layout depends on the terminal.
3. **Reading the email.** `gh run list` first showed shugo's July runs, because
   our repo has two remotes and `gh` picked `upstream`. Use
   `gh run list -R divijm12/agent-audit-proxy` to see ours.

---

## Phase 2 — The spending limit (2026-09-22)

### Where the money goes

Agents don't pay per question, they pay per **token** (roughly ¾ of a word),
and input (what you send) is cheaper than output (what the model writes).
Claude Haiku 4.5 costs $1 per million input tokens and $5 per million output.
Every Anthropic response ends with a **usage** block saying exactly how many of
each it used, so cost = tokens × price. That's all `pricing.py` does. (Cached
prompt tokens have their own cheaper rates, which it also handles.)

### A second proxy, for the model instead of the tools

shugo sits between the agent and its **tools**. The new spend proxy sits between
the agent and the **model**. It's a small web server (FastAPI) that speaks the
same language as `api.anthropic.com`, so an agent only has to change one
setting: `ANTHROPIC_BASE_URL=http://127.0.0.1:8787`. Its own API key passes
straight through; the proxy never stores it or logs it.

For every call, in order:

1. **Kill switch.** Is the `HALT` file there? Same file shugo checks, so one
   STOP freezes tools *and* model calls.
2. **Price.** Do we know what this model costs? If not, refuse by default,
   because you can't budget what you can't price.
3. **Budget.** Has this agent (named by an `x-agent-id` header) got room left?
4. **Forward**, then read the real usage from the reply and **record the cost**
   in a small SQLite database (the "ledger") and in the shared audit log.

### Streaming: pass the bytes, read over their shoulder

Most agents *stream* replies word by word (Server-Sent Events). The proxy must
not slow that down or change it, so it forwards each chunk the instant it
arrives and, on the side, watches for two events: `message_start` (input
tokens) and `message_delta` (output tokens, at the end). A test checks the
bytes the agent receives are identical to what Anthropic sent.

### The interesting problem: you can't know the price in advance

The proxy has to decide *before* sending a call, but the cost is only known
*after*: nobody knows how long the answer will be. Our first version guessed
from the size of the request. The demo agent sends tiny requests that produce
expensive answers, so the guess was ~$0, and the agent made one call too many:
it stopped at **$0.12** on a **$0.10** budget.

The fix uses what a runaway agent is: something repeating itself. The guess
for the next call is now *at least what this agent's last call cost*. At $0.09
spent, with the last call costing $0.03, the next one would reach $0.12, so it's
refused. The agent stops at **$0.09**, under the limit. Honest limits: an
agent's very first call has no history, and a call much pricier than the one
before can still overshoot by the difference. Those are written down in
`docs/plan.md` rather than hidden.

### Two agents calling at once

If an agent fires 5 calls in parallel, all 5 could pass the check before any
finishes. So each call **reserves** its estimated cost up front, and the
reservation is swapped for the real cost when the answer arrives. It's the same
idea as a hotel putting a hold on your card.

### A bug we'd have shipped: two writers, one log

The audit log's hash chain remembered the last entry's fingerprint *in memory*.
With one program writing, fine. With two (shugo **and** the spend proxy), each
would chain onto its own stale fingerprint, and `verify` would scream
"tampered!" at a log nobody tampered with. Fix: before writing, take a **file
lock** (so only one process writes at a time) and re-read the real last line
from disk. A test runs 3 processes × 40 writes at once and checks the chain.

### Why a 402, and why that matters

When an agent is over budget the proxy answers exactly like Anthropic would for
a billing problem: HTTP **402** `billing_error`. The Anthropic SDK turns that
into a normal exception and, importantly, **doesn't retry it** (it retries 429s
and 5xx errors). A "stop" that the client automatically retries isn't a stop.

---

## Phase 3 — The dashboard and the big red button (2026-09-23)

### What it is

A single web page, `http://127.0.0.1:8787/dashboard`, served by the spend
proxy. No React, no build step: one HTML file with a little JavaScript that
asks the proxy "what's going on?" (`GET /api/state`) every 1.5 seconds and
redraws. The answer contains three things: is everything stopped, how much
has each agent spent, and the last 50 audit entries.

### One button, both proxies

The STOP button creates the `HALT` file; RESUME deletes it. The tool guard and
the spend proxy both check that file before every single call, so one click
freezes tool calls *and* model calls, and even cuts off a reply that's already
streaming. We moved the halt logic into `killswitch.py` so the button and the
`shugo halt` command share it, and so every STOP/RESUME is written to the audit
log with who did it. For an auditor, "when were the agents frozen, and by whom?"
matters as much as "what did they do?"

### Two web-security ideas worth knowing

1. **Never paste untrusted text into a page as HTML.** Audit rows contain text an
   agent chose (its name, a reason). If an agent named itself
   `<script>…</script>` and we inserted it as HTML, that script would run in your
   browser. So the page only ever uses `textContent`, which shows text as text.
   A test checks the page never uses the HTML-inserting alternative.
2. **Cross-site request forgery (CSRF).** Any website you visit can make your
   browser send a request to `127.0.0.1:8787`. So a random page could "press"
   STOP for you. Fix: the buttons send a custom header (`x-shugo-dashboard: 1`).
   Browsers refuse to let another site add custom headers without asking our
   server first, and our server never says yes.

### Checking it like a user would

Tests proved the API worked, but a page has to be *seen*. Opening it in a real
browser showed two things tests couldn't: an agent that couldn't afford its next
call still looked "yellow, 90%", not blocked; and agent names wrapped onto two
lines. Both fixed: the ledger now reports `blocked` (can't afford a call like its
last one), and the bar turns red with the word **blocked**.

### A small operations lesson

Stopping the demo with a plain `kill` left its two servers running in the
background, still holding their ports, so the next run quietly talked to the
*old* code. Python only runs `finally:` clean-up on Ctrl+C by default, not on
`kill`. The demo scripts now turn `kill` into a normal exit so they clean up.
