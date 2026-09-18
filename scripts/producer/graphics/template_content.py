#!/usr/bin/env python3
"""Source-derived content intent for Hyperframes template variables.

The HTML catalogs expose type/default metadata but do not distinguish visible
editorial copy from asset selectors and timing controls.  Keep that exclusion
list intentionally narrow: every declared string is presumed visible copy
unless its id is an established asset or timing-control shape.
"""
from __future__ import annotations

import re
from typing import Any

_ASSET_EXACT = frozenset({"avatarSrc", "image", "iconFile"})
_ASSET_NUMBERED_RE = re.compile(r"(?:icon|media)\d*\Z")
_TIMING_CONTROLS = frozenset({"moduleLands", "rowLands", "statementLands"})


def is_content_string(key: str, row: dict) -> bool:
    """True when a declared string is presumed to paint visible copy."""
    if row.get("type") != "string" or key in _TIMING_CONTROLS:
        return False
    return key not in _ASSET_EXACT and _ASSET_NUMBERED_RE.fullmatch(key) is None


def content_contract(declared: dict[str, dict]) -> dict:
    """Catalog metadata authoring surfaces can enforce before render."""
    content = [key for key, row in declared.items()
               if is_content_string(key, row)]
    required = [key for key in content
                if isinstance(declared[key].get("default"), str)
                and bool(declared[key]["default"].strip())]
    return {"defaultsCountAsContent": False,
            "contentVariables": content,
            "requiredDefaultOverrides": required}


def default_copy_errors(kind: str, spec: dict,
                        declared: dict[str, dict]) -> list[str]:
    """Reject implicit demo copy while permitting an explicit blank."""
    if kind == "statement-card":
        return []  # its mutually exclusive grammars validate intent directly
    required = content_contract(declared)["requiredDefaultOverrides"]
    missing = [key for key in required if key not in spec]
    if not missing:
        return []
    fields = ", ".join(f"spec.{key}" for key in missing)
    return [f"template demo copy would leak through {fields}; explicitly "
            "override each field with planned copy or an intentional blank"]


def planned_copy_values(spec: dict, declared: dict[str, dict]) -> list[str]:
    """Visible, explicitly planned strings in source declaration order."""
    values: list[str] = []
    for key, row in declared.items():
        value = spec.get(key)
        if not is_content_string(key, row) or not isinstance(value, str):
            continue
        values.extend(_copy_parts(value))
    return values


def _copy_parts(value: str) -> list[str]:
    """Flatten pipe-delimited visible units and strip emphasis markers."""
    return [part.strip().replace("*", "") for part in value.split("|")
            if part.strip()]


def content_value_errors(spec: dict,
                         declared: dict[str, dict]) -> list[str]:
    """An explicit content override must be a string (empty is intentional)."""
    return [f"spec.{key} must be a string or an explicit empty string"
            for key, value in spec.items()
            if key in declared and is_content_string(key, declared[key])
            and not isinstance(value, str)]
