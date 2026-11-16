# `sources/bcra/` — BCRA connector

A `BcraExtractor` and a `BcraNormalizer` in `__init__.py`. Datasets in `config/sources/bcra.yaml`;
full survey in `docs/sources/bcra.md`.

| Dataset | Endpoint | How |
|---|---|---|
| `monetary_catalog` | `GET /estadisticas/v4.0/monetarias` | Paginated; one row per `idVariable` → `table` |
| `monetary_series` | `GET /estadisticas/v4.0/Monetarias/{id}` | One paginated call per id in `options.variables`; `results[0].detalle[{fecha, valor}]` → `series` |
| `fx_quotes` | `GET /estadisticascambiarias/v1.0/Cotizaciones` | One request returns every currency of the day; two variables per currency: `<ISO>.rate` and `<ISO>.usd_parity` |
| `fx_history` | `GET /estadisticascambiarias/v1.0/Cotizaciones/{currency}` | `fechadesde`/`fechahasta`, paginated; `results[{fecha, detalle[...]}]` → same variables |
| `fx_currencies` | `GET /estadisticascambiarias/v1.0/Maestros/Divisas` | Master `{codigo, denominacion}` → `table` |

Notes: Monetary v4.0 only (v1–v3 return HTTP 410); catalog of 1610 variables as of 2026-11-16;
series come in descending order; holidays are missing (no `null`); own rate limit 8 req/s.
