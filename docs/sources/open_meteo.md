# Source: open_meteo — daily weather per locality

- **Base URLs:** `https://api.open-meteo.com/v1/forecast` (forecast) and
  `https://archive-api.open-meteo.com/v1/archive` (observed, ERA5 reanalysis).
- **Auth:** none. **Rate limit:** the free plan allows 10,000 calls per day; with 74 localities
  in batches of 25 that is 3 calls per dataset per day.
- **Provenance:** **third party.** Open-Meteo aggregates national models (SMN, GFS, ECMWF, …) and
  Copernicus' ERA5 reanalysis. **Data: CC BY 4.0** (attribute Open-Meteo.com).
- **Terms:** the free API is **for non-commercial use only**. Commercial use needs a paid plan or
  a self-hosted instance (the server is open source, AGPLv3). This applies to whoever runs the
  extractor, not to the code in this repo.

## Response

Several coordinates in one request (`latitude=a,b,c&longitude=x,y,z`) → a list in the same order:
`[{latitude, longitude, daily{time[], temperature_2m_max[], temperature_2m_min[],
temperature_2m_mean[], precipitation_sum[]}}]`. With a single coordinate it returns an object, not
a list; the extractor accepts both. The reanalysis returns `null` for days it does not cover yet
(~5 days behind): those rows are dropped.

## Datasets

Columns: `locality_id`, `locality`, `province`, `lat`, `lon`, `date`, `temp_max`, `temp_min`,
`temp_mean` (°C), `precipitation_mm`.

| Dataset | Window | Key | Notes |
|---|---|---|---|
| `forecast` | 16 days ahead | `(locality_id, date)` | Each run keeps its forecast; `extraction_date` = run date. Changes between runs are recorded as revisions. |
| `observed` | last 10 days (`lookback_days`) | `(locality_id, date)` | History back to 1940 with `--since`. Preliminary ERA5T → final ERA5 after 2-3 months. |

The localities (74: provincial capitals and large urban areas, with Georef id and centroid) live
in the YAML under `options.localities`; adding one is adding a line.
