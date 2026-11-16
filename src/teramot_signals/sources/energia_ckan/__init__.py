"""datos.energia.gob.ar — CKAN datastore, fuel pump prices. Shape: `table`.

`GET /api/3/action/datastore_search?resource_id=<id>&limit=N&offset=M`
→ `{success, result{total, fields[{id,type}], records[...]}}`. License CC-BY-4.0 (in the package).
The portal redirects https → http: integrity is checked by schema and hash, not by transport.
"""

from __future__ import annotations

from typing import Any

from teramot_signals.core.config import DatasetConfig
from teramot_signals.core.extraction import FormatChanged, RawBatch, Window, require_keys
from teramot_signals.core.http import HttpClient
from teramot_signals.core.normalization import Normalized, to_table


def _items(page: Any) -> list[Any]:
    records = (page.get("result") or {}).get("records")
    if not isinstance(records, list):
        raise FormatChanged(["`result.records` is not a list"])
    return records


def _total(page: Any) -> int | None:
    return (page.get("result") or {}).get("total")


class EnergiaCkanExtractor:
    def extract(self, client: HttpClient, name: str, ds: DatasetConfig, window: Window) -> RawBatch:
        params: dict[str, Any] = dict(ds.params)
        records: list[dict[str, Any]] = []
        for page in client.paginate(
            ds.path,
            params,
            style=ds.pagination,
            page_limit=ds.page_limit,
            items_of=_items,
            total_of=_total,
        ):
            require_keys(page, ["success", "result"], ds.path)
            if page["success"] is not True:
                raise RuntimeError(f"CKAN returned success={page['success']}: {page.get('error')}")
            records.extend(r for r in _items(page) if isinstance(r, dict))
        return RawBatch(records=records, endpoint=ds.path, params=params)


class EnergiaCkanNormalizer:
    def normalize(self, batch: RawBatch, name: str, ds: DatasetConfig) -> Normalized:
        dates = [k for k, t in ds.expected_schema.items() if t == "date"]
        return to_table(batch.records, ds.natural_key, dates)


EXTRACTOR = EnergiaCkanExtractor()
NORMALIZER = EnergiaCkanNormalizer()
