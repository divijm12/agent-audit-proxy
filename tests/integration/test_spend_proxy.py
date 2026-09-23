"""Spend proxy end to end: a real FastAPI app in front of a fake Anthropic API."""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from shugo.audit.verify import verify_log
from shugo.spend.config import SpendConfig
from shugo.spend.server import create_app

HAIKU = "claude-haiku-4-5"
# 20k input + 2k output on Haiku = 0.02 + 0.01 = $0.03 per call
USAGE = {"input_tokens": 20_000, "output_tokens": 2_000}


def _message(model=HAIKU, usage=USAGE):
    return {
        "id": "msg_fake", "type": "message", "role": "assistant", "model": model,
        "content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn",
        "usage": usage,
    }


def _sse(model=HAIKU, input_tokens=20_000, output_tokens=2_000) -> list[bytes]:
    events = [
        ("message_start", {"type": "message_start", "message": {
            **_message(model, {"input_tokens": input_tokens, "output_tokens": 1}), "content": []}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": "hi"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                           "usage": {"output_tokens": output_tokens}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    raw = b"".join(f"event: {n}\ndata: {json.dumps(d)}\n\n".encode() for n, d in events)
    # Split at awkward places so events straddle chunk boundaries.
    return [raw[i:i + 37] for i in range(0, len(raw), 37)]


class FakeAnthropic:
    def __init__(self, status=200, on_chunk=None):
        self.requests: list[httpx.Request] = []
        self.status = status
        self.on_chunk = on_chunk

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"type": "error", "error": {
                "type": "invalid_request_error", "message": "bad"}})
        if request.url.path != "/v1/messages":
            return httpx.Response(200, json={"input_tokens": 12})
        body = json.loads(request.content)
        if body.get("stream"):
            chunks = _sse(body["model"])

            async def gen():
                for i, c in enumerate(chunks):
                    if self.on_chunk:
                        self.on_chunk(i)
                    yield c

            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=gen())
        return httpx.Response(200, json=_message(body["model"]))


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "shugo-home"
    monkeypatch.setenv("SHUGO_HOME", str(h))
    return h


def _client(fake, **cfg):
    cfg.setdefault("db_path", ":memory:")
    app = create_app(SpendConfig(upstream="https://fake.anthropic", **cfg),
                     transport=httpx.MockTransport(fake.handler))
    return TestClient(app)


def _post(c, agent="bot", model=HAIKU, stream=False):
    return c.post("/v1/messages", headers={"x-api-key": "sk-test", "x-agent-id": agent,
                                           "anthropic-version": "2023-06-01"},
                  json={"model": model, "max_tokens": 1024, "stream": stream,
                        "messages": [{"role": "user", "content": "hello"}]})


def _audit(home):
    return [json.loads(line) for line in (home / "audit.log").read_text().splitlines()]


def test_non_streaming_call_is_forwarded_priced_and_logged(home):
    fake = FakeAnthropic()
    with _client(fake) as c:
        r = _post(c)
        status = c.get("/spend/status").json()
    assert r.status_code == 200 and r.json()["content"][0]["text"] == "hi"
    sent = fake.requests[0]
    assert sent.headers["x-api-key"] == "sk-test"      # the agent's key passes through
    assert "x-agent-id" not in sent.headers             # our header doesn't leak upstream
    assert json.loads(sent.content)["messages"][0]["content"] == "hello"
    assert status["agents"][0]["total_spent"] == pytest.approx(0.03)
    (entry,) = _audit(home)
    assert entry["decision"] == "allow" and entry["agent_id"] == "bot"
    assert entry["cost_usd"] == pytest.approx(0.03) and entry["usage"] == USAGE
    assert "sk-test" not in (home / "audit.log").read_text()  # keys never logged


def test_streaming_bytes_pass_through_unchanged_and_usage_is_read(home):
    fake = FakeAnthropic()
    with _client(fake) as c:
        with c.stream("POST", "/v1/messages", headers={"x-agent-id": "bot"},
                      json={"model": HAIKU, "max_tokens": 10, "stream": True, "messages": []}) as r:
            received = b"".join(r.iter_bytes())
    assert received == b"".join(_sse())
    (entry,) = _audit(home)
    assert entry["usage"] == {"input_tokens": 20_000, "output_tokens": 2_000}
    assert entry["cost_usd"] == pytest.approx(0.03)


def test_runaway_agent_is_stopped_at_budget(home):
    fake = FakeAnthropic()
    with _client(fake, agents={"bot": {"budget_usd": 0.10}}) as c:
        codes = [_post(c).status_code for _ in range(10)]
        blocked = _post(c)
        spent = c.get("/spend/status").json()["agents"][0]["total_spent"]
    # $0.03/call: calls 1-3 run (0.09 spent); a 4th would reach 0.12, so it's refused.
    assert codes == [200] * 3 + [402] * 7
    assert len(fake.requests) == 3                     # blocked calls never reach the API
    assert spent == pytest.approx(0.09)                # stopped under the limit, not over
    err = blocked.json()["error"]
    assert err["type"] == "billing_error" and "budget exceeded for agent 'bot'" in err["message"]
    denies = [e for e in _audit(home) if e["decision"] == "deny"]
    assert len(denies) == 8 and all(e["matched_rule_id"] == "budget" for e in denies)


def test_other_agents_keep_working_when_one_is_blocked(home):
    fake = FakeAnthropic()
    with _client(fake, agents={"bot": {"budget_usd": 0.01}}) as c:
        _post(c, agent="bot")
        assert _post(c, agent="bot").status_code == 402
        assert _post(c, agent="other").status_code == 200


def test_kill_switch_blocks_before_anything_else(home):
    fake = FakeAnthropic()
    with _client(fake) as c:
        (home / "HALT").write_text("halted")
        r = _post(c)
    assert r.status_code == 403 and r.json()["error"]["type"] == "permission_error"
    assert fake.requests == []
    (entry,) = _audit(home)
    assert entry["decision"] == "deny" and entry["matched_rule_id"] == "kill-switch"


def test_kill_switch_cuts_an_open_stream(home):
    def halt_midway(i):
        if i == 3:
            (home / "HALT").write_text("halted")

    fake = FakeAnthropic(on_chunk=halt_midway)
    with _client(fake) as c:
        with c.stream("POST", "/v1/messages", headers={"x-agent-id": "bot"},
                      json={"model": HAIKU, "max_tokens": 10, "stream": True, "messages": []}) as r:
            received = b"".join(r.iter_bytes())
    assert b"halted by kill switch: stream closed" in received
    assert b"message_stop" not in received
    (entry,) = _audit(home)
    assert entry["reason"] == "stream cut by kill switch"


def test_unknown_model_is_denied_by_default(home):
    fake = FakeAnthropic()
    with _client(fake) as c:
        r = _post(c, model="gpt-6-sol")
    assert r.status_code == 403 and "not in the price table" in r.json()["error"]["message"]
    assert fake.requests == []


def test_unknown_model_can_be_charged_at_max_price(home):
    fake = FakeAnthropic()
    with _client(fake, unknown_model="max_price") as c:
        assert _post(c, model="claude-future-9").status_code == 200


def test_upstream_errors_pass_through_and_cost_nothing(home):
    fake = FakeAnthropic(status=400)
    with _client(fake, agents={"bot": {"budget_usd": 0.10}}) as c:
        r = _post(c)
        status = c.get("/spend/status").json()["agents"][0]
    assert r.status_code == 400 and r.json()["error"]["message"] == "bad"
    assert status["total_spent"] == 0 and status["reserved"] == 0


def test_other_endpoints_pass_through(home):
    fake = FakeAnthropic()
    with _client(fake) as c:
        r = c.post("/v1/messages/count_tokens", json={"model": HAIKU, "messages": []})
    assert r.json() == {"input_tokens": 12}
    assert fake.requests[0].url.path == "/v1/messages/count_tokens"


def test_audit_chain_verifies_after_mixed_traffic(home):
    fake = FakeAnthropic()
    with _client(fake, agents={"bot": {"budget_usd": 0.05}}) as c:
        for _ in range(4):
            _post(c)
        _post(c, stream=True)
        _post(c, model="nope")
    result = verify_log(home / "audit.log")
    assert result.ok and result.entries == 6
