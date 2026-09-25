"""The live demo: fake Claude, looping agents, resets."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient


def test_demo_agents_generate_traffic_and_blocks(tmp_path, monkeypatch):
    real_home = tmp_path / "real-home"
    monkeypatch.setenv("SHUGO_HOME", str(real_home))
    from shugo.spend import demo

    monkeypatch.setattr(demo, "AGENTS", [("runaway-bot", 0.10, 0.02, 20_000, 2_000),
                                         ("tool-bot", 1.00, 0.02, 1_500, 200)])
    with TestClient(demo.create_demo_app()) as c:
        deadline = time.time() + 10
        while time.time() < deadline:
            state = c.get("/api/state").json()
            decisions = {(r.get("kind"), r["decision"], r.get("matched_rule_id")) for r in state["audit"]}
            if {("model_call", "deny", "budget"), ("tool_call", "deny", "no-recursive-delete"),
                ("tool_call", "allow", "safe-shell")} <= decisions:
                break
            time.sleep(0.1)
        else:
            raise AssertionError(f"demo never produced the expected mix: {decisions}")
        assert state["demo"]["reset_every_s"] == 300
        assert "Live demo" in c.get("/dashboard").text
    assert not real_home.exists()  # the demo never touches a real SHUGO_HOME
