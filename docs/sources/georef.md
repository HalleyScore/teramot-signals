# Source: georef — official territorial units

- **Base URL:** `https://infra.datos.gob.ar` (Georef API bulk download).
- **Auth:** none. **Provenance:** official (IGN, INDEC via the Geographic Data Normalization
  Service). **License:** CC BY 4.0. Verified live 2026-11-16.
- **Pattern:** one full CSV per entity; everything is read as text (ids have leading zeros:
  `"02"`, `"06028010"`) and only the centroids are typed. Columns as published by Georef
  (`nombre`, `provincia_id`, `centroide_lat`, …).

| Dataset | File | Rows (2026-11-16) | Key |
|---|---|---|---|
| `provinces` | `/georef/provincias.csv` | 24 | `id` (2 digits) |
| `departments` | `/georef/departamentos.csv` | 529 | `id` (5 digits) |
| `census_localities` | `/georef/localidades_censales.csv` | 4,023 | `id` (8 digits) |

Useful to normalize place names from any other source (the ids are INDEC's) and to place things
on a map (centroid). The interactive API (`apis.datos.gob.ar/georef/api/...`) also normalizes
addresses; it is not used here.
