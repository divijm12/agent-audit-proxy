# Tool guard quickstart

The tool guard (`shugo serve`) stands in front of your MCP servers, evaluates a YAML policy on every `tools/call`, and records every decision to a tamper-evident audit log. This guide gets you from zero to guarded in under five minutes.

## 1. Install

```bash
uv tool install git+https://github.com/divijm12/agent-audit-proxy
shugo --version
```

This installs this repository's `shugo` (the tool guard plus the spend proxy). The older
`shugo` package on PyPI is the upstream project and lacks the fixes and features here.

## 2. Scaffold a policy

Point `shugo init` at your MCP client config (Claude Desktop / Claude Code / Cursor / VS Code). If you don't pass `--from`, SHUGO searches the standard locations for your OS.

```bash
shugo init
```

This writes `./guardrails.yaml` with:
- one `upstreams:` entry per MCP server you already have configured
- read-only tools (`get_*`, `list_*`, `search_*`, `read_*`) auto-allowed
- everything else set to `escalate` (deny by default until you approve)

Then follow the printed JSON snippet — replace your client's `mcpServers` block so it points at `shugo serve` instead of your servers directly.

## 3. Restart your MCP client

Restart Claude Desktop / Cursor / VS Code / Claude Code so it picks up the new config.

## 4. Approve requests as they come

Escalated calls block until you decide. Run the sidecar in a second terminal:

```bash
shugo approve --watch          # TUI
```

or open the browser UI:

```bash
shugo serve --approvals both   # start the proxy with the HTTP UI enabled
# then open http://127.0.0.1:6247
```

## 5. Verify the audit trail

```bash
shugo audit tail -n 20
shugo audit verify
```

`audit verify` recomputes the SHA-256 hash chain over `~/.shugo/audit.log` and exits non-zero if any line has been tampered with.

## 6. Generate evidence

```bash
shugo evidence -f owasp-llm -s 30d -o evidence/
```

Produces a control-by-control report of which rules fired, how many approvals happened, and where you have coverage gaps.

## Kill switch

```bash
shugo halt      # deny all calls until unhalt
shugo unhalt
```
