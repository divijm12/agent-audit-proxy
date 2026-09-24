"""Incident report: everything the agents did in the last N hours, as markdown."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from shugo.audit.verify import verify_log

NOTE = (
    "Incident-style report modeled on 72-hour incident-reporting timelines "
    "(e.g. Illinois SB 315). It describes what this guardrail layer observed "
    "and enforced; it is not a regulatory filing."
)


def _cell(value: Any) -> str:
    """Agent-controlled text goes into a markdown table: keep it inert."""
    text = "" if value is None else str(value)
    for a, b in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ("|", "\\|"), ("`", "'")):
        text = text.replace(a, b)
    return " ".join(text.split()) or "—"


def _ts(entry: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(entry["ts"])
    except (KeyError, TypeError, ValueError):
        return None


def _action(e: dict[str, Any]) -> str:
    if e.get("kind") == "model_call":
        return f"model call ({(e.get('args_redacted') or {}).get('model', '?')})"
    return f"{e.get('server')}::{e.get('tool')}"


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue  # a corrupt line is reported by the integrity check
    return out


def export_incident_report(path: str | Path, hours: int = 72, *, now: datetime | None = None) -> str:
    path = Path(path)
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(hours=hours)
    all_rows = _read(path)
    rows = [e for e in all_rows if (t := _ts(e)) is not None and start <= t <= now]
    check = verify_log(path)
    head = all_rows[-1].get("this_hash") if all_rows else None

    model_calls = [e for e in rows if e.get("kind") == "model_call"]
    switch = [e for e in rows if e.get("kind") == "kill_switch"]
    actions = [e for e in rows if e.get("kind") != "kill_switch"]
    blocked = [e for e in actions if e.get("decision") == "deny"]
    approved = [e for e in actions if e.get("approver")]
    cost = sum(float(e.get("cost_usd") or 0) for e in model_calls)

    per_agent: dict[str, dict[str, float]] = defaultdict(lambda: {"actions": 0, "blocked": 0, "cost": 0.0})
    for e in actions:
        a = per_agent[e.get("agent_id") or "(tool guard)"]
        a["actions"] += 1
        a["blocked"] += e.get("decision") == "deny"
        a["cost"] += float(e.get("cost_usd") or 0)

    fmt = "%Y-%m-%d %H:%M:%S UTC"
    L: list[str] = [
        f"# Agent incident report — last {hours} hours",
        "",
        f"> {NOTE}",
        "",
        f"- **Window:** {start.strftime(fmt)} → {now.strftime(fmt)}",
        f"- **Generated:** {now.strftime(fmt)}",
        f"- **Source:** `{path.name}` ({len(all_rows)} entries in total)",
        "",
        "## Log integrity",
        "",
    ]
    if check.ok:
        L.append(f"**PASS.** Hash chain intact across all {check.entries} entries: no entry was edited, "
                 "removed or reordered after it was written.")
    else:
        L.append(f"**FAIL.** The hash chain breaks at line {check.error_line}: {_cell(check.error)}. "
                 "Entries from that point on cannot be trusted.")
    if head:
        L += ["", f"Chain head: `{head}`. Keep a copy of this value elsewhere: a later report whose "
                  "chain doesn't contain it means entries were cut off the end."]

    L += ["", "## Summary", "", "| | |", "|---|---|",
          f"| Actions (model calls + tool calls) | {len(actions)} |",
          f"| Blocked | {len(blocked)} |",
          f"| Approved by a human | {len(approved)} |",
          f"| Model calls attempted | {len(model_calls)} |",
          f"| Model spend | ${cost:.4f} |",
          f"| Kill switch events | {len(switch)} |"]

    L += ["", "## By agent", ""]
    if per_agent:
        L += ["| Agent | Actions | Blocked | Spend |", "|---|---:|---:|---:|"]
        for name, a in sorted(per_agent.items()):
            L.append(f"| {_cell(name)} | {int(a['actions'])} | {int(a['blocked'])} | ${a['cost']:.4f} |")
    else:
        L.append("No agent activity in this window.")

    L += ["", "## Kill switch", ""]
    if switch:
        for e in switch:
            L.append(f"- {e['ts'][:19].replace('T', ' ')} — **{e.get('decision')}** by "
                     f"{_cell((e.get('args_redacted') or {}).get('by'))}")
    else:
        L.append("Not used in this window.")

    def table(entries: list[dict[str, Any]]) -> list[str]:
        out = ["| Time (UTC) | Agent | Action | Decision | Rule | Cost | Reason |",
               "|---|---|---|---|---|---:|---|"]
        for e in entries:
            c = e.get("cost_usd")
            out.append(
                f"| {e.get('ts', '')[:19].replace('T', ' ')} | {_cell(e.get('agent_id'))} | {_cell(_action(e))} "
                f"| {_cell(e.get('decision'))} | {_cell(e.get('matched_rule_id'))} "
                f"| {'—' if c is None else f'${float(c):.4f}'} | {_cell(e.get('reason'))} |")
        return out

    L += ["", "## Blocked actions", ""]
    L += table(blocked) if blocked else ["None."]
    L += ["", f"## Full audit trail ({len(rows)} entries)", ""]
    L += table(rows) if rows else ["No entries in this window."]
    return "\n".join(L) + "\n"
