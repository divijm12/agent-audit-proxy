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


def run_serve(config: Path, host: str, port: int, console: Console) -> None:
    import uvicorn

    from shugo.spend.server import create_app

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
    table = Table("agent", "spent", "limit", "used", "state")
    for r in rows:
        spent, limit = float(r["total_spent"]), float(r["budget_limit"])
        used = spent / limit if limit else 1.0
        state = "[red]blocked[/red]" if spent >= limit else "[green]ok[/green]"
        table.add_row(str(r["agent_id"]), f"${spent:.4f}", f"${limit:.2f}", f"{used:.0%}", state)
    console.print(table)


def run_reset(agent_id: str, config: Path, console: Console) -> None:
    cfg = _config(config, console)
    _store(cfg).reset(agent_id)
    console.print(f"reset spend for [bold]{agent_id}[/bold] to $0")
    raise typer.Exit(code=0)
