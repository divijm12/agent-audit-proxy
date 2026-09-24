from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from shugo import __version__

app = typer.Typer(
    name="shugo",
    help="SHUGO — MCP guardrails proxy. Policy-first, human approvals, hash-chained audit.",
    no_args_is_help=True,
    add_completion=False,
)

audit_app = typer.Typer(help="Inspect and verify the audit log.", no_args_is_help=True)
app.add_typer(audit_app, name="audit")

spend_app = typer.Typer(help="Spend proxy: per-agent budgets for Anthropic API calls.", no_args_is_help=True)
app.add_typer(spend_app, name="spend")

console = Console()


def _not_implemented(name: str) -> None:
    console.print(f"[yellow]shugo {name}[/yellow]: not implemented yet (v0.1 in development)")
    raise typer.Exit(code=2)


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-V", help="Show version and exit."),
) -> None:
    if version:
        console.print(f"shugo {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command()
def serve(
    config: Path = typer.Option(Path("guardrails.yaml"), "--config", "-c", help="Path to guardrails.yaml"),
    approvals: str = typer.Option("file", "--approvals", help="Approval channel: file, http, or both"),
    approvals_port: int = typer.Option(6247, "--approvals-port", help="Port for HTTP approval UI"),
) -> None:
    """Run the guard proxy over stdio."""
    from shugo.commands import serve as _cmd

    _cmd.run(config=config, console=console, approvals=approvals, approvals_port=approvals_port)


@app.command(name="init")
def init_cmd(
    from_: Optional[Path] = typer.Option(None, "--from", help="Path to existing MCP client config"),
    out: Path = typer.Option(Path("guardrails.yaml"), "--out", "-o", help="Output policy path"),
    skip_enumerate: bool = typer.Option(
        False, "--skip-enumerate", help="Don't spawn upstreams to enumerate tools"
    ),
) -> None:
    """Scaffold guardrails.yaml from installed MCP servers."""
    from shugo.commands import init as _cmd

    _cmd.run(from_=from_, out=out, console=console, enumerate_upstreams=not skip_enumerate)


@app.command()
def validate(
    config: Path = typer.Option(Path("guardrails.yaml"), "--config", "-c"),
) -> None:
    """Lint and schema-check the policy file."""
    from shugo.commands import validate as _cmd

    _cmd.run(config, console)


@app.command()
def explain(
    server: str = typer.Option(..., "--server", "-s"),
    tool: str = typer.Option(..., "--tool", "-t"),
    args: Optional[str] = typer.Option(None, "--args", "-a", help="JSON-encoded tool args"),
    config: Path = typer.Option(Path("guardrails.yaml"), "--config", "-c"),
) -> None:
    """Dry-run a call — show which rule fires and why."""
    from shugo.commands import explain as _cmd

    _cmd.run(server=server, tool=tool, args_json=args, config=config, console=console)


@audit_app.command("tail")
def audit_tail(
    follow: bool = typer.Option(False, "-f", "--follow"),
    n: int = typer.Option(20, "-n", help="Number of entries to show"),
) -> None:
    """Show recent audit log entries."""
    from shugo.commands import audit as _cmd

    _cmd.run_tail(n=n, follow=follow, console=console)


@audit_app.command("report")
def audit_report(
    hours: int = typer.Option(72, "--hours", "-H", help="How far back to report"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Write to a file instead of stdout"),
) -> None:
    """Incident report (markdown) for the last N hours, with a hash-chain check."""
    from shugo import paths
    from shugo.audit.report import export_incident_report

    text = export_incident_report(paths.audit_log(), hours=hours)
    if out is None:
        typer.echo(text)
    else:
        out.write_text(text, encoding="utf-8")
        console.print(f"wrote {out}")


@audit_app.command("verify")
def audit_verify(
    anchor: Optional[str] = typer.Option(
        None, "--anchor", help="A chain head saved earlier; fails if it's no longer in the chain"
    ),
) -> None:
    """Verify the audit log hash chain."""
    from shugo.commands import audit as _cmd

    _cmd.run_verify(console=console, anchor=anchor)


_SPEND_CONFIG = typer.Option(Path("spend.yaml"), "--config", "-c", help="Path to spend.yaml")


@spend_app.command("serve")
def spend_serve(
    config: Path = _SPEND_CONFIG,
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8787, "--port", "-p"),
) -> None:
    """Run the spend proxy in front of the Anthropic API."""
    from shugo.commands import spend as _cmd

    _cmd.run_serve(config=config, host=host, port=port, console=console)


@spend_app.command("status")
def spend_status(config: Path = _SPEND_CONFIG) -> None:
    """Show each agent's spend against its budget."""
    from shugo.commands import spend as _cmd

    _cmd.run_status(config=config, console=console)


@spend_app.command("reset")
def spend_reset(
    agent_id: str = typer.Argument(..., help="Agent to reset to $0"),
    config: Path = _SPEND_CONFIG,
) -> None:
    """Zero an agent's recorded spend."""
    from shugo.commands import spend as _cmd

    _cmd.run_reset(agent_id=agent_id, config=config, console=console)


@app.command()
def evidence(
    framework: str = typer.Option(..., "--framework", "-f"),
    since: str = typer.Option("30d", "--since", "-s"),
    out: Path = typer.Option(Path("evidence"), "--out", "-o"),
    config: Path = typer.Option(Path("guardrails.yaml"), "--config", "-c"),
) -> None:
    """Generate a framework-mapped evidence bundle from the audit log."""
    from shugo.commands import evidence as _cmd

    _cmd.run(framework=framework, since=since, out=out, config=config, console=console)


@app.command()
def approve(
    approval_id: Optional[str] = typer.Argument(None, help="Pending approval id"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Interactive TUI over pending approvals"),
    note: Optional[str] = typer.Option(None, "--note", help="Optional note on the decision"),
) -> None:
    """Approve a pending call, or run the watch TUI."""
    from shugo.commands import approve as _cmd

    _cmd.run_approve(approval_id=approval_id, watch=watch, note=note, console=console)


@app.command()
def deny(
    approval_id: str = typer.Argument(..., help="Pending approval id"),
    note: Optional[str] = typer.Option(None, "--note", help="Optional note on the decision"),
) -> None:
    """Deny a pending call."""
    from shugo.commands import approve as _cmd

    _cmd.run_deny(approval_id=approval_id, note=note, console=console)


@app.command()
def halt() -> None:
    """Kill switch — deny all subsequent calls until unhalted."""
    from shugo.commands import halt as _cmd

    _cmd.run_halt(console)


@app.command()
def unhalt() -> None:
    """Clear the halt sentinel."""
    from shugo.commands import halt as _cmd

    _cmd.run_unhalt(console)


if __name__ == "__main__":
    app()
