# tests

Everything runs **offline**: APIs are mocked with `respx` over real responses saved in
`fixtures/` or over small files built inside the test (CSV, EPH ZIP, INDEC sheets).

| File | What it guards |
|---|---|
| `core/test_http.py` | Retries 5xx and timeouts, never 4xx; the three pagination styles |
| `core/test_sink_and_revisions.py` | Same-day re-run → `part-1`, `part-0` byte-identical; per-key revision in `series` and `table`; append-only contract |
| `core/test_pipeline.py` | JSON sources end to end; next-day revision; a format change ends cleanly without writing data; an HTTP failure writes the contract and no data; the written tree follows the layout |
| `core/test_boundaries.py` | `core/` never imports `sources/`; every YAML has its package and vice versa |
| `core/test_catalog.py` | `__latest` keeps one row per key across runs; full history is kept; empty views for datasets without data; `argentina_pulse` compiles; `signals__contracts` |
| `sources/test_file_sources.py` | Georef (leading zeros, new column = format change); `sspm` (one CSV per distribution, missing column = format change); batched Open-Meteo; INDEC sheets (blocks, unknown label); EPH (unpublished quarter as HTML 200, changing columns, decimal comma); UNR dictionary |

`make test` → `uv run pytest`. `make check` also runs ruff and basedpyright.
