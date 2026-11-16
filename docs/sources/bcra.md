# Source: BCRA

Banco Central de la República Argentina — public APIs.

- **Base URL:** `https://api.bcra.gob.ar`
- **Auth:** none (public, free APIs; HTTPS only, GET only).
- **Format:** JSON with a `{ status, metadata, results }` envelope; on error, `errorMessages`.
- **Rate limit:** not declared. We self-limit to **8 req/s** with **exponential backoff** on
  5xx (1s, 2s, 4s, max 3 retries).
- **Language:** header `Accept-Language: es-AR` (default) or `en-US`. Field names are Spanish
  either way and are passed through as published.
- **Provenance:** official.

> Official catalog: https://www.bcra.gob.ar/apis-banco-central/ — each API has its own legal
> notice; read it before redistributing the data.

## Implemented datasets

| Dataset | Endpoint | Shape | Notes |
|---|---|---|---|
| `monetary_catalog` | `GET /estadisticas/v4.0/monetarias` | `table`, key `idVariable` | All 1610 monetary variables (paginated) |
| `monetary_series` | `GET /estadisticas/v4.0/Monetarias/{idVariable}` | `series` | 16 configured variables; incremental with `lookback_days: 45` |
| `fx_quotes` | `GET /estadisticascambiarias/v1.0/Cotizaciones` | `series` | Every currency for the last business day |
| `fx_history` | `GET /estadisticascambiarias/v1.0/Cotizaciones/{currency}` | `series` | 15 currencies and metals since 2003 (use `--since`), `fechadesde`/`fechahasta`, paginated |
| `fx_currencies` | `GET /estadisticascambiarias/v1.0/Maestros/Divisas` | `table`, key `codigo` | Currency master |

`limit` is at most 1000; on the exchange-rate API the minimum is 10. Monetary v1/v2/v3 are
deprecated (HTTP 410): only v4.0 is used.

### Variables

`monetary_series` writes one row per `(variable, ref_date)`. The `idVariable → variable` mapping
lives in `config/sources/bcra.yaml`; adding a variable is one line there (ids come from
`monetary_catalog`).

`fx_quotes` and `fx_history` write two variables per currency:

- `<ISO>.rate` — pesos per unit of the currency (`tipoCotizacion`).
- `<ISO>.usd_parity` — parity against the US dollar (`tipoPase`); for gold (XAU) and silver
  (XAG), USD per ounce.

Official rate only (no MEP, CCL or parallel "blue" rate). Cross rates can be derived downstream.

## Findings verified live

- Series and quotes come in **descending** date order; weekends and holidays are simply missing
  (no `null` values). The latest date usually lags 1–2 business days.
- `moneda` in the catalog is an internal code: `ML` (local), `ME` (foreign), `MEyML`, `USD` — not ISO.
- `periodicidad`: only `D` (daily) and `M` (monthly) in the current catalog.
- UVA is id **31**; the old id 6 ("Tasa de Política Monetaria") no longer exists.
- `Cotizaciones/MXN` returns 404: not every currency in the master has history.

## Other BCRA APIs (not ingested)

- **Cheques Denunciados** (`/cheques/v1.0`) and **Central de Deudores**
  (`/centraldedeudores/v1.0`) are per-identifier lookups, not bulk datasets. The debtor registry
  holds personal data protected by Argentine Law 25.326 and is intentionally not ingested.
- **Régimen de Transparencia** (`/transparencia/v1.0`): daily snapshots of financial product
  conditions (savings accounts, time deposits, loans, credit cards). A candidate for a future
  dataset.

## Ingestion notes

- **Suggested refresh:** daily around 19:00 ART (after the BCRA close, ~17:30).
- **Units:** reserves in millions of USD, aggregates in millions of pesos, rates in % annual
  nominal; see each variable's description in the YAML.
