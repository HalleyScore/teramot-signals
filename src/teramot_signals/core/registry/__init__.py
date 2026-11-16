"""Source discovery by name. The core never imports `sources` statically."""

from __future__ import annotations

import importlib
from pathlib import Path

from teramot_signals.core.config import SourceConfig, load_source
from teramot_signals.core.extraction import Extractor
from teramot_signals.core.normalization import Normalizer


def load_plugin(source: str) -> tuple[Extractor, Normalizer]:
    """Each `sources/<source>/__init__.py` exposes `EXTRACTOR` and `NORMALIZER`."""
    module = importlib.import_module(f"teramot_signals.sources.{source}")
    return module.EXTRACTOR, module.NORMALIZER


def load_source_config(config_dir: Path, source: str) -> SourceConfig:
    path = config_dir / "sources" / f"{source}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"source config not found: {path}")
    cfg = load_source(path)
    if cfg.source != source:
        raise ValueError(f"{path}: `source: {cfg.source}` does not match the file name")
    return cfg


def available_sources(config_dir: Path) -> list[str]:
    d = config_dir / "sources"
    return sorted(p.stem for p in d.glob("*.yaml")) if d.exists() else []
