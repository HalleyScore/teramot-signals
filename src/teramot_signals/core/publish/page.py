"""Static `index.html` for the public copy, rendered from `catalog.json`."""

from __future__ import annotations

from html import escape
from typing import Any

REPO_URL = "https://github.com/HalleyScore/teramot-signals"

_CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#5f6368;--line:#e3e3e3;--accent:#0b57d0;--code:#f5f5f5}
@media (prefers-color-scheme:dark){:root{--bg:#121212;--fg:#ececec;--muted:#a0a0a0;
--line:#2c2c2c;--accent:#8ab4f8;--code:#1e1e1e}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:960px;margin:0 auto;padding:40px 16px 64px}
h1{font-size:28px;margin:0 0 4px}h2{font-size:18px;margin:40px 0 12px}
p{margin:8px 0}.muted{color:var(--muted)}a{color:var(--accent)}
pre,code{font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--code)}
pre{padding:12px 14px;border-radius:6px;overflow-x:auto}code{padding:1px 4px;border-radius:4px}
pre code{padding:0}
.ds{border-top:1px solid var(--line);padding:16px 0}
.ds h3{font-size:16px;margin:0 0 4px}.ds h3 code{background:none;padding:0}
.links a{margin-right:12px;white-space:nowrap}
.meta{font-size:13px;color:var(--muted)}
details{margin-top:6px;font-size:13px}summary{cursor:pointer;color:var(--muted)}
""".strip()


def _desc(text: str) -> str:
    return escape(" ".join(text.split()))


def _dataset(base: str, d: dict[str, Any]) -> str:
    name = f"{d['source']}.{d['dataset']}"
    files = d["files"]
    links = " ".join(
        f'<a href="{escape(base)}/{escape(files[key]["path"])}">{label}</a>'
        for key, label in (
            ("latest_csv", "CSV"),
            ("latest_parquet", "Parquet"),
            ("history_parquet", "Full history (Parquet)"),
        )
        if key in files
    )
    rows = d.get("rows", {})
    meta = [
        f"{rows.get('latest', 0):,} rows" if rows else "",
        f"updated {escape(str(d.get('last_extraction_date', '')))}",
        escape(d.get("provenance", "")),
    ]
    if d.get("redacted_columns"):
        meta.append("personal data removed: " + escape(", ".join(d["redacted_columns"])))
    cols = ", ".join(f"<code>{escape(c['name'])}</code>" for c in d.get("columns", []))
    terms = escape(d.get("terms_url", ""))
    return f"""<div class="ds" id="{escape(d['source'])}__{escape(d['dataset'])}">
<h3><code>{escape(name)}</code></h3>
<p>{_desc(d.get("description", ""))}</p>
<p class="links">{links}</p>
<p class="meta">{" · ".join(m for m in meta if m)}</p>
<p class="meta">{escape(d.get("attribution", ""))}. License: {escape(d.get("license", ""))}.
<a href="{terms}">Terms</a></p>
<details><summary>Columns</summary><p>{cols}</p></details>
</div>"""


def render_index(catalog: dict[str, Any]) -> str:
    base = catalog["base_url"]
    datasets = catalog["datasets"]
    by_source: dict[str, int] = {}
    for d in datasets:
        by_source[d["source"]] = by_source.get(d["source"], 0) + 1
    duckdb_url = escape(f"{base}/signals.duckdb")
    first = f"{datasets[0]['source']}__{datasets[0]['dataset']}" if datasets else "catalog"
    body = "\n".join(_dataset(base, d) for d in datasets)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Argentine public data</title>
<meta name="description" content="Daily, normalized copies of Argentine public datasets.">
<style>{_CSS}</style>
</head>
<body><main>
<h1>Argentine public data</h1>
<p class="muted">Daily, normalized copies of {len(datasets)} public datasets from
{len(by_source)} Argentine publishers, as CSV, Parquet and a DuckDB database.
Updated {escape(catalog["generated_at"][:16].replace("T", " "))} UTC.</p>
<p>Built with <a href="{REPO_URL}">teramot-signals</a>, open source (Apache-2.0).
Every dataset keeps its publisher's license: credit the source when you reuse it.</p>

<h2>Query everything with DuckDB</h2>
<pre><code>ATTACH '{duckdb_url}' AS signals (READ_ONLY);
USE signals;
SHOW TABLES;
SELECT * FROM {escape(first)}__latest LIMIT 10;</code></pre>
<p class="muted">Machine-readable index with checksums:
<a href="{escape(base)}/catalog.json">catalog.json</a>.</p>

<h2>Datasets</h2>
{body}
</main></body>
</html>
"""
