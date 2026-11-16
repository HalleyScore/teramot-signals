# Architecture

`teramot-signals` is an ingestion framework with a **source-agnostic core** (`core/`) and
**pluggable connectors, one per public API** (`sources/<api>/`). The design goal: adding a new
API never requires touching the core.

## Data flow

```
                         ┌──────────────────────── core/ (source-agnostic) ─────────────────┐
  Public API             │                                                                   │
  (BCRA, …)  ──HTTP──▶  Extractor ──raw records──▶ Normalizer ──table──▶ Sink ──Parquet──▶ local / S3 / GCS
                         │  (http/)                (normalization/)      (sink/)             │
                         │     ▲                         ▲                                    │
                         └─────┼─────────────────────────┼────────────────────────────────────┘
                               │                         │
                     sources/<api>/ + config/sources/<api>.yaml define WHICH endpoints and HOW they are flattened
```

- The **core** defines the contracts (protocols) and the shared mechanics: an HTTP client with
  rate limiting, retries and pagination, the Hive-partitioned Parquet writer, the registry, the
  pipeline that orchestrates `extract → normalize → write`, and the DuckDB catalog.
- Each **source** contributes what is specific to its API: base URL, headers, how a given
  endpoint paginates, and how to map the raw payload to a tabular schema per dataset.

## Concepts

| Concept | Definition |
|---------|-----------|
| **Source** | A data provider = one public API (e.g. `bcra`). A package under `sources/`. |
| **Dataset** | A concrete resource within a source (e.g. `bcra.monetary_series`). Maps 1:1 to a Parquet table. |
| **Extractor** | Fetches a dataset's raw records from the API (paginates, retries, respects the rate limit). |
| **Normalizer** | Turns the raw payload into a typed columnar table. |
| **Sink** | Writes the table as Parquet, partitioned by extraction date. |
| **Pipeline** | Orchestrates `extract → normalize → write` for one or more datasets. |
| **Registry** | Discovers the available sources/datasets so the CLI can run them. |

## `core/` modules

| Module | Responsibility |
|--------|-----------------|
| `config/` | Load and validate `settings.yaml` and `config/sources/*.yaml` (pydantic). |
| `http/` | Shared HTTP client: timeouts, per-second rate limit, exponential backoff on 5xx/timeouts (never on 4xx), three pagination styles: `offset_envelope` (BCRA), `start_count` (datos.gob.ar), `ckan`. `get_json` and `get_bytes` (files: CSV, XLSX, ZIP; accepts an absolute URL). |
| `extraction/` | The `Extractor` contract, `RawBatch` (JSON records **or** a polars `frame` for file sources), `Window` (time window + run date), `FormatChanged`, `check_schema` / `check_frame` (format monitoring). |
| `normalization/` | The `Normalizer` contract and the two canonical shapes: `to_series` / `to_table` over records, `frame_to_series` / `frame_to_table` over polars frames. `revisions.py` flags revisions by key. |
| `sink/` | Immutable Parquet writes (local, S3 or GCS via fsspec), a manifest per part, the append-only contract, the description. |
| `registry/` | Registry of sources/datasets; resolves "what to run". |
| `pipeline/` | One run per dataset: extract → format check → normalize → revisions → write → contract. Never raises: it always ends in a status. |
| `catalog/` | DuckDB database of views over what was written: `<source>__<dataset>`, `…__latest`, `signals__contracts` and the marts in `sql/marts/`. |
| `cli/` | Entry point (`typer`): `run <source>... [--dataset …] [--since …] [--until …] [--output …]`, `catalog`, `sql` and `list`. |

**Dependency rule:** `core/` never imports from `sources/`. Sources are discovered through the
registry (`importlib` by name). Enforced by `tests/core/test_boundaries.py`.

## Anatomy of a source (e.g. `bcra/`)

| File | Responsibility |
|--------|-----------------|
| `sources/<api>/__init__.py` | One `Extractor` and one `Normalizer` per source, exposed as `EXTRACTOR` and `NORMALIZER`. The extractor interprets the provider's envelope and builds raw records; the normalizer turns them into `series` or `table`. |
| `config/sources/<api>.yaml` | Which datasets exist, endpoint, `shape`, `natural_key`, pagination, `expected_schema`, provenance, declared freshness, description. |

## Immutability and partitioning

- Output is partitioned by **extraction date** (not by the data's own date). Every run writes a
  new partition. **A written partition is never overwritten**: a same-day re-run writes
  `part-N+1` and leaves `part-N` untouched.
- An upstream **revision** (same key, different value) overwrites nothing: it shows up in the new
  extraction with `revision_of=<previous extraction_date>`. The previous row is left as is.
  Consumers choose which one to use; this repo keeps both and flags them.
- Every dataset carries a **quality contract** (`_contract.json`, append-only, one entry per run,
  failed runs included) and a human-readable **description** (`_description.md`).
  The exact contract is in [`OUTPUT_LAYOUT.md`](OUTPUT_LAYOUT.md).

## Two canonical shapes

| `shape` | Own columns | Key used to detect revisions | Example |
|---------|------------------|--------------------------------|---------|
| `series` | `variable: str`, `ref_date: date`, `value: float64` | `(variable, ref_date)` | BCRA, datos.gob.ar |
| `table` | the raw record's columns, typed | `natural_key` declared in the YAML | pump prices, holidays |

Both also carry `source, dataset, extraction_date, extracted_at, provenance, revision_of`.

## Format monitoring

Each dataset declares an `expected_schema` in its YAML (raw record key, or file column → type).
Before normalizing, a sample of records (or the frame's columns) is compared against it. A
missing key, a changed type or a new key (unless `allow_new_columns: true`, for tables the agency
extends on purpose, such as the EPH) ends the run **without an exception**, with
`status=format_changed` in the contract and no data written. Earlier partitions are untouched.
Extractors also validate each response envelope (`require_keys`).

## Window: history once, incremental every day

`--since/--until` set the window. Without `--since`, a dataset with `lookback_days: N` requests
only the last N days (BCRA 45, FX quotes 30, observed weather 10); a dataset without
`lookback_days` downloads everything the agency publishes (full files, catalogs). The daily run
stays cheap and the history is downloaded once (`run bcra --since 1996-01-01`). Revisions are
detected on the keys that overlap with the previous extraction; `__latest` in the catalog merges
all extractions and keeps the most recent one per key. The pipeline passes the run date in
`Window.today`: extractors never read the clock.

## Run statuses

`ok` · `revised` (revisions were found) · `format_changed` · `failed` (HTTP or other error).
CLI exit code: 0 if everything is ok/revised, 2 if any `format_changed`, 1 if any `failed`.

## Configuration

Two levels, both under `config/`:

1. `settings.yaml` — global: output root (local path, `s3://` or `gs://`) and timezone.
2. `sources/<api>.yaml` — declarative: the source's datasets, endpoint, shape, pagination,
   window and description.

Datasets can be enabled/disabled and windows tuned without touching code.
