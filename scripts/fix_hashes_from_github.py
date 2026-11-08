#!/usr/bin/env python3
# scripts/fix_hashes_from_github.py
"""
Verify and fix checksum_sha256 values in catalog.json.

For each item with a download_url, downloads the file, computes its
SHA-256, and writes the correct hash back to catalog.json if it differs.
The file is also rewritten when it does not end with a trailing LF, so
a plain `python scripts/fix_hashes_from_github.py` keeps the catalog in
a state that the CI accepts.

Proxy support: urllib honours HTTPS_PROXY / HTTP_PROXY environment
variables automatically. Set them before running if github.com is
unreachable from your network.

Exit codes:
    0   All checksums match, or all fixes were applied successfully.
    1   One or more packages could not be downloaded.
    2   Configuration problem (catalog missing or invalid JSON).
"""

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

CATALOG_FILE = Path(__file__).resolve().parent.parent / "catalog.json"
USER_AGENT = "PELDRUN-Catalog-Sync/1.0"
TIMEOUT = 30

# Mirror prefixes tried when the direct download_url is unreachable.
# Each prefix is prepended to the original URL, e.g.
#   https://ghproxy.net/https://github.com/...
# Order matters: the first one that responds wins.
MIRRORS = (
    "https://ghproxy.net",
    "https://gh-proxy.com",
    "https://ghfast.top",
)


def compute_sha256(url: str) -> str:
    """Stream-download url and return its SHA-256 hex digest."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    sha = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        for chunk in iter(lambda: response.read(64 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def download_and_hash(url: str) -> str:
    """
    Try downloading url directly first; on failure, try each mirror in
    MIRRORS in order. Returns the SHA-256 hex digest of the first
    successful download. Re-raises the last error if all attempts fail.
    """
    last_error: Exception | None = None

    try:
        return compute_sha256(url)
    except Exception as exc:
        last_error = exc
        print(f"  [DIRECT-FAIL] {exc}")

    for prefix in MIRRORS:
        mirrored = prefix + "/" + url
        print(f"  [MIRROR] {prefix}")
        try:
            return compute_sha256(mirrored)
        except Exception as exc:
            last_error = exc
            print(f"  [MIRROR-FAIL] {exc}")

    assert last_error is not None
    raise last_error


def main() -> int:
    if not CATALOG_FILE.exists():
        print(f"Error: {CATALOG_FILE} not found", file=sys.stderr)
        return 2

    try:
        original_text = CATALOG_FILE.read_text(encoding="utf-8")
        catalog = json.loads(original_text)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in {CATALOG_FILE}: {exc}", file=sys.stderr)
        return 2

    items = catalog.get("items", [])
    if not items:
        print("No items in catalog.")
        return 0

    print(f"Catalog: {CATALOG_FILE}")
    print(f"Items:   {len(items)}\n")

    updated = 0
    failed = 0

    for item in items:
        item_id = item.get("id", "unknown")
        url = item.get("download_url")

        if not url:
            print(f"[SKIP] {item_id}: no download_url")
            continue

        print(f"[FETCH] {item_id} -> {url}")
        try:
            actual = download_and_hash(url)
        except Exception as exc:
            print(f"  [ERROR] {exc}")
            failed += 1
            continue

        current = item.get("checksum_sha256")
        if current == actual:
            print(f"  [OK] {actual}")
        else:
            item["checksum_sha256"] = actual
            updated += 1
            print(f"  [FIXED]")
            print(f"    old: {current}")
            print(f"    new: {actual}")

    print()

    # Rewrite the file when either the checksums changed or the file
    # itself does not end with a newline (the CI enforces a trailing
    # LF). newline="\n" forces LF output on Windows too, so the file
    # never picks up CRLF line endings - the CI rejects those as well.
    needs_rewrite = updated > 0 or not original_text.endswith("\n")

    if needs_rewrite:
        CATALOG_FILE.write_text(
            json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if updated:
            print(f"Updated {updated} checksum(s) in {CATALOG_FILE}")
        else:
            print(f"Normalized {CATALOG_FILE} (added trailing newline)")
    else:
        print("No changes needed.")

    if failed:
        print(f"\n{failed} package(s) failed to download")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())