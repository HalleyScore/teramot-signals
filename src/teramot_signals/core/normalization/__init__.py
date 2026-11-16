"""Two canonical shapes: `series` (variable, ref_date, value) and `table` (natural key + cols)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

import polars as pl

from teramot_signals.core.config import DatasetConfig
from teramot_signals.core.extraction import RawBatch

# Provenance columns carried by both shapes.
COMMON_COLUMNS = (
    "source",
    "dataset",
    "extraction_date",
    "extracted_at",
    "provenance",
    "revision_of",
)
SERIES_KEY = ["variable", "ref_date"]
SERIES_VALUE = ["value"]


@dataclass
class Normalized:
    df: pl.DataFrame
    rejected: list[dict[str, Any]] = field(default_factory=list)


class Normalizer(Protocol):
    def normalize(self, batch: RawBatch, name: str, ds: DatasetConfig) -> Normalized: ...


def _to_date(raw: Any) -> date | None:
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str) and len(raw) >= 10:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def to_series(rows: list[tuple[Any, Any, Any]]) -> Normalized:
    """`rows` = (variable, ref_date, value). Non-numeric or undated rows go to `rejected`."""
    good: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for variable, raw_date, raw_value in rows:
        ref_date = _to_date(raw_date)
        value: float | None
        if raw_value is None:
            value = None
        elif isinstance(raw_value, int | float) and not isinstance(raw_value, bool):
            value = float(raw_value)
        else:
            try:
                value = float(str(raw_value))
            except ValueError:
                value = None
                rejected.append({"variable": variable, "ref_date": raw_date, "value": raw_value})
                continue
        if ref_date is None:
            rejected.append({"variable": variable, "ref_date": raw_date, "value": raw_value})
            continue
        good.append({"variable": str(variable), "ref_date": ref_date, "value": value})
    df = pl.DataFrame(
        good,
        schema={"variable": pl.Utf8, "ref_date": pl.Date, "value": pl.Float64},
    )
    return Normalized(df=df, rejected=rejected)


def to_table(
    records: list[dict[str, Any]], natural_key: list[str], date_columns: list[str] | None = None
) -> Normalized:
    """Dimensional table. A row without a complete natural key goes to `rejected`."""
    rejected = [r for r in records if any(r.get(k) is None for k in natural_key)]
    good = [r for r in records if all(r.get(k) is not None for k in natural_key)]
    df = pl.DataFrame(good, infer_schema_length=None) if good else pl.DataFrame()
    if df.is_empty():
        df = pl.DataFrame({k: pl.Series([], dtype=pl.Utf8) for k in natural_key})
    for c in date_columns or []:
        if c in df.columns and df.schema[c] == pl.Utf8:
            df = df.with_columns(pl.col(c).str.slice(0, 10).str.to_date(strict=False).alias(c))
    return Normalized(df=df, rejected=rejected)


def finalize(
    df: pl.DataFrame,
    *,
    source: str,
    dataset: str,
    extraction_date: date,
    extracted_at: datetime,
    provenance: str,
) -> pl.DataFrame:
    return df.with_columns(
        pl.lit(source).alias("source"),
        pl.lit(dataset).alias("dataset"),
        pl.lit(extraction_date).alias("extraction_date"),
        pl.lit(extracted_at).alias("extracted_at"),
        pl.lit(provenance).alias("provenance"),
        pl.lit(None, dtype=pl.Utf8).alias("revision_of"),
    )


def frame_to_table(
    df: pl.DataFrame, natural_key: list[str], date_columns: list[str] | None = None
) -> Normalized:
    """`to_table` for file sources: rows without a complete natural key go to `rejected`."""
    missing = pl.any_horizontal([pl.col(k).is_null() for k in natural_key])
    rejected = df.filter(missing)
    good = df.filter(~missing)
    for c in date_columns or []:
        if c in good.columns and good.schema[c] == pl.Utf8:
            good = good.with_columns(pl.col(c).str.slice(0, 10).str.to_date(strict=False))
    return Normalized(df=good, rejected=rejected.head(1000).to_dicts())


def frame_to_series(df: pl.DataFrame) -> Normalized:
    """`to_series` for a frame with columns (variable, ref_date, value)."""
    df = df.select(
        pl.col("variable").cast(pl.Utf8),
        pl.col("ref_date").cast(pl.Utf8).str.slice(0, 10).str.to_date(strict=False),
        pl.col("value").cast(pl.Utf8).str.strip_chars().cast(pl.Float64, strict=False),
        pl.col("value").alias("_raw"),
    )
    bad = df.filter(
        pl.col("ref_date").is_null() | (pl.col("value").is_null() & pl.col("_raw").is_not_null())
    )
    good = df.filter(pl.col("ref_date").is_not_null() & pl.col("value").is_not_null())
    return Normalized(df=good.drop("_raw"), rejected=bad.head(1000).to_dicts())
