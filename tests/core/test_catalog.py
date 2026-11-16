"""DuckDB catalog: full history, `__latest` without duplicates, empty views and marts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb
import httpx
import respx

from teramot_signals.core.catalog import build_catalog
from teramot_signals.core.config import Settings
from teramot_signals.core.pipeline import run_source
from teramot_signals.core.sink import Sink
from tests.conftest import fast_client

ADS = "https://api.argentinadatos.com"
MARTS = Path(__file__).resolve().parents[2] / "sql" / "marts"


def _mock(name: str) -> None:
    respx.get(url__regex=rf"{ADS}/v1/feriados/\d{{4}}").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"fecha": "2026-01-01", "tipo": "inamovible", "nombre": "Año nuevo"},
                {"fecha": "2026-05-25", "tipo": "inamovible", "nombre": name},
            ],
        )
    )
    respx.get(url__regex=rf"{ADS}/v1/feriados-bancarios/\d{{4}}").mock(
        return_value=httpx.Response(200, json=[{"fecha": "2026-01-01", "nombre": "Año nuevo"}])
    )


@respx.mock
def test_latest_view_has_one_row_per_key_and_marts_build_with_missing_sources(
    settings: Settings, sink: Sink, now: datetime, next_day: datetime, tmp_path: Path
) -> None:
    _mock("Revolución de Mayo")
    run_source(settings, "argentinadatos", now=now, sink=sink, client=fast_client(ADS))
    _mock("Día de la Revolución de Mayo")  # changes the natural key (fecha, nombre)
    run_source(settings, "argentinadatos", now=next_day, sink=sink, client=fast_client(ADS))
    run_source(settings, "argentinadatos", now=next_day, sink=sink, client=fast_client(ADS))

    db = str(tmp_path / "c.duckdb")
    res = build_catalog(settings, db, MARTS)
    assert "argentinadatos__holidays__latest" in res.views
    assert res.marts == ["argentina_pulse"]
    assert any(s.startswith("bcra.monetary_series") for s in res.skipped)

    con = duckdb.connect(db, read_only=True)
    try:
        hist = con.execute("select count(*) from argentinadatos__holidays").fetchone()
        assert hist == (4 * 3,)  # 2 years x 2 holidays x 3 runs, nothing overwritten
        latest = con.execute(
            "select nombre, extraction_date from argentinadatos__holidays__latest "
            "where year = 2026 order by fecha, nombre"
        ).fetchall()
        assert [r[0] for r in latest] == [
            "Año nuevo",
            "Día de la Revolución de Mayo",
            "Revolución de Mayo",
        ]
        assert latest[0][1] == next_day.date()
        dupes = con.execute(
            "select count(*) from (select fecha, nombre from argentinadatos__holidays__latest "
            "group by all having count(*) > 1)"
        ).fetchone()
        assert dupes == (0,)
        assert con.execute("select count(*) from bcra__monetary_series__latest").fetchone() == (0,)
        assert con.execute(
            "select count(*) from argentina_pulse where section <> 'meta'"
        ).fetchone() == (0,)
        statuses = con.execute(
            "select distinct status from signals__contracts where source = 'argentinadatos'"
        ).fetchall()
        assert {s for (s,) in statuses} <= {"ok", "revised"} and statuses
    finally:
        con.close()
