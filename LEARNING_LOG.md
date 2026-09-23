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
   print color codes, which broke a test that compared text. Not a bug in the
   product, just something to know.

### What shugo *can't* do (and why Phase 2 exists)

shugo sees tool calls, never model calls. It has no idea how many tokens an agent
used or what it cost. So a spending limit can't live inside shugo — it needs a
second, small proxy in front of the Anthropic API. See `docs/plan.md`.
