# `teramot_signals`

The main package, in two halves:

- **`core/`**: the source-agnostic framework (HTTP, extraction, normalization, fsspec sink,
  registry, pipeline, DuckDB catalog, CLI). It knows no concrete API.
- **`sources/`**: one connector per public source. Each implements what is specific to that
  source and declares its datasets.

Dependency rule: **`core/` never imports from `sources/`**. Sources are discovered through the
registry. See `docs/ARCHITECTURE.md`.
