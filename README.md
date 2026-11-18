# teramot-signals

**Argentine public data, with guarantees.**

`teramot-signals` downloads official Argentine public data (BCRA, INDEC, datos.gob.ar, Georef,
Secretaría de Energía) plus a few clearly labelled third-party sources (Open-Meteo, UNR,
ArgentinaDatos), normalizes it to Parquet, keeps every extraction immutable, flags upstream
revisions and format changes, and builds a DuckDB catalog you can query right away.

No accounts and no cloud required: it runs on a laptop and writes to a local folder, S3 or GCS.

```
Public APIs and files ──▶ run: extract → format check → normalize → revisions ──▶ Parquet
 (BCRA, INDEC, datos.gob.ar,                                                    (local, s3://, gs://)
  Georef, Energía, …)                                                                 │
                                                  catalog: DuckDB views ◀─────────────┘
                                                  <source>__<dataset>[__latest], contracts, marts
```

## Why

Public data is easy to download once and hard to trust over time. Agencies revise past values,
rename columns, change file layouts and go silent without notice. `teramot-signals` treats every
download as evidence:

- **Immutable history.** Every run writes `extraction_date=<today>/part-N.parquet`; a written
  partition is never touched again. You can always answer "what did the agency say on day X".
- **Revisions are flagged, not overwritten.** When an agency corrects a value, the new row carries
  `revision_of=<previous extraction>` and the run's contract lists the revised keys.
- **A format change is an alert, not garbage.** A missing key, a changed type or an unexpected new
  column ends the run as `format_changed`, writes no data, and exits with code 2.
- **Silence is not green.** Every run, including failed ones, appends an entry to `_contract.json`:
  status, rows, revisions, error, last successful extraction.
- **"Today" without duplicates.** The catalog's `__latest` views keep one row per key, even if the
  same table was downloaded a hundred times.

## Quickstart

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/HalleyScore/teramot-signals.git
cd teramot-signals
uv sync

# Download a few sources into ./data
uv run teramot-signals run bcra datos_gob_ar indec open_meteo --output data

# Build the DuckDB catalog (views only, no data copied) → signals.duckdb
uv run teramot-signals catalog --output data

# Query it
uv run teramot-signals sql "select section, key, name, last_date, last_value
                            from argentina_pulse where section in ('fx', 'bcra')"
```

Download the full history once; after that the daily run is incremental:

```bash
uv run teramot-signals run bcra --since 1996-01-01 --output data
uv run teramot-signals run indec -d eph_individuals --since 2016-10-01 --output data
```

Writing to the cloud: `uv sync --extra s3` (or `--extra gcs`) and pass
`--output s3://bucket/prefix`. Credentials come from the environment, never from the config.

Other commands: `teramot-signals list` shows the available sources; `teramot-signals run --help`
shows every option.

## Sources and datasets

| Source | Datasets | Publisher | Provenance |
|---|---|---|---|
| `bcra` | `monetary_catalog` (1,610 variables), `monetary_series` (reserves, exchange rates, interest rates, monetary aggregates, inflation, CER/UVA/ICL), `fx_quotes` (every currency, daily), `fx_history` (15 currencies and metals since 2003), `fx_currencies` | BCRA (central bank) | official |
| `datos_gob_ar` | `series` (time-series API), `sspm` (108 series with full history: CPI by region and division, EMAE economic activity and sectors, wages, RIPTE, supermarkets, shopping centers, BNA exchange rate), `sspm_catalog` | INDEC / SSPM | official |
| `indec` | `supermarkets_by_province` (sales, stores, floor area and categories by jurisdiction), `eph_households`, `eph_individuals` (EPH household survey microdata) | INDEC | official |
| `georef` | `provinces`, `departments`, `census_localities` | IGN / INDEC | official |
| `energia_ckan` | `pump_prices_current` (price per station, product and time band) | Secretaría de Energía | official |
| `open_meteo` | `forecast` (16 days), `observed` (ERA5) for 74 localities | Open-Meteo | third_party |
| `unr_dataverse` | `eph_dictionary` (EPH variables and codes) | Observatorio Económico Social, UNR | third_party |
| `argentinadatos` | `holidays`, `bank_holidays` | ArgentinaDatos | third_party |

`provenance` (`official` | `third_party`) travels in every row. Each source's details (endpoints,
format, quirks, license) are in [`docs/sources/`](docs/sources/). Column names and values passed
through from upstream keep the publisher's original (Spanish) wording.

## Output

```
<root>/source=<source>/dataset=<dataset>/
  _contract.json            append-only quality contract, one entry per run
  _description.md           what the table is, in plain words
  extraction_date=YYYY-MM-DD/part-N.parquet (+ part-N.manifest.json)
```

Two canonical shapes: `series` (`variable`, `ref_date`, `value`) and `table` (the record's own
columns, keyed by a declared `natural_key`). Every row also carries `source`, `dataset`,
`extraction_date`, `extracted_at`, `provenance` and `revision_of`. Any engine that reads
Hive-partitioned Parquet (DuckDB, Spark, Athena, BigQuery, polars) can read it directly.

Full contract: [`docs/OUTPUT_LAYOUT.md`](docs/OUTPUT_LAYOUT.md). Design:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Catalog and marts

`teramot-signals catalog` creates a DuckDB file **without copying data**:

| View | Use |
|---|---|
| `<source>__<dataset>` | Full history, revisions included |
| `<source>__<dataset>__latest` | The current value for each key |
| `signals__contracts` | Monitoring: the status of every run of every dataset |
| `argentina_pulse` | One-table dashboard: currencies, BCRA variables, supermarkets, fuel prices, forecast by city; latest value, previous, 30 days and one year ago, and two years of history as JSON |

Marts are plain SQL files in [`sql/marts/`](sql/marts/); adding one means adding a file.

## Public copy

`teramot-signals publish` builds a read-only copy of the datasets whose terms allow
redistribution (`publish: true` in their YAML): latest and history Parquet, CSV, a DuckDB file
with the same views, a `catalog.json` with each file's sha256 and each dataset's license and
attribution, and an `index.html` that lists it all for people. Rows that identify natural persons are redacted, and a series that jumps more than
its `max_change_pct` is held back. Details in
[`docs/OUTPUT_LAYOUT.md`](docs/OUTPUT_LAYOUT.md#public-copy-teramot-signals-publish).

```bash
uv run teramot-signals publish --output data --public-url https://example.org/signals/v1 \
  --staging public                      # add --dest s3://bucket/signals/v1 to upload
```

## Project layout

```
config/sources/<source>.yaml   datasets, shape, natural key, expected schema, window, description
src/teramot_signals/
  core/                        http · extraction · normalization · revisions · sink · registry
                               pipeline · catalog · publish · cli   (knows no specific source)
  sources/<source>/            one package per source: EXTRACTOR + NORMALIZER
sql/marts/                     derived views over the catalog
docs/                          architecture, output layout, adding a source, data licenses
tests/                         no network: real responses and files built inside the tests
.github/workflows/             ci (lint + types + tests) · daily (scheduled run) · secret-scan
```

## Development

Python 3.12+, **uv**, **ruff**, **basedpyright**, **pytest**.

```bash
uv sync --all-groups --all-extras
make check        # ruff + basedpyright + pytest (no network)
```

`run` exit codes: `0` everything ok or revised · `2` some dataset hit `format_changed` ·
`1` some dataset `failed`. `publish` exits `1` if some dataset was blocked by its checks.

## Contributing

Adding a source is additive: one YAML and one package, with no changes to `core/`. See
[`docs/ADDING_A_SOURCE.md`](docs/ADDING_A_SOURCE.md). Run `make check` before opening a pull
request, and document the source's license in [`docs/DATA_LICENSES.md`](docs/DATA_LICENSES.md).

## License

Code is licensed under [Apache-2.0](LICENSE). The data belongs to each publisher: read
[`docs/DATA_LICENSES.md`](docs/DATA_LICENSES.md) before redistributing it. Open-Meteo's free API
is for non-commercial use only.
