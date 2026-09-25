"""Run the four evals and write evals/results.json + evals/RESULTS.md.

All local and free: "Claude" is a fake API. Run from the repo root:

    .venv/bin/python evals/run_evals.py
"""
from __future__ import annotations

import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import httpx
import yaml
from fastapi.testclient import TestClient

HERE = Path(__file__).parent
ROOT = HERE.parent
MODEL = "claude-haiku-4-5"  # $1 / $5 per million tokens


def fresh_home() -> Path:
    home = Path(tempfile.mkdtemp(prefix="shugo-eval-"))
    os.environ["SHUGO_HOME"] = str(home)
    return home


def message(content, usage, stop="end_turn"):
    return {"id": "msg_eval", "type": "message", "role": "assistant", "model": MODEL, "content": content,
            "stop_reason": stop, "stop_sequence": None, "usage": usage}


def proxy(handler, **cfg):
    from shugo.spend.config import SpendConfig
    from shugo.spend.server import create_app

    app = create_app(SpendConfig(upstream="https://fake.anthropic", db_path=":memory:", **cfg),
                     transport=httpx.MockTransport(handler))
    return TestClient(app)


def sdk(client: TestClient, agent: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(base_url="http://testserver", api_key="fake", http_client=client,
                               default_headers={"x-agent-id": agent}, max_retries=0)


# ---------------------------------------------------------------- 1. runaway
def runaway(budget: float, cost_of_call, worth_usd: float) -> dict:
    """An agent calls Claude in a loop until the proxy stops it (or it has made
    `worth_usd` worth of calls, i.e. what it would have spent unsupervised)."""
    fresh_home()
    n = {"calls": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        i = n["calls"]
        n["calls"] += 1
        inp, out = cost_of_call(i)
        return httpx.Response(200, json=message([{"type": "text", "text": "again"}],
                                                {"input_tokens": inp, "output_tokens": out}))

    unsupervised, i = 0.0, 0
    while unsupervised < worth_usd:
        inp, out = cost_of_call(i)
        unsupervised += (inp * 1 + out * 5) / 1e6
        i += 1
    max_calls = i

    with proxy(handler, agents={"bot": {"budget_usd": budget}}) as c:
        client, ok, stop = sdk(c, "bot"), 0, None
        for _ in range(max_calls):
            try:
                client.messages.create(model=MODEL, max_tokens=1024,
                                       messages=[{"role": "user", "content": "again"}])
                ok += 1
            except anthropic.APIStatusError as e:
                stop = f"{e.status_code} {e.type}"
                break
        spent = c.get("/spend/status").json()["agents"][0]["total_spent"]
    return {"budget_usd": budget, "unsupervised_calls": max_calls, "unsupervised_usd": round(unsupervised, 2),
            "calls_allowed": ok, "spent_usd": round(spent, 4), "stopped_by": stop,
            "overshoot_usd": round(max(0.0, spent - budget), 4)}


# --------------------------------------------------------------- 2. red team
def red_team() -> dict:
    home = fresh_home()
    cases = yaml.safe_load((HERE / "redteam.yaml").read_text())
    current: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        block = {"type": "tool_use", "id": "toolu_eval", "name": current["tool"], "input": current["input"]}
        usage = {"input_tokens": 50, "output_tokens": 20}
        if json.loads(request.content).get("stream"):
            events = [
                ("message_start", {"type": "message_start", "message": message([], {"input_tokens": 50, "output_tokens": 1}, None)}),
                ("content_block_start", {"type": "content_block_start", "index": 0,
                                         "content_block": {**block, "input": {}}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                         "delta": {"type": "input_json_delta", "partial_json": json.dumps(current["input"])}}),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                                   "usage": {"output_tokens": 20}}),
                ("message_stop", {"type": "message_stop"}),
            ]
            body = b"".join(f"event: {k}\ndata: {json.dumps(v)}\n\n".encode() for k, v in events)
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)
        return httpx.Response(200, json=message([block], usage, "tool_use"))

    from shugo.spend.config import ToolPolicy

    rows = []
    with proxy(handler, default_budget_usd=100,
               tool_policy=ToolPolicy(policy=str(HERE / "policy.yaml"))) as c:
        client = sdk(c, "red-team")
        for group, expect in (("attacks", "blocked"), ("benign", "allowed")):
            for case in cases[group]:
                current.update(case)
                for mode in ("plain", "stream"):
                    kw = dict(model=MODEL, max_tokens=256, messages=[{"role": "user", "content": "go"}])
                    if mode == "plain":
                        msg = client.messages.create(**kw)
                    else:
                        with client.messages.stream(**kw) as s:
                            msg = s.get_final_message()
                    got = "allowed" if any(b.type == "tool_use" for b in msg.content) else "blocked"
                    rows.append({"group": group, "name": case["name"], "tool": case["tool"], "mode": mode,
                                 "expected": expect, "got": got})
    decisions = [json.loads(line) for line in (home / "audit.log").read_text().splitlines()]
    rules = [d.get("matched_rule_id") or "default deny" for d in decisions if d.get("kind") == "tool_call"]
    for row, rule in zip(rows, rules):
        row["rule"] = rule

    def rate(group, outcome):
        g = [r for r in rows if r["group"] == group]
        return sum(r["got"] == outcome for r in g), len(g)

    blocked, attacks = rate("attacks", "blocked")
    false_blocks, benign = rate("benign", "blocked")
    return {"attacks_blocked": blocked, "attack_checks": attacks, "block_rate": blocked / attacks,
            "benign_blocked": false_blocks, "benign_checks": benign, "false_block_rate": false_blocks / benign,
            "cases": rows}


# ------------------------------------------------------------------ 3. tamper
def tamper() -> dict:
    from shugo.audit.log import AuditLog, _hash_entry
    from shugo.audit.verify import verify_log

    work = Path(tempfile.mkdtemp(prefix="shugo-tamper-"))
    clean = work / "clean.log"
    log = AuditLog(clean)
    for i in range(200):
        log.append(log.build(request_id=f"r{i}", server="anthropic", tool="messages", args={"model": MODEL},
                             decision="deny" if i % 7 == 0 else "allow", matched_rule_id=None,
                             extra={"agent_id": "bot", "cost_usd": 0.03}))
    anchor = log.head  # saved somewhere the attacker can't reach, e.g. in an emailed report
    original = clean.read_text().splitlines()

    def rehash(lines):
        prev, out = "0" * 64, []
        for line in lines:
            e = json.loads(line)
            e["prev_hash"] = prev
            e["this_hash"] = _hash_entry(e, prev)
            prev = e["this_hash"]
            out.append(json.dumps(e, sort_keys=True))
        return out

    def flip(line, a, b):
        assert a in line
        return line.replace(a, b, 1)

    attacks = {
        "edit a decision (deny -> allow)": lambda L: L[:98] + [flip(L[98], '"deny"', '"allow"')] + L[99:],
        "edit a cost": lambda L: L[:50] + [flip(L[50], '"cost_usd": 0.03', '"cost_usd": 0.0')] + L[51:],
        "delete an entry": lambda L: L[:120] + L[121:],
        "swap two entries": lambda L: L[:60] + [L[61], L[60]] + L[62:],
        "insert a forged entry": lambda L: L[:30] + [flip(L[30], '"r30"', '"forged"')] + L[30:],
        "cut entries off the end": lambda L: L[:-10],
        "rewrite and recompute every hash": lambda L: rehash(L[:98] + [flip(L[98], '"deny"', '"allow"')] + L[99:]),
    }
    rows = []
    for name, attack in attacks.items():
        p = work / "t.log"
        p.write_text("\n".join(attack(list(original))) + "\n")
        rows.append({"attack": name, "caught_by_chain": not verify_log(p).ok,
                     "caught_with_anchor": not verify_log(p, anchor=anchor).ok})
    clean_ok = verify_log(clean).ok and verify_log(clean, anchor=anchor).ok
    shutil.rmtree(work, ignore_errors=True)
    return {"entries": 200, "untampered_passes": clean_ok, "attacks": rows,
            "caught_by_chain": sum(r["caught_by_chain"] for r in rows),
            "caught_with_anchor": sum(r["caught_with_anchor"] for r in rows), "total": len(rows)}


# ----------------------------------------------------------------- 4. latency
def latency(n: int = 400, warmup: int = 50) -> dict:
    """Real servers on localhost: time each call direct to the fake API vs through the proxy."""
    home = fresh_home()
    cfg = home / "spend.yaml"
    cfg.write_text("upstream: http://127.0.0.1:18788\ndefault_budget_usd: 1000000\n")
    env = {**os.environ, "SHUGO_HOME": str(home)}
    env.pop("FORCE_COLOR", None)
    bin_dir = Path(sys.executable).parent
    servers = [
        subprocess.Popen([sys.executable, str(ROOT / "examples/runaway-agent/fake_anthropic.py"), "18788"], env=env),
        subprocess.Popen([str(bin_dir / "shugo"), "spend", "serve", "-c", str(cfg), "--port", "18787"],
                         env=env, stdout=subprocess.DEVNULL),
    ]
    try:
        for url in ("http://127.0.0.1:18788/docs", "http://127.0.0.1:18787/healthz"):
            for _ in range(100):
                try:
                    urllib.request.urlopen(url, timeout=0.2)
                    break
                except OSError:
                    time.sleep(0.1)
        body = {"model": MODEL, "max_tokens": 64, "messages": [{"role": "user", "content": "hi"}]}
        headers = {"x-api-key": "fake", "anthropic-version": "2023-06-01", "x-agent-id": "latency"}

        def timed(client, url, stream):
            t0 = time.perf_counter()
            if stream:
                with client.stream("POST", url, json={**body, "stream": True}, headers=headers) as r:
                    first = None
                    for _ in r.iter_raw():
                        first = first or time.perf_counter()
                end = time.perf_counter()
                return (first - t0) * 1000, (end - t0) * 1000
            client.post(url, json=body, headers=headers).raise_for_status()
            return None, (time.perf_counter() - t0) * 1000

        out = {}
        with httpx.Client() as client:
            for stream in (False, True):
                direct, via = [], []
                for i in range(warmup + n):
                    d = timed(client, "http://127.0.0.1:18788/v1/messages", stream)
                    p = timed(client, "http://127.0.0.1:18787/v1/messages", stream)
                    if i >= warmup:
                        direct.append(d)
                        via.append(p)
                idx = 0 if stream else 1  # time-to-first-byte for streams, total for plain calls

                def pct(xs, q):
                    xs = sorted(x[idx] for x in xs)
                    return xs[min(len(xs) - 1, math.ceil(q * len(xs)) - 1)]

                out["streaming_first_byte" if stream else "plain"] = {
                    "direct_p50_ms": round(pct(direct, .5), 2), "proxy_p50_ms": round(pct(via, .5), 2),
                    "direct_p95_ms": round(pct(direct, .95), 2), "proxy_p95_ms": round(pct(via, .95), 2),
                    "added_p50_ms": round(pct(via, .5) - pct(direct, .5), 2),
                    "added_p95_ms": round(pct(via, .95) - pct(direct, .95), 2),
                    "added_mean_ms": round(statistics.mean(v[idx] for v in via) - statistics.mean(d[idx] for d in direct), 2),
                }
        out["samples"] = n
        return out
    finally:
        for s in servers:
            s.terminate()
            s.wait()


# ------------------------------------------------------------------- report
def write_markdown(r: dict) -> str:
    a, b, t, lat, rt = r["runaway_steady"], r["runaway_growing"], r["tamper"], r["latency"], r["red_team"]
    tick = lambda ok: "yes" if ok else "**no**"  # noqa: E731
    L = [
        "# Eval results",
        "",
        f"Generated {r['generated']} on {r['machine']}. Reproduce with `.venv/bin/python evals/run_evals.py`.",
        "Every eval uses a fake Claude API on this machine: no real API calls, $0 spent.",
        "",
        "## Headline",
        "",
        "| Eval | Target | Result |",
        "|---|---|---|",
        f"| Runaway agent, ${a['budget_usd']:.2f} budget | stops at budget, not ${a['unsupervised_usd']:.0f} | "
        f"stopped at **${a['spent_usd']:.2f}** after {a['calls_allowed']} calls |",
        f"| Red-team tool calls blocked | 100% | **{rt['attacks_blocked']}/{rt['attack_checks']}** "
        f"({rt['block_rate']:.0%}) |",
        f"| Harmless tool calls wrongly blocked | 0% | **{rt['benign_blocked']}/{rt['benign_checks']}** "
        f"({rt['false_block_rate']:.0%}) |",
        f"| Tampering caught (hash chain only) | — | {t['caught_by_chain']}/{t['total']} |",
        f"| Tampering caught (chain + saved anchor) | all | **{t['caught_with_anchor']}/{t['total']}** |",
        f"| Latency added, plain call (p50 / p95) | < 20 ms | **{lat['plain']['added_p50_ms']} / "
        f"{lat['plain']['added_p95_ms']} ms** |",
        f"| Latency added, stream first byte (p50 / p95) | < 20 ms | **{lat['streaming_first_byte']['added_p50_ms']} / "
        f"{lat['streaming_first_byte']['added_p95_ms']} ms** |",
        "",
        "## 1. Runaway agent",
        "",
        "An agent calls Claude (Haiku 4.5 prices) in a loop through the proxy. \"Unsupervised\" is what the same "
        "loop would have spent with no proxy.",
        "",
        "| Scenario | Budget | Unsupervised | Calls allowed | Spent | Over budget by | Stopped with |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for name, x in (("Same cost every call ($0.03)", a), ("Growing conversation (each call costs more)", b)):
        L.append(f"| {name} | ${x['budget_usd']:.2f} | ${x['unsupervised_usd']:.2f} ({x['unsupervised_calls']} calls) "
                 f"| {x['calls_allowed']} | ${x['spent_usd']:.4f} | ${x['overshoot_usd']:.4f} | {x['stopped_by']} |")
    worst = max(a["overshoot_usd"], b["overshoot_usd"])
    L += ["",
          "The proxy predicts the next call's cost from the agent's previous call: exact for a repeating loop, "
          "slightly low when every call costs more than the last. So an agent can go over its budget by at most "
          "the difference between two consecutive calls (checked by `test_growing_costs_overshoot_by_at_most_one_step`). "
          + ("In these runs it didn't go over at all." if worst == 0 else f"Worst overshoot in these runs: ${worst:.4f}."),
          "",
          "## 2. Red team",
          "",
          f"{len(yaml.safe_load((HERE / 'redteam.yaml').read_text())['attacks'])} dangerous and "
          f"{len(yaml.safe_load((HERE / 'redteam.yaml').read_text())['benign'])} harmless tool calls "
          "(`evals/redteam.yaml`), each returned by the fake Claude as a `tool_use` block and sent through the "
          "proxy twice (plain and streaming), read back with the official Anthropic SDK. The policy "
          "(`evals/policy.yaml`) was written first, as an allow-list, so most attacks fall to *default deny* rather "
          "than a rule written for them. Caveat: the same person wrote the policy and the attacks.",
          "",
          "| Case | Tool | Expected | Plain | Streaming | Rule |",
          "|---|---|---|---|---|---|"]
    by_case: dict = {}
    for row in rt["cases"]:
        by_case.setdefault((row["group"], row["name"]), {})[row["mode"]] = row
    for (_group, name), modes in by_case.items():
        p, s = modes["plain"], modes["stream"]
        ok = lambda x: x["got"] + ("" if x["got"] == x["expected"] else " ✗")  # noqa: E731
        L.append(f"| {name} | {p['tool']} | {p['expected']} | {ok(p)} | {ok(s)} | {p['rule']} |")
    L += ["",
          "## 3. Tamper evidence",
          "",
          f"A {t['entries']}-entry log, attacked seven ways. The untampered log passes: {tick(t['untampered_passes'])}.",
          "",
          "| Attack | Caught by the chain | Caught with a saved anchor |",
          "|---|---|---|"]
    for row in t["attacks"]:
        L.append(f"| {row['attack']} | {tick(row['caught_by_chain'])} | {tick(row['caught_with_anchor'])} |")
    L += ["",
          "The hash chain has no secret key, so anyone who can edit the file can also recompute every hash after "
          "their edit, or simply cut entries off the end. Both slip past the chain alone. They're caught by "
          "comparing against a chain head saved somewhere else (`shugo audit verify --anchor <hash>`; every "
          "incident report prints the current head).",
          "",
          "## 4. Latency",
          "",
          f"Real servers on localhost; {lat['samples']} calls each way after warm-up, direct to the fake API vs "
          "through the proxy. Real Claude calls take seconds, so this is the whole cost of the proxy, not a fraction.",
          "",
          "| | Direct p50 | Proxy p50 | Added p50 | Direct p95 | Proxy p95 | Added p95 |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for name, key in (("Plain call (total)", "plain"), ("Streaming (first byte)", "streaming_first_byte")):
        x = lat[key]
        L.append(f"| {name} | {x['direct_p50_ms']} ms | {x['proxy_p50_ms']} ms | {x['added_p50_ms']} ms "
                 f"| {x['direct_p95_ms']} ms | {x['proxy_p95_ms']} ms | {x['added_p95_ms']} ms |")
    return "\n".join(L) + "\n"


def main() -> None:
    os.environ.pop("FORCE_COLOR", None)
    print("1/4 runaway…", flush=True)
    steady = runaway(0.50, lambda i: (20_000, 2_000), worth_usd=50)            # $0.03 per call
    growing = runaway(0.50, lambda i: (5_000 + 2_000 * i, 500), worth_usd=50)  # +$0.002 per call
    print("2/4 red team…", flush=True)
    rt = red_team()
    print("3/4 tamper…", flush=True)
    tp = tamper()
    print("4/4 latency…", flush=True)
    lat = latency()
    results = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "machine": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "runaway_steady": steady, "runaway_growing": growing, "red_team": rt, "tamper": tp, "latency": lat,
    }
    (HERE / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    (HERE / "RESULTS.md").write_text(write_markdown(results))
    print((HERE / "RESULTS.md").read_text().split("## 1.")[0])


if __name__ == "__main__":
    main()
