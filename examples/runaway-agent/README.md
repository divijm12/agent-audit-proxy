# Runaway agent: stopped at its budget

Local and free: the "Anthropic API" here is `fake_anthropic.py`, and the agent
uses a fake key. Nothing reaches api.anthropic.com.

| File | Role |
|---|---|
| `fake_anthropic.py` | Pretends to be the Anthropic API. Every call reports 20,000 input + 2,000 output tokens = **$0.03** on Claude Haiku 4.5. |
| `spend.yaml` | Spend proxy config: forward to the fake API; `runaway-bot` gets **$0.10**. |
| `runaway_agent.py` | An agent stuck in a loop, using the official `anthropic` SDK. Only `base_url` changes. |
| `run_demo.py` | Starts the fake API + `shugo spend serve`, runs the agent, prints status and the audit log. |

```bash
.venv/bin/python examples/runaway-agent/run_demo.py            # plain calls
.venv/bin/python examples/runaway-agent/run_demo.py --stream   # streaming calls
```

Expected:

```
call  1: ok  (20,000 in / 2,000 out tokens)
call  2: ok  (20,000 in / 2,000 out tokens)
call  3: ok  (20,000 in / 2,000 out tokens)
call  4: BLOCKED (402 billing_error): ... budget exceeded for agent 'runaway-bot':
         spent $0.0900 of $0.10, and the next call is estimated at ~$0.0300
```

The agent stops at **$0.09**, under its $0.10 limit: a fourth call would have
made it $0.12, and the proxy refuses it before it's sent.

## Using it with a real agent

```bash
shugo spend serve -c spend.yaml          # upstream defaults to https://api.anthropic.com
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
```

Name each agent with an `x-agent-id` header (SDK: `default_headers={"x-agent-id": "my-bot"}`;
Claude Code: `ANTHROPIC_CUSTOM_HEADERS="x-agent-id: my-bot"`). Unnamed agents share
the `default` budget.
