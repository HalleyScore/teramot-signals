"""ArgentinaDatos — national and bank holidays. Shape: `table`. Provenance: third party.

`/v1/feriados/{year}` → `[{fecha, tipo, nombre}]`;
`/v1/feriados-bancarios/{year}` → `[{fecha, nombre}]`.
Not an official source (the official one, argentina.gob.ar, has no API). Fallback: a curated YAML.
"""

from __future__ import annotations

from typing import Any

from teramot_signals.core.config import DatasetConfig
from teramot_signals.core.extraction import FormatChanged, RawBatch, Window
from teramot_signals.core.http import HttpClient, HttpError
from teramot_signals.core.normalization import Normalized, to_table


def _years(ds: DatasetConfig, window: Window) -> list[int]:
    if window.since or window.until:
        lo = (window.since or window.until or window.reference()).year
        hi = (window.until or window.since or window.reference()).year
        return list(range(lo, hi + 1))
    base = window.reference().year
    spec = ds.options.get("years", ["current", "next"])
    out: list[int] = []
    for y in spec:
        if y == "current":
            out.append(base)
        elif y == "next":
            out.append(base + 1)
        else:
            out.append(int(y))
    return out


class ArgentinaDatosExtractor:
    def extract(self, client: HttpClient, name: str, ds: DatasetConfig, window: Window) -> RawBatch:
        records: list[dict[str, Any]] = []
        years: list[int] = []
        future = window.reference().year
        for year in _years(ds, window):
            path = ds.path.format(year=year)
            try:
                page = client.get_json(path)
            except HttpError:
                if year > future:
                    continue  # next year is not published yet
                raise
            years.append(year)
            if not isinstance(page, list):
                raise FormatChanged([f"{path}: expected a list, got {type(page).__name__}"])
            records.extend({**row, "year": year} for row in page if isinstance(row, dict))
        return RawBatch(records=records, endpoint=ds.path, params={"years": years})


class ArgentinaDatosNormalizer:
    def normalize(self, batch: RawBatch, name: str, ds: DatasetConfig) -> Normalized:
        dates = [k for k, t in ds.expected_schema.items() if t == "date"]
        return to_table(batch.records, ds.natural_key, dates)


EXTRACTOR = ArgentinaDatosExtractor()
NORMALIZER = ArgentinaDatosNormalizer()
