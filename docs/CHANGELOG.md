```markdown
# Changelog

All notable changes to the PELDRUN Provider Catalog are recorded in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changes are listed in reverse chronological order (newest first). Each entry corresponds to a merged pull request that modified `catalog.json` or the catalog's supporting infrastructure.

---

## [Unreleased]

_Changes that have been merged but not yet reflected in any catalog consumer's cache. Consumers refresh automatically within 24 hours of merge, or immediately via `POST /api/store/providers/catalog/refresh`._

### Added

_No entries yet._

### Changed

_No entries yet._

### Removed

_No entries yet._

---

## 2026-11-04

### Added

- **Repository bootstrap.** Initial creation of `peldrun-provider-catalog` with:
  - `catalog.json` — empty items array, schema version 1.
  - `schema/catalog.schema.json` — JSON Schema Draft-07 definition.
  - `scripts/validate.py` — local validation script mirroring PELDRUN's runtime rules.
  - `.github/workflows/validate-catalog.yml` — CI validation on push and pull request.
  - `README.md`, `LICENSE` (MIT), `docs/ADDING_A_PROVIDER.md`, and supporting files.

_No catalog items have been published yet. The first installable provider will appear under a future date section._

---

## Entry format

Every entry added to this changelog must include:

1. **Date** — ISO-8601 (`YYYY-MM-DD`), matching the merge date of the pull request.
2. **Category** — one of `Added`, `Changed`, `Removed`, `Deprecated`, `Fixed`, `Security`.
3. **Item reference** — the catalog item's `id` in backticks, followed by the version it applies to.
4. **Summary** — a single line describing the change, written for a user who reads the changelog without opening the diff.

### Example entries

```markdown
### Added
- `gigachat` v1.0.0 — Native GigaChat adapter for the Sber GigaChat API. Requires a custom CA bundle (installed via the Certificate Manager).

### Changed
- `gigachat` v1.0.0 → v1.1.0 — Updated download URL and SHA-256 to point at the v1.1.0 release. Adds streaming support for `GigaChat-Pro`.

### Removed
- `example-provider` — Withdrawn from the catalog after upstream maintenance ended. No user-visible uninstall is triggered; existing installations remain functional.
```

---

## Versioning policy

The catalog is not itself a software package — it has no version number and no release tags. Instead:

- Every push to `main` is treated as a **catalog snapshot** identified by its commit SHA.
- Consumers cache the snapshot for 24 hours.
- A "catalog version" is therefore a function of `(commit_sha, fetch_timestamp)`, not a human-readable tag.

This policy avoids the common trap of trying to version a data file that changes item-by-item: a `v1.2.0` tag would be meaningless to a consumer whose cache still holds `v1.1.0` for another 23 hours.

The `schema_version` field inside `catalog.json` is a **format** version, not a **content** version. It is incremented only when the on-disk shape changes in a way that requires consumer code changes (e.g. adding a required field, renaming a field). In that case, PELDRUN's fetcher rejects caches whose `schema_version` does not match what its `catalog.py` knows how to parse.

---

## Related repositories

- [peldrun](https://github.com/peldrun/peldrun) — the main application.
- [peldrun-provider-gigachat](https://github.com/peldrunai/peldrun-provider-gigachat) — the first provider package intended for this catalog.
```