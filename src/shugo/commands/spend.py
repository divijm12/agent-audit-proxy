from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from shugo.spend.budget import BudgetStore
from shugo.spend.config import SpendConfig, load_spend_config


def _config(path: Path, console: Console) -> SpendConfig:
    if not path.exists():
        console.print(f"[dim]no {path}; using defaults (upstream api.anthropic.com, $1.00/agent)[/dim]")
        return SpendConfig()
    return load_spend_config(path)


LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def refuse_open_internet(host: str, no_login: bool, console: Console) -> None:
    """Listening beyond this machine with no password would let anyone press STOP."""
    from shugo.spend.auth import PASSWORD_ENV, protection

    if host in LOOPBACK or no_login or protection()[0]:
        return
    console.print(
        f"[red]refusing to listen on {host} without a dashboard password.[/red]\n"
        f"Set {PASSWORD_ENV} (and ideally SHUGO_AGENT_TOKEN), or pass --no-login if this "
        "network is already private."
    )
    raise typer.Exit(code=2)


def run_serve(config: Path, host: str, port: int, console: Console, no_login: bool = False) -> None:
    import uvicorn

    from shugo.spend.server import create_app

    refuse_open_internet(host, no_login, console)
    cfg = _config(config, console)
    console.print(
        f"spend proxy on [bold]http://{host}:{port}[/bold] -> {cfg.upstream}\n"
        f"point agents at it:  ANTHROPIC_BASE_URL=http://{host}:{port}  (name them with an x-agent-id header)"
    )
    uvicorn.run(create_app(cfg), host=host, port=port, log_level="warning")


def _store(cfg: SpendConfig) -> BudgetStore:
    return BudgetStore(
        cfg.ledger_path(),
        default_limit=cfg.default_budget_usd,
        limits={a: b.budget_usd for a, b in cfg.agents.items()},
    )


def run_status(config: Path, console: Console) -> None:
    cfg = _config(config, console)
    rows = _store(cfg).status()
    if not rows:
        console.print("[dim]no agents have made calls yet[/dim]")
        return
    table = Table("agent", "spent", "limit", "used", "left")
    for r in rows:
        spent, limit = float(r["total_spent"]), float(r["budget_limit"])
        used = spent / limit if limit else 1.0
        left = "[red]none - blocked[/red]" if spent >= limit else f"${limit - spent:.4f}"
        table.add_row(str(r["agent_id"]), f"${spent:.4f}", f"${limit:.2f}", f"{used:.0%}", left)
    console.print(table)


def run_reset(agent_id: str, config: Path, console: Console) -> None:
    cfg = _config(config, console)
    _store(cfg).reset(agent_id)
    console.print(f"reset spend for [bold]{agent_id}[/bold] to $0")
    raise typer.Exit(code=0)
