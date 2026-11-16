"""CLI: `run` downloads, `catalog` builds the DuckDB file, `sql` queries it, `list` sources."""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path
from typing import Annotated

import duckdb
import structlog
import typer

from teramot_signals.core.catalog import build_catalog
from teramot_signals.core.config import load_settings
from teramot_signals.core.extraction import Window
from teramot_signals.core.pipeline import exit_code, run_source
from teramot_signals.core.registry import available_sources

app = typer.Typer(no_args_is_help=True, add_completion=False)


def _configure_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), stream=sys.stderr, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        logger_factory=structlog.PrintLoggerFactory(sys.stderr),
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
    )


@app.command("list")
def list_sources(config_dir: Annotated[Path, typer.Option()] = Path("config")) -> None:
    for s in available_sources(config_dir):
        typer.echo(s)


@app.command()
def run(
    sources: Annotated[
        list[str], typer.Argument(help="One or more sources (config/sources/<s>.yaml)")
    ],
    dataset: Annotated[
        list[str] | None, typer.Option("--dataset", "-d", help="Only these datasets")
    ] = None,
    since: Annotated[str | None, typer.Option(help="YYYY-MM-DD")] = None,
    until: Annotated[str | None, typer.Option(help="YYYY-MM-DD")] = None,
    config_dir: Annotated[Path, typer.Option()] = Path("config"),
    output: Annotated[str | None, typer.Option(help="Local path or s3://bucket/prefix")] = None,
    log_level: Annotated[str, typer.Option()] = "INFO",
) -> None:
    _configure_logging(log_level)
    settings = load_settings(config_dir, output)
    window = Window(
        since=date.fromisoformat(since) if since else None,
        until=date.fromisoformat(until) if until else None,
    )
    results = []
    for s in sources:
        results.extend(run_source(settings, s, datasets=dataset, window=window))
    for r in results:
        detail = (
            r.error
            or "; ".join(r.format_diff)
            or f"{r.rows_written} rows, {len(r.revisions)} revisions"
        )
        typer.echo(f"{r.source}.{r.dataset}\t{r.status}\t{detail}")
    raise typer.Exit(code=exit_code(results))


@app.command()
def catalog(
    db: Annotated[str, typer.Option(help="DuckDB file to (re)create")] = "signals.duckdb",
    marts: Annotated[Path, typer.Option(help="SQL marts folder")] = Path("sql/marts"),
    config_dir: Annotated[Path, typer.Option()] = Path("config"),
    output: Annotated[str | None, typer.Option(help="Local path or remote URI")] = None,
) -> None:
    """DuckDB views over the written Parquet: dataset, `__latest`, contracts and marts."""
    settings = load_settings(config_dir, output)
    res = build_catalog(settings, db, marts if marts.exists() else None)
    typer.echo(f"{db}: {len(res.views)} views, marts: {', '.join(res.marts) or '-'}")
    for s in res.skipped:
        typer.echo(f"  skipped: {s}", err=True)


@app.command()
def sql(
    query: Annotated[str, typer.Argument(help="SQL (DuckDB) over the catalog")],
    db: Annotated[str, typer.Option()] = "signals.duckdb",
    limit: Annotated[int, typer.Option(help="Rows to show")] = 50,
) -> None:
    """Queries the catalog. E.g.: sql "select * from argentina_pulse where section = 'fx'"."""
    con = duckdb.connect(db, read_only=True)
    try:
        con.sql(query).show(max_rows=limit, max_width=200)
    finally:
        con.close()
