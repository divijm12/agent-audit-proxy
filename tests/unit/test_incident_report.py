from datetime import datetime, timedelta, timezone

from shugo.audit.log import AuditLog
from shugo.audit.report import export_incident_report

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def _at(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def _seed(path):
    log = AuditLog(path)
    rows = [
        (100, dict(server="anthropic", tool="messages", args={"model": "claude-haiku-4-5"}, decision="allow",
                   matched_rule_id=None, extra={"kind": "model_call", "agent_id": "old-bot", "cost_usd": 9.0})),
        (10, dict(server="anthropic", tool="messages", args={"model": "claude-haiku-4-5"}, decision="allow",
                  matched_rule_id=None, extra={"kind": "model_call", "agent_id": "bot", "cost_usd": 0.03})),
        (9, dict(server="anthropic", tool="messages", args={"model": "claude-haiku-4-5"}, decision="deny",
                 matched_rule_id="budget", reason="budget exceeded", extra={"kind": "model_call", "agent_id": "bot"})),
        (8, dict(server="api", tool="bash", args={"command": "rm -rf /"}, decision="deny",
                 matched_rule_id="no-rm", reason="nope | <b>x</b>", extra={"kind": "tool_call", "agent_id": "bot"})),
        (7, dict(server="gh", tool="create_pr", args={}, decision="allow", matched_rule_id="r", approver="alice")),
        (6, dict(server="shugo", tool="kill_switch", args={"by": "dashboard"}, decision="halt",
                 matched_rule_id="kill-switch", extra={"kind": "kill_switch"})),
    ]
    for hours_ago, kw in rows:
        log.append(log.build(request_id=f"r{hours_ago}", ts=_at(hours_ago), **kw))


def test_report_covers_only_the_window_and_counts_correctly(tmp_path):
    path = tmp_path / "audit.log"
    _seed(path)
    md = export_incident_report(path, hours=72, now=NOW)
    assert "# Agent incident report — last 72 hours" in md
    assert "not a regulatory filing" in md
    assert "old-bot" not in md and "$9.0000" not in md          # 100h ago: outside the window
    assert "| Actions (model calls + tool calls) | 4 |" in md
    assert "| Blocked | 2 |" in md
    assert "| Approved by a human | 1 |" in md
    assert "| Model spend | $0.0300 |" in md
    assert "| Kill switch events | 1 |" in md
    assert "| bot | 3 | 2 | $0.0300 |" in md
    assert "**halt** by dashboard" in md
    assert "**PASS.**" in md and "6 entries" in md
    assert "## Full audit trail (5 entries)" in md


def test_agent_text_cannot_break_the_table_or_inject_html(tmp_path):
    path = tmp_path / "audit.log"
    _seed(path)
    md = export_incident_report(path, hours=72, now=NOW)
    assert "nope \\| &lt;b&gt;x&lt;/b&gt;" in md and "<b>" not in md


def test_tampering_shows_up_as_fail(tmp_path):
    path = tmp_path / "audit.log"
    _seed(path)
    lines = path.read_text().splitlines()
    lines[2] = lines[2].replace('"deny"', '"allow"')
    path.write_text("\n".join(lines) + "\n")
    md = export_incident_report(path, hours=72, now=NOW)
    assert "**FAIL.**" in md and "line 3" in md


def test_empty_log(tmp_path):
    md = export_incident_report(tmp_path / "audit.log", hours=24, now=NOW)
    assert "No agent activity in this window." in md and "No entries in this window." in md
