# `core/` — source-agnostic framework

Mechanics shared by every public API. **Never imports from `sources/`** (a test enforces it).

| Module | Responsibility |
|--------|----------------|
| `config/` | `settings.yaml` + `config/sources/*.yaml` validated with pydantic (`shape`, `natural_key`, `expected_schema`, …). |
| `http/` | httpx client: rate limit, backoff on 5xx/timeout (never 4xx), `offset_envelope` / `start_count` / `ckan` pagination, `get_bytes` for files. |
| `extraction/` | `Extractor`, `RawBatch` (records or `frame`), `Window` (window + `today`), `FormatChanged`, `check_schema`, `check_frame`, `require_keys`. |
| `normalization/` | `to_series`, `to_table`, `frame_to_series`, `frame_to_table`, `finalize` (provenance columns). |
| `revisions.py` | `mark_revisions`: same key, different value → `revision_of`. The previous row is never touched. |
| `sink/` | Immutable Parquet (`part-N+1`, never overwrite), manifest, append-only `_contract.json`, `_description.md`. Local, S3 or GCS via fsspec. |
| `registry/` | Loads a source's YAML and package by name (`importlib`). |
| `pipeline/` | `run_dataset` / `run_source`: window (`lookback_days`) → extract → check → normalize → revisions → write → contract. Never raises. |
| `catalog/` | `build_catalog`: DuckDB views `<source>__<dataset>`, `__latest`, `signals__contracts`, marts. |
| `cli/` | `teramot-signals run <source>... [--dataset] [--since] [--until] [--output]` · `catalog` · `sql` · `list`. Exit 0/2/1. |

Full design in `docs/ARCHITECTURE.md`.
