"""Shared HTTP client: rate limit, backoff retries on 5xx/timeout, pagination."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import structlog
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from teramot_signals.core.config import Pagination

log = structlog.get_logger(__name__)


class HttpError(Exception):
    """4xx: not retried."""


class RetryableHttpError(Exception):
    """5xx or timeout: retried with backoff."""


# style → (page size parameter name, offset parameter name)
_PAGE_PARAMS: dict[str, tuple[str, str]] = {
    "offset_envelope": ("limit", "offset"),  # BCRA: metadata.resultset.count
    "start_count": ("limit", "start"),  # datos.gob.ar: count
    "ckan": ("limit", "offset"),  # CKAN datastore_search: result.total
}


class HttpClient:
    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        rate_limit_per_second: float = 5.0,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        backoff_base_seconds: float = 1.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers=headers or {},
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=True,
        )
        self._min_interval = 1.0 / rate_limit_per_second if rate_limit_per_second > 0 else 0.0
        self._last_call = 0.0
        self._max_retries = max_retries
        self._backoff = backoff_base_seconds
        self._sleep = sleep

    def close(self) -> None:
        self._client.close()

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._min_interval:
            self._sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()

    def _get_once(self, path: str, params: dict[str, Any] | None, *, raw: bool = False) -> Any:
        self._throttle()
        try:
            resp = self._client.get(path, params=params)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise RetryableHttpError(f"{path}: {exc!r}") from exc
        if resp.status_code >= 500:
            raise RetryableHttpError(f"{path}: HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise HttpError(f"{path}: HTTP {resp.status_code}")
        return resp.content if raw else resp.json()

    def _retrying(self) -> Retrying:
        return Retrying(
            stop=stop_after_attempt(self._max_retries + 1),
            wait=wait_exponential(multiplier=self._backoff, min=0, max=30),
            retry=retry_if_exception_type(RetryableHttpError),
            sleep=self._sleep,
            reraise=True,
        )

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        for attempt in self._retrying():
            with attempt:
                return self._get_once(path, params)
        raise AssertionError("unreachable")

    def get_bytes(self, path: str, params: dict[str, Any] | None = None) -> bytes:
        """Downloads a file (CSV, XLSX, ZIP). `path` may be an absolute URL."""
        for attempt in self._retrying():
            with attempt:
                return self._get_once(path, params, raw=True)
        raise AssertionError("unreachable")

    def paginate(
        self,
        path: str,
        params: dict[str, Any],
        *,
        style: Pagination,
        page_limit: int,
        items_of: Callable[[Any], list[Any]],
        total_of: Callable[[Any], int | None],
    ) -> Iterator[Any]:
        """Yields each raw page. The caller extracts the items with `items_of`."""
        if style == "none":
            yield self.get_json(path, params)
            return
        limit_param, offset_param = _PAGE_PARAMS[style]
        offset = 0
        while True:
            page = self.get_json(path, {**params, limit_param: page_limit, offset_param: offset})
            items = items_of(page)
            yield page
            if not items:
                return
            offset += len(items)
            total = total_of(page)
            if total is not None:
                if offset >= total:
                    return
            elif len(items) < page_limit:
                return
