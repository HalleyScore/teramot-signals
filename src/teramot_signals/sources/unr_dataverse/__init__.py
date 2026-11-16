"""Observatorio Económico Social (UNR), Dataverse — EPH data dictionary. Shape: `table`.

`GET /api/datasets/:persistentId/?persistentId=<doi>` lists the files; the dictionary
(`eph_dict_capa1.json`) is downloaded by id with `/api/access/datafile/<id>`.
Format: `{metadata, variables[{name, original_var, type, label, ..., values[{value, original}]}]}`.
Provenance: third party (curated by UNR from INDEC's documentation). CC BY 4.0.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from teramot_signals.core.config import DatasetConfig
from teramot_signals.core.extraction import FormatChanged, RawBatch, Window, require_keys
from teramot_signals.core.http import HttpClient
from teramot_signals.core.normalization import Normalized, frame_to_table

_COLUMNS = (
    "variable",
    "position",
    "indec_variable",
    "type",
    "label",
    "description",
    "base",
    "category",
    "section",
    "methodology",
    "origin",
    "value_position",
    "code",
    "value_label",
    "original_value",
)


def _text(v: Any) -> str | None:
    return None if v is None else str(v)


def flatten_dictionary(doc: Any) -> pl.DataFrame:
    require_keys(doc, ["variables"], "eph_dict")
    rows: list[dict[str, Any]] = []
    for i, var in enumerate(doc["variables"]):
        require_keys(var, ["name", "label"], "eph_dict.variables[]")
        base = {
            "variable": _text(var["name"]),
            "position": i,
            "indec_variable": _text(var.get("original_var")),
            "type": _text(var.get("type")),
            "label": _text(var.get("label")),
            "description": _text(var.get("description")),
            "base": _text(var.get("base")),
            "category": _text(var.get("category")),
            "section": _text(var.get("section")),
            "methodology": _text(var.get("methodology")),
            "origin": _text(var.get("origin")),
        }
        values = var.get("values") or [{}]
        for k, v in enumerate(values):
            if not isinstance(v, dict):
                raise FormatChanged(["eph_dict: `values[]` is not an object"])
            original = _text(v.get("original"))
            code = original.split("=", 1)[0].strip() if original and "=" in original else None
            rows.append(
                {
                    **base,
                    "value_position": k,
                    "code": code,
                    "value_label": _text(v.get("value")),
                    "original_value": original,
                }
            )
    schema = {c: (pl.Int64 if c in ("position", "value_position") else pl.Utf8) for c in _COLUMNS}
    return pl.DataFrame(rows, schema=schema)


class UnrDataverseExtractor:
    def extract(self, client: HttpClient, name: str, ds: DatasetConfig, window: Window) -> RawBatch:
        doi = ds.options["doi"]
        listing = client.get_json(ds.path, {"persistentId": doi})
        require_keys(listing, ["data"], ds.path)
        files = ((listing["data"] or {}).get("latestVersion") or {}).get("files") or []
        wanted = ds.options["file"]
        match = next((f for f in files if f.get("label") == wanted), None)
        if match is None:
            raise FormatChanged([f"dataset {doi} no longer has `{wanted}`"])
        file_id = match["dataFile"]["id"]
        doc = client.get_json(f"/api/access/datafile/{file_id}")
        frame = flatten_dictionary(doc)
        return RawBatch(
            records=[], frame=frame, endpoint=ds.path, params={"doi": doi, "file_id": file_id}
        )


class UnrDataverseNormalizer:
    def normalize(self, batch: RawBatch, name: str, ds: DatasetConfig) -> Normalized:
        assert batch.frame is not None
        return frame_to_table(batch.frame, ds.natural_key)


EXTRACTOR = UnrDataverseExtractor()
NORMALIZER = UnrDataverseNormalizer()
