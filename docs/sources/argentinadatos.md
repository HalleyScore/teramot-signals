# Source: argentinadatos — holiday calendar

- **Base URL:** `https://api.argentinadatos.com`
- **Auth:** none. **Rate limit:** not declared; we self-limit to 4 req/s.
- **Provenance:** **third party.** An open project under the MIT license that aggregates public
  data. It is not the agency. The official source (`argentina.gob.ar/interior/feriados`) has no API.
- **Terms:** the legal notice page (`argentinadatos.com/docs/aviso-legal`) returned 404 on
  2026-09-14. Pending. Fallback if the API disappears: a hand-curated YAML citing the official
  source (about 19 rows per year).

## Endpoints verified live (2026-09-14)

| Dataset | Endpoint | Shape | Response |
|---|---|---|---|
| `holidays` | `GET /v1/feriados/{year}` | `table`, key `(fecha, nombre)` | List `[{fecha, tipo, nombre}]`. 19 holidays in 2026. `tipo ∈ inamovible, trasladable, puente` (fixed, movable, bridge) |
| `bank_holidays` | `GET /v1/feriados-bancarios/{year}` | `table`, key `(fecha, nombre)` | List `[{fecha, nombre}]`. 18 in 2026 |

Columns are passed through as published (`fecha` = date, `nombre` = name, `tipo` = type); the
extractor adds `year` to every row. No pagination. By default it downloads the current and the
next year; with `--since/--until` it downloads the years in the window. A next year that is not
published yet (404) is skipped.

## Other endpoints of the same API (not ingested)

- `/v1/cotizaciones/dolares/{casa}/{yyyy}/{mm}/{dd}` → `{casa, compra, venta, fecha}` (blue, MEP, CCL…).
- `/v1/finanzas/indices/inflacion` → monthly points `[{fecha, valor}]`.
- `/v1/finanzas/indices/riesgo-pais/ultimo` → `{valor, fecha}`.
- `/v1/finanzas/indices/uva`, `/v1/finanzas/tasas/plazo-fijo`, mutual funds, Congress.

## Revisions

Bridge holidays are decreed at year end and may move. A holiday whose `tipo` changes for the
same `(fecha, nombre)` is flagged as a revision; one that changes date shows up as a new row
(the old one stays in the previous partition).
