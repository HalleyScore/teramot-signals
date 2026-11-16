"""HTTP client: three pagination styles, retries 5xx and timeouts, never 4xx."""

from __future__ import annotations

import httpx
import pytest
import respx

from teramot_signals.core.http import HttpError, RetryableHttpError
from tests.conftest import fast_client

BASE = "https://api.test"


@respx.mock
def test_retries_5xx_then_succeeds() -> None:
    route = respx.get(f"{BASE}/x").mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json={"ok": True})]
    )
    assert fast_client(BASE).get_json("/x") == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_does_not_retry_4xx() -> None:
    route = respx.get(f"{BASE}/x").mock(return_value=httpx.Response(404))
    with pytest.raises(HttpError):
        fast_client(BASE).get_json("/x")
    assert route.call_count == 1


@respx.mock
def test_gives_up_after_max_retries() -> None:
    route = respx.get(f"{BASE}/x").mock(side_effect=httpx.ReadTimeout("t"))
    with pytest.raises(RetryableHttpError):
        fast_client(BASE).get_json("/x")
    assert route.call_count == 3  # 1 attempt + 2 retries


@respx.mock
def test_paginate_offset_envelope_stops_at_count() -> None:
    def page(offset: int, n: int) -> dict:
        return {
            "metadata": {"resultset": {"count": 5, "offset": offset, "limit": 2}},
            "results": [{"detalle": [{"i": offset + k} for k in range(n)]}],
        }

    respx.get(f"{BASE}/s", params={"limit": 2, "offset": 0}).mock(
        return_value=httpx.Response(200, json=page(0, 2))
    )
    respx.get(f"{BASE}/s", params={"limit": 2, "offset": 2}).mock(
        return_value=httpx.Response(200, json=page(2, 2))
    )
    respx.get(f"{BASE}/s", params={"limit": 2, "offset": 4}).mock(
        return_value=httpx.Response(200, json=page(4, 1))
    )
    pages = list(
        fast_client(BASE).paginate(
            "/s",
            {},
            style="offset_envelope",
            page_limit=2,
            items_of=lambda p: p["results"][0]["detalle"],
            total_of=lambda p: p["metadata"]["resultset"]["count"],
        )
    )
    assert [len(p["results"][0]["detalle"]) for p in pages] == [2, 2, 1]


@respx.mock
def test_paginate_start_count_and_ckan_use_their_own_params() -> None:
    respx.get(f"{BASE}/t", params={"limit": 2, "start": 0}).mock(
        return_value=httpx.Response(200, json={"data": [[1], [2]], "count": 3})
    )
    respx.get(f"{BASE}/t", params={"limit": 2, "start": 2}).mock(
        return_value=httpx.Response(200, json={"data": [[3]], "count": 3})
    )
    got = list(
        fast_client(BASE).paginate(
            "/t",
            {},
            style="start_count",
            page_limit=2,
            items_of=lambda p: p["data"],
            total_of=lambda p: p["count"],
        )
    )
    assert len(got) == 2

    respx.get(f"{BASE}/c", params={"limit": 2, "offset": 0}).mock(
        return_value=httpx.Response(200, json={"result": {"total": 2, "records": [{}, {}]}})
    )
    got = list(
        fast_client(BASE).paginate(
            "/c",
            {},
            style="ckan",
            page_limit=2,
            items_of=lambda p: p["result"]["records"],
            total_of=lambda p: p["result"]["total"],
        )
    )
    assert len(got) == 1  # offset reached total: no empty page requested
