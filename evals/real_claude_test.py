"""The one real-money test: a runaway agent on real Claude Haiku 4.5, through the proxy.

Proves the budget stop works against the real Anthropic API, not just a fake.
Safety, independent of the proxy being tested:
  * at most MAX_CALLS calls, each with max_tokens = MAX_OUT
  * this script keeps its own running cost from the real `usage` of every reply
    and stops before the total could pass HARD_CAP_USD, whatever the proxy does
  * the API key is read from .env (or the environment) and never printed

    .venv/bin/python evals/real_claude_test.py --fake   # rehearsal, $0
    .venv/bin/python evals/real_claude_test.py          # real, <= $0.30
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import httpx
from fastapi.testclient import TestClient

HERE = Path(__file__).parent
MODEL = "claude-haiku-4-5"
IN_PRICE, OUT_PRICE = 1.00 / 1e6, 5.00 / 1e6    # Haiku 4.5, USD per token
AGENT_BUDGET_USD = 0.10                         # what the proxy should stop the agent at
HARD_CAP_USD = 0.30                             # what this script will never let it pass
MAX_CALLS = 20
MAX_OUT = 300
# ~26k characters: roughly 10-15k tokens (~$0.01-0.02) a call, so the agent reaches its
# $0.10 budget in a handful of calls.
PROMPT = ("Summarize this log in one sentence.\n\n"
          + "\n".join(f"2026-09-25T00:{i // 60:02d}:{i % 60:02d}Z agent=runaway-bot action=retry "
                      f"status=failed attempt={i} reason=tests still failing" for i in range(250)))


def api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    env = HERE.parent / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        sys.exit("No ANTHROPIC_API_KEY in the environment or .env")
    return key


def fake_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        tokens_in = len(json.dumps(body["messages"])) // 4
        return httpx.Response(200, json={
            "id": "msg_fake", "type": "message", "role": "assistant", "model": MODEL,
            "content": [{"type": "text", "text": "Tests keep failing."}], "stop_reason": "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": tokens_in, "output_tokens": 12}})
    return httpx.MockTransport(handler)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake", action="store_true", help="rehearse against a fake Claude ($0)")
    args = ap.parse_args()
    os.environ["SHUGO_HOME"] = tempfile.mkdtemp(prefix="shugo-real-test-")
    os.environ.pop("FORCE_COLOR", None)
    from shugo.audit.verify import verify_log
    from shugo.spend.config import SpendConfig
    from shugo.spend.server import create_app

    cfg = SpendConfig(agents={"runaway-bot": {"budget_usd": AGENT_BUDGET_USD}}, db_path=":memory:")
    app = create_app(cfg, transport=fake_transport() if args.fake else None)
    # Hard upper bound per call: plain ASCII text is never more than one token per byte.
    worst_call = len(PROMPT.encode()) * IN_PRICE + MAX_OUT * OUT_PRICE

    calls, total, stop = [], 0.0, None
    with TestClient(app) as proxy:
        client = anthropic.Anthropic(base_url="http://testserver", http_client=proxy, max_retries=0,
                                     api_key="fake" if args.fake else api_key(),
                                     default_headers={"x-agent-id": "runaway-bot"})
        for n in range(1, MAX_CALLS + 1):
            if total + worst_call > HARD_CAP_USD:
                stop = f"script safety cap: next call could pass ${HARD_CAP_USD:.2f}"
                break
            try:
                msg = client.messages.create(model=MODEL, max_tokens=MAX_OUT,
                                             messages=[{"role": "user", "content": PROMPT}])
            except anthropic.APIStatusError as e:
                stop = f"proxy: {e.status_code} {e.type}: {e.body['error']['message']}"
                break
            cost = msg.usage.input_tokens * IN_PRICE + msg.usage.output_tokens * OUT_PRICE
            total += cost
            calls.append({"call": n, "input_tokens": msg.usage.input_tokens,
                          "output_tokens": msg.usage.output_tokens, "cost_usd": round(cost, 5)})
            print(f"call {n}: {msg.usage.input_tokens:,} in / {msg.usage.output_tokens} out = ${cost:.4f}"
                  f"  (total ${total:.4f})", flush=True)
        ledger = proxy.get("/spend/status").json()["agents"][0]["total_spent"]
    chain = verify_log(Path(os.environ["SHUGO_HOME"]) / "audit.log")

    result = {
        "mode": "fake (rehearsal)" if args.fake else "real Anthropic API",
        "ran_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "model": MODEL,
        "agent_budget_usd": AGENT_BUDGET_USD, "hard_cap_usd": HARD_CAP_USD,
        "calls_allowed": len(calls), "script_total_usd": round(total, 5),
        "proxy_ledger_usd": round(ledger, 5), "stopped_by": stop,
        "audit_log_ok": chain.ok, "audit_entries": chain.entries, "calls": calls,
    }
    print(json.dumps({k: v for k, v in result.items() if k != "calls"}, indent=2))
    if not args.fake:
        (HERE / "real_test_result.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
