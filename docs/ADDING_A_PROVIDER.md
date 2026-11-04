```markdown
# Adding a Provider to the Catalog

This guide walks through every step required to publish a new Provider Package in the PELDRUN catalog. It assumes the provider's source code and build pipeline already exist in a separate repository (for example `peldrunai/peldrun-provider-gigachat`).

The catalog itself only carries **metadata**. The actual ZIP archive lives elsewhere — by convention, as a GitHub Release asset on the provider's own repository.

---

## Prerequisites

Before you can add an item to `catalog.json`, you need:

1. **A published ZIP** of the provider package, built from the provider's own repository.
2. **The SHA-256 checksum** of that exact ZIP.
3. **The manifest fields** that the catalog item mirrors:
   - `id` — the provider package's canonical ID (from `manifest.json`).
   - `name`, `display_name`, `description`.
   - `version` — the semantic version from `manifest.json`.
   - `transport` — `native`, `compatible`, or `custom`.
   - `features`, `permissions` — copied verbatim from `manifest.json`.

If the provider has no Release yet, complete those steps first. The catalog cannot reference a ZIP that does not exist at a stable URL.

---

## Step 1 — Build the ZIP

From the provider's own repository:

```bash
./scripts/build.sh
```

This produces a deterministic ZIP under `dist/`, for example:

```
dist/gigachat-1.0.0.zip
```

Verify the ZIP contains a `manifest.json` at its root (or inside a single top-level folder — both layouts are accepted by PELDRUN's installer):

```bash
unzip -l dist/gigachat-1.0.0.zip | head -20
```

Expected: `manifest.json` and any Python modules referenced by `entry_point` are present.

---

## Step 2 — Compute the SHA-256 checksum

```bash
# Linux / macOS
sha256sum dist/gigachat-1.0.0.zip

# Windows PowerShell
Get-FileHash -Algorithm SHA256 -Path dist\gigachat-1.0.0.zip
```

The output is a 64-character lowercase hex string. Save it — it goes into `catalog.json` as `checksum_sha256`.

```
a1b2c3d4e5f67890abcdef1234567890abcdef1234567890abcdef1234567890
```

**This checksum is not optional.** PELDRUN refuses to install any package whose catalog entry lacks a valid SHA-256. The intent is supply-chain integrity: if someone compromises the download server, the checksum will not match and the install aborts.

---

## Step 3 — Publish the ZIP as a GitHub Release

In the **provider's own repository**:

```bash
gh release create v1.0.0 \
  --repo peldrunai/peldrun-provider-gigachat \
  --title "GigaChat Provider v1.0.0" \
  --notes "Initial release" \
  dist/gigachat-1.0.0.zip
```

Or via the web UI:

1. Open `https://github.com/peldrunai/peldrun-provider-gigachat/releases/new`.
2. Fill in `Tag: v1.0.0`, `Title: ...`, `Description: ...`.
3. Drag `dist/gigachat-1.0.0.zip` into the attachments area.
4. Click **Publish release**.

The resulting direct download URL will have this shape:

```
https://github.com/peldrunai/peldrun-provider-gigachat/releases/download/v1.0.0/gigachat-1.0.0.zip
```

**Do not use** `https://github.com/.../archive/refs/tags/v1.0.0.zip` — that returns the source tree, not the built ZIP, and its SHA-256 will not match what the provider's build script produced.

**Do not use** `https://raw.githubusercontent.com/.../dist/gigachat-1.0.0.zip` — raw URLs are size-capped and not intended for release artifacts.

---

## Step 4 — Verify the download URL

From any machine with internet access:

```bash
curl -L -o /tmp/gigachat-test.zip \
  "https://github.com/peldrunai/peldrun-provider-gigachat/releases/download/v1.0.0/gigachat-1.0.0.zip"

sha256sum /tmp/gigachat-test.zip
```

The hash must equal the one computed in Step 2. If it differs, the ZIP was modified after publishing — re-upload the Release asset and retry.

---

## Step 5 — Add the item to `catalog.json`

Open `catalog.json` and append a new object under `items`. A minimal installable item looks like this:

```json
{
  "id": "gigachat",
  "name": "GigaChat",
  "display_name": "GigaChat",
  "description": "Native GigaChat adapter for the Sber GigaChat API.",
  "version": "1.0.0",
  "transport": "native",
  "features": {
    "model_discovery": true,
    "native_streaming": true,
    "tool_calling": true,
    "vision": false,
    "reasoning": false
  },
  "permissions": {
    "network": "connection_endpoint",
    "secrets": ["connection.api_key"]
  },
  "download_url": "https://github.com/peldrunai/peldrun-provider-gigachat/releases/download/v1.0.0/gigachat-1.0.0.zip",
  "checksum_sha256": "a1b2c3d4e5f67890abcdef1234567890abcdef1234567890abcdef1234567890",
  "author": "peldrunai",
  "author_url": "https://github.com/peldrunai",
  "homepage": "https://developers.sber.ru/docs/ru/gigachat",
  "tags": ["gigachat", "sber", "cloud"]
}
```

### Field reference

| Field | Required | Notes |
|---|---|---|
| `id` | ✅ | Lowercase, `[a-z0-9._-]`, must match the manifest's `id` |
| `name` | ✅ | Technical name |
| `version` | ✅ | Semver, must match the ZIP's `manifest.json` |
| `transport` | ✅ | `native`, `compatible`, or `custom` |
| `download_url` | Either both, or neither | HTTPS only |
| `checksum_sha256` | Either both, or neither | 64-char lowercase hex |
| `display_name`, `description` | Recommended | Shown on the catalog card |
| `features`, `permissions` | Recommended | Mirror from `manifest.json` for accurate UI warnings |
| `author`, `author_url`, `homepage` | Optional | Shown in the details drawer |
| `tags` | Optional | Free-form; used for filtering |

### Preview-only items

If the ZIP is not ready yet, add the item with both `download_url` and `checksum_sha256` set to `null`:

```json
{
  "id": "future-provider",
  "name": "Future Provider",
  "version": "1.0.0",
  "transport": "native",
  "download_url": null,
  "checksum_sha256": null,
  "tags": ["preview"]
}
```

PELDRUN renders preview-only items in the store with a **Preview** badge and a disabled **Install** button. Users can see that the provider exists, without being able to install an unfinished package.

---

## Step 6 — Validate locally

```bash
python scripts/validate.py
```

Expected output:

```
Validating /path/to/peldrun-provider-catalog/catalog.json
OK: catalog.json is valid (0 warning(s)).
```

The validator enforces every rule that PELDRUN's runtime enforces:

- `id` matches `^[a-z0-9][a-z0-9._-]*$`
- `version` matches semver
- `transport` is one of the three allowed values
- `download_url` is `https://`
- `checksum_sha256` is a valid SHA-256 hex digest
- The two integrity fields are both set or both `null`
- No duplicate `id` values

If it reports errors, fix them before continuing. The same script runs in CI — a failing local check will fail the PR.

---

## Step 7 — Update `docs/CHANGELOG.md`

Add an entry to the top of the changelog:

```markdown
## 2026-11-04

- **Added:** `gigachat` v1.0.0 — Native GigaChat adapter for the Sber GigaChat API.
```

Every catalog change must be accompanied by a changelog entry. The changelog is the authoritative record of what changed and when.

---

## Step 8 — Commit and open a pull request

```bash
git checkout -b add-gigachat-provider
git add catalog.json docs/CHANGELOG.md
git commit -m "Add gigachat provider v1.0.0"
git push -u origin add-gigachat-provider
```

Then open a pull request against `main`. The CI workflow (`Validate Catalog`) runs automatically and blocks merge on any failure.

### Pull request checklist

- [ ] `catalog.json` validates locally (`python scripts/validate.py` returns 0).
- [ ] The new `download_url` is a GitHub Releases asset (not a raw URL or archive tag).
- [ ] The `checksum_sha256` matches the exact ZIP at that URL.
- [ ] The ZIP's `manifest.json` `id` and `version` match the catalog entry.
- [ ] `docs/CHANGELOG.md` has a corresponding entry.
- [ ] Only the intended files are touched (no unrelated reformatting).

---

## Step 9 — Post-merge propagation

After the PR is merged to `main`, PELDRUN instances that have `PELDRUN_PROVIDER_CATALOG_URL` set will pick up the new item at the next TTL expiry (24 hours by default) — or immediately, if an administrator runs:

```bash
curl -X POST http://localhost:8088/api/store/providers/catalog/refresh
```

Verify the fetch succeeded:

```bash
curl http://localhost:8088/api/store/providers/catalog/status
```

Expected response includes:

```json
{
  "catalog": {
    "remote_url_configured": true,
    "remote_count": 1,
    "remote_last_error": null
  }
}
```

The new provider is now visible in **Store → Providers → Catalog** with an **Install** button.

---

## Updating an existing provider

When a provider publishes a new version:

1. Build and publish a new ZIP as a GitHub Release (e.g. `v1.1.0`).
2. Compute its SHA-256.
3. In `catalog.json`, update **only** these fields on the existing item:
   - `version`
   - `download_url`
   - `checksum_sha256`
4. Add a changelog entry.
5. Open a PR.

Do **not** duplicate the item. PELDRUN treats the `id` field as the identity — two items with the same `id` fail the validator. Updating in place preserves user-facing continuity (the provider appears at the same position in the store, with the same tags and metadata).

---

## Removing a provider from the catalog

To hide a provider from the store without breaking users who already installed it:

1. Set `download_url` and `checksum_sha256` to `null` (demote to preview-only).
2. Add a changelog entry explaining why.

To fully remove a provider:

1. Delete the item from `catalog.json`.
2. Add a changelog entry.

Existing installations on user machines are **not** affected. Removing a catalog item only affects future installs — PELDRUN never uninstalls a package because it disappeared from the catalog. Users who want to remove it do so manually via **Store → Providers → Installed → Uninstall**.

---

## Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| PELDRUN shows "Preview only" for an item you marked installable | `checksum_sha256` is missing or malformed | Verify it's 64 lowercase hex characters |
| Install fails with "checksum mismatch" | ZIP was re-uploaded after the checksum was recorded | Recompute the SHA-256 and update `catalog.json` |
| CI fails on `trailing whitespace` | Editor added spaces at line ends | Enable "trim trailing whitespace on save" |
| CI fails on `CRLF line endings` | File saved with Windows line endings | Configure editor to use LF, or run `dos2unix catalog.json` |
| Install fails with "HTTP 404 from download_url" | The GitHub Release was deleted, or the tag is wrong | Verify the URL in a browser first |
| PELDRUN shows a stale item after a merge | 24-hour TTL has not expired on that instance | Call `POST /api/store/providers/catalog/refresh` |

---

## See also

- [`../README.md`](../README.md) — repository overview and admin commands.
- [`../schema/catalog.schema.json`](../schema/catalog.schema.json) — JSON Schema reference.
- [`CHANGELOG.md`](CHANGELOG.md) — full history of catalog changes.
- [`../../backend/omweb/provider_packages/catalog.py`](https://github.com/peldrunai/peldrun/blob/main/backend/omweb/provider_packages/catalog.py) — PELDRUN's catalog fetcher (reference implementation).
```