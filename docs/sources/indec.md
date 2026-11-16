# Source: indec — files from INDEC's public FTP

- **Base URL:** `https://www.indec.gob.ar/ftp/...`. No API: the published file is downloaded.
- **Auth:** none. **Provenance:** official. **Terms:** INDEC data is public and may be reproduced
  citing the source («Fuente: INDEC»).
- Verified live 2026-11-16.

## `supermarkets_by_province` — Supermarket Survey

`/ftp/cuadros/economia/serie_supermercados.xlsx`, sheets «Cuadro 5.» (sales by product group) and
«Cuadro 6.» (sales, stores, floor area, transactions). Each sheet is wide: a `Período` row with
the jurisdiction at the start of each block of columns, the label row below it, and one row per
month. The parser:

- finds the `Período` row (it does not depend on row numbers);
- maps each column to its jurisdiction by block and to its output column by **label prefix**
  (ignoring accents and case);
- an unknown label is `format_changed` (INDEC added or renamed a category).

Result: one row per (month, jurisdiction) since 2017, 3,016 rows as of 2026-08. Jurisdictions keep
INDEC's labels: «Total del país» (national total), CABA, «24 partidos del Gran Buenos Aires»,
«Resto de Buenos Aires» and the other provinces. Sales in **thousands of current pesos**.

| Column | INDEC label |
|---|---|
| `sales_total`, `stores`, `sales_per_store`, `floor_area_m2`, `sales_per_m2`, `transactions`, `sales_per_transaction` | Cuadro 6: ventas totales, cantidad de bocas, ventas por boca, superficie, ventas por m², cantidad de operaciones, ventas por operación |
| `sales_total_products`, `sales_beverages`, `sales_groceries`, `sales_bakery`, `sales_dairy`, `sales_meat`, `sales_fruit_vegetables`, `sales_prepared_food`, `sales_cleaning_personal_care`, `sales_clothing_footwear_textiles`, `sales_electronics_household`, `sales_other` | Cuadro 5: sales by product group |

## `eph_households` / `eph_individuals` — Permanent Household Survey (EPH), public-use files

`/ftp/cuadros/menusuperior/eph/EPH_usu_{q}_Trim_{yyyy}_txt.zip` → `usu_hogar_T{q}{yy}.txt` and
`usu_individual_T{q}{yy}.txt`: `;`-separated text, quoted, CRLF, with a **decimal comma** in some
income columns (`IPCF`).

- When a quarter does not exist, INDEC answers **200 with an HTML page** (not 404): the extractor
  detects it because it is not a ZIP and moves on to the next one.
- By default it downloads the last 4 quarters (`quarters_back`); history with `--since`.
- Columns as published by INDEC, lowercased; each column becomes int, float or text depending on
  its contents.
- **INDEC changed the questionnaire in 2024Q4**: some columns appear and others are retired. That
  is why these datasets declare `allow_new_columns: true` and only watch the key and the weights.
  Quarters are unioned by column name.
- Microdata anonymized by INDEC (no names or addresses). The dictionary is in
  `unr_dataverse.eph_dictionary`.
