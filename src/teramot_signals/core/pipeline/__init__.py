"""One run: extract → format check → normalize → revisions → write → contract.

Never raises: every outcome ends in a contract status.
`status ∈ {ok, revised, format_changed, failed}`. The contract is ALWAYS written,
even when the run failed before extracting a single row ("silence is not green").
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog

from teramot_signals.core.config import DatasetConfig, Settings, SourceConfig
from teramot_signals.core.extraction import (
    Extractor,
    FormatChanged,
    Window,
    check_frame,
    check_schema,
)
from teramot_signals.core.http import HttpClient
from teramot_signals.core.normalization import SERIES_KEY, Normalizer, finalize
from teramot_signals.core.registry import load_plugin, load_source_config
from teramot_signals.core.revisions import mark_revisions
from teramot_signals.core.sink import Sink

log = structlog.get_logger(__name__)

STATUS_OK = "ok"
STATUS_REVISED = "revised"
STATUS_FORMAT_CHANGED = "format_changed"
STATUS_FAILED = "failed"


@dataclass
class RunResult:
    source: str
    dataset: str
    status: str
    extraction_date: str
    rows_written: int = 0
    rows_rejected: int = 0
    revisions: list[dict[str, Any]] = field(default_factory=list)
    format_diff: list[str] = field(default_factory=list)
    error: str | None = None
    partition: str | None = None


def run_dataset(
    src: SourceConfig,
    name: str,
    ds: DatasetConfig,
    *,
    client: HttpClient,
    extractor: Extractor,
    normalizer: Normalizer,
    sink: Sink,
    now: datetime,
    window: Window,
) -> RunResult:
    extraction_date = now.date()
    result = RunResult(
        source=src.source,
        dataset=name,
        status=STATUS_FAILED,
        extraction_date=extraction_date.isoformat(),
    )
    endpoint = ds.path
    params: dict[str, Any] = {}
    descriptions: dict[str, str] = {}
    since = window.since
    if since is None and ds.lookback_days is not None:
        since = extraction_date - timedelta(days=ds.lookback_days)
    window = Window(since=since, until=window.until, today=extraction_date)
    try:
        batch = extractor.extract(client, name, ds, window)
        endpoint, params, descriptions = batch.endpoint, batch.params, batch.descriptions
        if batch.frame is not None:
            diff = check_frame(batch.frame, ds.expected_schema, allow_new=ds.allow_new_columns)
        else:
            diff = check_schema(batch.records, ds.expected_schema)
        if diff:
            raise FormatChanged(diff)
        norm = normalizer.normalize(batch, name, ds)
        df = finalize(
            norm.df,
            source=src.source,
            dataset=name,
            extraction_date=extraction_date,
            extracted_at=now,
            provenance=ds.provenance,
        )
        key = SERIES_KEY if ds.shape == "series" else ds.natural_key
        prev, prev_date = sink.latest_previous(src.source, name, extraction_date)
        df, revisions = mark_revisions(df, prev, key, prev_date)
        manifest = {
            "source": src.source,
            "dataset": name,
            "extraction_date": extraction_date.isoformat(),
            "extracted_at": now.isoformat(),
            "endpoint": endpoint,
            "params": params,
            "shape": ds.shape,
            "natural_key": key,
            "provenance": ds.provenance,
            "compared_against": prev_date,
        }
        result.partition = sink.write_partition(df, src.source, name, extraction_date, manifest)
        result.rows_written = df.height
        result.rows_rejected = len(norm.rejected)
        result.revisions = revisions
        result.status = STATUS_REVISED if revisions else STATUS_OK
    except FormatChanged as exc:
        result.status = STATUS_FORMAT_CHANGED
        result.format_diff = exc.diff
        log.warning("format_changed", source=src.source, dataset=name, diff=exc.diff)
    except Exception as exc:
        result.status = STATUS_FAILED
        result.error = f"{type(exc).__name__}: {exc}"
        log.error("failed", source=src.source, dataset=name, error=result.error)

    history = sink.read_contract(src.source, name)
    last_ok = next(
        (
            e.get("extraction_date")
            for e in reversed(history)
            if e.get("status") in (STATUS_OK, STATUS_REVISED)
        ),
        None,
    )
    entry = {
        "run_at": now.isoformat(),
        "extraction_date": result.extraction_date,
        "status": result.status,
        "shape": ds.shape,
        "natural_key": SERIES_KEY if ds.shape == "series" else ds.natural_key,
        "provenance": ds.provenance,
        "declared_freshness": ds.declared_freshness,
        "revision_policy": ds.revision_policy,
        "last_attempt": now.isoformat(),
        "last_successful_extraction": result.extraction_date
        if result.status in (STATUS_OK, STATUS_REVISED)
        else last_ok,
        "rows_written": result.rows_written,
        "rows_rejected": result.rows_rejected,
        "revisions_detected": result.revisions,
        "format_changes_detected": result.format_diff,
        "error": result.error,
        "endpoint": endpoint,
        "partition": result.partition,
    }
    sink.append_contract(src.source, name, entry)
    text = ds.description.strip()
    if descriptions:
        text = "\n\n".join([text, *descriptions.values()]).strip()
    if text:
        sink.write_description(src.source, name, text + "\n")
    log.info("run", **{k: v for k, v in asdict(result).items() if k not in ("revisions",)})
    return result


def run_source(
    settings: Settings,
    source: str,
    *,
    datasets: list[str] | None = None,
    window: Window | None = None,
    now: datetime | None = None,
    sink: Sink | None = None,
    client: HttpClient | None = None,
) -> list[RunResult]:
    src = load_source_config(settings.config_dir, source)
    extractor, normalizer = load_plugin(source)
    sink = sink or Sink(settings.output_root)
    now = now or datetime.now(ZoneInfo(settings.timezone))
    window = window or Window()
    own_client = client is None
    client = client or HttpClient(
        src.base_url,
        headers=src.headers,
        rate_limit_per_second=src.rate_limit_per_second,
        timeout_seconds=src.timeout_seconds,
        max_retries=src.max_retries,
    )
    results: list[RunResult] = []
    try:
        for name, ds in src.datasets.items():
            if not ds.enabled or (datasets and name not in datasets):
                continue
            results.append(
                run_dataset(
                    src,
                    name,
                    ds,
                    client=client,
                    extractor=extractor,
                    normalizer=normalizer,
                    sink=sink,
                    now=now,
                    window=window,
                )
            )
    finally:
        if own_client:
            client.close()
    return results


def exit_code(results: list[RunResult]) -> int:
    """0 all ok/revised · 2 any format_changed · 1 any failed."""
    statuses = {r.status for r in results}
    if STATUS_FAILED in statuses:
        return 1
    if STATUS_FORMAT_CHANGED in statuses:
        return 2
    return 0
