"""CLI entry point for Learning Navigator.

Uses Typer for a clean, typed command-line interface.
Actual commands will be added in later phases.
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
) -> None:
    """Start the Learning Navigator API server."""
    settings = get_settings(log_level=log_level, log_format=log_format)
    setup_logging(log_level=settings.log_level, log_format=settings.log_format)

    typer.echo(f"Starting Learning Navigator ({settings.environment.value}) ...")
    # TODO(phase3): Launch FastAPI via uvicorn here
    typer.echo("Server not yet implemented — see Phase 3.")


if __name__ == "__main__":
    app()
