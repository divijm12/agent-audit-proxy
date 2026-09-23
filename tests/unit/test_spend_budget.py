import pytest

from shugo.spend.budget import BudgetExceeded, BudgetStore


def _store(**limits):
    return BudgetStore(":memory:", default_limit=1.0, limits=limits)


def test_unknown_agent_gets_default_limit():
    s = _store()
    s.settle(s.reserve("new-bot", 0.0), 0.25)
    assert s.status() == [{"agent_id": "new-bot", "total_spent": 0.25, "budget_limit": 1.0, "reserved": 0.0}]


def test_blocks_once_spent_reaches_limit():
    s = _store(bot=0.10)
    s.settle(s.reserve("bot", 0.0), 0.11)  # a first call can overshoot: nothing to go on yet
    with pytest.raises(BudgetExceeded) as e:
        s.reserve("bot", 0.0)
    assert e.value.limit == 0.10 and e.value.spent == pytest.approx(0.11)
    assert str(e.value) == "budget exceeded for agent 'bot': spent $0.1100 of $0.10"


def test_repeating_calls_are_stopped_before_crossing_the_limit():
    s = _store(bot=0.10)
    for _ in range(3):
        s.settle(s.reserve("bot", 0.0), 0.03)  # 0.09 spent, last call cost 0.03
    with pytest.raises(BudgetExceeded) as e:
        s.reserve("bot", 0.0)  # size-based estimate says ~0, history says 0.03
    assert e.value.spent == pytest.approx(0.09) and e.value.estimate == pytest.approx(0.03)
    assert "next call is estimated at ~$0.0300" in str(e.value)


def test_failed_calls_do_not_change_the_estimate():
    s = _store(bot=0.10)
    s.settle(s.reserve("bot", 0.0), 0.03)
    s.settle(s.reserve("bot", 0.0), 0.0)  # e.g. upstream 400
    s.settle(s.reserve("bot", 0.0), 0.03)  # 0.06 spent
    s.reserve("bot", 0.0)  # estimated at the last real cost, 0.03: 0.09 in total, fits
    with pytest.raises(BudgetExceeded):
        s.reserve("bot", 0.0)  # a second one in flight would make 0.12


def test_blocks_when_estimate_would_cross_limit():
    s = _store(bot=0.10)
    s.settle(s.reserve("bot", 0.0), 0.08)
    with pytest.raises(BudgetExceeded):
        s.reserve("bot", 0.05)


def test_in_flight_reservations_count_against_budget():
    s = _store(bot=0.10)
    r1 = s.reserve("bot", 0.06)  # not settled yet
    with pytest.raises(BudgetExceeded):
        s.reserve("bot", 0.06)  # parallel request would push 0.12 in flight
    s.settle(r1, 0.01)  # real cost was lower
    s.reserve("bot", 0.06)  # now fits


def test_agents_are_independent():
    s = _store(a=0.10, b=0.10)
    s.settle(s.reserve("a", 0.0), 0.20)
    with pytest.raises(BudgetExceeded):
        s.reserve("a", 0.0)
    s.reserve("b", 0.05)


def test_config_limits_override_stored_limits(tmp_path):
    db = tmp_path / "spend.db"
    s1 = BudgetStore(db, default_limit=1.0, limits={"bot": 0.10})
    s1.settle(s1.reserve("bot", 0.0), 0.05)
    s2 = BudgetStore(db, default_limit=1.0, limits={"bot": 0.50})  # restart with a new limit
    assert s2.status()[0]["budget_limit"] == 0.50
    assert s2.status()[0]["total_spent"] == pytest.approx(0.05)  # spend survives restarts


def test_reset_clears_spend():
    s = _store(bot=0.10)
    s.settle(s.reserve("bot", 0.0), 0.50)
    s.reset("bot")
    s.reserve("bot", 0.05)
