"""Open-Meteo — daily weather per locality: observed (ERA5 reanalysis) and forecast. `table`.

`GET /v1/archive` (archive-api) and `GET /v1/forecast` (api) with several coordinates per request
→ a list `[{latitude, longitude, daily{time[], temperature_2m_max[], ...}}]`, in request order.
Provenance: third party. Data CC BY 4.0; the free API is for non-commercial use only.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import polars as pl

from teramot_signals.core.config import DatasetConfig
from teramot_signals.core.extraction import FormatChanged, RawBatch, Window, require_keys
from teramot_signals.core.http import HttpClient
from teramot_signals.core.normalization import Normalized, to_table

# Open-Meteo daily variable → Parquet column
_DAILY = {
    "temperature_2m_max": "temp_max",
    "temperature_2m_min": "temp_min",
    "temperature_2m_mean": "temp_mean",
    "precipitation_sum": "precipitation_mm",
}
_BATCH = 25


class OpenMeteoExtractor:
    def extract(self, client: HttpClient, name: str, ds: DatasetConfig, window: Window) -> RawBatch:
        locations: list[dict[str, Any]] = ds.options["localities"]
        params: dict[str, Any] = {
            "daily": ",".join(_DAILY),
            "timezone": ds.options.get("timezone", "America/Argentina/Buenos_Aires"),
        }
        if ds.options.get("kind") == "forecast":
            params["forecast_days"] = int(ds.options.get("forecast_days", 16))
        else:
            until = window.until or window.reference() - timedelta(days=1)
            params["start_date"] = (window.since or until - timedelta(days=10)).isoformat()
            params["end_date"] = until.isoformat()
        records: list[dict[str, Any]] = []
        for i in range(0, len(locations), _BATCH):
            chunk = locations[i : i + _BATCH]
            page = client.get_json(
                ds.path,
                {
                    **params,
                    "latitude": ",".join(str(loc["lat"]) for loc in chunk),
                    "longitude": ",".join(str(loc["lon"]) for loc in chunk),
                },
            )
            answers = page if isinstance(page, list) else [page]
            if len(answers) != len(chunk):
                raise FormatChanged([f"requested {len(chunk)} locations, got {len(answers)}"])
            for loc, ans in zip(chunk, answers, strict=True):
                require_keys(ans, ["daily"], ds.path)
                daily = ans["daily"]
                require_keys(daily, ["time", *_DAILY], f"{ds.path}.daily")
                for j, day in enumerate(daily["time"]):
                    row = {col: daily[var][j] for var, col in _DAILY.items()}
                    if all(v is None for v in row.values()):
                        continue  # the reanalysis does not cover that day yet
                    records.append(
                        {
                            "locality_id": str(loc["id"]),
                            "locality": loc["name"],
                            "province": loc["province"],
                            "lat": float(loc["lat"]),
                            "lon": float(loc["lon"]),
                            "date": day,
                            **row,
                        }
                    )
        return RawBatch(records=records, endpoint=ds.path, params=params)


class OpenMeteoNormalizer:
    def normalize(self, batch: RawBatch, name: str, ds: DatasetConfig) -> Normalized:
        norm = to_table(batch.records, ds.natural_key, ["date"])
        floats = [c for c in (*_DAILY.values(), "lat", "lon") if c in norm.df.columns]
        norm.df = norm.df.with_columns(pl.col(c).cast(pl.Float64) for c in floats)
        return norm


EXTRACTOR = OpenMeteoExtractor()
NORMALIZER = OpenMeteoNormalizer()
