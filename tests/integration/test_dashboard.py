"""Dashboard: STOP/RESUME, spend bars data, recent audit rows."""
from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from shugo.audit.verify import verify_log
from shugo.spend.config import SpendConfig
from shugo.spend.server import create_app

from .test_spend_proxy import FakeAnthropic, _post, home  # noqa: F401  (fixture)

BUTTON = {"x-shugo-dashboard": "1"}


def _client(fake, **cfg):
    cfg.setdefault("db_path", ":memory:")
    return TestClient(create_app(SpendConfig(upstream="https://fake.anthropic", **cfg),
                                 transport=httpx.MockTransport(fake.handler)))


def test_dashboard_page_is_served(home):
    with _client(FakeAnthropic()) as c:
        r = c.get("/dashboard")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "STOP" in r.text and "/api/state" in r.text
    assert "innerHTML" not in r.text  # agent-controlled text only ever goes in via textContent


def test_click_stop_blocks_the_next_agent_request_instantly(home):
    fake = FakeAnthropic()
    with _client(fake) as c:
        assert _post(c).status_code == 200
        state = c.post("/api/stop", headers=BUTTON).json()
        assert state["halted"] is True and state["by"] == "dashboard"
        blocked = _post(c)
        assert blocked.status_code == 403
        assert blocked.json()["error"]["message"].startswith("halted by kill switch")
        assert len(fake.requests) == 1  # the blocked call never left the proxy

        state = c.post("/api/resume", headers=BUTTON).json()
        assert state["halted"] is False
        assert _post(c).status_code == 200


def test_stop_and_resume_need_the_dashboard_header(home):
    with _client(FakeAnthropic()) as c:
        assert c.post("/api/stop").status_code == 403
        assert c.get("/api/state").json()["halted"] is False


def test_stop_is_idempotent_and_both_actions_are_audited(home):
    with _client(FakeAnthropic()) as c:
        c.post("/api/stop", headers=BUTTON)
        c.post("/api/stop", headers=BUTTON)  # second click changes nothing
        c.post("/api/resume", headers=BUTTON)
        rows = c.get("/api/state").json()["audit"]
    actions = [(r["tool"], r["decision"], r["args_redacted"]["by"]) for r in rows]
    assert actions == [("kill_switch", "resume", "dashboard"), ("kill_switch", "halt", "dashboard")]
    assert verify_log(home / "audit.log").ok


def test_state_has_spend_per_agent_and_newest_rows_first(home):
    with _client(FakeAnthropic(), agents={"bot": {"budget_usd": 0.10}}) as c:
        _post(c, agent="bot")
        _post(c, agent="other")
        state = c.get("/api/state").json()
    spend = {a["agent_id"]: (round(a["total_spent"], 4), a["budget_limit"]) for a in state["agents"]}
    assert spend == {"bot": (0.03, 0.10), "other": (0.03, 1.0)}
    assert [r["agent_id"] for r in state["audit"]] == ["other", "bot"]


def test_state_shows_at_most_50_rows(home):
    with _client(FakeAnthropic(), default_budget_usd=100) as c:
        for _ in range(55):
            _post(c)
        assert len(c.get("/api/state").json()["audit"]) == 50


def test_cli_halt_is_audited_too(home, monkeypatch):
    from typer.testing import CliRunner

    from shugo.cli import app

    CliRunner().invoke(app, ["halt"])
    CliRunner().invoke(app, ["unhalt"])
    lines = (home / "audit.log").read_text().splitlines()
    assert len(lines) == 2 and '"by": "cli"' in lines[0]
