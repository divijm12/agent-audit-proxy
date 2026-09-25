# Tool guard: one agent, three tool calls, one audit log

Everything here is local and free — no API keys, no network, no real files touched.

| File | Role |
|---|---|
| `demo_tools_server.py` | A fake MCP tool server with `read_file`, `delete_file`, `bash`. The tools only *pretend*. |
| `guardrails.yaml` | The policy: allow reads, deny deletes, ask a human for `bash`. |
| `send_tool_calls.py` | Plays the agent: connects to shugo and sends one call of each kind. |

Run from the repo root:

```bash
export SHUGO_HOME=examples/tool-guard/.shugo-home   # keep the demo's log out of ~/.shugo
.venv/bin/python examples/tool-guard/send_tool_calls.py
.venv/bin/shugo audit tail -n 5
.venv/bin/shugo audit verify
```

Expected:

```
demo__read_file   -> OK: (pretend contents of notes.txt)
demo__delete_file -> ERROR: Deleting files is prohibited for autonomous agents.
demo__bash        -> ERROR: approval timed out after 5s (on_timeout=deny)
...
OK examples/tool-guard/.shugo-home/audit.log: 3 entries verified
```

To approve the `bash` call instead of letting it time out, run
`SHUGO_HOME=examples/tool-guard/.shugo-home .venv/bin/shugo approve --watch` in a second
terminal first (and raise `timeout_seconds` in `guardrails.yaml`).
