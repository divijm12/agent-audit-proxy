"""Login for an internet-facing spend proxy."""
from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from shugo.spend.config import SpendConfig
from shugo.spend.server import create_app

from .test_spend_proxy import FakeAnthropic, _post


def _client(fake):
    return TestClient(create_app(SpendConfig(upstream="https://fake.anthropic", db_path=":memory:"),
                                 transport=httpx.MockTransport(fake.handler)))


def test_everything_open_when_no_secrets_are_set(home, monkeypatch):
    monkeypatch.delenv("SHUGO_DASHBOARD_PASSWORD", raising=False)
    monkeypatch.delenv("SHUGO_AGENT_TOKEN", raising=False)
    with _client(FakeAnthropic()) as c:
        assert c.get("/dashboard").status_code == 200 and _post(c).status_code == 200


def test_dashboard_needs_the_password(home, monkeypatch):
    monkeypatch.setenv("SHUGO_DASHBOARD_PASSWORD", "hunter2")
    with _client(FakeAnthropic()) as c:
        for path in ("/dashboard", "/api/state", "/export", "/spend/status"):
            r = c.get(path)
            assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic")
        assert c.get("/dashboard", auth=("anyone", "wrong")).status_code == 401
        assert c.get("/dashboard", auth=("anyone", "hunter2")).status_code == 200
        assert c.post("/api/stop", headers={"x-shugo-dashboard": "1"}).status_code == 401
        assert c.get("/healthz").status_code == 200        # load balancer health checks stay open
        assert _post(c).status_code == 200                  # no agent token set: agents unaffected


def test_agents_need_the_token_when_set(home, monkeypatch):
    monkeypatch.setenv("SHUGO_AGENT_TOKEN", "tok-123")
    fake = FakeAnthropic()
    with _client(fake) as c:
        r = _post(c)
        assert r.status_code == 401 and r.json()["error"]["type"] == "authentication_error"
        assert fake.requests == []
        ok = c.post("/v1/messages", headers={"x-agent-id": "bot", "x-shugo-token": "tok-123"},
                    json={"model": "claude-haiku-4-5", "max_tokens": 5, "messages": []})
        assert ok.status_code == 200


def test_api_docs_are_not_exposed(home):
    with _client(FakeAnthropic()) as c:
        assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404


def test_serve_refuses_the_open_internet_without_a_password(home, monkeypatch):
    from typer.testing import CliRunner

    from shugo.cli import app

    monkeypatch.delenv("SHUGO_DASHBOARD_PASSWORD", raising=False)
    result = CliRunner().invoke(app, ["spend", "serve", "--host", "0.0.0.0"])
    assert result.exit_code == 2 and "refusing to listen" in result.output


def test_serve_explains_a_missing_policy_file_instead_of_crashing(home, tmp_path):
    from typer.testing import CliRunner

    from shugo.cli import app

    cfg = tmp_path / "spend.yaml"
    cfg.write_text("tool_policy:\n  policy: guardrails.yaml\n")
    result = CliRunner().invoke(app, ["spend", "serve", "-c", str(cfg)])
    assert result.exit_code == 1
    assert "policy file not found" in result.output and "tool_policy.policy" in result.output
    assert "Traceback" not in result.output


def test_serve_explains_an_invalid_config(home, tmp_path):
    from typer.testing import CliRunner

    from shugo.cli import app

    cfg = tmp_path / "spend.yaml"
    cfg.write_text("agents:\n  bot: {budget_usd: -5}\n")
    result = CliRunner().invoke(app, ["spend", "serve", "-c", str(cfg)])
    assert result.exit_code == 1 and "is not valid" in result.output
