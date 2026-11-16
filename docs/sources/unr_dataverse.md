# Source: unr_dataverse — EPH dictionary (UNR)

- **Base URL:** `https://dataverse.unr.edu.ar` (Dataverse of the Universidad Nacional de Rosario).
- **Dataset:** Observatorio Económico Social, DOI `10.57715/UNR/BL85Z8`. **License: CC BY 4.0.**
- **Provenance:** **third party** (curated by UNR from INDEC's documentation).

`GET /api/datasets/:persistentId/?persistentId=doi:10.57715/UNR/BL85Z8` lists the files of the
latest version; `eph_dict_capa1.json` is downloaded by id with `/api/access/datafile/<id>` (the id
changes with each version, so it is resolved on every run).

Format: `{metadata, variables[{name, original_var, type, label, description, base, category,
section, methodology, origin, values[{value, original}]}]}`. `original` holds «code = label»
(`"01 = Gran Buenos Aires"`); some values have no `original` (ranges, notes). One row is published
per (variable, value position), with `code`, `value_label` and `original_value` split out.
`methodology ∈ legacy | new | both` says whether the variable applies before or after the 2024Q4
questionnaire change. Labels and descriptions are in Spanish, as published.
