# Source: datos_gob_ar — Time Series API (prices, activity, foreign trade)

- **Base URL:** `https://apis.datos.gob.ar`
- **Auth:** none. **Rate limit:** not declared; 4 req/s.
- **Provenance:** official (INDEC and other agencies, republished by the national portal).
- **Terms:** `datos.gob.ar/acerca/seccion/terminos-y-condiciones` returned 404 on 2026-09-14.
  Packages from the same ecosystem declare `CC-BY-4.0` (see `energia_ckan.md`); the `sspm`
  catalog declares CC BY 4.0. **To be confirmed** for the API itself.
- **Docs:** `datosgobar.github.io/series-tiempo-ar-api/`.

## Endpoint verified live (2026-09-14)

`GET /series/api/series/?ids=<id>&format=json&metadata=full&limit=1000&start=<n>[&start_date=&end_date=]`

```json
{
  "data": [["2026-06-01", 11826.41], ["2026-07-01", 12076.39]],
  "count": 117,
  "meta": [
    {"dataset": {"title": "...", "source": "Instituto Nacional de Estadística y Censos (INDEC)"}},
    {"field": {"id": "148.3_INIVELNAL_DICI_M_26", "title": "...", "description": "...", "units": "Índice", "frequency": "R/P1M"}}
  ],
  "params": {"ids": "..."}
}
```

- `start_count` pagination: `limit` (maximum **1000**) and `start`; `count` is the total.
- `last=N` exists but disables pagination: not used.
- `collapse` and `representation_mode` exist and are **not used** (this repo does not model).
- `metadata=full` returns each series' description → it goes to `_description.md` automatically.
- The API **does not flag revisions**. INDEC revises foreign trade and activity backwards:
  detecting that is this repo's job.

## `series`: first-cut series (verified ids)

| Variable in the Parquet output | API id | Agency | Unit | Last value seen |
|---|---|---|---|---|
| `cpi_national_headline` | `148.3_INIVELNAL_DICI_M_26` | INDEC | Index Dec-2016=100 | 2026-08-01 = 12,276.77 |
| `cpi_gba_core` | `103.1_I2N_2016_M_15` | INDEC | Index | 2026-08-01 = 12,488.49 |
| `exports_total_musd` | `74.3_IET_0_M_16` | INDEC | Millions of USD FOB | monthly |
| `exports_primary_products_musd` | `75.3_IETPP_0_M_43` | INDEC | Millions of USD FOB | monthly |
| `exports_industrial_manufactures_musd` | `75.3_ITM_0_M_13` | INDEC | Millions of USD FOB | monthly |

To find ids:
`GET /series/api/search/?q=<text>&limit=40` → `{data[{field{id, description, frequency, units}, dataset{source}}], count}`.

Adding a series is one line in the YAML's `options.ids`. No code to touch.

## `sspm` and `sspm_catalog`: full history from the CSV distributions

Requesting one series at a time from the API (1000 rows per page, ~4 req/s) does not scale to a
hundred series with twenty years of history. The `sspm` catalog publishes each dataset as a wide
CSV (`indice_tiempo` + one column per series), so the extractor:

1. Resolves, in batches of 20 ids, `GET /series/api/series/?ids=a,b,…&metadata=only` →
   `meta[1..n] = {catalog, dataset, distribution{downloadURL}, field{id, title, units, …}}`.
   The API accepts ids with different frequencies in the same request.
2. Downloads each CSV **only once** and takes each series' `field.title` column.
3. A missing column is `format_changed`, not an empty series.

The 108 configured series (CPI by region and division, EMAE economic activity and sectors, wages
and RIPTE, supermarkets by category, channel and payment method, shopping centers, BNA exchange
rate) carry `[variable, group]` in the YAML. `sspm_catalog` publishes their metadata (unit,
frequency, source, license, source CSV) with English column names; the agency's own titles and
descriptions stay in Spanish. Catalog license: CC BY 4.0.
