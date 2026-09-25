"""Start the fake API + spend proxy, open the dashboard, and run two agents.

Run from the repo root:  .venv/bin/python examples/dashboard/run_demo.py
Then click STOP in the browser and watch the agents get blocked. Ctrl+C to quit.
"""
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).parent
HOME = HERE / ".shugo-home"
BIN = Path(sys.executable).parent
URL = "http://127.0.0.1:8787/dashboard"
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
shutil.rmtree(HOME, ignore_errors=True)
servers = [
    subprocess.Popen([sys.executable, str(HERE.parent / "runaway-agent" / "fake_anthropic.py"), "8788"], env=env),
    subprocess.Popen([str(BIN / "shugo"), "spend", "serve", "-c", str(HERE / "spend.yaml")],
                     env=env, stdout=subprocess.DEVNULL),
]
try:
    wait_for("http://127.0.0.1:8788/docs")
    wait_for("http://127.0.0.1:8787/healthz")
    print(f"Dashboard: {URL}  (click STOP / RESUME; Ctrl+C here to quit)", flush=True)
    if "--no-browser" not in sys.argv:
        webbrowser.open(URL)
    passthrough = [a for a in sys.argv[1:] if a != "--no-browser"]
    subprocess.run([sys.executable, str(HERE / "agents.py"), *passthrough], env=env)
except KeyboardInterrupt:
    pass
finally:
    for s in servers:
        s.terminate()
        s.wait()
