"""datos.gob.ar — Time Series API and the `sspm` catalog (INDEC and other agencies).

- `series` (shape `series`): `GET /series/api/series/?ids=<id>&metadata=full&limit=1000&start=N`
  → `{data[[date, value]], count, meta[...]}`.
- `sspm` (shape `series`): the full history comes from the catalog's CSV distributions
  (one download per file, not one call per series). The API only resolves, per batch of ids,
  which CSV and which column belong to each series (`metadata=only`).
- `sspm_catalog` (shape `table`): metadata for those same series (unit, frequency,
  source, license, dates), one row per id.
"""

from __future__ import annotations

import io
from typing import Any

import polars as pl

from teramot_signals.core.config import DatasetConfig
from teramot_signals.core.extraction import FormatChanged, RawBatch, Window, require_keys
from teramot_signals.core.http import HttpClient
from teramot_signals.core.normalization import (
    Normalized,
    frame_to_series,
    frame_to_table,
    to_series,
)

_META_BATCH = 20


def _items(page: Any) -> list[Any]:
    data = page.get("data")
    if not isinstance(data, list):
        raise FormatChanged(["`data` is not a list"])
    return data


def _total(page: Any) -> int | None:
    return page.get("count")


def _describe(slug: str, entry: Any) -> str:
    ds_meta = (entry or {}).get("dataset") or {}
    field = (entry or {}).get("field") or {}
    parts = [
        f"### {slug}",
        f"**{field.get('title', '')}** — {field.get('description', '')}".strip(),
    ]
    extra = [
        f"Unit: {field.get('units')}" if field.get("units") else "",
        f"Frequency: {field.get('frequency')}" if field.get("frequency") else "",
        f"Source: {ds_meta.get('source')} · {ds_meta.get('title')}" if ds_meta else "",
        f"API id: `{field.get('id')}`" if field.get("id") else "",
    ]
    parts.extend(e for e in extra if e)
    return "\n".join(parts)


def _series_spec(ds: DatasetConfig) -> dict[str, tuple[str, str]]:
    """options.series: {id: [variable, group]} → {id: (variable, group)}."""
    out: dict[str, tuple[str, str]] = {}
    for sid, spec in ds.options["series"].items():
        variable, group = (spec, "") if isinstance(spec, str) else (spec[0], spec[1])
        out[str(sid)] = (str(variable), str(group))
    return out


def _metadata(client: HttpClient, path: str, ids: list[str]) -> dict[str, dict[str, Any]]:
    """id → {catalog, dataset, distribution, field}, in batches (the API accepts several ids)."""
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(ids), _META_BATCH):
        chunk = ids[i : i + _META_BATCH]
        page = client.get_json(path, {"ids": ",".join(chunk), "metadata": "only", "format": "json"})
        require_keys(page, ["meta"], path)
        meta = page["meta"]
        if not isinstance(meta, list) or len(meta) != len(chunk) + 1:
            raise FormatChanged([f"`meta` does not have one entry per id ({len(chunk)} requested)"])
        for entry in meta[1:]:
            require_keys(entry, ["field", "distribution", "dataset"], f"{path}.meta[]")
            out[str(entry["field"]["id"])] = entry
    missing = [s for s in ids if s not in out]
    if missing:
        raise FormatChanged([f"the API returned no metadata for {missing}"])
    return out


class DatosGobArExtractor:
    def extract(self, client: HttpClient, name: str, ds: DatasetConfig, window: Window) -> RawBatch:
        kind = ds.options.get("kind", "api")
        if kind == "sspm":
            return self._sspm(client, ds, window)
        if kind == "sspm_catalog":
            return self._catalog(client, ds)
        return self._api(client, ds, window)

    def _api(self, client: HttpClient, ds: DatasetConfig, window: Window) -> RawBatch:
        base_params: dict[str, Any] = {"format": "json", "metadata": "full", **ds.params}
        if window.since:
            base_params["start_date"] = window.since.isoformat()
        if window.until:
            base_params["end_date"] = window.until.isoformat()
        records: list[dict[str, Any]] = []
        descriptions: dict[str, str] = {}
        for series_id, slug in ds.options["ids"].items():
            params = {**base_params, "ids": series_id}
            for page in client.paginate(
                ds.path,
                params,
                style=ds.pagination,
                page_limit=ds.page_limit,
                items_of=_items,
                total_of=_total,
            ):
                require_keys(page, ["data", "count", "meta"], ds.path)
                meta = page["meta"]
                if not isinstance(meta, list) or len(meta) < 2:
                    raise FormatChanged(["`meta` does not have [dataset, field]"])
                if slug not in descriptions:
                    descriptions[str(slug)] = _describe(str(slug), meta[1])
                for row in _items(page):
                    if not isinstance(row, list) or len(row) < 2:
                        raise FormatChanged(["`data` is not [date, value]"])
                    records.append(
                        {"series_id": series_id, "variable": slug, "date": row[0], "value": row[1]}
                    )
        return RawBatch(
            records=records, endpoint=ds.path, params=base_params, descriptions=descriptions
        )

    def _sspm(self, client: HttpClient, ds: DatasetConfig, window: Window) -> RawBatch:
        spec = _series_spec(ds)
        meta = _metadata(client, ds.path, list(spec))
        by_url: dict[str, list[str]] = {}
        for sid, entry in meta.items():
            url = entry["distribution"].get("downloadURL")
            if not url:
                raise FormatChanged([f"{sid}: the distribution has no `downloadURL`"])
            by_url.setdefault(str(url), []).append(sid)
        frames: list[pl.DataFrame] = []
        descriptions: dict[str, str] = {}
        for url, sids in sorted(by_url.items()):
            csv = pl.read_csv(io.BytesIO(client.get_bytes(url)), infer_schema=False)
            if "indice_tiempo" not in csv.columns:
                raise FormatChanged([f"{url}: missing column `indice_tiempo`"])
            for sid in sids:
                column = str(meta[sid]["field"].get("title", ""))
                if column not in csv.columns:
                    raise FormatChanged([f"{url}: missing column `{column}` for series {sid}"])
                variable = spec[sid][0]
                descriptions[variable] = _describe(variable, meta[sid])
                frames.append(
                    csv.select(
                        pl.lit(sid).alias("series_id"),
                        pl.lit(variable).alias("variable"),
                        pl.col("indice_tiempo").alias("date"),
                        pl.col(column).alias("value"),
                    )
                )
        frame = pl.concat(frames) if frames else pl.DataFrame()
        if window.since and not frame.is_empty():
            frame = frame.filter(pl.col("date") >= window.since.isoformat())
        frame = frame.with_columns(pl.col("value").cast(pl.Float64, strict=False))
        return RawBatch(
            records=[],
            frame=frame,
            endpoint=ds.path,
            params={"distributions": sorted(by_url)},
            descriptions=descriptions,
        )

    def _catalog(self, client: HttpClient, ds: DatasetConfig) -> RawBatch:
        spec = _series_spec(ds)
        meta = _metadata(client, ds.path, list(spec))
        rows: list[dict[str, Any]] = []
        for sid, (variable, group) in spec.items():
            field = meta[sid]["field"]
            dataset = meta[sid]["dataset"]
            dist = meta[sid]["distribution"]
            rows.append(
                {
                    "series_id": sid,
                    "variable": variable,
                    "group": group,
                    "title": field.get("title"),
                    "description": field.get("description"),
                    "unit": field.get("units"),
                    "frequency": field.get("frequency"),
                    "start_date": field.get("time_index_start"),
                    "end_date": field.get("time_index_end"),
                    "dataset_title": dataset.get("title"),
                    "source": dataset.get("source"),
                    "publisher": (dataset.get("publisher") or {}).get("name"),
                    "license": dataset.get("license"),
                    "distribution_url": dist.get("downloadURL"),
                }
            )
        frame = pl.DataFrame(rows, infer_schema_length=None, schema_overrides=_CATALOG_SCHEMA)
        return RawBatch(records=[], frame=frame, endpoint=ds.path, params={"ids": len(spec)})


_CATALOG_SCHEMA = {
    k: pl.Utf8
    for k in (
        "series_id",
        "variable",
        "group",
        "title",
        "description",
        "unit",
        "frequency",
        "start_date",
        "end_date",
        "dataset_title",
        "source",
        "publisher",
        "license",
        "distribution_url",
    )
}


class DatosGobArNormalizer:
    def normalize(self, batch: RawBatch, name: str, ds: DatasetConfig) -> Normalized:
        if batch.frame is not None:
            if ds.shape == "series":
                return frame_to_series(
                    batch.frame.rename({"date": "ref_date"}).select("variable", "ref_date", "value")
                )
            dates = [k for k, t in ds.expected_schema.items() if t == "date"]
            return frame_to_table(batch.frame, ds.natural_key, dates)
        return to_series([(r["variable"], r["date"], r["value"]) for r in batch.records])


EXTRACTOR = DatosGobArExtractor()
NORMALIZER = DatosGobArNormalizer()
