"""Agents that keep calling Claude through the proxy, once a second each.

Unlike the runaway-agent example they don't give up when refused, so you can watch
STOP block them and RESUME let them continue.
"""
import argparse
import threading
import time

import anthropic

parser = argparse.ArgumentParser()
parser.add_argument("--proxy", default="http://127.0.0.1:8787")
parser.add_argument("--seconds", type=float, default=0, help="stop after N seconds (0 = until Ctrl+C)")
parser.add_argument("--interval", type=float, default=1.0)
args = parser.parse_args()
stop = threading.Event()


def agent(name: str) -> None:
    client = anthropic.Anthropic(base_url=args.proxy, api_key="fake-key-for-local-demo",
                                 default_headers={"x-agent-id": name}, max_retries=0)
    while not stop.is_set():
        try:
            client.messages.create(model="claude-haiku-4-5", max_tokens=1024,
                                   messages=[{"role": "user", "content": "Keep going."}])
            print(f"{name:>12}: ok", flush=True)
        except anthropic.APIStatusError as e:
            print(f"{name:>12}: BLOCKED ({e.status_code}) {e.body['error']['message']}", flush=True)
        stop.wait(args.interval)


threads = [threading.Thread(target=agent, args=(n,), daemon=True) for n in ("research-bot", "runaway-bot")]
for t in threads:
    t.start()
try:
    if args.seconds:
        time.sleep(args.seconds)
    else:
        while True:
            time.sleep(1)
except KeyboardInterrupt:
    pass
stop.set()
