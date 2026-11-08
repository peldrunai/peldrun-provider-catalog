#!/usr/bin/env python3
# scripts/validate.py
"""
Local validation for catalog.json.

This script mirrors the checks performed by the CI workflow
(.github/workflows/validate-catalog.yml) and the JSON Schema at
schema/catalog.schema.json, so contributors can catch problems
BEFORE pushing. It has no third-party dependencies - only the
Python standard library - so it can be run on any machine with
Python 3.10+.

Checks
------
    1. catalog.json exists and parses as JSON.
    2. schema_version is a supported integer (currently only 1).
    3. Every item in "items" is a JSON object.
    4. Every item contains only known fields (mirrors
       `additionalProperties: false` in the JSON Schema) and every
       known field is type-checked against its documented contract.
    5. Every item passes the field-level rules enforced by PELDRUN's
       runtime (backend/omweb/provider_packages/catalog.py and
       schema.py) and by schema/catalog.schema.json:
         - id matches ^[a-z0-9][a-z0-9._-]*$
         - name is a non-empty string
         - version matches semver
         - transport in {native, compatible, custom}
         - download_url, when set, is https://
         - checksum_sha256, when set, is a 64-char lowercase hex digest
         - download_url and checksum_sha256 are both set, or both null
           (a ZIP URL without a checksum is rejected - supply-chain
           integrity is non-negotiable)
         - URL-shaped fields (homepage, author_url, developer.url)
           are syntactically valid URIs
         - developer, permissions, features are well-formed objects
         - brand_color, icon_type, license match their documented
           formats when present
    6. No duplicate "id" values.

Exit code
---------
    0   All checks passed.
    1   One or more checks failed. All failures are printed so the
        contributor can fix them in one pass.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants - must match backend/omweb/provider_packages/schema.py and
# schema/catalog.schema.json
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
BRAND_COLOR_PATTERN = re.compile(
    r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$"
)
#: Pragmatic RFC 3986 scheme check. Catches obvious junk like "not a url"
#: while staying close to jsonschema's FormatChecker("uri") behaviour.
URI_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:\S+$")
ALLOWED_TRANSPORTS = {"native", "compatible", "custom"}
ALLOWED_ICON_TYPES = {"name", "url"}

#: Fields accepted at the top level of catalog.json.
#: Must mirror the root `properties` map in schema/catalog.schema.json.
ALLOWED_TOP_LEVEL_FIELDS: frozenset[str] = frozenset({
    "schema_version",
    "description",
    "updated_at",
    "items",
})

#: Fields accepted on a catalog item.
#: Must mirror the `properties` map of `catalogItem` in
#: schema/catalog.schema.json - any field listed there must be listed
#: here, and vice versa, or the local and CI checks diverge.
ALLOWED_ITEM_FIELDS: frozenset[str] = frozenset({
    "id",
    "name",
    "display_name",
    "description",
    "version",
    "transport",
    "features",
    "permissions",
    "brand_color",
    "icon",
    "icon_type",
    "download_url",
    "checksum_sha256",
    "author",
    "author_url",
    "developer",
    "repository_url",
    "homepage",
    "license",
    "tags",
    "connection_fields",
    "certificates",
})

#: Fields accepted inside the nested `developer` object.
ALLOWED_DEVELOPER_FIELDS: frozenset[str] = frozenset({
    "name",
    "url",
    "github_username",
    "verified",
})


# ---------------------------------------------------------------------------
# ANSI colours - degrade gracefully on terminals that do not support them
# ---------------------------------------------------------------------------

def _supports_colour() -> bool:
    if sys.platform == "win32":
        return sys.stdout.isatty() and "ANSICON" in os.environ
    return sys.stdout.isatty()


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

        Returns True only when the file loads, the top-level structure
        is valid, and every individual item check has also passed.
        Every problem - top-level or per-item - is recorded on
        ``self.errors`` so the caller can report them all at once.
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
        # --- unknown top-level fields (mirrors additionalProperties:false)
        unknown = set(payload) - ALLOWED_TOP_LEVEL_FIELDS
        if unknown:
            self._err(
                f"catalog.json contains unknown top-level field(s) "
                f"{sorted(unknown)}. Allowed: "
                f"{sorted(ALLOWED_TOP_LEVEL_FIELDS)}"
            )

        # --- schema_version -----------------------------------------
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

        # --- description (optional) ---------------------------------
        description = payload.get("description")
        if description is not None and not isinstance(description, str):
            self._err(
                f"'description' must be a string, "
                f"got {type(description).__name__}"
            )

        # --- updated_at (optional) ----------------------------------
        updated_at = payload.get("updated_at")
        if updated_at is not None and not isinstance(updated_at, str):
            self._err(
                f"'updated_at' must be a string, "
                f"got {type(updated_at).__name__}"
            )

        # --- items ---------------------------------------------------
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

        # --- unknown fields (mirrors additionalProperties: false) ----
        unknown = set(item) - ALLOWED_ITEM_FIELDS
        if unknown:
            self._err(
                f"{label}: unknown field(s) {sorted(unknown)}. "
                f"Allowed fields: {sorted(ALLOWED_ITEM_FIELDS)}"
            )

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
        name = item.get("name")
        if not isinstance(name, str) or not name:
            self._err(f"{label}.name must be a non-empty string")

        # --- display_name (optional) --------------------------------
        self._validate_optional_string(item, "display_name", label)

        # --- description (optional) ---------------------------------
        self._validate_optional_string(item, "description", label)

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
            elif not download_url.startswith("https://"):
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
                f"without a published SHA-256 - this is a "
                f"supply-chain integrity requirement."
            )
        elif has_hash and not has_url:
            self._err(
                f"{label}: checksum_sha256 is set but download_url "
                f"is missing. Either publish the ZIP and its hash "
                f"together, or set both to null for a preview-only "
                f"item."
            )

        # --- author / author_url / homepage -------------------------
        self._validate_optional_string(item, "author", label)
        self._validate_optional_uri(item, "author_url", label)
        self._validate_optional_uri(item, "homepage", label)

        # --- developer (optional nested object) ---------------------
        self._validate_developer(item.get("developer"), label)

        # --- repository_url (optional, https:// only) --------------
        repository_url = item.get("repository_url")
        if repository_url is not None:
            if not isinstance(repository_url, str) or not repository_url:
                self._err(
                    f"{label}.repository_url must be a non-empty "
                    f"string or null"
                )
            elif not repository_url.startswith("https://"):
                self._err(
                    f"{label}.repository_url must use https://, "
                    f"got {repository_url!r}"
                )

        # --- license (optional non-empty string) -------------------
        license_id = item.get("license")
        if license_id is not None:
            if not isinstance(license_id, str) or not license_id:
                self._err(
                    f"{label}.license must be a non-empty string or null"
                )

        # --- brand_color (optional hex) ----------------------------
        brand_color = item.get("brand_color")
        if brand_color is not None:
            if (
                not isinstance(brand_color, str)
                or not BRAND_COLOR_PATTERN.match(brand_color)
            ):
                self._err(
                    f"{label}.brand_color must be a hex colour like "
                    f"'#21A038', got {brand_color!r}"
                )

        # --- icon / icon_type --------------------------------------
        icon = item.get("icon")
        if icon is not None:
            if not isinstance(icon, str) or not icon:
                self._err(
                    f"{label}.icon must be a non-empty string or null"
                )

        icon_type = item.get("icon_type")
        if icon_type is not None:
            if (
                not isinstance(icon_type, str)
                or icon_type not in ALLOWED_ICON_TYPES
            ):
                self._err(
                    f"{label}.icon_type must be one of "
                    f"{sorted(ALLOWED_ICON_TYPES)} or null, "
                    f"got {icon_type!r}"
                )

        # --- permissions (optional object) -------------------------
        permissions = item.get("permissions")
        if permissions is not None and not isinstance(permissions, dict):
            self._err(
                f"{label}.permissions must be a JSON object, "
                f"got {type(permissions).__name__}"
            )

        # --- features (must be a boolean map) ----------------------
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

        # --- connection_fields / certificates ---------------------
        for field in ("connection_fields", "certificates"):
            value = item.get(field)
            if value is None:
                continue
            if not isinstance(value, list):
                self._err(
                    f"{label}.{field} must be a JSON array, "
                    f"got {type(value).__name__}"
                )
                continue
            for element_index, element in enumerate(value):
                if not isinstance(element, dict):
                    self._err(
                        f"{label}.{field}[{element_index}] must be a "
                        f"JSON object, got {type(element).__name__}"
                    )

    # ------------------------------------------------------------------
    # Field helpers
    # ------------------------------------------------------------------

    def _validate_optional_string(
        self, item: dict[str, Any], field: str, label: str
    ) -> None:
        value = item.get(field)
        if value is not None and not isinstance(value, str):
            self._err(
                f"{label}.{field} must be a string or null, "
                f"got {type(value).__name__}"
            )

    def _validate_optional_uri(
        self, item: dict[str, Any], field: str, label: str
    ) -> None:
        value = item.get(field)
        if value is None:
            return
        if not isinstance(value, str):
            self._err(
                f"{label}.{field} must be a string or null, "
                f"got {type(value).__name__}"
            )
            return
        if not URI_PATTERN.match(value):
            self._err(
                f"{label}.{field} must be a valid URI "
                f"(e.g. 'https://example.com'), got {value!r}"
            )
        elif not value.lower().startswith(("https://", "http://")):
            self._warn(
                f"{label}.{field} uses a non-HTTP scheme; "
                f"PELDRUN's UI expects an http(s) URL, got {value!r}"
            )

    def _validate_developer(self, developer: Any, label: str) -> None:
        if developer is None:
            return
        if not isinstance(developer, dict):
            self._err(
                f"{label}.developer must be a JSON object or null, "
                f"got {type(developer).__name__}"
            )
            return

        unknown = set(developer) - ALLOWED_DEVELOPER_FIELDS
        if unknown:
            self._err(
                f"{label}.developer contains unknown field(s) "
                f"{sorted(unknown)}. Allowed: "
                f"{sorted(ALLOWED_DEVELOPER_FIELDS)}"
            )

        dev_name = developer.get("name")
        if dev_name is not None and (
            not isinstance(dev_name, str) or not dev_name
        ):
            self._err(
                f"{label}.developer.name must be a non-empty string"
            )

        dev_url = developer.get("url")
        if dev_url is not None:
            if not isinstance(dev_url, str):
                self._err(f"{label}.developer.url must be a string")
            elif not URI_PATTERN.match(dev_url):
                self._err(
                    f"{label}.developer.url must be a valid URI, "
                    f"got {dev_url!r}"
                )

        dev_gh = developer.get("github_username")
        if dev_gh is not None and not isinstance(dev_gh, str):
            self._err(
                f"{label}.developer.github_username must be a string"
            )

        dev_verified = developer.get("verified")
        if dev_verified is not None and not isinstance(dev_verified, bool):
            self._err(f"{label}.developer.verified must be a boolean")

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