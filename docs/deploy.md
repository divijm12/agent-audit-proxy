# Deploying

Two ways to run this online. Start with the demo.

## 1. Live demo (free, safe to share)

`shugo spend demo` runs the proxy with a **fake Claude** and three agents that
never stop, all in one process. No API key, no real money, nothing private.
Visitors can press STOP / RESUME and export a report; everything resets every
5 minutes. This is what the `Dockerfile` runs by default.

On your machine first:

```bash
.venv/bin/shugo spend demo        # http://127.0.0.1:8787/dashboard
```

On [Fly.io](https://fly.io) (you need an account; Fly may ask for a card):

```bash
brew install flyctl
fly auth login                          # opens a browser, you log in
# edit fly.toml: set `app` to a name that isn't taken, e.g. agent-audit-proxy-<you>
fly apps create <that-name>
fly deploy                              # builds the Dockerfile on Fly's servers
fly open /dashboard
```

`fly.toml` stops the machine when nobody's visiting (`min_machines_running = 0`),
so it costs close to nothing; the first visit after a pause takes a few seconds to
wake it.

## 2. The real proxy (your agents, real Claude)

Only do this when you mean it: agents' real API keys pass through this server.

1. **A volume** so the spend ledger and audit log survive restarts:
   `fly volumes create shugo_data --size 1`, then in `fly.toml`:
   ```toml
   [[mounts]]
     source = "shugo_data"
     destination = "/data"

   [env]
     SHUGO_HOME = "/data"

   # Replace the image's default command (the demo) with the real proxy.
   [experimental]
     cmd = ["shugo", "spend", "serve", "-c", "/data/spend.yaml", "--host", "0.0.0.0", "--port", "8080"]
   ```
   (Syntax per Fly's [configuration reference](https://docs.fly.io/reference/configuration/).)
2. **Secrets** (never in a file):
   ```bash
   fly secrets set SHUGO_DASHBOARD_PASSWORD='<long random password>' \
                   SHUGO_AGENT_TOKEN='<another long random value>'
   ```
   `shugo spend serve` refuses to listen publicly without the password.
3. **Config**: copy your `spend.yaml` (and `guardrails.yaml`, if you use
   `tool_policy`) onto the volume, e.g. with `fly ssh sftp shell`.
4. **Agents** point at it and send the token:
   ```bash
   export ANTHROPIC_BASE_URL=https://<your-app>.fly.dev
   export ANTHROPIC_CUSTOM_HEADERS=$'x-agent-id: my-bot\nx-shugo-token: <token>'   # Claude Code
   ```
   With the Python SDK: `default_headers={"x-agent-id": "my-bot", "x-shugo-token": "<token>"}`.

The dashboard asks for the password (any username). One machine only: the spend
ledger is SQLite on the volume, so don't scale this to several machines.
