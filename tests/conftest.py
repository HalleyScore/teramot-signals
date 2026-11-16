"""Shared fixtures: test config, local sink, no-wait client, fixed `now`."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from teramot_signals.core.config import Settings
from teramot_signals.core.http import HttpClient
from teramot_signals.core.sink import Sink

FIXTURES = Path(__file__).parent / "fixtures"
REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"
TZ = ZoneInfo("America/Argentina/Buenos_Aires")


def fixture_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(output_root=str(tmp_path / "data"), config_dir=REPO_CONFIG)


@pytest.fixture
def sink(settings: Settings) -> Sink:
    return Sink(settings.output_root)


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 9, 14, 19, 0, tzinfo=TZ)


@pytest.fixture
def next_day(now: datetime) -> datetime:
    return now.replace(day=15)


def fast_client(base_url: str) -> HttpClient:
    """No rate limit and no sleep between retries, so tests never wait."""
    return HttpClient(base_url, rate_limit_per_second=0, max_retries=2, sleep=lambda _s: None)
