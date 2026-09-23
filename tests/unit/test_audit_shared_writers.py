"""The tool guard and the spend proxy are separate processes writing one log."""
import multiprocessing as mp

from shugo.audit.log import AuditLog
from shugo.audit.verify import verify_log


def _entry(log, i, who):
    return log.build(
        request_id=f"{who}-{i}", server=who, tool="t", args={}, decision="allow",
        matched_rule_id="r",
    )


def test_two_writers_on_one_file_keep_one_chain(tmp_path):
    path = tmp_path / "audit.log"
    a = AuditLog(path)  # both open before either writes, so both
    b = AuditLog(path)  # start with the same (empty) chain head
    for i in range(5):
        a.append(_entry(a, i, "a"))
        b.append(_entry(b, i, "b"))
    result = verify_log(path)
    assert result.ok, result.error
    assert result.entries == 10


def _writer(path, who, n):
    log = AuditLog(path)
    for i in range(n):
        log.append(_entry(log, i, who))


def test_concurrent_processes_keep_one_chain(tmp_path):
    path = tmp_path / "audit.log"
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=_writer, args=(str(path), w, 40)) for w in ("a", "b", "c")]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    result = verify_log(path)
    assert result.ok, result.error
    assert result.entries == 120


def test_extra_fields_are_recorded_and_hashed(tmp_path):
    path = tmp_path / "audit.log"
    log = AuditLog(path)
    entry = log.build(
        request_id="r1", server="anthropic", tool="messages", args={}, decision="allow",
        matched_rule_id=None, extra={"agent_id": "bot-1", "cost_usd": 0.0123},
    )
    rec = log.append(entry)
    assert rec["agent_id"] == "bot-1" and rec["cost_usd"] == 0.0123
    assert verify_log(path).ok
    # editing an extra field must break the chain like any other field
    path.write_text(path.read_text().replace("0.0123", "0.0001"))
    assert not verify_log(path).ok
