"""End to end with the four JSON sources over local fixtures, offline."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import httpx
import respx
import yaml

from teramot_signals.core.config import Settings
from teramot_signals.core.pipeline import exit_code, run_source
from teramot_signals.core.sink import Sink
from tests.conftest import REPO_CONFIG, fast_client, fixture_json

BCRA = "https://api.bcra.gob.ar"
DGA = "https://apis.datos.gob.ar"
ENE = "http://datos.energia.gob.ar"
ADS = "https://api.argentinadatos.com"


_BCRA_LABELS = yaml.safe_load((REPO_CONFIG / "sources" / "bcra.yaml").read_text())["datasets"][
    "monetary_series"
]["options"]["variables"]
BCRA_VARIABLES = [int(v) for v in _BCRA_LABELS]
RESERVES_LABEL = str(_BCRA_LABELS[1])


def _mock_bcra() -> None:
    respx.get(f"{BCRA}/estadisticas/v4.0/Monetarias/1").mock(
        return_value=httpx.Response(200, json=fixture_json("bcra_monetarias_1.json"))
    )
    for vid in [v for v in BCRA_VARIABLES if v != 1]:
        respx.get(f"{BCRA}/estadisticas/v4.0/Monetarias/{vid}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": 200,
                    "metadata": {"resultset": {"count": 1, "offset": 0, "limit": 1000}},
                    "results": [
                        {
                            "idVariable": vid,
                            "detalle": [{"fecha": "2026-09-11", "valor": vid * 1.5}],
                        }
                    ],
                },
            )
        )
    respx.get(f"{BCRA}/estadisticascambiarias/v1.0/Cotizaciones").mock(
        return_value=httpx.Response(200, json=fixture_json("bcra_cotizaciones.json"))
    )
    day = fixture_json("bcra_cotizaciones.json")["results"]
    respx.get(url__regex=rf"{BCRA}/estadisticascambiarias/v1.0/Cotizaciones/[A-Z]{{3}}").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": 200,
                "metadata": {"resultset": {"count": 1, "offset": 0, "limit": 1000}},
                "results": [{"fecha": day["fecha"], "detalle": day["detalle"][:1]}],
            },
        )
    )
    respx.get(f"{BCRA}/estadisticascambiarias/v1.0/Maestros/Divisas").mock(
        return_value=httpx.Response(
            200, json={"status": 200, "results": [{"codigo": "USD", "denominacion": "DOLAR"}]}
        )
    )
    respx.get(f"{BCRA}/estadisticas/v4.0/monetarias").mock(
        return_value=httpx.Response(200, json=fixture_json("bcra_monetary_catalog.json"))
    )


def _mock_datos_gob_ar() -> None:
    page1 = fixture_json("datos_gob_ar_ipc_page1.json")
    page2 = fixture_json("datos_gob_ar_ipc_page2.json")
    respx.get(f"{DGA}/series/api/series/", params__contains={"start": "0"}).mock(
        return_value=httpx.Response(200, json=page1)
    )
    respx.get(f"{DGA}/series/api/series/", params__contains={"start": "2"}).mock(
        return_value=httpx.Response(200, json=page2)
    )


def _mock_energia() -> None:
    respx.get(f"{ENE}/api/3/action/datastore_search", params__contains={"offset": "0"}).mock(
        return_value=httpx.Response(200, json=fixture_json("energia_ckan_page1.json"))
    )
    respx.get(f"{ENE}/api/3/action/datastore_search", params__contains={"offset": "2"}).mock(
        return_value=httpx.Response(200, json=fixture_json("energia_ckan_page2.json"))
    )


def _mock_argentinadatos() -> None:
    respx.get(url__regex=rf"{ADS}/v1/feriados/\d{{4}}").mock(
        return_value=httpx.Response(200, json=fixture_json("argentinadatos_feriados.json"))
    )
    respx.get(url__regex=rf"{ADS}/v1/feriados-bancarios/\d{{4}}").mock(
        return_value=httpx.Response(200, json=[{"fecha": "2026-01-01", "nombre": "Año nuevo"}])
    )


def _sha(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@respx.mock
def test_four_sources_run_end_to_end_without_network(
    settings: Settings, sink: Sink, now: datetime
) -> None:
    _mock_bcra()
    _mock_datos_gob_ar()
    _mock_energia()
    _mock_argentinadatos()
    results = []
    for source, base, only in (
        ("bcra", BCRA, None),
        ("datos_gob_ar", DGA, ["series"]),  # sspm: tests/sources/test_file_sources.py
        ("energia_ckan", ENE, None),
        ("argentinadatos", ADS, None),
    ):
        results += run_source(
            settings, source, datasets=only, now=now, sink=sink, client=fast_client(base)
        )
    assert {r.status for r in results} == {"ok"}, [(r.dataset, r.status, r.error) for r in results]
    assert exit_code(results) == 0
    by_name = {r.dataset: r for r in results}
    assert by_name["monetary_series"].rows_written == 3 + len(BCRA_VARIABLES) - 1
    assert by_name["monetary_catalog"].rows_written == 2
    assert by_name["fx_currencies"].rows_written == 1
    # 1 day x 2 variables (quote, swap) per configured currency
    assert by_name["fx_history"].rows_written == 2 * 15
    # datos_gob_ar: the 5 ids hit the same mocked route, 3 rows over 2 pages each
    assert by_name["series"].rows_written == 15
    assert by_name["fx_quotes"].rows_written == 4  # 2 currencies x (quote, swap)
    assert by_name["pump_prices_current"].rows_written == 3
    assert by_name["holidays"].rows_written == 6  # 3 holidays x 2 years

    # One contract per dataset, with provenance; description non-empty and not just the id.
    for r in results:
        contract = sink.read_contract(r.source, r.dataset)
        assert contract[-1]["status"] == "ok"
        assert contract[-1]["provenance"] in ("official", "third_party")
        desc = Path(sink.dataset_dir(r.source, r.dataset), "_description.md").read_text("utf-8")
        assert desc.strip() and desc.strip() != r.dataset
    assert sink.read_contract("argentinadatos", "holidays")[-1]["provenance"] == "third_party"
    # The datos.gob.ar description comes from the API (metadata=full).
    dga_desc = Path(sink.dataset_dir("datos_gob_ar", "series"), "_description.md").read_text(
        "utf-8"
    )
    assert "IPC. Nivel General Nacional" in dga_desc and "INDEC" in dga_desc


@respx.mock
def test_revision_next_day_marks_row_and_previous_partition_is_byte_identical(
    settings: Settings, sink: Sink, now: datetime, next_day: datetime
) -> None:
    _mock_bcra()
    r0 = run_source(
        settings,
        "bcra",
        datasets=["monetary_series"],
        now=now,
        sink=sink,
        client=fast_client(BCRA),
    )
    h0 = _sha(r0[0].partition or "")
    revised = fixture_json("bcra_monetarias_1.json")
    revised["results"][0]["detalle"][2]["valor"] = 50701.0  # the BCRA corrected day 7
    respx.get(f"{BCRA}/estadisticas/v4.0/Monetarias/1").mock(
        return_value=httpx.Response(200, json=revised)
    )
    r1 = run_source(
        settings,
        "bcra",
        datasets=["monetary_series"],
        now=next_day,
        sink=sink,
        client=fast_client(BCRA),
    )
    assert r1[0].status == "revised"
    assert r1[0].revisions == [{"variable": RESERVES_LABEL, "ref_date": "2026-09-07"}]
    assert _sha(r0[0].partition or "") == h0
    contract = sink.read_contract("bcra", "monetary_series")
    assert [e["status"] for e in contract] == ["ok", "revised"]
    assert contract[-1]["revisions_detected"] == r1[0].revisions


@respx.mock
def test_format_change_ends_clean_with_status_and_writes_no_partition(
    settings: Settings, sink: Sink, now: datetime, next_day: datetime
) -> None:
    _mock_bcra()
    r0 = run_source(
        settings,
        "bcra",
        datasets=["monetary_series"],
        now=now,
        sink=sink,
        client=fast_client(BCRA),
    )
    h0 = _sha(r0[0].partition or "")
    broken = fixture_json("bcra_monetarias_1.json")
    for row in broken["results"][0]["detalle"]:
        row["value"] = row.pop("valor")  # renamed key
    for vid in BCRA_VARIABLES:
        respx.get(f"{BCRA}/estadisticas/v4.0/Monetarias/{vid}").mock(
            return_value=httpx.Response(200, json=broken)
        )
    r1 = run_source(
        settings,
        "bcra",
        datasets=["monetary_series"],
        now=next_day,
        sink=sink,
        client=fast_client(BCRA),
    )
    assert r1[0].status == "format_changed"
    assert any("valor" in d for d in r1[0].format_diff) and any(
        "value" in d for d in r1[0].format_diff
    )
    assert exit_code(r1) == 2
    assert sink.list_partitions("bcra", "monetary_series") == [now.date().isoformat()]
    assert _sha(r0[0].partition or "") == h0
    assert (
        sink.read_contract("bcra", "monetary_series")[-1]["format_changes_detected"]
        == r1[0].format_diff
    )


@respx.mock
def test_ckan_column_renamed_is_format_change(
    settings: Settings, sink: Sink, now: datetime
) -> None:
    page = fixture_json("energia_ckan_page1.json")
    page["result"]["total"] = 2
    for rec in page["result"]["records"]:
        rec["precio_final"] = rec.pop("precio")
    respx.get(f"{ENE}/api/3/action/datastore_search").mock(
        return_value=httpx.Response(200, json=page)
    )
    r = run_source(settings, "energia_ckan", now=now, sink=sink, client=fast_client(ENE))
    assert r[0].status == "format_changed"
    assert sink.list_partitions("energia_ckan", "pump_prices_current") == []


@respx.mock
def test_http_failure_still_writes_contract_with_failed_and_no_data(
    settings: Settings, sink: Sink, now: datetime
) -> None:
    respx.get(url__regex=rf"{ADS}/v1/.*").mock(return_value=httpx.Response(503))
    r = run_source(settings, "argentinadatos", now=now, sink=sink, client=fast_client(ADS))
    assert {x.status for x in r} == {"failed"}
    assert exit_code(r) == 1
    for x in r:
        contract = sink.read_contract("argentinadatos", x.dataset)
        assert contract[-1]["status"] == "failed"
        assert contract[-1]["error"] and "503" in contract[-1]["error"]
        assert contract[-1]["last_successful_extraction"] is None
        assert sink.list_partitions("argentinadatos", x.dataset) == []


@respx.mock
def test_written_tree_matches_layout_and_nothing_else(
    settings: Settings, sink: Sink, now: datetime
) -> None:
    _mock_argentinadatos()
    run_source(settings, "argentinadatos", now=now, sink=sink, client=fast_client(ADS))
    root = Path(settings.output_root)
    files = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    for f in files:
        parts = f.split("/")
        assert parts[0].startswith("source=") and parts[1].startswith("dataset=")
        if len(parts) == 3:
            assert parts[2] in ("_contract.json", "_description.md")
        else:
            assert parts[2].startswith("extraction_date=") and (
                parts[3].endswith(".parquet") or parts[3].endswith(".manifest.json")
            )
    manifest = json.loads(
        (
            root
            / "source=argentinadatos/dataset=holidays"
            / f"extraction_date={now.date()}"
            / "part-0.manifest.json"
        ).read_text()
    )
    assert manifest["provenance"] == "third_party" and manifest["natural_key"] == [
        "fecha",
        "nombre",
    ]
