# Examples

All run locally against a fake Anthropic API: no API key, no cost. Run from the repo root
after `uv sync --extra dev`.

| Example | Shows | Run |
|---|---|---|
| [`tool-guard/`](tool-guard/) | MCP tool calls allowed, denied and escalated by `shugo serve`, and the hash-chained audit log | `.venv/bin/python examples/tool-guard/send_tool_calls.py` |
| [`runaway-agent/`](runaway-agent/) | An agent on the Anthropic SDK looping until the spend proxy stops it at its budget | `.venv/bin/python examples/runaway-agent/run_demo.py` |
| [`dashboard/`](dashboard/) | The dashboard: per-agent spend, STOP / RESUME, incident export | `.venv/bin/python examples/dashboard/run_demo.py` |
