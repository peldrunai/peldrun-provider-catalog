#!/usr/bin/env python3
# scripts/import_catalog_entry.py
"""
Fetch a remote catalog-entry.json and merge it into the local catalog.

Designed for the PELDRUN provider catalog repository. Add a new provider
by pointing this script at its published catalog entry:

    python scripts/import_catalog_entry.py \
        --url https://github.com/OWNER/REPO/releases/download/v1.0.0/catalog-entry.json

The script:
  1. Downloads the entry from a http(s) URL.
  2. Validates it parses as JSON and has an ``id`` field.
  3. Loads the local ``catalog.json``.
  4. Replaces any existing item with the same ``id`` (idempotent),
     or appends the new item.
  5. Updates ``updated_at`` to the current UTC timestamp.
  6. Writes ``catalog.json`` atomically.

Design constraints
------------------
* **Stdlib only** — no ``requests``, no ``httpx``. Works in a bare
  Python environment without installing anything.
* **Bounded network** — hard timeout, size cap, redirect limit.
* **Atomic write** — a crash mid-write leaves the previous catalog
  intact.
* **Idempotent** — re-running with the same URL produces the same
  file (modulo ``updated_at``).

Usage
-----
    # Basic: fetch + merge in place
    python scripts/import_catalog_entry.py --url <URL>

    # Preview only, do not write:
    python scripts/import_catalog_entry.py --url <URL> --dry-run

    # Custom catalog path:
    python scripts/import_catalog_entry.py --url <URL> --catalog other.json

    # Skip the "updated_at" bump (rare; usually not what you want):
    python scripts/import_catalog_entry.py --url <URL> --no-touch-timestamp

Exit codes
----------
    0 — success (or --dry-run completed)
    1 — invalid URL or missing required args
    2 — fetch failed (network / HTTP / size / timeout)
    3 — catalog-entry.json is not valid JSON or missing ``id``
    4 — catalog.json is missing / invalid, or write failed
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CATALOG_PATH = Path("catalog.json")
FETCH_TIMEOUT_SECONDS = 30.0
MAX_ENTRY_BYTES = 2 * 1024 * 1024  # 2 MB — an entry is a few KB
MAX_REDIRECTS = 3

USER_AGENT = (
    "peldrun-catalog-importer/1.0 "
    "(+https://github.com/peldrunai/peldrun-provider-catalog)"
)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def _fetch_json(url: str) -> Dict[str, Any]:
    """
    Download ``url`` and parse it as JSON.

    Raises ``RuntimeError`` with a clear message on any failure —
    network, HTTP, size, or JSON parse.
    """
    if not url.lower().startswith(("http://", "https://")):
        raise RuntimeError(
            f"URL scheme must be http or https, got {url!r}"
        )

    # Custom opener that enforces a max redirect count.
    class _LimitedRedirect(urllib.request.HTTPRedirectHandler):
        max_repeats = MAX_REDIRECTS
        max_redirections = MAX_REDIRECTS

    opener = urllib.request.build_opener(_LimitedRedirect())

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    try:
        with opener.open(request, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            if status != 200:
                raise RuntimeError(
                    f"HTTP {status} from {url}"
                )

            # Enforce size cap while reading.
            chunks = []
            total = 0
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ENTRY_BYTES:
                    raise RuntimeError(
                        f"Entry exceeds {MAX_ENTRY_BYTES} bytes "
                        f"(aborted at {total} bytes)."
                    )
                chunks.append(chunk)
            raw = b"".join(chunks)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"HTTP {exc.code} from {url}: {exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not fetch {url}: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise RuntimeError(
            f"Fetch timed out after {FETCH_TIMEOUT_SECONDS:.0f}s: {url}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"Fetch failed for {url}: {exc}"
        ) from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            f"Entry is not valid UTF-8: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Entry is not valid JSON: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


def _validate_entry(entry: Any) -> Dict[str, Any]:
    """Ensure the parsed entry is an object with a non-empty string ``id``."""
    if not isinstance(entry, dict):
        raise RuntimeError(
            f"Entry must be a JSON object, got {type(entry).__name__}"
        )
    entry_id = entry.get("id")
    if not isinstance(entry_id, str) or not entry_id.strip():
        raise RuntimeError(
            "Entry is missing a non-empty string 'id' field."
        )
    return entry


# ---------------------------------------------------------------------------
# Catalog load / write
# ---------------------------------------------------------------------------


def _load_catalog(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"Catalog not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Catalog at {path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError(
            f"Catalog at {path} must be a JSON object."
        )
    if "items" not in data or not isinstance(data["items"], list):
        raise RuntimeError(
            f"Catalog at {path} has no 'items' array."
        )
    return data


def _write_catalog(path: Path, data: Dict[str, Any]) -> None:
    serialized = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(serialized, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        raise RuntimeError(
            f"Could not write {path}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def _merge(
    catalog: Dict[str, Any],
    entry: Dict[str, Any],
    *,
    touch_timestamp: bool,
) -> str:
    """
    Merge ``entry`` into ``catalog["items"]``.

    Returns ``"replaced"`` when an existing item with the same id was
    overwritten, ``"added"`` otherwise.
    """
    entry_id = entry["id"]
    items = catalog["items"]

    replaced = False
    for idx, existing in enumerate(items):
        if isinstance(existing, dict) and existing.get("id") == entry_id:
            items[idx] = entry
            replaced = True
            break
    if not replaced:
        items.append(entry)

    if touch_timestamp:
        catalog["updated_at"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )

    return "replaced" if replaced else "added"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch a remote catalog-entry.json and merge it into the "
            "local catalog.json."
        ),
    )
    parser.add_argument(
        "--url",
        required=True,
        help=(
            "Direct URL to a catalog-entry.json file. The file must be "
            "served over http(s) and contain a non-empty 'id' field."
        ),
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG_PATH,
        help=(
            f"Path to the catalog file to update "
            f"(default: {DEFAULT_CATALOG_PATH})."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and merge in memory, print a summary, do not write.",
    )
    parser.add_argument(
        "--no-touch-timestamp",
        action="store_true",
        help=(
            "Do not update 'updated_at' in the catalog. Usually not "
            "what you want — the timestamp exists for a reason."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = _parse_args(argv)

    url = args.url.strip()
    if not url:
        print("error: --url must not be empty", file=sys.stderr)
        return 1

    catalog_path = Path(args.catalog).resolve()

    print(f"Fetching: {url}")
    try:
        entry = _fetch_json(url)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        entry = _validate_entry(entry)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    try:
        catalog = _load_catalog(catalog_path)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4

    entry_id = entry["id"]
    entry_version = entry.get("version", "?")
    entry_checksum = entry.get("checksum_sha256", "")
    entry_download = entry.get("download_url", "")

    action = _merge(
        catalog,
        entry,
        touch_timestamp=not args.no_touch_timestamp,
    )

    print()
    print(f"Entry id:        {entry_id}")
    print(f"Entry version:   {entry_version}")
    if entry_checksum:
        print(f"SHA-256:         {entry_checksum[:16]}...")
    if entry_download:
        print(f"Download URL:    {entry_download}")
    print()
    print(f"Action:          {action}")
    print(f"Catalog:         {catalog_path}")
    print(f"Total items:     {len(catalog['items'])}")

    if args.dry_run:
        print()
        print("Dry run — no files were written.")
        return 0

    try:
        _write_catalog(catalog_path, catalog)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4

    print()
    print("Wrote catalog.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))