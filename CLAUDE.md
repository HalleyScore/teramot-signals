# CLAUDE.md — teramot-signals

Guidance for Claude Code when working in this repo.

## What it is

An open-source (Apache-2.0) ingestion framework for **Argentine public data**. It downloads public
APIs and files (BCRA, datos.gob.ar, INDEC, Georef, Energía, Open-Meteo, UNR, ArgentinaDatos),
**normalizes them to immutable Parquet** partitioned by extraction date (local, S3 or GCS) and
builds a **DuckDB catalog** (a view per dataset, `__latest`, contracts and marts in `sql/marts/`).

It depends on no commercial product: anyone must be able to clone it, run it and query it on
their own machine. It does no business modeling; the marts are reading examples.

## Status

Eight sources, 21 datasets; tests run without network. Verify with `make check` before claiming
anything works.

## Rules the tests enforce (do not erode them)

- A written partition is **never** overwritten: a same-day re-run → `part-N+1`.
- A revision is **flagged** (`revision_of`), never overwritten. This repo does not pick the right value.
- A format change ends the run **without an exception**, with `format_changed` and no data.
- The contract is **always** written, including on `failed`.
- `core/` never imports from `sources/`. Every YAML has its package and vice versa.
- `provenance` (`official` | `third_party`) travels in every row, the manifest and the contract.
- `__latest` keeps one row per key; the unsuffixed view keeps the full history.
- Extractors use `window.reference()` as "today", never `date.today()`.

## Architecture (summary)

- `core/` — source-agnostic: HTTP (rate limit, retries, pagination, `get_bytes`), extractor
  contract (JSON records or a polars `frame`), normalization, revisions, fsspec sink, registry,
  pipeline (incremental window via `lookback_days`), DuckDB catalog, CLI.
- `sources/<api>/` — one connector per source. `EXTRACTOR` + `NORMALIZER`.
- `sql/marts/` — derived views over the catalog.

Design: `docs/ARCHITECTURE.md`. Adding a source: `docs/ADDING_A_SOURCE.md`.
Output contract: `docs/OUTPUT_LAYOUT.md`. Data licenses: `docs/DATA_LICENSES.md`.

## Conventions

- **uv**, **ruff**, **basedpyright**, **pytest**. `make check` before calling anything done.
- `src/` layout; the importable package is `teramot_signals`.
- Config is YAML under `config/`. Never commit `config/settings.yaml` or `.env` (only the
  `*.example` files). Data, DuckDB files and logs go to `data/`, `*.duckdb` and `logs/`
  (gitignored), never into the repo.
- Secrets come from the environment, never hardcoded.
- Respect each provider's rate limit (set in the YAML) and terms (`DATA_LICENSES.md`).
- Everything (code, docs, messages) is in English. Upstream column names and values are passed
  through as published.
