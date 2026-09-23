from __future__ import annotations

from rich.console import Console

from shugo import killswitch, paths


def run_halt(console: Console) -> int:
    if not killswitch.halt(by="cli"):
        console.print(f"[dim]already halted ({paths.halt_sentinel()})[/dim]")
        return 0
    console.print(f"[red]HALT[/red] set at {paths.halt_sentinel()} — all calls will be denied")
    return 0


def run_unhalt(console: Console) -> int:
    if killswitch.resume(by="cli"):
        console.print(f"[green]cleared[/green] {paths.halt_sentinel()}")
    else:
        console.print(f"[dim]no halt sentinel at {paths.halt_sentinel()}[/dim]")
    return 0
