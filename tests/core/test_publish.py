"""Public copy: allowlist, CUIT redaction, CSV escaping, checks, catalog and DuckDB file."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import polars as pl

from teramot_signals.core.config import Settings
from teramot_signals.core.normalization import finalize
from teramot_signals.core.publish import publish
from teramot_signals.core.sink import Sink

MARTS = Path(__file__).resolve().parents[2] / "sql" / "marts"
URL = "https://data.example.org/signals/v1"


def _write(sink: Sink, source: str, dataset: str, df: pl.DataFrame, at: datetime) -> None:
    df = finalize(
        df,
        source=source,
        dataset=dataset,
        extraction_date=at.date(),
        extracted_at=at,
        provenance="official",
    )
    sink.write_partition(df, source, dataset, at.date(), {"source": source})


def _fx(sink: Sink, at: datetime, last_usd: float) -> None:
    df = pl.DataFrame(
        {
            "variable": ["USD.rate", "USD.rate", "EUR.rate", "EUR.rate"],
            "ref_date": [date(2026, 9, 10), date(2026, 9, 11)] * 2,
            "value": [1400.0, last_usd, 1600.0, 1610.0],
        }
    )
    _write(sink, "bcra", "fx_history", df, at)


def _pumps(sink: Sink, at: datetime) -> None:
    base = {
        "indice_tiempo": ["2026-09", "2026-09", "2026-09"],
        "idempresa": [1.0, 2.0, 3.0],
        "cuit": ["20-12345678-9", "30-71234567-8", "27123456781"],
        "empresa": ["PEREZ JUAN", '=HYPERLINK("x")', "GOMEZ ANA"],
        "direccion": ["Calle 1", "Ruta 2 km 3", "Av 4"],
        "localidad": ["A", "B", "C"],
        "provincia": ["P", "P", "P"],
        "idproducto": [2.0, 2.0, 2.0],
        "producto": ["Nafta"] * 3,
        "idtipohorario": [1.0, 1.0, 1.0],
        "precio": [1500.0, 1510.0, 1490.0],
        "latitud": [-34.1, -34.2, -34.3],
        "longitud": [-58.1, -58.2, -58.3],
        "region": ["PAMPEANA"] * 3,
        "tipohorario": ["Diurno"] * 3,
        "fecha_vigencia": ["2026-09-01"] * 3,
        "idempresabandera": [28.0, 28.0, 28.0],
        "empresabandera": ["YPF"] * 3,
        "geojson": ["{}"] * 3,
    }
    _write(sink, "energia_ckan", "pump_prices_current", pl.DataFrame(base), at)


def _ad(sink: Sink, at: datetime) -> None:
    df = pl.DataFrame({"fecha": ["2026-01-01"], "nombre": ["Año nuevo"], "tipo": ["inamovible"]})
    _write(sink, "argentinadatos", "holidays", df, at)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_publish_stages_uploads_and_redacts(
    settings: Settings, sink: Sink, now: datetime, next_day: datetime, tmp_path: Path
) -> None:
    _fx(sink, now, 1450.0)
    _fx(sink, next_day, 1455.0)
    _pumps(sink, now)
    _ad(sink, now)
    dest = tmp_path / "dest"

    res = publish(settings, tmp_path / "stage", URL, dest=str(dest), marts_dir=MARTS)

    assert set(res.published) == {"bcra__fx_history", "energia_ckan__pump_prices_current"}
    assert not res.blocked and "bcra__fx_quotes" in res.missing
    assert "argentinadatos__holidays" not in res.published + res.missing
    assert res.uploaded[-1] == "catalog.json"

    catalog = json.loads((dest / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["base_url"] == URL
    assert _sha(dest / "signals.duckdb") == catalog["duckdb"]["sha256"]
    names = [f"{d['source']}__{d['dataset']}" for d in catalog["datasets"]]
    assert names == ["bcra__fx_history", "energia_ckan__pump_prices_current"]
    for d in catalog["datasets"]:
        assert d["license"] and d["attribution"]
        for f in d["files"].values():
            assert _sha(dest / f["path"]) == f["sha256"]
    fx = catalog["datasets"][0]
    assert fx["rows"] == {"latest": 4, "history": 8}

    pumps = pl.read_parquet(dest / "latest" / "energia_ckan__pump_prices_current.parquet")
    pumps = pumps.sort("idproducto", "precio")
    assert pumps["cuit"].to_list() == [None, None, "30-71234567-8"]
    assert pumps["empresa"].to_list() == [None, None, '=HYPERLINK("x")']
    assert pumps["latitud"].null_count() == 2
    assert pumps["localidad"].to_list() == ["C", "A", "B"]
    history = pl.read_parquet(dest / "history" / "energia_ckan__pump_prices_current.parquet")
    assert history["cuit"].drop_nulls().to_list() == ["30-71234567-8"]

    csv = (dest / "latest" / "energia_ckan__pump_prices_current.csv").read_text(encoding="utf-8")
    assert "'=HYPERLINK" in csv and "PEREZ" not in csv and "20-12345678-9" not in csv

    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{dest / 'signals.duckdb'}' AS s (READ_ONLY)")
        con.execute(f"SET VARIABLE signals_base = '{dest}'")
        con.execute("USE s")
        assert con.execute("SELECT count(*) FROM bcra__fx_history__latest").fetchone() == (4,)
        assert con.execute("SELECT count(*) FROM bcra__fx_history").fetchone() == (8,)
        assert con.execute("SELECT count(*) FROM open_meteo__forecast").fetchone() == (0,)
        assert con.execute("SELECT count(*) FROM argentinadatos__holidays").fetchone() == (0,)
        usd = con.execute(
            "SELECT last_value FROM argentina_pulse WHERE section = 'fx' AND key = 'USD'"
        ).fetchone()
        assert usd == (1455.0,)
    finally:
        con.close()


def test_implausible_jump_blocks_and_keeps_previous_version(
    settings: Settings, sink: Sink, now: datetime, tmp_path: Path
) -> None:
    dest = tmp_path / "dest"
    _fx(sink, now, 1450.0)
    publish(settings, tmp_path / "stage", URL, dest=str(dest), marts_dir=MARTS)
    before = (dest / "latest" / "bcra__fx_history.parquet").read_bytes()

    _fx(sink, now + timedelta(days=1), 99999.0)
    res = publish(settings, tmp_path / "stage2", URL, dest=str(dest), marts_dir=MARTS)

    assert "max_change_pct" in res.blocked["bcra__fx_history"]
    assert res.carried_over == ["bcra__fx_history"]
    assert (dest / "latest" / "bcra__fx_history.parquet").read_bytes() == before
    catalog = json.loads((dest / "catalog.json").read_text(encoding="utf-8"))
    assert [d["dataset"] for d in catalog["datasets"]] == ["fx_history"]

    forced = publish(
        settings, tmp_path / "stage3", URL, dest=str(dest), marts_dir=MARTS, allow_implausible=True
    )
    assert forced.published == ["bcra__fx_history"] and not forced.blocked


def test_stage_only_writes_nothing_remote(
    settings: Settings, sink: Sink, now: datetime, tmp_path: Path
) -> None:
    _fx(sink, now, 1450.0)
    res = publish(settings, tmp_path / "stage", URL, marts_dir=MARTS)
    assert res.uploaded == []
    assert (tmp_path / "stage" / "catalog.json").exists()
    assert (tmp_path / "stage" / "latest" / "bcra__fx_history.csv").exists()


def test_published_datasets_declare_terms_and_excluded_sources_stay_out() -> None:
    from teramot_signals.core.registry import available_sources, load_source_config
    from tests.conftest import REPO_CONFIG

    for source in available_sources(REPO_CONFIG):
        cfg = load_source_config(REPO_CONFIG, source)
        published = [n for n, ds in cfg.datasets.items() if ds.publish]
        if published:
            assert cfg.license and cfg.attribution and cfg.terms_url, source
        if source in ("open_meteo", "argentinadatos"):
            assert not published, source
    eph = load_source_config(REPO_CONFIG, "indec").datasets
    assert not eph["eph_households"].publish and not eph["eph_individuals"].publish
    pumps = load_source_config(REPO_CONFIG, "energia_ckan").datasets["pump_prices_current"]
    assert pumps.redact is not None and "cuit" in pumps.redact.columns
