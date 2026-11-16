# Data licenses and terms

The **code** in this repo is Apache-2.0 (see `LICENSE`). The **data** it downloads does not
belong to this repo: each agency publishes it under its own license or terms, and whoever runs
the extractor and redistributes the output must respect them and credit the source. Provenance
travels in every row (`source`, `provenance`), in the manifest and in the contract.

| Source | Publisher | Provenance | License / terms | Suggested attribution |
|---|---|---|---|---|
| `bcra` | Banco Central de la República Argentina | official | [Legal notice](https://www.bcra.gob.ar/aviso-legal/): reuse for informational, educational or academic purposes, with attribution and without altering the data; **commercial or advertising use requires the BCRA's express authorization** | "Source: BCRA" |
| `datos_gob_ar` | Subsecretaría de Programación Macroeconómica (INDEC and other agencies' data) | official | CC BY 4.0 (declared in the catalog) | "Source: INDEC / SSPM, via datos.gob.ar" |
| `georef` | IGN, INDEC (Geographic Data Normalization Service) | official | CC BY 4.0 | "Source: Georef, datos.gob.ar" |
| `energia_ckan` | Secretaría de Energía | official | CC BY 4.0 (declared in the CKAN package) | "Source: Secretaría de Energía" |
| `indec` | Instituto Nacional de Estadística y Censos | official | Free reproduction with attribution | "Source: INDEC" |
| `open_meteo` | Open-Meteo (national weather models, ERA5/Copernicus) | **third_party** | Data CC BY 4.0; **free API is for non-commercial use only** | "Weather data by Open-Meteo.com" |
| `unr_dataverse` | Observatorio Económico Social, UNR | **third_party** | CC BY 4.0 | "Observatorio Económico Social UNR, doi:10.57715/UNR/BL85Z8" |
| `argentinadatos` | ArgentinaDatos (open project) | **third_party** | Code MIT; no legal notice published as of 2026-09-14 | "ArgentinaDatos" |

## Personal data

- `energia_ckan.pump_prices_current` identifies each station by `cuit`, `empresa` and address.
  Stations run by a natural person (CUIT prefixes 20, 23, 24, 27) expose that person's tax id and
  name, which are personal data under Argentina's Ley 25.326. The private output keeps the data
  as published; the public copy redacts those rows (see `redact` in the YAML).
- `indec.eph_households` / `eph_individuals` are anonymized survey microdata covered by
  statistical secrecy (Ley 17.622). They are not re-identifiable as published, but they are not
  part of the public copy.

## What the public copy (`teramot-signals publish`) includes

Only datasets marked `publish: true`, with the license, attribution and terms URL of their source
carried into `catalog.json`:

| Source | Published | Not published, and why |
|---|---|---|
| `bcra` | every dataset | — (non-commercial reuse with attribution; see the terms above) |
| `datos_gob_ar` | every dataset | — |
| `georef` | every dataset | — |
| `energia_ckan` | `pump_prices_current`, redacted | `pump_prices_history` (disabled) |
| `indec` | `supermarkets_by_province` | `eph_households`, `eph_individuals` (microdata) |
| `unr_dataverse` | `eph_dictionary` | — |
| `open_meteo` | — | the free API is non-commercial only; forecasts are not a record |
| `argentinadatos` | — | no license published |

Anyone running the extractors keeps every source; this table only describes the hosted copy.
