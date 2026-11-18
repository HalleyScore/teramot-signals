# Output contract (local disk, S3 or GCS)

This is the repo's boundary: the only thing `teramot-signals run` produces. Any engine that reads
Hive-partitioned Parquet (DuckDB, Spark, Athena/Glue, BigQuery, Trino, pandas/polars) consumes it
as is; `teramot-signals catalog` also builds a DuckDB database ready to query (see
"DuckDB catalog" below).

## Format

- **Parquet** (columnar), `snappy` compression.
- One **table per dataset**. Two canonical shapes: `series` and `table` (see `ARCHITECTURE.md`).
- The destination is a local path (`data/`) or a URI such as `s3://bucket/prefix`
  (`output_root` in `config/settings.yaml`, `SIGNALS_OUTPUT_ROOT` or `--output`). Same layout in
  every case.

## Key layout (Hive partitioning)

```
<root>/
  source=<source>/
    dataset=<dataset>/
      _contract.json                      # quality contract, append-only, one entry per run
      _description.md                     # what the table is, in plain words, for a modeler
      extraction_date=YYYY-MM-DD/
        part-0.parquet
        part-0.manifest.json
        part-1.parquet                    # only if there was a same-day re-run
        part-1.manifest.json
```

Real example (run of 2026-09-14):

```
source=bcra/dataset=monetary_series/extraction_date=2026-09-14/part-0.parquet               163 rows
source=bcra/dataset=fx_quotes/extraction_date=2026-09-14/part-0.parquet                      78 rows
source=datos_gob_ar/dataset=series/extraction_date=2026-09-14/part-0.parquet
source=energia_ckan/dataset=pump_prices_current/extraction_date=2026-09-14/part-0.parquet  36,669 rows
source=argentinadatos/dataset=holidays/extraction_date=2026-09-14/part-0.parquet             19 rows
```

The `key=value` style lets Glue/Athena, Spark, DuckDB or BigQuery (external tables) discover the
partitions (`source`, `dataset`, `extraction_date`) on their own.

## Partition = extraction date, never overwritten

Partitions reflect **when we downloaded it**, not the data's date. The business date
(`ref_date`, `fecha`, `indice_tiempo`, …) stays a **column**.

- Each run writes to the `extraction_date=<today>` partition.
- **A written partition is immutable.** A same-day re-run writes `part-N+1`; `part-N` stays
  byte-identical. Enforced by a test.
- This answers "what did the agency say on day X", not only "what does it say today".

## Revisions

A **revision** is the same key (`(variable, ref_date)` for `series`; the `natural_key` for
`table`) with a different value than in the most recent previous extraction. The new row carries
`revision_of = <previous extraction_date>`; the previous row is untouched. The contract lists the
revised keys in `revisions_detected`. This repo does **not** reconcile or pick the correct value:
it keeps both and flags them. The consumer decides.

## Per-part manifest

`part-N.manifest.json`:

```json
{
  "source": "bcra",
  "dataset": "monetary_series",
  "extraction_date": "2026-09-14",
  "extracted_at": "2026-09-14T15:53:45-03:00",
  "endpoint": "/estadisticas/v4.0/Monetarias/{id_variable}",
  "params": {"desde": "2026-08-01"},
  "shape": "series",
  "natural_key": ["variable", "ref_date"],
  "provenance": "official",
  "compared_against": "2026-09-13",
  "part": 0,
  "row_count": 163
}
```

`params` are the upstream API's own query parameters, as sent.

## Quality contract (`_contract.json`)

A JSON list, **append-only**: one entry per run, including runs that failed before extracting a
single row ("silence is not green").

| Field | Meaning |
|---|---|
| `status` | `ok` · `revised` · `format_changed` · `failed` |
| `provenance` | `official` (the agency itself) · `third_party` (an aggregator or a third party) |
| `shape`, `natural_key` | The shape and the key used to detect revisions |
| `declared_freshness` | The cadence the agency declares, in words |
| `revision_policy` | What is known about how the agency revises, or `unknown` |
| `last_attempt`, `last_successful_extraction` | When it was last attempted and last succeeded |
| `rows_written`, `rows_rejected` | Rows written and rows dropped (no date or non-numeric value) |
| `revisions_detected` | Keys whose value changed since the previous extraction |
| `format_changes_detected` | Differences against the YAML's `expected_schema` |
| `error` | Reason for `failed`, if any |
| `endpoint`, `partition` | What was called and where it was written |

## Description (`_description.md`)

Plain-language text about the table and each variable, so a modeler does not have to reason
about cryptic agency codes. It comes from the source's YAML; datos.gob.ar fills it in from the
API's own metadata.

## Column conventions

- `snake_case`.
- Every row carries `source`, `dataset`, `extraction_date`, `extracted_at`, `provenance`, `revision_of`.
- In `series`: `variable: str`, `ref_date: date`, `value: float64`.
- In `table`: the raw record's columns (for API sources, as published upstream, so some are in
  Spanish); those declared as `date` in `expected_schema` are cast to `date`.
- Units: in the dataset's `_description.md`.

## DuckDB catalog (`teramot-signals catalog`)

A DuckDB database **with no data copied**: only views over the Parquet (local, or remote via
`httpfs`).

| View | Contents |
|---|---|
| `<source>__<dataset>` | Every extraction: the immutable history, revisions included |
| `<source>__<dataset>__latest` | One row per key (`(variable, ref_date)` or `natural_key`): the one from the most recent extraction |
| `signals__contracts` | Every entry of every `_contract.json` (monitoring: status, rows, revisions, errors) |
| `sql/marts/*.sql` | Derived views; currently `argentina_pulse` |

A declared dataset with no partitions yet shows up as an **empty view with its columns** (taken
from `expected_schema`), so marts compile even if a source has not run.

Use `__latest` for "today's value": a daily load that is re-run, or a series downloaded in full
every day, does not duplicate rows, because the view keeps the latest extraction for each key.
The full history stays in the unsuffixed view.

## Public copy (`teramot-signals publish`)

A read-only copy for people who do not want to run the extractors. Only datasets marked
`publish: true` in their YAML are included; the private output root keeps everything.

```
<dest>/
  catalog.json                          # what is published: license, attribution, columns, rows,
                                        # last extraction, and sha256 + bytes of every file
  signals.duckdb                        # views over the files below, plus the marts
  latest/<source>__<dataset>.parquet    # one row per key (same as the `__latest` view)
  latest/<source>__<dataset>.csv        # same rows; text starting with = + - @ gets a leading '
  history/<source>__<dataset>.parquet   # every extraction, revisions included
```

- **Built locally first.** Everything is written to `--staging` and checked there; then the files
  are uploaded to `--dest` (`SIGNALS_PUBLISH_DEST`), `catalog.json` last.
- **Checks.** A dataset with no rows, a series that moves more than `max_change_pct` between its
  last two dates, or a redaction that left a natural-person CUIT behind is **blocked**: it keeps
  its previously published files and catalog entry, and the command exits `1`.
  `--allow-implausible` publishes a large move after checking it by hand.
- **Redaction.** `redact` nulls the listed columns on rows whose CUIT belongs to a natural person
  (prefixes 20, 23, 24, 27), in both `latest` and `history`.
- **DuckDB file.** Its views read `getvariable('signals_base')`, defaulting to `--public-url`:

  ```sql
  ATTACH '<public-url>/signals.duckdb' AS signals (READ_ONLY);
  SELECT * FROM signals.bcra__fx_quotes__latest;
  -- a local mirror of <dest>: SET VARIABLE signals_base = '/path/to/mirror';
  ```

  Datasets that are not published are empty views with their columns, so marts still compile.

## Out of scope

Business joins (sales in dollars per business day, prices against CPI, freight against diesel)
belong to the consumer. The marts in `sql/marts/` are reading examples, not a model.
**Mind the refresh:** if another tool copies these tables, it must re-read them daily; otherwise
it keeps last week's exchange rate with no signal that it is stale.
