"""BCRA — Monetary Statistics v4.0 and Exchange Rate Statistics v1.0.

Envelope: `{status, metadata.resultset{count, offset, limit}, results}`.
- Monetary catalog: `results[{idVariable, descripcion, categoria, ...}]` (table).
- Series: `results[0].detalle[{fecha, valor}]`, descending, no holidays (series).
- Quotes of the day: `results{fecha, detalle[{codigoMoneda, descripcion, tipoPase,
  tipoCotizacion}]}` (series).
- History per currency: `results[{fecha, detalle[...]}]`, paginated (series).
- Currency master: `results[{codigo, denominacion}]` (table).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from teramot_signals.core.config import DatasetConfig
from teramot_signals.core.extraction import FormatChanged, RawBatch, Window, require_keys
from teramot_signals.core.http import HttpClient
from teramot_signals.core.normalization import Normalized, to_series, to_table


def _detalle(page: Any) -> list[Any]:
    results = page.get("results") or []
    if not results:
        return []
    first = results[0]
    if not isinstance(first, dict) or "detalle" not in first:
        raise FormatChanged(["results[0] has no `detalle`"])
    return list(first["detalle"])


def _results(page: Any) -> list[Any]:
    results = page.get("results")
    if not isinstance(results, list):
        raise FormatChanged(["`results` is not a list"])
    return results


def _total(page: Any) -> int | None:
    return (page.get("metadata") or {}).get("resultset", {}).get("count")


def _rows_fx(records: list[dict[str, Any]]) -> list[tuple[Any, Any, Any]]:
    rows: list[tuple[Any, Any, Any]] = []
    for r in records:
        code = r.get("codigoMoneda")
        rows.append((f"{code}.rate", r.get("fecha"), r.get("tipoCotizacion")))
        rows.append((f"{code}.usd_parity", r.get("fecha"), r.get("tipoPase")))
    return rows


class BcraExtractor:
    def extract(self, client: HttpClient, name: str, ds: DatasetConfig, window: Window) -> RawBatch:
        kind = ds.options.get("kind", name)
        if kind == "monetary_series":
            return self._series(client, ds, window)
        if kind == "fx_quotes":
            return self._quotes(client, ds, window)
        if kind == "fx_history":
            return self._history(client, ds, window)
        if kind in ("monetary_catalog", "fx_currencies"):
            return self._listing(client, ds)
        raise ValueError(f"bcra: unknown kind `{kind}`")

    def _listing(self, client: HttpClient, ds: DatasetConfig) -> RawBatch:
        records: list[dict[str, Any]] = []
        for page in client.paginate(
            ds.path,
            dict(ds.params),
            style=ds.pagination,
            page_limit=ds.page_limit,
            items_of=_results,
            total_of=_total,
        ):
            require_keys(page, ["status", "results"], ds.path)
            records.extend(r for r in _results(page) if isinstance(r, dict))
        return RawBatch(records=records, endpoint=ds.path, params=dict(ds.params))

    def _series(self, client: HttpClient, ds: DatasetConfig, window: Window) -> RawBatch:
        params: dict[str, Any] = {}
        if window.since:
            params["desde"] = window.since.isoformat()
        if window.until:
            params["hasta"] = window.until.isoformat()
        records: list[dict[str, Any]] = []
        for vid in ds.options["variables"]:
            path = ds.path.format(id_variable=vid)
            for page in client.paginate(
                path,
                params,
                style=ds.pagination,
                page_limit=ds.page_limit,
                items_of=_detalle,
                total_of=_total,
            ):
                require_keys(page, ["status", "results"], path)
                records.extend({"idVariable": int(vid), **row} for row in _detalle(page))
        return RawBatch(records=records, endpoint=ds.path, params=params)

    def _quotes(self, client: HttpClient, ds: DatasetConfig, window: Window) -> RawBatch:
        params: dict[str, Any] = {}
        if window.until:
            params["fecha"] = window.until.isoformat()
        page = client.get_json(ds.path, params)
        require_keys(page, ["status", "results"], ds.path)
        results = page["results"]
        require_keys(results, ["fecha", "detalle"], f"{ds.path}.results")
        records = [{**row, "fecha": results["fecha"]} for row in results["detalle"]]
        return RawBatch(records=records, endpoint=ds.path, params=params)

    def _history(self, client: HttpClient, ds: DatasetConfig, window: Window) -> RawBatch:
        params: dict[str, Any] = {
            "fechadesde": (window.since or date(2003, 1, 1)).isoformat(),
            "fechahasta": (window.until or window.reference()).isoformat(),
        }
        records: list[dict[str, Any]] = []
        for currency in ds.options["currencies"]:
            path = ds.path.format(currency=currency)
            for page in client.paginate(
                path,
                params,
                style=ds.pagination,
                page_limit=ds.page_limit,
                items_of=_results,
                total_of=_total,
            ):
                require_keys(page, ["status", "results"], path)
                for day in _results(page):
                    require_keys(day, ["fecha", "detalle"], f"{path}.results[]")
                    records.extend({**row, "fecha": day["fecha"]} for row in day["detalle"])
        return RawBatch(records=records, endpoint=ds.path, params=params)


class BcraNormalizer:
    def normalize(self, batch: RawBatch, name: str, ds: DatasetConfig) -> Normalized:
        kind = ds.options.get("kind", name)
        if kind == "monetary_series":
            labels = {int(k): str(v) for k, v in ds.options["variables"].items()}
            rows = [
                (labels[r["idVariable"]], r.get("fecha"), r.get("valor")) for r in batch.records
            ]
            return to_series(rows)
        if kind in ("fx_quotes", "fx_history"):
            return to_series(_rows_fx(batch.records))
        dates = [k for k, t in ds.expected_schema.items() if t == "date"]
        return to_table(batch.records, ds.natural_key, dates)


EXTRACTOR = BcraExtractor()
NORMALIZER = BcraNormalizer()
