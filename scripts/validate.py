#!/usr/bin/env python3
# scripts/validate.py
"""
Local validation for catalog.json.

This script mirrors the checks performed by the CI workflow
(.github/workflows/validate-catalog.yml) so contributors can catch
problems BEFORE pushing. It has no third-party dependencies — only
the Python standard library — so it can be run on any machine with
Python 3.10+.

Checks
------
    1. catalog.json exists and parses as JSON.
    2. schema_version is a supported integer (currently only 1).
    3. Every item in "items" is a JSON object.
    4. Every item passes the field-level rules enforced by PELDRUN's
       runtime (backend/omweb/provider_packages/catalog.py and
       schema.py):
         - id matches ^[a-z0-9][a-z0-9._-]*$
         - version matches semver
         - transport in {native, compatible, custom}
         - download_url, when set, is https://
         - checksum_sha256, when set, is a 64-char lowercase hex digest
         - download_url and checksum_sha256 are both set, or both null
           (a ZIP URL without a checksum is rejected — supply-chain
           integrity is non-negotiable)
    5. No duplicate "id" values.

Exit code
---------
    0   All checks passed.
    1   One or more checks failed. All failures are printed so the
        contributor can fix them in one pass.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants — must match backend/omweb/provider_packages/schema.py
# ---------------------------------------------------------------------------

#: Root of the repository (this script lives in scripts/).
REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = REPO_ROOT / "catalog.json"

SUPPORTED_SCHEMA_VERSIONS = {1}

PROVIDER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
VERSION_PATTERN = re.compile(
    r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_TRANSPORTS = {"native", "compatible", "custom"}


# ---------------------------------------------------------------------------
# ANSI colours — degrade gracefully on terminals that do not support them
# ---------------------------------------------------------------------------

def _supports_colour() -> bool:
    return sys.stdout.isatty() and sys.platform != "win32" or (
        sys.platform == "win32"
        and "ANSICON" in __import__("os").environ
    )


_RED = "\033[31m" if _supports_colour() else ""
_GREEN = "\033[32m" if _supports_colour() else ""
_YELLOW = "\033[33m" if _supports_colour() else ""
_DIM = "\033[2m" if _supports_colour() else ""
_RESET = "\033[0m" if _supports_colour() else ""


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class CatalogValidator:
    """
    Accumulate every error in one pass, then report them together.

    Reporting all errors at once (rather than exiting on the first
    failure) is deliberate: a contributor who fixed one issue should
    not have to re-run the script to discover the next.
    """

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def _err(self, message: str) -> None:
        self.errors.append(message)

    def _warn(self, message: str) -> None:
        self.warnings.append(message)

    # ------------------------------------------------------------------
    # Top-level
    # ------------------------------------------------------------------

    def validate_file(self) -> bool:
        """
        Load and validate catalog.json.

        Returns True when the file loads and every structural check
        passes. The individual item checks are still recorded on
        ``self.errors`` — the caller decides how to report them.
        """
        if not CATALOG_PATH.is_file():
            self._err(f"catalog.json not found at {CATALOG_PATH}")
            return False

        try:
            raw = CATALOG_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            self._err(f"Could not read catalog.json: {exc}")
            return False

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._err(
                f"catalog.json is not valid JSON: {exc.msg} "
                f"(line {exc.lineno}, column {exc.colno})"
            )
            return False

        if not isinstance(payload, dict):
            self._err(
                f"catalog.json root must be a JSON object, "
                f"got {type(payload).__name__}"
            )
            return False

        self._validate_top_level(payload)
        return not self.errors

    def _validate_top_level(self, payload: dict[str, Any]) -> None:
        # schema_version
        version = payload.get("schema_version")
        if version is None:
            self._err("catalog.json is missing required field 'schema_version'")
        elif not isinstance(version, int):
            self._err(
                f"'schema_version' must be an integer, "
                f"got {type(version).__name__}"
            )
        elif version not in SUPPORTED_SCHEMA_VERSIONS:
            self._err(
                f"Unsupported 'schema_version' {version}. "
                f"Supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )

        # items
        items = payload.get("items")
        if items is None:
            self._err("catalog.json is missing required field 'items'")
            return
        if not isinstance(items, list):
            self._err(
                f"'items' must be a JSON array, "
                f"got {type(items).__name__}"
            )
            return

        if len(items) == 0:
            self._warn(
                "catalog.json contains zero items. This is valid, but "
                "PELDRUN will log a warning and fall back to its "
                "built-in catalog when the remote fetch returns an "
                "empty item list."
            )

        seen_ids: set[str] = set()
        for index, item in enumerate(items):
            self._validate_item(item, index, seen_ids)

    # ------------------------------------------------------------------
    # Per-item
    # ------------------------------------------------------------------

    def _validate_item(
        self,
        item: Any,
        index: int,
        seen_ids: set[str],
    ) -> None:
        label = f"items[{index}]"

        if not isinstance(item, dict):
            self._err(f"{label} must be a JSON object, got {type(item).__name__}")
            return

        # --- id ------------------------------------------------------
        raw_id = item.get("id")
        if not isinstance(raw_id, str) or not raw_id:
            self._err(f"{label}.id must be a non-empty string")
        else:
            label = f"items[{index}] (id={raw_id!r})"
            if not PROVIDER_ID_PATTERN.match(raw_id):
                self._err(
                    f"{label}.id must match "
                    f"{PROVIDER_ID_PATTERN.pattern}, got {raw_id!r}"
                )
            if raw_id in seen_ids:
                self._err(f"{label}.id is a duplicate")
            else:
                seen_ids.add(raw_id)

        # --- name ----------------------------------------------------
        if not isinstance(item.get("name"), str) or not item.get("name"):
            self._err(f"{label}.name must be a non-empty string")

        # --- version -------------------------------------------------
        version = item.get("version")
        if not isinstance(version, str) or not version:
            self._err(f"{label}.version must be a non-empty string")
        elif not VERSION_PATTERN.match(version):
            self._err(
                f"{label}.version must be semver "
                f"(e.g. '1.0.0', '1.0.0-beta.1'), got {version!r}"
            )

        # --- transport -----------------------------------------------
        transport = item.get("transport")
        if transport not in ALLOWED_TRANSPORTS:
            self._err(
                f"{label}.transport must be one of "
                f"{sorted(ALLOWED_TRANSPORTS)}, got {transport!r}"
            )

        # --- download_url --------------------------------------------
        download_url = item.get("download_url")
        if download_url is not None:
            if not isinstance(download_url, str) or not download_url:
                self._err(
                    f"{label}.download_url must be a non-empty string "
                    f"or null"
                )
            elif not download_url.lower().startswith("https://"):
                self._err(
                    f"{label}.download_url must use https://, "
                    f"got {download_url!r}"
                )

        # --- checksum_sha256 -----------------------------------------
        checksum = item.get("checksum_sha256")
        if checksum is not None:
            if not isinstance(checksum, str) or not checksum:
                self._err(
                    f"{label}.checksum_sha256 must be a non-empty "
                    f"string or null"
                )
            elif not SHA256_HEX_PATTERN.match(checksum):
                self._err(
                    f"{label}.checksum_sha256 must be a 64-character "
                    f"lowercase hex digest, got {checksum!r}"
                )

        # --- integrity: both or neither -------------------------------
        has_url = isinstance(download_url, str) and bool(download_url)
        has_hash = isinstance(checksum, str) and bool(checksum)

        if has_url and not has_hash:
            self._err(
                f"{label}: download_url is set but checksum_sha256 "
                f"is missing. PELDRUN refuses to install a package "
                f"without a published SHA-256 — this is a "
                f"supply-chain integrity requirement."
            )
        elif has_hash and not has_url:
            self._err(
                f"{label}: checksum_sha256 is set but download_url "
                f"is missing. Either publish the ZIP and its hash "
                f"together, or set both to null for a preview-only "
                f"item."
            )

        # --- author / homepage (warnings only) -----------------------
        author = item.get("author")
        if author is not None and not isinstance(author, str):
            self._err(f"{label}.author must be a string or null")

        homepage = item.get("homepage")
        if homepage is not None and not (
            isinstance(homepage, str) and homepage.startswith(("https://", "http://"))
        ):
            self._warn(
                f"{label}.homepage should be an http(s) URL, "
                f"got {homepage!r}"
            )

        # --- features (must be a boolean map) ------------------------
        features = item.get("features")
        if features is not None:
            if not isinstance(features, dict):
                self._err(f"{label}.features must be a JSON object")
            else:
                for key, value in features.items():
                    if not isinstance(key, str):
                        self._err(
                            f"{label}.features keys must be strings, "
                            f"got {type(key).__name__}"
                        )
                        continue
                    if not isinstance(value, bool):
                        self._err(
                            f"{label}.features[{key!r}] must be a "
                            f"boolean, got {type(value).__name__}"
                        )

        # --- tags ----------------------------------------------------
        tags = item.get("tags")
        if tags is not None:
            if not isinstance(tags, list):
                self._err(f"{label}.tags must be a JSON array")
            else:
                for t_index, tag in enumerate(tags):
                    if not isinstance(tag, str):
                        self._err(
                            f"{label}.tags[{t_index}] must be a string, "
                            f"got {type(tag).__name__}"
                        )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def report(self) -> int:
        """Print all warnings and errors, then return an exit code."""
        if self.warnings:
            print(f"{_YELLOW}Warnings:{_RESET}")
            for w in self.warnings:
                print(f"  {_YELLOW}~{_RESET} {w}")
            print()

        if self.errors:
            print(f"{_RED}Errors:{_RESET}")
            for e in self.errors:
                print(f"  {_RED}x{_RESET} {e}")
            print()
            print(
                f"{_RED}FAILED{_RESET}: {len(self.errors)} error(s), "
                f"{len(self.warnings)} warning(s)."
            )
            return 1

        print(
            f"{_GREEN}OK{_RESET}: catalog.json is valid "
            f"({len(self.warnings)} warning(s))."
        )
        return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    print(f"{_DIM}Validating {CATALOG_PATH}{_RESET}")
    validator = CatalogValidator()
    validator.validate_file()
    return validator.report()


if __name__ == "__main__":
    sys.exit(main())