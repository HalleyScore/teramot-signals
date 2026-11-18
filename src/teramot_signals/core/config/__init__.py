"""Loading and validation of `settings.yaml` and `config/sources/<source>.yaml`."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

Shape = Literal["series", "table"]
Provenance = Literal["official", "third_party"]
Pagination = Literal["none", "offset_envelope", "start_count", "ckan"]

# Types allowed in `expected_schema` (raw record key → type).
SCHEMA_TYPES = ("str", "int", "number", "bool", "list", "dict", "date")


class Redaction(BaseModel):
    """Rows whose `natural_person_cuit` is a natural person's CUIT get `columns` nulled."""

    natural_person_cuit: str
    columns: list[str]


class DatasetConfig(BaseModel):
    enabled: bool = True
    shape: Shape
    path: str
    description: str = ""
    provenance: Provenance = "official"
    declared_freshness: str = "unknown"
    revision_policy: str = "unknown"
    natural_key: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    pagination: Pagination = "none"
    page_limit: int = 1000
    expected_schema: dict[str, str] = Field(default_factory=dict)
    # Tables the agency widens over time (EPH): a new column is not format_changed.
    allow_new_columns: bool = False
    # Without --since, the run requests only the last N days (incremental). None = everything.
    lookback_days: int | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    # `publish` command: only datasets marked `publish: true` leave the private output root.
    publish: bool = False
    redact: Redaction | None = None
    # Series only: block publication if any variable moves more than this between its last two
    # dates. Guards the hosted copy against a corrupt or tampered upstream response.
    max_change_pct: float | None = None

    @model_validator(mode="after")
    def _check(self) -> DatasetConfig:
        if self.shape == "table" and not self.natural_key:
            raise ValueError("a `table`-shaped dataset needs `natural_key`")
        bad = [f"{k}: {v}" for k, v in self.expected_schema.items() if v not in SCHEMA_TYPES]
        if bad:
            raise ValueError(f"unsupported types in expected_schema: {bad}")
        if self.max_change_pct is not None and self.shape != "series":
            raise ValueError("`max_change_pct` only applies to `series` datasets")
        return self


class SourceConfig(BaseModel):
    source: str
    base_url: str
    description: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    rate_limit_per_second: float = 5.0
    timeout_seconds: float = 30.0
    max_retries: int = 3
    license: str = ""
    attribution: str = ""
    terms_url: str = ""
    datasets: dict[str, DatasetConfig]


class Settings(BaseModel):
    # Local path (`data`) or fsspec URI (`s3://`, `gs://`, …). Env: SIGNALS_OUTPUT_ROOT.
    output_root: str = "data"
    timezone: str = "America/Argentina/Buenos_Aires"
    config_dir: Path = Path("config")


def load_source(path: Path) -> SourceConfig:
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return SourceConfig.model_validate(raw)


def load_settings(config_dir: Path, output_root: str | None = None) -> Settings:
    raw: dict[str, Any] = {}
    settings_file = config_dir / "settings.yaml"
    if settings_file.exists():
        with settings_file.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    root = output_root or os.environ.get("SIGNALS_OUTPUT_ROOT") or raw.get("output_root")
    tz = raw.get("timezone")
    return Settings(
        output_root=root or "data",
        timezone=tz or "America/Argentina/Buenos_Aires",
        config_dir=config_dir,
    )
