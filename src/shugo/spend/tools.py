"""Apply tool rules to the tool calls Claude asks for in its replies.

Agents that define tools in the API request (not through MCP) run whatever
`tool_use` blocks come back. shugo's tool guard never sees those, but the
reply passes through this proxy, so we check each one here, with the same
rules file and engine, before the agent can act on it.

A blocked call is replaced by a text block explaining why ("rewrite", the
default), so the agent never receives the instruction and the model can adapt
on its next turn; or the whole reply is refused ("error").
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Callable

from shugo.approval.channel import ApprovalChannel
from shugo.approval.resolve import resolve_escalation
from shugo.policy.engine import Decision, EvalContext, PolicyEngine

Recorder = Callable[[str, str, dict[str, Any], Decision], None]

class ToolBlocked(Exception):
    """Raised in 'error' mode: the reply is refused as a whole."""

def blocked_text(name: str, decision: Decision) -> str:
    return f"[blocked by policy] Tool call `{name}` was not run: {decision.reason or 'denied by policy'}"

class ToolGate:
    def __init__(self, engine: PolicyEngine, *, server: str, on_deny: str,
                 approval: ApprovalChannel | None, record: Recorder) -> None:
        self.engine, self.server, self.on_deny = engine, server, on_deny
        self.approval, self.record = approval, record

    async def judge(self, name: str, args: Any) -> Decision:
        args = args if isinstance(args, dict) else {"input": args}
        req_id = uuid.uuid4().hex
        decision = self.engine.evaluate(EvalContext(server=self.server, tool=name, args=args))
        decision = await resolve_escalation(
            decision, self.approval, request_id=req_id, server=self.server, tool=name, args=args
        )
        self.record(req_id, name, args, decision)
        if decision.kind != "allow" and self.on_deny == "error":
            raise ToolBlocked(f"tool call `{name}` blocked by policy: {decision.reason or 'denied'}")
        return decision

    async def filter_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Non-streaming reply: judge every tool_use block, replace the blocked ones."""
        content, kept_tools, saw_tools = [], 0, False
        for block in message.get("content") or []:
            if block.get("type") == "tool_use":
                saw_tools = True
                decision = await self.judge(block.get("name", ""), block.get("input"))
                if decision.kind == "allow":
                    kept_tools += 1
                    content.append(block)
                else:
                    content.append({"type": "text", "text": blocked_text(block.get("name", ""), decision)})
            else:
                content.append(block)
        out = {**message, "content": content}
        if saw_tools and kept_tools == 0 and out.get("stop_reason") == "tool_use":
            out["stop_reason"] = "end_turn"  # nothing left for the agent to run
        return out

    def stream_filter(self) -> "StreamFilter":
        return StreamFilter(self)

def _parse(event: bytes) -> tuple[str | None, dict[str, Any] | None]:
    name, data = None, None
    for line in event.split(b"\n"):
        if line.startswith(b"event:"):
            name = line[6:].strip().decode()
        elif line.startswith(b"data:"):
            try:
                data = json.loads(line[5:].strip())
            except ValueError:
                data = None
    return name, data

def _event(name: str, data: dict[str, Any]) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()

class StreamFilter:
    """Streaming reply: text flows through event by event; a tool_use block is
    held until it's complete (its input arrives in pieces), judged, then either
    released unchanged or swapped for a text block at the same index."""

    def __init__(self, gate: ToolGate) -> None:
        self.gate = gate
        self._buf = b""
        self._held: list[bytes] | None = None
        self._held_index: int | None = None
        self._name = ""
        self._json: list[str] = []
        self._initial_input: Any = None
        self._saw_tools = False
        self._kept_tools = 0

    async def feed(self, chunk: bytes) -> bytes:
        self._buf += chunk.replace(b"\r\n", b"\n")
        out: list[bytes] = []
        while b"\n\n" in self._buf:
            raw, self._buf = self._buf.split(b"\n\n", 1)
            out.append(await self._on_event(raw + b"\n\n"))
        return b"".join(out)

    def flush(self) -> bytes:
        rest, self._buf = self._buf, b""
        return rest if self._held is None else b""  # an unfinished tool call is never released

    async def _on_event(self, raw: bytes) -> bytes:
        name, data = _parse(raw)
        kind = (data or {}).get("type")

        if kind == "content_block_start" and (data.get("content_block") or {}).get("type") == "tool_use":
            block = data["content_block"]
            self._saw_tools = True
            self._held, self._held_index = [raw], data.get("index")
            self._name, self._json = block.get("name", ""), []
            self._initial_input = block.get("input")
            return b""

        if self._held is not None and data and data.get("index") == self._held_index:
            self._held.append(raw)
            if kind == "content_block_delta" and (data.get("delta") or {}).get("type") == "input_json_delta":
                self._json.append(data["delta"].get("partial_json", ""))
                return b""
            if kind == "content_block_stop":
                return await self._release()
            return b""

        if kind == "message_delta" and self._saw_tools and self._kept_tools == 0:
            delta = data.get("delta") or {}
            if delta.get("stop_reason") == "tool_use":
                return _event(name or "message_delta", {**data, "delta": {**delta, "stop_reason": "end_turn"}})
        return raw

    async def _release(self) -> bytes:
        held, index, name = self._held or [], self._held_index, self._name
        self._held, self._held_index = None, None
        joined = "".join(self._json)
        try:
            args = json.loads(joined) if joined else (self._initial_input or {})
        except ValueError:
            args = {"_unparseable_input": joined}
        decision = await self.gate.judge(name, args)
        if decision.kind == "allow":
            self._kept_tools += 1
            return b"".join(held)
        text = blocked_text(name, decision)
        return (
            _event("content_block_start", {"type": "content_block_start", "index": index,
                                           "content_block": {"type": "text", "text": ""}})
            + _event("content_block_delta", {"type": "content_block_delta", "index": index,
                                             "delta": {"type": "text_delta", "text": text}})
            + _event("content_block_stop", {"type": "content_block_stop", "index": index})
        )
