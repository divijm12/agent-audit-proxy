# Changelog

All notable changes are documented here. This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Versions up to 0.1.0 are upstream [shugo](https://github.com/aritraghosh01/shugo); 0.2.0 onward is Agent Audit Proxy.

## [0.2.0] — 2026-09-25

### Added
- **Spend proxy** (`shugo spend serve`): Anthropic-compatible `/v1/messages` passthrough with per-agent
  budgets (SQLite ledger, in-flight reservations, estimate from the agent's previous call), pricing from
  published per-token rates incl. cache reads/writes, streaming relayed unchanged; `spend status | reset`.
- **Tool policy on model responses** (`tool_policy` in `spend.yaml`): `tool_use` blocks judged against
  `guardrails.yaml`; denied calls rewritten to an explanation or refused; `escalate` waits for approval;
  streamed tool calls buffered until complete.
- **Policy `args_regex`**: regex matching inside tool arguments (dotted paths or `*`).
- **Dashboard** (`/dashboard`): STOP/RESUME, per-agent spend, recent audit entries, incident export.
- **Incident reports**: `GET /export?hours=N`, `shugo audit report`; integrity check and chain head.
- **Kill switch** shared by the tool guard and spend proxy; every halt/resume is audited.
- **`shugo audit verify --anchor`** detects tail truncation and full rewrites.
- **Live demo** (`shugo spend demo`), Dockerfile, `fly.toml`, optional login
  (`SHUGO_DASHBOARD_PASSWORD`, `SHUGO_AGENT_TOKEN`).
- **Evaluations** (`evals/`): runaway, red team, tamper, latency; one real-API run.
- Install straight from GitHub: `uv tool install git+https://github.com/divijm12/agent-audit-proxy`.
- Dashboard link-preview (Open Graph / Twitter card) tags and a favicon.

### Changed
- `shugo spend serve` explains a missing `guardrails.yaml` or an invalid `spend.yaml` instead of
  printing a traceback.
- CLI help describes the whole project; `--version` is read from the package metadata.
- Examples renamed to `tool-guard/`, `runaway-agent/`, `dashboard/`; tool-guard docs install this
  repository rather than the upstream PyPI package.

### Fixed
- Proxy forwarded only `result.content`, dropping `structuredContent` and failing allowed calls to tools
  with an `outputSchema` (sent upstream as shugo#14).
- Audit log is safe for multiple writer processes (file lock; head re-read on append).
- CI: committed `uv.lock`, install via `uv sync`; date- and terminal-dependent tests (sent upstream as shugo#13).
- Streaming relay forwards decoded bytes (compressed streams previously reached agents undecoded).

### Removed
- PyPI release workflow (publishes upstream `shugo`; not applicable to this repository).

## [0.1.0] — 2026-07-30

### Added
- Initial project skeleton and packaging (`pyproject.toml`, `src/shugo/` layout).
- Typer-based CLI surface with all v0.1 subcommand stubs: `serve`, `init`, `validate`, `explain`, `audit tail|verify`, `evidence`, `approve`, `deny`, `halt`, `unhalt`.
- Cross-platform `~/.shugo/` layout helpers (`SHUGO_HOME` override supported).
- GitHub Actions CI matrix (Python 3.11–3.13 × macOS / Ubuntu / Windows).
- Policy models (`shugo.policy.models`): Pydantic v2, `extra=forbid`, unique rule ids, `escalate` requires an `approval` block.
- Policy loader (`shugo.policy.loader.load_config`): YAML parse + schema validate with clear error messages.
- Policy engine (`shugo.policy.engine.PolicyEngine`): deny-by-default, first-match-wins, `fnmatch` globs on server/tool, nested-equality on args.
- Working `shugo validate` and `shugo explain` commands.
- `policies/starter.yaml` reference policy modeled on the README example.
- Audit log (`shugo.audit`): append-only JSONL with rolling SHA-256 hash chain (seed = 64×"0"), NFC-normalized canonical JSON, per-line `os.fsync`, thread-safe append. Redaction of dotted arg paths is applied before hashing so log and hash agree.
- Log verification (`shugo audit verify`): streams each line, recomputes hash, checks both `this_hash` and next `prev_hash`. Reports first divergence with line number and exits non-zero.
- `shugo audit tail [-n N] [-f]` and `shugo halt` / `shugo unhalt` kill-switch controls (writes `~/.shugo/HALT`).
- Router (`shugo.router`): namespaces tools as `<server>__<tool>` so multiple upstreams merge cleanly under a single `tools/list`.
- Upstream (`shugo.upstream.StdioUpstream`): MCP client wrapping a stdio subprocess per upstream, managed via `AsyncExitStack` for clean teardown.
- Proxy (`shugo.proxy`): full async MCP server that intercepts `tools/list` and `tools/call`, routes to the right upstream, evaluates policy, records to the audit log, and respects the HALT sentinel. `serve_with_upstreams(...)` is exposed for integration tests using in-memory streams and fake upstreams.
- Working `shugo serve` with allow/deny paths (escalate temporarily rendered as deny; PR #5 wires real approvals).
- File-drop approval channel (`shugo.approval.FileApprovalChannel`): proxy writes `~/.shugo/pending/<uuid>.json`, blocks on 250 ms poll of the `approved/` / `denied/` / `timeout/` directories; verdicts move atomically via `os.replace`.
- Sidecar TUI (`shugo approve --watch`): polls the pending queue and prompts approve/deny/skip per request.
- One-shot CLI: `shugo approve <id>` and `shugo deny <id> [--note NOTE]`.
- Proxy escalate path now fully wired: request-approval, on-timeout honors policy (`allow` or `deny`), audit log records approver.
- Opt-in local HTTP approval UI (`shugo.approval.http_ui`): single-file HTML page + `GET /api/pending` + `POST /api/verdict/<id>`. Bound to `127.0.0.1` only; shares the file-drop backend so `shugo approve --watch` and the browser resolve the same queue.
- `shugo serve --approvals file|http|both --approvals-port N` (default port 6247).
- Evidence packs (`shugo.evidence`): four framework mappings shipped as data files (OWASP LLM Top 10, NIST AI RMF, EU AI Act, ISO/IEC 42001) — control identifiers only, authored by the SHUGO project from public sources.
- `shugo evidence -f FRAMEWORK -s SINCE -o OUT -c POLICY` generates a bundle: `report.md` (per-control fires / approvals / denies + coverage gaps), `rules.yaml` (policy snapshot), `audit-window.jsonl` (filtered entries), `manifest.json` (SHA-256 of every file + audit-log integrity check).
- `shugo init` (`shugo.discovery` + `shugo.commands.init`): finds Claude Desktop / Claude Code / Cursor / VS Code configs per-OS, enumerates upstream tools via 10 s stdio probe, writes a starter `guardrails.yaml` with `read_*|list_*|get_*|search_*` allowed and everything else escalated, prints the exact JSON snippet to paste into the client config, backs up any existing policy.
- Documentation: `docs/quickstart.md`, `docs/policy-guide.md`, `docs/approvals.md`, `docs/evidence.md`, and `incident-playbook.md`.
- End-to-end test against real `@modelcontextprotocol/server-filesystem` via `npx` (marked `slow`; runs in CI on Ubuntu).
- Release workflow (`.github/workflows/release.yml`) publishes to PyPI via trusted publishing on `v*` tags.
