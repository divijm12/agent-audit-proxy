# Dashboard: the kill switch and live spend

Local and free (uses the fake Anthropic API from `examples/runaway-agent`).

```bash
.venv/bin/python examples/dashboard/run_demo.py
```

This opens **http://127.0.0.1:8787/dashboard** and starts two agents that each
call Claude once a second:

| Agent | Budget | What you'll see |
|---|---|---|
| `research-bot` | $0.60 | Blue bar filling up, ~$0.03 per second |
| `runaway-bot` | $0.10 | Turns red and says **blocked** after 3 calls ($0.09) |

Click **STOP**: the terminal immediately shows both agents
`BLOCKED (403) halted by kill switch`, and the audit table gets a
`shugo::kill_switch halt` row saying who pressed it. Click **RESUME**:
`research-bot` carries on; `runaway-bot` stays blocked by its budget.
Ctrl+C in the terminal to quit.

The same STOP also freezes the tool guard (`shugo serve`): both read one
`HALT` file. `shugo halt` / `shugo unhalt` in a terminal do exactly what the
button does, and are logged the same way.

**Local only.** Anyone who can open the page can press STOP, so the proxy
listens on 127.0.0.1 by default. For internet-facing use, set a dashboard password (see [`docs/deploy.md`](../../docs/deploy.md)).
