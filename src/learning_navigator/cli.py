"""CLI entry point for Learning Navigator.

Uses Typer for a clean, typed command-line interface.

Commands:
- ``run``      — Start the REST API server
- ``evaluate`` — Run the evaluation harness
"""

from __future__ import annotations

import typer

from learning_navigator import __version__
from learning_navigator.infra.config import get_settings
from learning_navigator.infra.logging import setup_logging

app = typer.Typer(
    name="learning-nav",
    help="Learning Navigator AI — Multi-Agent Learning GPS",
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(False, "--version", "-v", help="Show version and exit."),
) -> None:
    """Learning Navigator CLI."""
    if version:
        typer.echo(f"learning-navigator {__version__}")
        raise typer.Exit()


@app.command()
def run(
    log_level: str = typer.Option("INFO", help="Log level (DEBUG, INFO, WARNING, ERROR)"),
    log_format: str = typer.Option("console", help="Log format (json, console)"),
    host: str = typer.Option("127.0.0.1", help="Server bind address"),
    port: int = typer.Option(8000, help="Server port"),
    reload: bool = typer.Option(False, help="Enable auto-reload for development"),
) -> None:
    """Start the Learning Navigator API server."""
    import uvicorn

    settings = get_settings(log_level=log_level, log_format=log_format)
    setup_logging(log_level=settings.log_level, log_format=settings.log_format)

    typer.echo(f"Starting Learning Navigator ({settings.environment.value}) on {host}:{port} ...")
    uvicorn.run(
        "learning_navigator.api.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level.lower(),
    )


@app.command()
def evaluate(
    tag: str = typer.Option("", help="Only run scenarios matching this tag (e.g. 'core', 'safety')"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON instead of text"),
    log_level: str = typer.Option("WARNING", help="Log level (DEBUG, INFO, WARNING, ERROR)"),
    adaptive_routing: bool = typer.Option(False, help="Enable adaptive routing during eval"),
) -> None:
    """Run the evaluation harness against built-in scenarios."""
    import asyncio
    import json

    from learning_navigator.evaluation.harness import EvaluationHarness
    from learning_navigator.evaluation.scenarios import get_all_scenarios, get_scenarios_by_tag

    setup_logging(log_level=log_level, log_format="console")

    scenarios = get_scenarios_by_tag(tag) if tag else get_all_scenarios()
    if not scenarios:
        typer.echo(f"No scenarios matching tag '{tag}'", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Running {len(scenarios)} evaluation scenario(s) ...")

    harness = EvaluationHarness(
        scenarios=scenarios,
        adaptive_routing_enabled=adaptive_routing,
    )
    result = asyncio.run(harness.run_all())

    if json_output:
        typer.echo(json.dumps(result.to_dict(), indent=2))
    else:
        typer.echo(result.summary())

    raise typer.Exit(code=0 if result.all_passed else 1)


if __name__ == "__main__":
    app()
