"""Guards that history is never rewritten, and per-key revisions in both shapes."""

from __future__ import annotations

import hashlib
from datetime import date, datetime

import polars as pl

from teramot_signals.core.normalization import SERIES_KEY, finalize, to_series, to_table
from teramot_signals.core.revisions import mark_revisions
from teramot_signals.core.sink import Sink


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _series(values: list[float], now: datetime) -> pl.DataFrame:
    rows = [("x", date(2026, 9, d + 1), v) for d, v in enumerate(values)]
    return finalize(
        to_series(rows).df,
        source="s",
        dataset="d",
        extraction_date=now.date(),
        extracted_at=now,
        provenance="official",
    )


def test_same_day_rerun_writes_part_1_and_leaves_part_0_untouched(
    sink: Sink, now: datetime
) -> None:
    df = _series([1.0, 2.0], now)
    p0 = sink.write_partition(df, "s", "d", now.date(), {})
    h0 = _sha(p0)
    p1 = sink.write_partition(_series([1.0, 99.0], now), "s", "d", now.date(), {})
    assert p0.endswith("part-0.parquet") and p1.endswith("part-1.parquet")
    assert _sha(p0) == h0
    assert sink.read_latest_part("s", "d", now.date().isoformat()) is not None


def test_revision_series_marks_new_row_and_keeps_old_partition_bytes(
    sink: Sink, now: datetime, next_day: datetime
) -> None:
    p0 = sink.write_partition(_series([1.0, 2.0, 3.0], now), "s", "d", now.date(), {})
    h0 = _sha(p0)
    new = _series([1.0, 2.0, 3.5], next_day)  # day 3 changed
    prev, prev_date = sink.latest_previous("s", "d", next_day.date())
    marked, revised = mark_revisions(new, prev, SERIES_KEY, prev_date)
    assert prev_date == now.date().isoformat()
    assert revised == [{"variable": "x", "ref_date": "2026-09-03"}]
    assert marked.filter(pl.col("revision_of").is_not_null()).height == 1
    assert marked.filter(pl.col("revision_of") == now.date().isoformat()).height == 1
    sink.write_partition(marked, "s", "d", next_day.date(), {})
    assert _sha(p0) == h0


def test_revision_table_uses_natural_key(now: datetime) -> None:
    key = ["fecha", "nombre"]
    prev = finalize(
        to_table(
            [
                {"fecha": "2026-03-23", "nombre": "Puente", "tipo": "puente", "year": 2026},
                {"fecha": "2026-01-01", "nombre": "Año nuevo", "tipo": "inamovible", "year": 2026},
            ],
            key,
        ).df,
        source="s",
        dataset="f",
        extraction_date=now.date(),
        extracted_at=now,
        provenance="third_party",
    )
    new = finalize(
        to_table(
            [
                {"fecha": "2026-03-23", "nombre": "Puente", "tipo": "trasladable", "year": 2026},
                {"fecha": "2026-01-01", "nombre": "Año nuevo", "tipo": "inamovible", "year": 2026},
                {"fecha": "2026-12-08", "nombre": "Inmaculada", "tipo": "inamovible", "year": 2026},
            ],
            key,
        ).df,
        source="s",
        dataset="f",
        extraction_date=now.date(),
        extracted_at=now,
        provenance="third_party",
    )
    marked, revised = mark_revisions(new, prev, key, "2026-09-13")
    assert revised == [{"fecha": "2026-03-23", "nombre": "Puente"}]
    assert marked.filter(pl.col("revision_of") == "2026-09-13")["nombre"].to_list() == ["Puente"]
    assert marked.height == 3  # the new row is not a revision


def test_to_series_rejects_non_numeric_without_breaking() -> None:
    n = to_series([("x", "2026-01-01", "n/d"), ("x", "2026-01-02", "12.5"), ("x", None, 1)])
    assert n.df.height == 1
    assert n.df["value"].to_list() == [12.5]
    assert len(n.rejected) == 2


def test_contract_is_append_only(sink: Sink) -> None:
    sink.append_contract("s", "d", {"status": "failed", "n": 1})
    sink.append_contract("s", "d", {"status": "ok", "n": 2})
    assert [e["n"] for e in sink.read_contract("s", "d")] == [1, 2]
