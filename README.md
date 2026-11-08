# PELDRUN Provider Catalog

> The official machine-readable catalog of Provider Packages for [PELDRUN](https://github.com/peldrun/peldrun).

This repository hosts a single JSON file — `catalog.json` — that PELDRUN instances can fetch over HTTPS to discover installable Provider Packages. It is the remote companion to the built-in catalog shipped inside every PELDRUN backend (`backend/omweb/provider_packages/builtin_catalog.json`).

---

## How PELDRUN uses this repository

PELDRUN never calls GitHub by default. Remote fetching is opt-in and requires a single environment variable:

```bash
export PELDRUN_PROVIDER_CATALOG_URL="https://raw.githubusercontent.com/peldrunai/peldrun-provider-catalog/main/catalog.json"
```

When set, PELDRUN:

1. Fetches `catalog.json` on the first Store → Providers → Catalog page load.
2. Caches it to disk at `backend/data/catalog_remote_cache.json` for 24 hours.
3. Serves the cached copy if GitHub is unreachable (offline-safe).
4. Merges the remote items with the built-in and any custom local catalog, with this precedence (lowest first):
   - built-in
   - remote (this repository)
   - custom local (`PELDRUN_PROVIDER_CATALOG_PATH`)
   - test injections (`extra_paths`)

When the variable is **unset** (the default), PELDRUN operates entirely offline against its bundled catalog and never sends a single request to GitHub. See `backend/omweb/provider_packages/catalog.py` for the full reference implementation.

---

## Repository structure

```
.
├── catalog.json                    # The file PELDRUN fetches. Edit this.
├── schema/
│   └── catalog.schema.json         # JSON Schema for catalog.json
├── docs/
│   ├── ADDING_A_PROVIDER.md        # Step-by-step guide
│   └── CHANGELOG.md                # Human-readable history
├── scripts/
│   └── validate.py                 # Local validation (pre-push)
└── .github/
    └── workflows/
        └── validate-catalog.yml    # CI validation on every push/PR
```

Only `catalog.json` is consumed by PELDRUN. Everything else exists to keep that one file correct, reviewable, and auditable.

---

## Security model

**A catalog item without a SHA-256 checksum is not installable.** This is enforced at three layers:

1. **This repository** — the CI validator rejects any `download_url` that lacks a matching `checksum_sha256`.
2. **PELDRUN's fetcher** (`catalog.py::is_installable`) — refuses to download a package when either field is missing or the checksum is malformed.
3. **PELDRUN's installer** — computes the SHA-256 of the downloaded ZIP and aborts on mismatch before anything reaches disk.

The intent: a compromised GitHub account cannot push a malicious catalog entry that causes PELDRUN users to install arbitrary code, because the attacker would also need the SHA-256 of a ZIP they control — and that hash must match what the ZIP bytes actually produce.

---

## Adding a provider

See [`docs/ADDING_A_PROVIDER.md`](docs/ADDING_A_PROVIDER.md).

In short:

1. Build and publish the provider's ZIP as a GitHub Release asset (e.g. `https://github.com/peldrunai/peldrun-provider-gigachat/releases/download/v1.0.0/gigachat-1.0.0.zip`).
2. Compute `sha256sum` of that ZIP.
3. Add an entry to `catalog.json` under `items`.
4. Run `python scripts/validate.py` locally.
5. Commit, push, open a PR. CI validates before merge.

---

## For PELDRUN administrators

### Enable remote catalog fetching

```bash
export PELDRUN_PROVIDER_CATALOG_URL="https://raw.githubusercontent.com/peldrunai/peldrun-provider-catalog/main/catalog.json"
```

Restart the backend. The next Store → Providers → Catalog page load fetches the file.

### Force an immediate refresh

```bash
curl -X POST http://localhost:8088/api/store/providers/catalog/refresh
```

Bypasses the 24-hour TTL and refetches from GitHub.

### Inspect the catalog state

```bash
curl http://localhost:8088/api/store/providers/catalog/status
```

Returns per-source item counts (built-in / custom / remote), cache age, and the last fetch error (if any).

### Disable remote fetching

```bash
unset PELDRUN_PROVIDER_CATALOG_URL
```

PELDRUN reverts to its bundled catalog. No data is deleted — the cached copy remains on disk until manually removed.

---

## Local validation

Requires Python 3.10+.

```bash
python scripts/validate.py
```

The script checks:

- `catalog.json` parses as JSON.
- `schema_version` matches a supported value.
- Every item passes `ProviderPackageCatalogItem` Pydantic validation.
- Every `download_url` is `https://`.
- Every `checksum_sha256` is a 64-character lowercase hex digest.
- No duplicate IDs.

Exit code is `0` on success, `1` on any failure. CI runs the same script.

---

## License

MIT — see [`LICENSE`](LICENSE).

---

## Related repositories

- [peldrun](https://github.com/peldrun/peldrun) — the main application.
- [peldrun-provider-gigachat](https://github.com/peldrunai/peldrun-provider-gigachat) — GigaChat provider package.
```
