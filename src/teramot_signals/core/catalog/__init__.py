"""DuckDB catalog over the written data: one view per dataset, its `__latest` and the SQL marts.

  <source>__<dataset>          every extraction (immutable history, revisions included)
  <source>__<dataset>__latest  one row per key: the one from the latest extraction
  signals__contracts           every entry of every `_contract.json`
  sql/marts/*.sql              derived views (e.g. `argentina_pulse`)

The database copies no data: they are views over the Parquet, local or remote.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from teramot_signals.core.config import DatasetConfig, Settings
from teramot_signals.core.normalization import SERIES_KEY
from teramot_signals.core.registry import available_sources, load_source_config
from teramot_signals.core.sink import Sink


@dataclass
class CatalogResult:
    views: list[str] = field(default_factory=list)
    marts: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _lit(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _root_uri(root: str) -> str:
    return root.rstrip("/") if "://" in root else str(Path(root).resolve())


_DUCK_TYPES = {
    "str": "VARCHAR",
    "int": "BIGINT",
    "number": "DOUBLE",
    "bool": "BOOLEAN",
    "date": "DATE",
    "list": "JSON",
    "dict": "JSON",
}
_COMMON = (
    ("source", "VARCHAR"),
    ("dataset", "VARCHAR"),
    ("extraction_date", "DATE"),
    ("extracted_at", "TIMESTAMPTZ"),
    ("provenance", "VARCHAR"),
    ("revision_of", "VARCHAR"),
)


def _empty_select(ds: DatasetConfig) -> str:
    """Empty view with the declared columns: marts compile even when a source is missing."""
    if ds.shape == "series":
        cols = [("variable", "VARCHAR"), ("ref_date", "DATE"), ("value", "DOUBLE")]
    else:
        cols = [(k, _DUCK_TYPES[t]) for k, t in ds.expected_schema.items()]
        cols += [(k, "VARCHAR") for k in ds.natural_key if k not in ds.expected_schema]
    cols += list(_COMMON)
    return "SELECT " + ", ".join(f"CAST(NULL AS {t}) AS {_q(c)}" for c, t in cols) + " WHERE false"


def _remote_setup(con: duckdb.DuckDBPyConnection, root: str) -> None:
    if root.startswith(("s3://", "gs://", "gcs://", "http://", "https://", "az://", "abfss://")):
        con.execute("INSTALL httpfs; LOAD httpfs;")
    if root.startswith("s3://"):
        con.execute("CREATE OR REPLACE SECRET signals_s3 (TYPE s3, PROVIDER credential_chain);")


def build_catalog(settings: Settings, db_path: str, marts_dir: Path | None) -> CatalogResult:
    root = _root_uri(settings.output_root)
    sink = Sink(settings.output_root)
    out = CatalogResult()
    con = duckdb.connect(db_path)
    try:
        _remote_setup(con, root)
        for source in available_sources(settings.config_dir):
            cfg = load_source_config(settings.config_dir, source)
            for name, ds in cfg.datasets.items():
                view = f"{source}__{name}"
                if sink.list_partitions(source, name):
                    files = (
                        f"{root}/source={source}/dataset={name}/extraction_date=*/part-*.parquet"
                    )
                    body = (
                        f"SELECT * FROM read_parquet({_lit(files)}, union_by_name = true, "
                        "hive_partitioning = false)"
                    )
                else:
                    out.skipped.append(f"{source}.{name}: no partitions (empty view)")
                    body = _empty_select(ds)
                con.execute(f"CREATE OR REPLACE VIEW {_q(view)} AS {body}")
                key = SERIES_KEY if ds.shape == "series" else ds.natural_key
                parts = ", ".join(_q(k) for k in key)
                con.execute(
                    f"CREATE OR REPLACE VIEW {_q(view + '__latest')} AS SELECT * FROM {_q(view)} "
                    f"QUALIFY row_number() OVER (PARTITION BY {parts} "
                    f"ORDER BY extracted_at DESC) = 1"
                )
                out.views += [view, view + "__latest"]
        contracts = f"{root}/source=*/dataset=*/_contract.json"
        try:
            con.execute(
                "CREATE OR REPLACE VIEW signals__contracts AS SELECT "
                "regexp_extract(filename, 'source=([^/]+)', 1) AS source, "
                "regexp_extract(filename, 'dataset=([^/]+)', 1) AS dataset, * EXCLUDE (filename) "
                f"FROM read_json_auto({_lit(contracts)}, format = 'array', filename = true, "
                "union_by_name = true)"
            )
            out.views.append("signals__contracts")
        except duckdb.Error as exc:
            out.skipped.append(f"signals__contracts: {exc}")
        for sql_file in sorted(marts_dir.glob("*.sql")) if marts_dir else []:
            try:
                con.execute(sql_file.read_text(encoding="utf-8"))
                out.marts.append(sql_file.stem)
            except duckdb.Error as exc:
                out.skipped.append(f"mart {sql_file.stem}: {str(exc).splitlines()[0]}")
    finally:
        con.close()
    return out
