# Data licenses and terms

The **code** in this repo is Apache-2.0 (see `LICENSE`). The **data** it downloads does not
belong to this repo: each agency publishes it under its own license or terms, and whoever runs
the extractor and redistributes the output must respect them and credit the source. Provenance
travels in every row (`source`, `provenance`), in the manifest and in the contract.

| Source | Publisher | Provenance | License / terms | Suggested attribution |
|---|---|---|---|---|
| `bcra` | Banco Central de la República Argentina | official | Legal notice of each API at bcra.gob.ar/apis-banco-central | "Source: BCRA" |
| `datos_gob_ar` | Subsecretaría de Programación Macroeconómica (INDEC and other agencies' data) | official | CC BY 4.0 (declared in the catalog) | "Source: INDEC / SSPM, via datos.gob.ar" |
| `georef` | IGN, INDEC (Geographic Data Normalization Service) | official | CC BY 4.0 | "Source: Georef, datos.gob.ar" |
| `energia_ckan` | Secretaría de Energía | official | CC BY 4.0 (declared in the CKAN package) | "Source: Secretaría de Energía" |
| `indec` | Instituto Nacional de Estadística y Censos | official | Free reproduction with attribution | "Source: INDEC" |
| `open_meteo` | Open-Meteo (national weather models, ERA5/Copernicus) | **third_party** | Data CC BY 4.0; **free API is for non-commercial use only** | "Weather data by Open-Meteo.com" |
| `unr_dataverse` | Observatorio Económico Social, UNR | **third_party** | CC BY 4.0 | "Observatorio Económico Social UNR, doi:10.57715/UNR/BL85Z8" |
| `argentinadatos` | ArgentinaDatos (open project) | **third_party** | Code MIT; no legal notice published as of 2026-09-14 | "ArgentinaDatos" |

No source includes personally identifiable data: the EPH (household survey) microdata is
anonymized by INDEC.
