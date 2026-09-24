"""Turn an `escalate` decision into allow / deny by asking a human."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from shugo.approval.channel import ApprovalChannel, PendingApproval
from shugo.policy.engine import Decision


async def resolve_escalation(
    decision: Decision,
    approval: ApprovalChannel | None,
    *,
    request_id: str,
    server: str,
    tool: str,
    args: dict[str, Any],
) -> Decision:
    """Wait for a human verdict on an escalate decision; other decisions pass through."""
    if decision.kind != "escalate":
        return decision
    if approval is None:
        return Decision(
            kind="deny",
            rule_id=decision.rule_id,
            reason="escalate rule matched but no approval channel is configured",
            controls=decision.controls,
        )
    assert decision.approval is not None
    pending = PendingApproval(
        id=request_id,
        ts=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        server=server,
        tool=tool,
        args=dict(args),
        rule_id=decision.rule_id,
        reason=decision.reason,
        timeout_s=decision.approval.timeout_seconds,
        pid=os.getpid(),
        controls=decision.controls,
    )
    verdict = await approval.request(pending)
    if verdict.kind == "timeout":
        on_timeout = decision.approval.on_timeout
        return Decision(
            kind=on_timeout,
            rule_id=decision.rule_id,
            reason=f"approval timed out after {decision.approval.timeout_seconds}s "
                   f"(on_timeout={on_timeout})",
            controls=decision.controls,
            approver=None,
        )
    return decision.with_verdict(verdict.kind, approver=verdict.approver)
