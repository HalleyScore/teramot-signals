"""Guards the dependency rule: `core/` never imports from `sources/`."""

from __future__ import annotations

import ast
from pathlib import Path

CORE = Path(__file__).resolve().parents[2] / "src" / "teramot_signals" / "core"


def test_core_never_imports_sources() -> None:
    offenders: list[str] = []
    for py in CORE.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n.startswith("teramot_signals.sources") for n in names):
                offenders.append(str(py))
    assert offenders == []


def test_every_source_config_has_a_plugin_and_vice_versa() -> None:
    root = Path(__file__).resolve().parents[2]
    configs = {p.stem for p in (root / "config" / "sources").glob("*.yaml")}
    plugins = {
        p.name
        for p in (root / "src" / "teramot_signals" / "sources").iterdir()
        if p.is_dir() and (p / "__init__.py").exists()
    }
    assert configs == plugins
