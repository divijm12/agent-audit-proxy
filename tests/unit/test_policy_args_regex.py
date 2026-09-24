import pytest
from pydantic import ValidationError

from shugo.policy.engine import EvalContext, PolicyEngine
from shugo.policy.models import Config


def _engine(rules, default="allow"):
    return PolicyEngine(Config.model_validate(
        {"version": "0.1", "defaults": {"decision": default}, "rules": rules}))


RM = {"id": "no-rm-rf", "match": {"tool": "bash", "args_regex": {"command": r"rm\s+-\w*[rR]\w*f|rm\s+-\w*f\w*[rR]"}},
      "decision": "deny", "reason": "recursive force delete"}


@pytest.mark.parametrize("cmd", ["rm -rf /", "sudo rm -rf ~", "cd /tmp && rm -fr x", "rm -Rf ."])
def test_regex_matches_inside_the_field(cmd):
    d = _engine([RM]).evaluate(EvalContext("api", "bash", {"command": cmd}))
    assert d.kind == "deny" and d.rule_id == "no-rm-rf"


@pytest.mark.parametrize("cmd", ["rm notes.txt", "ls -rf", "echo hi"])
def test_regex_does_not_match_other_commands(cmd):
    assert _engine([RM]).evaluate(EvalContext("api", "bash", {"command": cmd})).kind == "allow"


def test_missing_or_non_string_field_does_not_match():
    e = _engine([RM])
    assert e.evaluate(EvalContext("api", "bash", {})).kind == "allow"
    assert e.evaluate(EvalContext("api", "bash", {"command": ["rm", "-rf"]})).kind == "allow"


def test_dotted_path_reaches_nested_fields():
    rule = {"id": "r", "match": {"args_regex": {"options.path": r"^/etc/"}}, "decision": "deny"}
    e = _engine([rule])
    assert e.evaluate(EvalContext("s", "t", {"options": {"path": "/etc/passwd"}})).kind == "deny"
    assert e.evaluate(EvalContext("s", "t", {"options": {"path": "/home/x"}})).kind == "allow"


def test_star_searches_every_string_anywhere_in_args():
    rule = {"id": "r", "match": {"args_regex": {"*": r"\.ssh/id_"}}, "decision": "deny"}
    e = _engine([rule])
    assert e.evaluate(EvalContext("s", "t", {"a": [{"b": "cat ~/.ssh/id_rsa"}]})).kind == "deny"
    assert e.evaluate(EvalContext("s", "t", {"a": [{"b": "cat notes"}]})).kind == "allow"


def test_all_regex_fields_must_match_along_with_args_equality():
    rule = {"id": "r", "match": {"args": {"force": True}, "args_regex": {"branch": "^main$"}},
            "decision": "deny"}
    e = _engine([rule])
    assert e.evaluate(EvalContext("s", "push", {"force": True, "branch": "main"})).kind == "deny"
    assert e.evaluate(EvalContext("s", "push", {"force": False, "branch": "main"})).kind == "allow"
    assert e.evaluate(EvalContext("s", "push", {"force": True, "branch": "dev"})).kind == "allow"


def test_invalid_regex_is_rejected_when_the_policy_loads():
    with pytest.raises(ValidationError, match="invalid regex"):
        Config.model_validate({"version": "0.1", "rules": [
            {"id": "bad", "match": {"args_regex": {"command": "rm ("}}, "decision": "deny"}]})
