"""An agent stuck in a loop, calling Claude over and over through the spend proxy.

Uses the official Anthropic SDK exactly as a real agent would; the only
change is base_url, which points at the proxy instead of api.anthropic.com.
"""
import argparse

import anthropic

parser = argparse.ArgumentParser()
parser.add_argument("--proxy", default="http://127.0.0.1:8787")
parser.add_argument("--agent", default="runaway-bot")
parser.add_argument("--stream", action="store_true", help="use streaming calls")
parser.add_argument("--max-calls", type=int, default=50)
args = parser.parse_args()

client = anthropic.Anthropic(
    base_url=args.proxy,
    api_key="fake-key-for-local-demo",  # the fake upstream ignores it
    default_headers={"x-agent-id": args.agent},
    max_retries=0,
)

for call in range(1, args.max_calls + 1):
    try:
        if args.stream:
            with client.messages.stream(
                model="claude-haiku-4-5", max_tokens=1024,
                messages=[{"role": "user", "content": "Do the task again."}],
            ) as stream:
                msg = stream.get_final_message()
        else:
            msg = client.messages.create(
                model="claude-haiku-4-5", max_tokens=1024,
                messages=[{"role": "user", "content": "Do the task again."}],
            )
        print(f"call {call:>2}: ok  ({msg.usage.input_tokens:,} in / {msg.usage.output_tokens:,} out tokens)")
    except anthropic.APIStatusError as e:
        print(f"call {call:>2}: BLOCKED ({e.status_code} {e.type}): {e.message}")
        break
