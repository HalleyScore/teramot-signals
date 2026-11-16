"""File sources (CSV, XLSX, ZIP) and multi-coordinate sources, end to end and offline."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime

import httpx
import polars as pl
import respx

from teramot_signals.core.config import Settings
from teramot_signals.core.pipeline import run_source
from teramot_signals.core.sink import Sink
from teramot_signals.sources.indec import _TABLE5, _TABLE6, parse_block_sheet
from teramot_signals.sources.unr_dataverse import flatten_dictionary
from tests.conftest import fast_client

DGA = "https://apis.datos.gob.ar"
GEO = "https://infra.datos.gob.ar"
OM = "https://api.open-meteo.com"
INDEC = "https://www.indec.gob.ar"


def _partition(sink: Sink, source: str, dataset: str, now: datetime) -> pl.DataFrame:
    df = sink.read_latest_part(source, dataset, now.date().isoformat())
    assert df is not None
    return df


@respx.mock
def test_georef_csv_keeps_leading_zeros_and_types_centroids(
    settings: Settings, sink: Sink, now: datetime
) -> None:
    csv = (
        '"categoria","centroide_lat","centroide_lon","fuente","id","iso_id","iso_nombre",'
        '"nombre","nombre_completo"\n'
        '"Ciudad Autónoma",-34.61,-58.44,"IGN","02","AR-C","CABA","CABA","Ciudad Autónoma"\n'
        '"Provincia",-36.6,-60.5,"IGN","06","AR-B","Buenos Aires","Buenos Aires","Provincia BA"\n'
    )
    respx.get(f"{GEO}/georef/provincias.csv").mock(return_value=httpx.Response(200, text=csv))
    r = run_source(
        settings, "georef", datasets=["provinces"], now=now, sink=sink, client=fast_client(GEO)
    )
    assert r[0].status == "ok", r[0]
    df = _partition(sink, "georef", "provinces", now)
    assert df["id"].to_list() == ["02", "06"]
    assert df.schema["centroide_lat"] == pl.Float64


@respx.mock
def test_georef_new_column_is_format_change(settings: Settings, sink: Sink, now: datetime) -> None:
    csv = (
        "categoria,centroide_lat,centroide_lon,fuente,id,iso_id,iso_nombre,nombre,"
        "nombre_completo,x\n"
    )
    respx.get(f"{GEO}/georef/provincias.csv").mock(return_value=httpx.Response(200, text=csv))
    r = run_source(
        settings, "georef", datasets=["provinces"], now=now, sink=sink, client=fast_client(GEO)
    )
    assert r[0].status == "format_changed"
    assert r[0].format_diff == ["new column `x`"]


def _sspm_meta(ids: list[str]) -> dict[str, object]:
    url = f"{GEO}/catalog/sspm/dataset/1/distribution/1.1/download/x.csv"
    entries = [
        {
            "catalog": {},
            "dataset": {"title": "IPC", "source": "INDEC", "license": "CC BY 4.0"},
            "distribution": {"downloadURL": url},
            "field": {"id": sid, "title": f"col_{i}", "units": "Índice", "frequency": "R/P1M"},
        }
        for i, sid in enumerate(ids)
    ]
    return {"data": [], "count": 0, "meta": [{"frequency": "month"}, *entries]}


@respx.mock
def test_sspm_reads_each_csv_once_and_maps_columns_to_variables(
    settings: Settings, sink: Sink, now: datetime
) -> None:
    def meta(request: httpx.Request) -> httpx.Response:
        ids = request.url.params["ids"].split(",")
        all_ids = list(settings_series)
        return httpx.Response(200, json=_sspm_meta_for(ids, all_ids))

    import yaml

    from tests.conftest import REPO_CONFIG

    settings_series = yaml.safe_load((REPO_CONFIG / "sources/datos_gob_ar.yaml").read_text())[
        "datasets"
    ]["sspm"]["options"]["series"]

    def _sspm_meta_for(ids: list[str], all_ids: list[str]) -> dict[str, object]:
        out = _sspm_meta(ids)
        for entry in out["meta"][1:]:  # type: ignore[index]
            entry["field"]["title"] = f"col_{all_ids.index(entry['field']['id'])}"
        return out

    respx.get(f"{DGA}/series/api/series/").mock(side_effect=meta)
    header = "indice_tiempo," + ",".join(f"col_{i}" for i in range(len(settings_series)))
    rows = [
        "2026-01-01," + ",".join(str(i) for i in range(len(settings_series))),
        "2026-02-01," + ",".join("" for _ in settings_series),  # no value yet: dropped
    ]
    csv_route = respx.get(url__regex=rf"{GEO}/catalog/sspm/.*\.csv").mock(
        return_value=httpx.Response(200, text="\n".join([header, *rows]))
    )
    r = run_source(
        settings,
        "datos_gob_ar",
        datasets=["sspm", "sspm_catalog"],
        now=now,
        sink=sink,
        client=fast_client(DGA),
    )
    assert [x.status for x in r] == ["ok", "ok"], r
    assert csv_route.call_count == 1  # one download for all the series in the file
    df = _partition(sink, "datos_gob_ar", "sspm", now)
    assert df.height == len(settings_series)
    first_id, (first_var, _) = next(iter(settings_series.items()))
    assert df.filter(pl.col("variable") == first_var)["value"].to_list() == [0.0]
    cat = _partition(sink, "datos_gob_ar", "sspm_catalog", now)
    assert cat.filter(pl.col("series_id") == first_id)["unit"].to_list() == ["Índice"]


@respx.mock
def test_sspm_missing_column_is_format_change(
    settings: Settings, sink: Sink, now: datetime
) -> None:
    respx.get(f"{DGA}/series/api/series/").mock(
        side_effect=lambda req: httpx.Response(
            200, json=_sspm_meta(req.url.params["ids"].split(","))
        )
    )
    respx.get(url__regex=rf"{GEO}/catalog/sspm/.*\.csv").mock(
        return_value=httpx.Response(200, text="indice_tiempo,other\n2026-01-01,1\n")
    )
    r = run_source(
        settings, "datos_gob_ar", datasets=["sspm"], now=now, sink=sink, client=fast_client(DGA)
    )
    assert r[0].status == "format_changed"
    assert "col_0" in r[0].format_diff[0]


@respx.mock
def test_open_meteo_batches_locations_and_keeps_their_ids(
    settings: Settings, sink: Sink, now: datetime
) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        n = len(request.url.params["latitude"].split(","))
        daily = {
            "time": ["2026-09-14", "2026-09-15"],
            "temperature_2m_max": [20.0, 21.5],
            "temperature_2m_min": [10, 11],
            "temperature_2m_mean": [15.0, 16.0],
            "precipitation_sum": [0.0, None],
        }
        return httpx.Response(200, json=[{"daily": daily} for _ in range(n)])

    route = respx.get(f"{OM}/v1/forecast").mock(side_effect=answer)
    r = run_source(
        settings, "open_meteo", datasets=["forecast"], now=now, sink=sink, client=fast_client(OM)
    )
    assert r[0].status == "ok", r[0]
    df = _partition(sink, "open_meteo", "forecast", now)
    n_loc = df["locality_id"].n_unique()
    assert route.call_count == -(-n_loc // 25)
    assert df.height == 2 * n_loc
    assert "02007010" in df["locality_id"].to_list()
    assert df.schema["temp_min"] == pl.Float64


def test_supermarkets_block_sheet_parses_jurisdictions_and_labels() -> None:
    rows: list[list[object]] = [
        ["Encuesta de supermercados", None, None, None, None],
        ["Período", "Total del país", None, "Córdoba", None],
        [None, "Ventas totales", "Cantidad de bocas", "Ventas totales", "Cantidad de bocas"],
        [None, "Miles de pesos", "Unidades", "Miles de pesos", "Unidades"],
        ["2026-07-01 00:00:00", "100.5", "10", "20", "2"],
        ["2026-08-01 00:00:00", "110", "11", "22", "2"],
        ["Fuente: INDEC", None, None, None, None],
    ]
    df = parse_block_sheet(rows, _TABLE6, "Cuadro 6")
    assert df.height == 4
    cba = df.filter(pl.col("jurisdiction") == "Córdoba").sort("date")
    assert cba["sales_total"].to_list() == [20.0, 22.0]
    assert cba["stores"].to_list() == [2.0, 2.0]


def test_supermarkets_unknown_label_is_format_change() -> None:
    rows: list[list[object]] = [
        ["Período", "Total del país"],
        [None, "Mascotas"],
        ["2026-07-01 00:00:00", "1"],
    ]
    try:
        parse_block_sheet(rows, _TABLE5, "Cuadro 5")
    except Exception as exc:  # FormatChanged
        assert "Mascotas" in str(exc)
    else:
        raise AssertionError("expected FormatChanged")


def _eph_zip(year: int, quarter: int, extra_column: bool) -> bytes:
    cols = [
        "CODUSU",
        "ANO4",
        "TRIMESTRE",
        "NRO_HOGAR",
        "COMPONENTE",
        "AGLOMERADO",
        "PONDERA",
        "IPCF",
    ]
    if extra_column:
        cols.append("NUEVA")
    row = ['"ABC"', str(year), str(quarter), "1", "1", "33", "150", "1234,5"]
    if extra_column:
        row.append("7")
    text = ";".join(f'"{c}"' for c in cols) + "\r\n" + ";".join(row) + "\r\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"usu_individual_T{quarter}{str(year)[2:]}.txt", text)
        zf.writestr(f"usu_hogar_T{quarter}{str(year)[2:]}.txt", "x")
    return buf.getvalue()


@respx.mock
def test_eph_skips_unpublished_quarters_and_unions_changing_columns(
    settings: Settings, sink: Sink, now: datetime
) -> None:
    base = f"{INDEC}/ftp/cuadros/menusuperior/eph"
    respx.get(f"{base}/EPH_usu_4_Trim_2025_txt.zip").mock(
        return_value=httpx.Response(200, content=_eph_zip(2025, 4, extra_column=False))
    )
    respx.get(f"{base}/EPH_usu_1_Trim_2026_txt.zip").mock(
        return_value=httpx.Response(200, content=_eph_zip(2026, 1, extra_column=True))
    )
    # INDEC answers 200 with HTML when the quarter does not exist yet
    respx.get(f"{base}/EPH_usu_2_Trim_2026_txt.zip").mock(
        return_value=httpx.Response(200, text="<html>no</html>")
    )
    respx.get(f"{base}/EPH_usu_3_Trim_2026_txt.zip").mock(return_value=httpx.Response(404))
    r = run_source(
        settings,
        "indec",
        datasets=["eph_individuals"],
        now=now,
        sink=sink,
        client=fast_client(INDEC),
    )
    assert r[0].status == "ok", r[0]
    df = _partition(sink, "indec", "eph_individuals", now)
    assert df.height == 2
    assert df.schema["ipcf"] == pl.Float64 and df["ipcf"].to_list() == [1234.5, 1234.5]
    assert df.sort("ano4")["nueva"].to_list() == [None, 7]


def test_eph_dictionary_splits_code_and_label() -> None:
    doc = {
        "variables": [
            {
                "name": "region",
                "original_var": "REGION",
                "label": "Región",
                "values": [
                    {"value": "GBA", "original": "01 = Gran Buenos Aires"},
                    {"value": "NOA", "original": "40 = NOA"},
                ],
            },
            {"name": "id_hogar", "label": "ID", "values": [{"value": "Código"}]},
            {"name": "pondera", "label": "Ponderador"},
        ]
    }
    df = flatten_dictionary(doc)
    assert df.height == 4
    assert df.filter(pl.col("variable") == "region")["code"].to_list() == ["01", "40"]
    assert df.filter(pl.col("variable") == "id_hogar")["code"].to_list() == [None]
