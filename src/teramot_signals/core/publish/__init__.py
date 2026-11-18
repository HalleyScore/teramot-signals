"""Builds the public, read-only copy of the datasets marked `publish: true`.

Layout under the destination (e.g. `s3://bucket/signals/v1`, served over HTTPS):

  latest/<source>__<dataset>.parquet   one row per key (the `__latest` view)
  latest/<source>__<dataset>.csv       same rows; text cells escaped against formula injection
  history/<source>__<dataset>.parquet  every extraction, revisions included
  signals.duckdb                       views over the files above, plus marts
  catalog.json                         per file: sha256, bytes, rows; per dataset: license

Everything is built and checked in a local staging folder first. Only then are the files
uploaded, `catalog.json` last, so a reader never sees a catalog that points at missing files.
A dataset that fails its checks keeps its previously published files and catalog entry.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import fsspec
from fsspec.implementations.local import LocalFileSystem

from teramot_signals.core.catalog import _empty_select, _lit, _q, _remote_setup, _root_uri
from teramot_signals.core.config import DatasetConfig, Redaction, Settings, SourceConfig
from teramot_signals.core.normalization import SERIES_KEY
from teramot_signals.core.registry import available_sources, load_source_config
from teramot_signals.core.sink import Sink

CATALOG_VERSION = 1
BASE_VARIABLE = "signals_base"
# CUIT prefixes assigned to natural persons; companies use 30, 33 and 34.
NATURAL_PERSON_CUIT_PREFIXES = ("20", "23", "24", "27")
_FORMULA_START = "^[=+\\-@\t\r]"
_CONTENT_TYPES = {
    ".parquet": "application/vnd.apache.parquet",
    ".csv": "text/csv; charset=utf-8",
    ".json": "application/json",
    ".duckdb": "application/octet-stream",
}


@dataclass
class PublishResult:
    published: list[str] = field(default_factory=list)
    blocked: dict[str, str] = field(default_factory=dict)
    carried_over: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    uploaded: list[str] = field(default_factory=list)
    staging: Path | None = None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_entry(staging: Path, rel: str) -> dict[str, Any]:
    p = staging / rel
    return {"path": rel, "sha256": _sha256(p), "bytes": p.stat().st_size}


def _natural_person(column: str) -> str:
    digits = f"regexp_replace(CAST({_q(column)} AS VARCHAR), '[^0-9]', '', 'g')"
    prefixes = ", ".join(_lit(p) for p in NATURAL_PERSON_CUIT_PREFIXES)
    return f"left({digits}, 2) IN ({prefixes})"


def _redacted_select(con: duckdb.DuckDBPyConnection, table: str, r: Redaction | None) -> str:
    if r is None:
        return f"SELECT * FROM {table}"
    present = {c for (c,) in con.execute(f"SELECT column_name FROM (DESCRIBE {table})").fetchall()}
    cols = [c for c in r.columns if c in present]
    if not cols:
        return f"SELECT * FROM {table}"
    cond = _natural_person(r.natural_person_cuit)
    swaps = ", ".join(f"CASE WHEN {cond} THEN NULL ELSE {_q(c)} END AS {_q(c)}" for c in cols)
    return f"SELECT * REPLACE ({swaps}) FROM {table}"


def _csv_select(con: duckdb.DuckDBPyConnection, table: str) -> str:
    """Text cells that a spreadsheet would run as a formula get a leading quote."""
    exprs: list[str] = []
    for name, typ in con.execute(
        f"SELECT column_name, column_type FROM (DESCRIBE {table})"
    ).fetchall():
        col = _q(name)
        if typ == "VARCHAR":
            exprs.append(
                f"CASE WHEN regexp_matches({col}, {_lit(_FORMULA_START)}) "
                f"THEN '''' || {col} ELSE {col} END AS {col}"
            )
        elif typ.endswith("[]") or typ.startswith(("STRUCT", "MAP", "JSON")):
            exprs.append(f"CAST(to_json({col}) AS VARCHAR) AS {col}")
        else:
            exprs.append(col)
    return f"SELECT {', '.join(exprs)} FROM {table}"


def _check(
    con: duckdb.DuckDBPyConnection, ds: DatasetConfig, latest: str, redacted: list[str]
) -> str | None:
    """None if the dataset may be published, else the reason it may not."""
    (rows,) = con.execute(f"SELECT count(*) FROM {latest}").fetchone() or (0,)
    if rows == 0:
        return "no rows"
    if ds.redact is not None and ds.redact.natural_person_cuit in redacted:
        (left,) = con.execute(
            f"SELECT count(*) FROM {latest} WHERE {_natural_person(ds.redact.natural_person_cuit)}"
        ).fetchone() or (0,)
        if left:
            return f"{left} natural-person CUITs left after redaction"
    if ds.shape == "series" and ds.max_change_pct is not None:
        jumps = con.execute(
            f"""
            WITH ranked AS (
                SELECT variable, value,
                       row_number() OVER (PARTITION BY variable ORDER BY ref_date DESC) AS rn
                FROM {latest} WHERE value IS NOT NULL
            )
            SELECT a.variable, round(abs(a.value - b.value) / abs(b.value) * 100, 1) AS pct
            FROM ranked a JOIN ranked b ON a.variable = b.variable AND a.rn = 1 AND b.rn = 2
            WHERE b.value <> 0 AND abs(a.value - b.value) / abs(b.value) * 100 > ?
            ORDER BY pct DESC LIMIT 5
            """,
            [ds.max_change_pct],
        ).fetchall()
        if jumps:
            detail = ", ".join(f"{v} {p}%" for v, p in jumps)
            return f"change above max_change_pct={ds.max_change_pct}: {detail}"
    return None


def _columns(con: duckdb.DuckDBPyConnection, table: str) -> list[dict[str, str]]:
    return [
        {"name": n, "type": t}
        for n, t in con.execute(
            f"SELECT column_name, column_type FROM (DESCRIBE {table})"
        ).fetchall()
    ]


def _stage_dataset(
    con: duckdb.DuckDBPyConnection,
    root: str,
    staging: Path,
    cfg: SourceConfig,
    name: str,
    ds: DatasetConfig,
    allow_implausible: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    source = cfg.source
    stem = f"{source}__{name}"
    files = f"{root}/source={source}/dataset={name}/extraction_date=*/part-*.parquet"
    key = SERIES_KEY if ds.shape == "series" else ds.natural_key
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE raw_hist AS SELECT * FROM read_parquet({_lit(files)}, "
        "union_by_name = true, hive_partitioning = false)"
    )
    con.execute(
        "CREATE OR REPLACE TEMP TABLE raw_latest AS SELECT * FROM raw_hist QUALIFY row_number() "
        f"OVER (PARTITION BY {', '.join(_q(k) for k in key)} ORDER BY extracted_at DESC) = 1"
    )
    redacted = list(ds.redact.columns) if ds.redact else []
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE pub_hist AS {_redacted_select(con, 'raw_hist', ds.redact)}"
    )
    pub_latest = _redacted_select(con, "raw_latest", ds.redact)
    con.execute(f"CREATE OR REPLACE TEMP TABLE pub_latest AS {pub_latest}")
    problem = _check(con, ds, "pub_latest", redacted)
    if problem and not (allow_implausible and problem.startswith("change above")):
        return None, problem

    rel = {
        "latest_parquet": f"latest/{stem}.parquet",
        "latest_csv": f"latest/{stem}.csv",
        "history_parquet": f"history/{stem}.parquet",
    }
    for d in ("latest", "history"):
        (staging / d).mkdir(parents=True, exist_ok=True)
    order = ", ".join(_q(k) for k in key)
    con.execute(
        f"COPY (SELECT * FROM pub_latest ORDER BY {order}) TO "
        f"{_lit(str(staging / rel['latest_parquet']))} (FORMAT parquet, COMPRESSION zstd)"
    )
    con.execute(
        f"COPY (SELECT * FROM pub_hist ORDER BY extraction_date, {order}) TO "
        f"{_lit(str(staging / rel['history_parquet']))} (FORMAT parquet, COMPRESSION zstd)"
    )
    con.execute(
        f"COPY ({_csv_select(con, 'pub_latest')} ORDER BY {order}) TO "
        f"{_lit(str(staging / rel['latest_csv']))} (FORMAT csv, HEADER)"
    )
    (latest_rows,) = con.execute("SELECT count(*) FROM pub_latest").fetchone() or (0,)
    (hist_rows,) = con.execute("SELECT count(*) FROM pub_hist").fetchone() or (0,)
    (last_extraction,) = con.execute("SELECT max(extraction_date) FROM pub_hist").fetchone() or (
        None,
    )
    entry: dict[str, Any] = {
        "source": source,
        "dataset": name,
        "shape": ds.shape,
        "provenance": ds.provenance,
        "description": ds.description.strip(),
        "license": cfg.license,
        "attribution": cfg.attribution,
        "terms_url": cfg.terms_url,
        "natural_key": key,
        "last_extraction_date": str(last_extraction) if last_extraction else None,
        "rows": {"latest": latest_rows, "history": hist_rows},
        "redacted_columns": redacted,
        "columns": _columns(con, "pub_latest"),
        "files": {k: _file_entry(staging, v) for k, v in rel.items()},
    }
    if problem:
        entry["warning"] = problem
    return entry, None


def _read_previous(dest: str) -> dict[str, Any]:
    fs, base = fsspec.core.url_to_fs(dest)
    path = f"{base.rstrip('/')}/catalog.json"
    if not fs.exists(path):
        return {}
    with fs.open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else {}


def _fetch(dest: str, rel: str, staging: Path) -> None:
    fs, base = fsspec.core.url_to_fs(dest)
    (staging / rel).parent.mkdir(parents=True, exist_ok=True)
    fs.get_file(f"{base.rstrip('/')}/{rel}", str(staging / rel))


def _build_duckdb(
    staging: Path,
    public_url: str,
    datasets: list[tuple[str, str, DatasetConfig]],
    entries: dict[str, dict[str, Any]],
    marts_dir: Path | None,
) -> list[str]:
    """Views read `getvariable('signals_base')`, defaulting to the public URL: the file can be
    attached remotely as is, or pointed at a local mirror with `SET VARIABLE signals_base`."""
    db = staging / "signals.duckdb"
    db.unlink(missing_ok=True)
    base = f"coalesce(getvariable({_lit(BASE_VARIABLE)}), {_lit(public_url.rstrip('/'))})"
    skipped: list[str] = []
    con = duckdb.connect(str(db))
    try:
        con.execute(f"SET VARIABLE {BASE_VARIABLE} = {_lit(str(staging))}")
        for source, name, ds in datasets:
            view = f"{source}__{name}"
            entry = entries.get(view)
            if entry:
                hist = entry["files"]["history_parquet"]["path"]
                latest = entry["files"]["latest_parquet"]["path"]
                con.execute(
                    f"CREATE VIEW {_q(view)} AS SELECT * FROM "
                    f"read_parquet({base} || {_lit('/' + hist)})"
                )
                con.execute(
                    f"CREATE VIEW {_q(view + '__latest')} AS SELECT * FROM "
                    f"read_parquet({base} || {_lit('/' + latest)})"
                )
            else:
                con.execute(f"CREATE VIEW {_q(view)} AS {_empty_select(ds)}")
                con.execute(f"CREATE VIEW {_q(view + '__latest')} AS {_empty_select(ds)}")
        for sql_file in sorted(marts_dir.glob("*.sql")) if marts_dir else []:
            try:
                con.execute(sql_file.read_text(encoding="utf-8"))
            except duckdb.Error as exc:
                skipped.append(f"mart {sql_file.stem}: {str(exc).splitlines()[0]}")
        con.execute(f"RESET VARIABLE {BASE_VARIABLE}")
    finally:
        con.close()
    return skipped


def _upload(staging: Path, dest: str, rels: list[str]) -> None:
    fs, base = fsspec.core.url_to_fs(dest)
    base = base.rstrip("/")
    remote = not isinstance(fs, LocalFileSystem)
    for rel in rels:
        target = f"{base}/{rel}"
        if not remote:
            fs.makedirs(target.rsplit("/", 1)[0], exist_ok=True)
        extra: dict[str, str] = {}
        if remote:
            extra = {
                "ContentType": _CONTENT_TYPES.get(Path(rel).suffix, "application/octet-stream"),
                "CacheControl": "public, max-age=300",
            }
        fs.put_file(str(staging / rel), target, **extra)


def publish(
    settings: Settings,
    staging: Path,
    public_url: str,
    *,
    dest: str | None = None,
    marts_dir: Path | None = None,
    allow_implausible: bool = False,
    now: datetime | None = None,
) -> PublishResult:
    """Stages the public copy in `staging`; uploads it to `dest` if given."""
    staging.mkdir(parents=True, exist_ok=True)
    for old in ("latest", "history"):
        for f in (staging / old).glob("*"):
            f.unlink()
    out = PublishResult(staging=staging)
    root = _root_uri(settings.output_root)
    sink = Sink(settings.output_root)
    previous = _read_previous(dest) if dest else {}
    prev_entries = {f"{e['source']}__{e['dataset']}": e for e in previous.get("datasets", [])}

    datasets: list[tuple[str, str, DatasetConfig]] = []
    entries: dict[str, dict[str, Any]] = {}
    fresh: list[str] = []
    con = duckdb.connect()
    try:
        _remote_setup(con, root)
        for source in available_sources(settings.config_dir):
            cfg = load_source_config(settings.config_dir, source)
            for name, ds in cfg.datasets.items():
                datasets.append((source, name, ds))
                if not ds.publish:
                    continue
                stem = f"{source}__{name}"
                if not sink.list_partitions(source, name):
                    out.missing.append(stem)
                    continue
                entry, problem = _stage_dataset(
                    con, root, staging, cfg, name, ds, allow_implausible
                )
                if entry is not None:
                    entries[stem] = entry
                    fresh += [f["path"] for f in entry["files"].values()]
                    out.published.append(stem)
                    continue
                out.blocked[stem] = problem or "unknown"
                prev = prev_entries.get(stem)
                if prev and dest:
                    for key in ("latest_parquet", "history_parquet"):
                        _fetch(dest, prev["files"][key]["path"], staging)
                    entries[stem] = prev
                    out.carried_over.append(stem)
    finally:
        con.close()

    skipped = _build_duckdb(staging, public_url, datasets, entries, marts_dir)
    if skipped:
        raise RuntimeError("; ".join(skipped))
    catalog = {
        "version": CATALOG_VERSION,
        "generated_at": (now or datetime.now(UTC)).isoformat(),
        "base_url": public_url.rstrip("/"),
        "notice": (
            "Each dataset keeps the license and terms of its publisher (see `license`, "
            "`attribution`, `terms_url`). Redistribute with attribution."
        ),
        "duckdb": _file_entry(staging, "signals.duckdb"),
        "datasets": [entries[k] for k in sorted(entries)],
    }
    (staging / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    if dest:
        rels = [*fresh, "signals.duckdb", "catalog.json"]
        _upload(staging, dest, rels)
        out.uploaded = rels
    return out
