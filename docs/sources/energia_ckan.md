# Source: energia_ckan — fuel pump prices

> **Network reachability:** `datos.energia.gob.ar` may be unreachable from some networks
> ("No route to host") while every other source works. When that happens the run ends in
> `failed` with the error in the contract, and the catalog publishes an empty typed view, so
> `argentina_pulse` still compiles without the fuel section.

- **Base URL:** `http://datos.energia.gob.ar` — **the portal redirects https → http.** The
  download travels in clear text; integrity is checked by `expected_schema` and partition hash,
  not by transport.
- **Auth:** none. **Rate limit:** not declared; 3 req/s. 36,669 rows = 37 requests ≈ 15 s.
- **Provenance:** official (Secretaría de Energía). **License: `CC-BY-4.0`**, declared in the
  package (`license_title`). Verified 2026-09-14. Attribute to the Secretaría de Energía.
- **Pattern:** CKAN `datastore_search`. It works the same for any government CKAN portal
  (`datos.gob.ar`, provinces, ministries): another YAML, same source code.

## Endpoints verified live (2026-09-14)

`GET /api/3/action/package_show?id=precios-en-surtidor`
→ title "Precios en Surtidor - Resolución 314/2016", two resources with `datastore_active: true`:

| Resource | `resource_id` | Modified |
|---|---|---|
| Current prices | `80ac25de-a44a-4445-9215-090cf55cfda5` | 2026-09-14 |
| Historical prices | `f8dda0d5-2a9f-4d34-b79b-4e63de3995df` | 2026-09-14 |

`GET /api/3/action/datastore_search?resource_id=<id>&limit=1000&offset=<n>`

```json
{"success": true, "result": {"total": 36669, "fields": [{"id": "precio", "type": "numeric"}, ...], "records": [...]}}
```

`ckan` pagination: `limit`/`offset`; `result.total` is the total.

## Columns (19) and natural key

Columns are passed through as published (Spanish): `indice_tiempo` (YYYY-MM month), `idempresa`,
`cuit` (tax id), `empresa` (company), `direccion` (address), `localidad` (locality), `provincia`,
`region`, `idproducto`, `producto` (product), `idtipohorario`, `tipohorario` (Diurno/Nocturno =
day/night), `precio` (pesos per liter), `fecha_vigencia` (effective date), `idempresabandera`,
`empresabandera` (brand), `latitud`, `longitud`, `geojson`.

Natural key: `(cuit, direccion, idproducto, idtipohorario, indice_tiempo)`. If the agency
re-reports the same month for the same station and product with a different price, it is a
revision.

## Datasets

| Dataset | Status | Note |
|---|---|---|
| `pump_prices_current` | enabled | 36,669 rows on 2026-09-14 |
| `pump_prices_history` | `enabled: false` | millions of rows; enable after the first cut, with a window |
