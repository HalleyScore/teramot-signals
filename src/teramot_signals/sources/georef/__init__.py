"""Georef (datos.gob.ar) — official territorial units, bulk CSV download. Shape: `table`.

`https://infra.datos.gob.ar/georef/<entity>.csv`: provinces, departments, municipalities,
census localities. One row per entity, with INDEC id, name, hierarchy and centroid.
Columns are passed through as published by Georef.
"""

from __future__ import annotations

import io

import polars as pl

from teramot_signals.core.config import DatasetConfig
from teramot_signals.core.extraction import RawBatch, Window
from teramot_signals.core.http import HttpClient
from teramot_signals.core.normalization import Normalized, frame_to_table


class GeorefExtractor:
    def extract(self, client: HttpClient, name: str, ds: DatasetConfig, window: Window) -> RawBatch:
        # Ids have leading zeros ("02", "06028010"): everything is read as text.
        frame = pl.read_csv(io.BytesIO(client.get_bytes(ds.path)), infer_schema=False)
        numeric = [k for k, t in ds.expected_schema.items() if t == "number" and k in frame.columns]
        frame = frame.with_columns(pl.col(c).cast(pl.Float64, strict=False) for c in numeric)
        return RawBatch(records=[], frame=frame, endpoint=ds.path)


class GeorefNormalizer:
    def normalize(self, batch: RawBatch, name: str, ds: DatasetConfig) -> Normalized:
        assert batch.frame is not None
        return frame_to_table(batch.frame, ds.natural_key)


EXTRACTOR = GeorefExtractor()
NORMALIZER = GeorefNormalizer()
