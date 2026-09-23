"""Read token usage out of an Anthropic SSE stream without altering the bytes."""
from __future__ import annotations

import json
from typing import Any


class UsageTracker:
    """Feed raw stream chunks in order; `usage` and `model` fill in as events arrive.

    message_start carries the input-side usage; each message_delta carries
    cumulative usage (output_tokens, sometimes updated input fields), so later
    values overwrite earlier ones.
    """

    def __init__(self) -> None:
        self._buf = b""
        self.usage: dict[str, Any] = {}
        self.model: str | None = None
        self.stop_reason: str | None = None

    def feed(self, chunk: bytes) -> None:
        self._buf += chunk
        *lines, self._buf = self._buf.split(b"\n")
        for line in lines:
            line = line.strip()
            if line.startswith(b"data:"):
                self._event(line[5:].strip())

    def _event(self, data: bytes) -> None:
        try:
            ev = json.loads(data)
        except ValueError:
            return
        kind = ev.get("type")
        if kind == "message_start":
            msg = ev.get("message") or {}
            self.model = msg.get("model") or self.model
            self.usage.update({k: v for k, v in (msg.get("usage") or {}).items() if v is not None})
        elif kind == "message_delta":
            self.usage.update({k: v for k, v in (ev.get("usage") or {}).items() if v is not None})
            self.stop_reason = (ev.get("delta") or {}).get("stop_reason") or self.stop_reason
