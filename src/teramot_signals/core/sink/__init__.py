"""Immutable writes of Parquet partitions (local or S3), manifest, contract and description.

Layout:
  <root>/source=<s>/dataset=<d>/extraction_date=YYYY-MM-DD/part-N.parquet
                                                            part-N.manifest.json
  <root>/source=<s>/dataset=<d>/_contract.json      (append-only, one entry per run)
  <root>/source=<s>/dataset=<d>/_description.md
A written partition is never overwritten: a same-day re-run writes part-N+1.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import fsspec
import polars as pl
from fsspec.implementations.local import LocalFileSystem

_PART_RE = re.compile(r"part-(\d+)\.parquet$")


class Sink:
    def __init__(self, root: str) -> None:
        fs, base = fsspec.core.url_to_fs(root)
        self.fs = fs
        self.base = base.rstrip("/")

    def _ensure_dir(self, path: str) -> None:
        # Object stores have no directories; s3fs.makedirs would try CreateBucket.
        if isinstance(self.fs, LocalFileSystem):
            self.fs.makedirs(path, exist_ok=True)

    # ── paths ───────────────────────────────────────────────────────────────
    def dataset_dir(self, source: str, dataset: str) -> str:
        return f"{self.base}/source={source}/dataset={dataset}"

    def partition_dir(self, source: str, dataset: str, extraction_date: date | str) -> str:
        return f"{self.dataset_dir(source, dataset)}/extraction_date={extraction_date}"

    # ── reading ─────────────────────────────────────────────────────────────
    def list_partitions(self, source: str, dataset: str) -> list[str]:
        d = self.dataset_dir(source, dataset)
        if not self.fs.exists(d):
            return []
        out: list[str] = []
        for p in self.fs.ls(d, detail=False):
            name = str(p).rstrip("/").rsplit("/", 1)[-1]
            if name.startswith("extraction_date="):
                out.append(name.split("=", 1)[1])
        return sorted(out)

    def _parts(self, pdir: str) -> list[str]:
        if not self.fs.exists(pdir):
            return []
        parts = [str(p) for p in self.fs.ls(pdir, detail=False) if _PART_RE.search(str(p))]
        return sorted(parts, key=lambda p: int(_PART_RE.search(p).group(1)))  # type: ignore[union-attr]

    def read_latest_part(
        self, source: str, dataset: str, extraction_date: str
    ) -> pl.DataFrame | None:
        parts = self._parts(self.partition_dir(source, dataset, extraction_date))
        if not parts:
            return None
        with self.fs.open(parts[-1], "rb") as fh:
            return pl.read_parquet(fh)

    def latest_previous(
        self, source: str, dataset: str, before: date
    ) -> tuple[pl.DataFrame | None, str | None]:
        """Most recent partition before `before`, and its date."""
        for ed in reversed(self.list_partitions(source, dataset)):
            if ed < before.isoformat():
                return self.read_latest_part(source, dataset, ed), ed
        return None, None

    # ── writing ─────────────────────────────────────────────────────────────
    def write_partition(
        self,
        df: pl.DataFrame,
        source: str,
        dataset: str,
        extraction_date: date,
        manifest: dict[str, Any],
    ) -> str:
        pdir = self.partition_dir(source, dataset, extraction_date)
        self._ensure_dir(pdir)
        n = len(self._parts(pdir))
        path = f"{pdir}/part-{n}.parquet"
        if self.fs.exists(path):  # never overwrite
            raise FileExistsError(path)
        with self.fs.open(path, "wb") as fh:
            df.write_parquet(fh, compression="snappy")
        with self.fs.open(f"{pdir}/part-{n}.manifest.json", "w", encoding="utf-8") as fh:
            json.dump(
                {**manifest, "part": n, "row_count": df.height}, fh, ensure_ascii=False, indent=2
            )
        return path

    def read_contract(self, source: str, dataset: str) -> list[dict[str, Any]]:
        path = f"{self.dataset_dir(source, dataset)}/_contract.json"
        if not self.fs.exists(path):
            return []
        with self.fs.open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []

    def append_contract(self, source: str, dataset: str, entry: dict[str, Any]) -> None:
        d = self.dataset_dir(source, dataset)
        self._ensure_dir(d)
        entries = [*self.read_contract(source, dataset), entry]
        with self.fs.open(f"{d}/_contract.json", "w", encoding="utf-8") as fh:
            json.dump(entries, fh, ensure_ascii=False, indent=2, default=str)

    def write_description(self, source: str, dataset: str, text: str) -> None:
        d = self.dataset_dir(source, dataset)
        self._ensure_dir(d)
        with self.fs.open(f"{d}/_description.md", "w", encoding="utf-8") as fh:
            fh.write(text)
