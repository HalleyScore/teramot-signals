"""Extractor contract, raw batch and format check against the expected schema."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

import polars as pl

from teramot_signals.core.config import DatasetConfig
from teramot_signals.core.http import HttpClient

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class Window:
    since: date | None = None
    until: date | None = None
    # Run date (set by the pipeline): "today" for extractors, deterministic in tests.
    today: date | None = None

    def reference(self) -> date:
        return self.today or date.today()


@dataclass
class RawBatch:
    records: list[dict[str, Any]]
    endpoint: str
    params: dict[str, Any] = field(default_factory=dict)
    # Descriptions shipped by the API itself (datos.gob.ar): variable → markdown.
    descriptions: dict[str, str] = field(default_factory=dict)
    # File sources (CSV, XLSX, ZIP): the raw table already parsed, instead of `records`.
    frame: pl.DataFrame | None = None


class FormatChanged(Exception):  # noqa: N818 — a contract status, not an error
    """The agency changed the format. The run ends cleanly with `format_changed`."""

    def __init__(self, diff: list[str]) -> None:
        super().__init__("; ".join(diff))
        self.diff = diff


class Extractor(Protocol):
    def extract(
        self, client: HttpClient, name: str, ds: DatasetConfig, window: Window
    ) -> RawBatch: ...


def _type_ok(value: Any, expected: str) -> bool:
    if value is None:
        return True
    if expected == "str":
        return isinstance(value, str)
    if expected == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected == "bool":
        return isinstance(value, bool)
    if expected == "list":
        return isinstance(value, list)
    if expected == "dict":
        return isinstance(value, dict)
    if expected == "date":
        return isinstance(value, str) and bool(_DATE_RE.match(value))
    return False


def check_schema(
    records: list[dict[str, Any]], expected: dict[str, str], sample: int = 50
) -> list[str]:
    """Compares a sample of records with the expected schema. Empty = no changes."""
    if not expected or not records:
        return []
    diff: list[str] = []
    seen_new: set[str] = set()
    for rec in records[:sample]:
        for key, typ in expected.items():
            if key not in rec:
                msg = f"missing key `{key}`"
                if msg not in diff:
                    diff.append(msg)
            elif not _type_ok(rec[key], typ):
                msg = f"`{key}` expected {typ}, got {type(rec[key]).__name__}"
                if msg not in diff:
                    diff.append(msg)
        for key in rec:
            if key not in expected and key not in seen_new:
                seen_new.add(key)
                diff.append(f"new key `{key}`")
    return diff


_POLARS_OK: dict[str, tuple[type[pl.DataType], ...]] = {
    "str": (pl.Utf8,),
    "int": (pl.Int8, pl.Int16, pl.Int32, pl.Int64, pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64),
    "number": (
        pl.Int8,
        pl.Int16,
        pl.Int32,
        pl.Int64,
        pl.UInt8,
        pl.UInt16,
        pl.UInt32,
        pl.UInt64,
        pl.Float32,
        pl.Float64,
    ),
    "bool": (pl.Boolean,),
    "date": (pl.Date, pl.Datetime, pl.Utf8),
    "list": (pl.List,),
    "dict": (pl.Struct,),
}


def check_frame(
    frame: pl.DataFrame, expected: dict[str, str], *, allow_new: bool = False
) -> list[str]:
    """Like `check_schema`, on columns: missing, changed type or (unless allow_new) new."""
    if not expected:
        return []
    diff: list[str] = []
    for col, typ in expected.items():
        if col not in frame.columns:
            diff.append(f"missing column `{col}`")
            continue
        dtype = frame.schema[col]
        if dtype != pl.Null and not isinstance(dtype, _POLARS_OK[typ]):
            diff.append(f"`{col}` expected {typ}, got {dtype}")
    if not allow_new:
        diff.extend(f"new column `{c}`" for c in frame.columns if c not in expected)
    return diff


def require_keys(obj: Any, keys: list[str], where: str) -> None:
    """Validates a response envelope. A missing key ⇒ FormatChanged."""
    if not isinstance(obj, dict):
        raise FormatChanged([f"{where}: expected an object, got {type(obj).__name__}"])
    missing = [k for k in keys if k not in obj]
    if missing:
        raise FormatChanged([f"{where}: missing {missing}"])
