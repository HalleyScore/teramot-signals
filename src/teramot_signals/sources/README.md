# `sources/` — one connector per public source

One subpackage per source. Each exposes `EXTRACTOR` and `NORMALIZER` and declares its datasets in
`config/sources/<source>.yaml`. Very different response shapes, one shared core:

| Source | What it brings | How it arrives | Provenance | Doc |
|--------|----------------|----------------|------------|-----|
| `bcra/` | monetary and FX | JSON, `offset_envelope` pagination, fan-out per variable and currency | official | `docs/sources/bcra.md` |
| `datos_gob_ar/` | prices, activity, wages, consumption | JSON (`start_count`) and wide CSVs from the `sspm` catalog | official | `docs/sources/datos_gob_ar.md` |
| `indec/` | supermarkets, EPH | XLSX tables, microdata ZIPs | official | `docs/sources/indec.md` |
| `georef/` | provinces, departments, localities | full CSVs | official | `docs/sources/georef.md` |
| `energia_ckan/` | fuel prices | JSON, `ckan` pagination | official | `docs/sources/energia_ckan.md` |
| `open_meteo/` | daily weather per locality | JSON, several coordinates per request | **third_party** | `docs/sources/open_meteo.md` |
| `unr_dataverse/` | EPH dictionary | Dataverse JSON | **third_party** | `docs/sources/unr_dataverse.md` |
| `argentinadatos/` | holidays | JSON, no pagination | **third_party** | `docs/sources/argentinadatos.md` |

How to add a new one: `docs/ADDING_A_SOURCE.md`.
