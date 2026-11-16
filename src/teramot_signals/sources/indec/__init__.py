"""INDEC — files published under www.indec.gob.ar/ftp. Shape: `table`.

- `supermarkets_by_province`: `serie_supermercados.xlsx`, tables 5 (sales by product group)
  and 6 (stores, floor area, transactions), one block of columns per jurisdiction.
- `eph_households` / `eph_individuals`: Permanent Household Survey (EPH) microdata, one ZIP per
  quarter with `usu_hogar_T<t><yy>.txt` and `usu_individual_T<t><yy>.txt` (`;`, decimal comma).
  INDEC changed the questionnaire in Q4 2024: columns vary by quarter.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from datetime import date
from typing import Any

import fastexcel
import polars as pl

from teramot_signals.core.config import DatasetConfig
from teramot_signals.core.extraction import FormatChanged, RawBatch, Window
from teramot_signals.core.http import HttpClient, HttpError
from teramot_signals.core.normalization import Normalized, frame_to_table

# ── Supermarkets ─────────────────────────────────────────────────────────────────

# INDEC label prefix (no accents, lowercase) → column
_TABLE5 = {
    "total": "sales_total_products",
    "bebidas": "sales_beverages",
    "almacen": "sales_groceries",
    "panaderia": "sales_bakery",
    "lacteos": "sales_dairy",
    "carnes": "sales_meat",
    "verduleria": "sales_fruit_vegetables",
    "alimentos preparados": "sales_prepared_food",
    "articulos de limpieza": "sales_cleaning_personal_care",
    "indumentaria": "sales_clothing_footwear_textiles",
    "electronicos": "sales_electronics_household",
    "otros": "sales_other",
}
_TABLE6 = {
    "ventas totales": "sales_total",
    "cantidad de bocas": "stores",
    "ventas por boca": "sales_per_store",
    "superficie": "floor_area_m2",
    "ventas por m2": "sales_per_m2",
    "cantidad de operaciones": "transactions",
    "ventas por operacion": "sales_per_transaction",
}
_DATE_CELL = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _norm(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(plain.lower().split())


def _label(text: str, mapping: dict[str, str], where: str) -> str:
    key = _norm(text)
    for prefix, col in mapping.items():
        if key.startswith(prefix):
            return col
    raise FormatChanged([f"{where}: unknown label `{text}`"])


def parse_block_sheet(rows: list[list[Any]], mapping: dict[str, str], where: str) -> pl.DataFrame:
    """Wide INDEC sheet: a `Período` row with jurisdictions per block, the label row below it."""
    head = next((i for i, r in enumerate(rows) if r and str(r[0]).strip() == "Período"), None)
    if head is None or head + 1 >= len(rows):
        raise FormatChanged([f"{where}: `Período` row not found"])
    juris_row, label_row = rows[head], rows[head + 1]
    columns: list[tuple[int, str, str]] = []
    current = ""
    for j in range(1, len(label_row)):
        if juris_row[j] not in (None, ""):
            current = " ".join(str(juris_row[j]).split())
        if label_row[j] in (None, ""):
            continue
        if not current:
            raise FormatChanged([f"{where}: column {j} has no jurisdiction"])
        columns.append((j, current, _label(str(label_row[j]), mapping, where)))
    out: list[dict[str, Any]] = []
    for r in rows[head + 2 :]:
        m = _DATE_CELL.match(str(r[0] or ""))
        if not m:
            continue
        by_juris: dict[str, dict[str, Any]] = {}
        for j, juris, col in columns:
            rec = by_juris.setdefault(juris, {"date": m.group(1), "jurisdiction": juris})
            rec[col] = r[j]
        out.extend(by_juris.values())
    if not out:
        raise FormatChanged([f"{where}: no dated rows"])
    df = pl.DataFrame(out, infer_schema_length=None)
    values = [c for c in df.columns if c not in ("date", "jurisdiction")]
    return df.with_columns(
        pl.col(c).cast(pl.Utf8).str.strip_chars().cast(pl.Float64, strict=False) for c in values
    )


def _sheet_rows(book: fastexcel.ExcelReader, prefix: str) -> list[list[Any]]:
    name = next((n for n in book.sheet_names if n.strip().startswith(prefix)), None)
    if name is None:
        raise FormatChanged([f"missing sheet `{prefix}` (sheets: {book.sheet_names})"])
    sheet = book.load_sheet_by_name(name, header_row=None, dtypes="string")
    return [list(r) for r in sheet.to_polars().rows()]


# ── EPH ─────────────────────────────────────────────────────────────────────────


def _quarters(ds: DatasetConfig, window: Window, today: date) -> list[tuple[int, int]]:
    last = (today.year, (today.month - 1) // 3 + 1)
    if window.since:
        first = (window.since.year, (window.since.month - 1) // 3 + 1)
    else:
        n = int(ds.options.get("quarters_back", 4))
        idx = last[0] * 4 + last[1] - 1 - (n - 1)
        first = (idx // 4, idx % 4 + 1)
    out: list[tuple[int, int]] = []
    y, q = first
    while (y, q) <= last:
        out.append((y, q))
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


def _cast_columns(df: pl.DataFrame, keep_text: set[str]) -> pl.DataFrame:
    """All text: int if every value is an int, else float (decimal comma), else text."""
    out: list[pl.Series] = []
    for c in df.columns:
        if c in keep_text:
            out.append(df[c])
            continue
        s = df[c].str.strip_chars().replace("", None)
        as_int = s.cast(pl.Int64, strict=False)
        if as_int.null_count() == s.null_count():
            out.append(as_int)
            continue
        as_float = s.str.replace(",", ".", literal=True).cast(pl.Float64, strict=False)
        out.append(as_float if as_float.null_count() == s.null_count() else s)
    return pl.DataFrame(out)


def read_eph_member(content: bytes, member_prefix: str) -> pl.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        name = next(
            (n for n in zf.namelist() if n.rsplit("/", 1)[-1].lower().startswith(member_prefix)),
            None,
        )
        if name is None:
            raise FormatChanged([f"the ZIP has no `{member_prefix}*` ({zf.namelist()})"])
        raw = zf.read(name)
    df = pl.read_csv(io.BytesIO(raw), separator=";", infer_schema=False, encoding="utf8-lossy")
    df = df.rename({c: c.strip().lower() for c in df.columns})
    return _cast_columns(df, keep_text={"codusu", "mas_500", "ch05"})


class IndecExtractor:
    def extract(self, client: HttpClient, name: str, ds: DatasetConfig, window: Window) -> RawBatch:
        kind = ds.options.get("kind")
        if kind == "supermarkets_by_province":
            book = fastexcel.read_excel(client.get_bytes(ds.path))
            sales = parse_block_sheet(_sheet_rows(book, "Cuadro 5"), _TABLE5, "Cuadro 5")
            indicators = parse_block_sheet(_sheet_rows(book, "Cuadro 6"), _TABLE6, "Cuadro 6")
            frame = indicators.join(
                sales, on=["date", "jurisdiction"], how="full", coalesce=True
            ).sort("jurisdiction", "date")
            return RawBatch(records=[], frame=frame, endpoint=ds.path)
        if kind == "eph":
            return self._eph(client, ds, window)
        raise ValueError(f"indec: unknown kind `{kind}`")

    def _eph(self, client: HttpClient, ds: DatasetConfig, window: Window) -> RawBatch:
        frames: list[pl.DataFrame] = []
        found: list[str] = []
        for year, quarter in _quarters(ds, window, window.until or window.reference()):
            path = ds.path.format(quarter=quarter, year=year)
            try:
                content = client.get_bytes(path)
            except HttpError:
                continue  # quarter not published yet
            if not zipfile.is_zipfile(io.BytesIO(content)):
                continue  # INDEC answers 200 with an HTML page when the ZIP does not exist
            frames.append(read_eph_member(content, ds.options["member"]))
            found.append(f"{year}T{quarter}")
        if not frames:
            raise RuntimeError("INDEC has not published any quarter in the requested window")
        frame = pl.concat(frames, how="diagonal_relaxed")
        return RawBatch(records=[], frame=frame, endpoint=ds.path, params={"quarters": found})


class IndecNormalizer:
    def normalize(self, batch: RawBatch, name: str, ds: DatasetConfig) -> Normalized:
        assert batch.frame is not None
        dates = [k for k, t in ds.expected_schema.items() if t == "date"]
        return frame_to_table(batch.frame, ds.natural_key, dates)


EXTRACTOR = IndecExtractor()
NORMALIZER = IndecNormalizer()
