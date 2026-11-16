"""Revision detection: the new row is flagged; the previous one is never touched."""

from __future__ import annotations

from typing import Any

import polars as pl

from teramot_signals.core.normalization import COMMON_COLUMNS


def value_columns(df: pl.DataFrame, key: list[str]) -> list[str]:
    return [c for c in df.columns if c not in key and c not in COMMON_COLUMNS]


def mark_revisions(
    new: pl.DataFrame,
    prev: pl.DataFrame | None,
    key: list[str],
    prev_extraction: str | None,
) -> tuple[pl.DataFrame, list[dict[str, Any]]]:
    """Rows of `new` whose key is in `prev` with another value → `revision_of=prev_extraction`."""
    if prev is None or prev.is_empty() or new.is_empty() or prev_extraction is None:
        return new, []
    values = value_columns(new, key)
    shared = [c for c in values if c in prev.columns]
    if not shared:
        return new, []

    def fingerprint(df: pl.DataFrame, alias: str) -> pl.DataFrame:
        cols = [pl.col(c).cast(pl.Utf8).fill_null("∅") for c in shared]
        return df.select(
            [
                *[pl.col(k).cast(pl.Utf8) for k in key],
                pl.concat_str(cols, separator="|").alias(alias),
            ]
        )

    prev_fp = fingerprint(prev, "_prev").unique(subset=key, keep="last")
    new_fp = fingerprint(new, "_new")
    joined = new_fp.join(prev_fp, on=key, how="left")
    changed = joined.filter(
        pl.col("_prev").is_not_null() & (pl.col("_prev") != pl.col("_new"))
    ).select(key)
    if changed.is_empty():
        return new, []
    flag = changed.with_columns(pl.lit(True).alias("_rev"))
    out = (
        new.with_columns([pl.col(k).cast(pl.Utf8).alias(f"__k_{k}") for k in key])
        .join(flag.rename({k: f"__k_{k}" for k in key}), on=[f"__k_{k}" for k in key], how="left")
        .with_columns(
            pl.when(pl.col("_rev").fill_null(False))
            .then(pl.lit(prev_extraction))
            .otherwise(pl.col("revision_of"))
            .alias("revision_of")
        )
        .drop(["_rev", *[f"__k_{k}" for k in key]])
    )
    return out, changed.to_dicts()
