"""The kill switch: one file that freezes the tool guard and the spend proxy.

Every STOP and RESUME is written to the audit log, so the record shows who
froze the agents, when, and when they were let go again.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from shugo import paths
from shugo.audit.log import AuditLog


def is_halted() -> bool:
    return paths.halt_sentinel().exists()


def status() -> dict[str, Any]:
    sentinel = paths.halt_sentinel()
    if not sentinel.exists():
        return {"halted": False}
    info: dict[str, Any] = {"halted": True}
    for line in sentinel.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition(":")
        if key.strip() in ("halted-at", "by"):
            info[key.strip().replace("-", "_")] = value.strip()
    return info


def _record(action: str, by: str) -> None:
    audit = AuditLog(paths.audit_log())
    audit.append(audit.build(
        request_id=uuid.uuid4().hex, server="shugo", tool="kill_switch", args={"by": by},
        decision=action, matched_rule_id="kill-switch",
        reason=f"kill switch {'engaged' if action == 'halt' else 'released'} by {by}",
        extra={"kind": "kill_switch"},
    ))


def halt(by: str) -> bool:
    """Freeze everything. Returns False if already halted (nothing changes)."""
    if is_halted():
        return False
    paths.ensure_layout()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    paths.halt_sentinel().write_text(f"halted-at: {now}\nby: {by}\n", encoding="utf-8")
    _record("halt", by)
    return True


def resume(by: str) -> bool:
    """Unfreeze. Returns False if nothing was halted."""
    sentinel = paths.halt_sentinel()
    if not sentinel.exists():
        return False
    sentinel.unlink()
    _record("resume", by)
    return True
