# Adding a new public API

Adding an API is **additive**: a new package under `sources/` and a new YAML under
`config/sources/`. `core/` is not touched (a test enforces it).

## Steps

1. **Survey the API and write it down** in `docs/sources/<api>.md`: response envelope, keys and
   types of each record, pagination, whether it reports a total, time window, cadence, whether
   it revises past values, license and terms of use. That survey becomes the `expected_schema`.

2. **Declare the datasets** in `config/sources/<api>.yaml`:

   ```yaml
   source: <api>                     # must match the file name and the package name
   base_url: https://...
   rate_limit_per_second: 4
   license: "CC BY 4.0"              # as declared by the publisher
   attribution: "Source: ..."
   terms_url: https://...
   datasets:
     <dataset>:
       shape: series | table
       path: /path/{parameter}
       pagination: none | offset_envelope | start_count | ckan
       page_limit: 1000
       natural_key: [a, b]           # required when shape = table
       provenance: official | third_party
       declared_freshness: "..."
       revision_policy: "..."
       expected_schema: {key: str|int|number|bool|list|dict|date, ...}
       allow_new_columns: false      # true only if the agency adds columns on purpose
       lookback_days: 30             # without --since, request only the last N days
       options: {...}                # whatever the extractor needs (ids, variables, years)
       publish: false                # true only if the terms allow redistribution (see step 6)
       max_change_pct: 50            # series only: `publish` blocks larger moves
       redact:                       # only if rows can identify a natural person
         natural_person_cuit: cuit
         columns: [cuit, name]
       description: |
         What this table is, in plain words, with units.
   ```

3. **Write the source** in `src/teramot_signals/sources/<api>/__init__.py`: one class with
   `extract(client, name, ds, window) -> RawBatch` and another with
   `normalize(batch, name, ds) -> Normalized`, exposed as `EXTRACTOR` and `NORMALIZER`.
   - Use `client.get_json`, `client.paginate` or `client.get_bytes` (rate limiting, retries and
     pagination are handled; `get_bytes` accepts an absolute URL on another host).
   - File sources (CSV, XLSX, ZIP): return `RawBatch(records=[], frame=<polars>)`; the format is
     monitored by column and normalized with `frame_to_table` / `frame_to_series`.
   - For "today" use `window.reference()`, never `date.today()`, so runs are reproducible.
   - Validate the envelope with `require_keys`; if the API changed shape, raise `FormatChanged`.
   - Pass raw records through **as they arrive** (plus whatever you add), so `expected_schema`
     detects new upstream keys.
   - Normalize with `to_series(rows)` or `to_table(records, natural_key, date_columns)`.
   - If the dataset feeds a mart, add or adjust the SQL in `sql/marts/`.

4. **Fixture and test** in `tests/`: a real response JSON under `tests/fixtures/`, mocked with
   `respx`, and an end-to-end run with `run_source(...)`. No network.

5. **Try it live** once: `uv run teramot-signals run <api> --output /tmp/x`, inspect the Parquet,
   `_contract.json` and `_description.md`, and query it with `catalog --output /tmp/x` +
   `sql "select * from <api>__<dataset>__latest limit 5"`.

6. **Document the license** in `docs/DATA_LICENSES.md` and in the YAML (`license`,
   `attribution`, `terms_url`). Mark a dataset `publish: true` only if its terms allow
   redistribution and it holds no personal data (or `redact` removes it).

## Per-API checklist

- [ ] Does it require authentication? If so, the secret comes from the environment, never the repo.
- [ ] Declared or prudent rate limit? It goes in the YAML.
- [ ] Official source or aggregator? `provenance` says so and travels in every row and the contract.
- [ ] Terms of use read? Can it be redistributed? It goes in `docs/sources/<api>.md`.
- [ ] Personal or sensitive data? Not ingested by default.
- [ ] How does it paginate? Does it report a total? Time window?
- [ ] Does it revise past values? How would you find out? It goes in `revision_policy`.
- [ ] Complete `expected_schema`: every raw record key, with its type.

## What the core already gives you

Rate limiting, exponential backoff, three pagination styles, file downloads, format monitoring
(records or columns), two canonical shapes, incremental windows, revision detection, immutable
writes to local disk, S3 or GCS, manifests, the append-only contract, descriptions, a DuckDB
catalog with `__latest` views, and a CLI with per-status exit codes. A source only contributes
**which endpoints** and **how they are flattened**.
