"""Start the fake API and the spend proxy, run the runaway agent, show the result.

Run from the repo root:  .venv/bin/python examples/runaway-agent/run_demo.py [--stream]
"""
import functools
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

print = functools.partial(print, flush=True)  # keep our headings in order with child output
HERE = Path(__file__).parent
HOME = HERE / ".shugo-home"
BIN = Path(sys.executable).parent
env = {**os.environ, "SHUGO_HOME": str(HOME), "NO_COLOR": "1"}
env.pop("FORCE_COLOR", None)


def wait_for(url: str) -> None:
    for _ in range(100):
        try:
            urllib.request.urlopen(url, timeout=0.2)
            return
        except OSError:
            time.sleep(0.1)
    sys.exit(f"timed out waiting for {url}")


# A plain `kill` should still shut the servers down (via the finally below).
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
shutil.rmtree(HOME, ignore_errors=True)  # fresh ledger + audit log each run
servers = [
    subprocess.Popen([sys.executable, str(HERE / "fake_anthropic.py"), "8788"], env=env),
    subprocess.Popen([str(BIN / "shugo"), "spend", "serve", "-c", str(HERE / "spend.yaml")],
                     env=env, stdout=subprocess.DEVNULL),
]
try:
    wait_for("http://127.0.0.1:8788/docs")
    wait_for("http://127.0.0.1:8787/healthz")
    print("== runaway agent (budget $0.10, each call costs $0.03) ==")
    subprocess.run([sys.executable, str(HERE / "runaway_agent.py"), *sys.argv[1:]], env=env)
    print("\n== shugo spend status ==")
    subprocess.run([str(BIN / "shugo"), "spend", "status", "-c", str(HERE / "spend.yaml")], env=env)
    print("== shugo audit tail ==")
    subprocess.run([str(BIN / "shugo"), "audit", "tail", "-n", "10"], env=env)
    print("== shugo audit verify ==")
    subprocess.run([str(BIN / "shugo"), "audit", "verify"], env=env)
finally:
    for s in servers:
        s.terminate()
        s.wait()
