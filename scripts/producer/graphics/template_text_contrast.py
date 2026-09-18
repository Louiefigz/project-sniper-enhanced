"""Source-bound local text-plate facts for existing lint and decoded Audit B.

Declarations are not approval by themselves. Only exact reviewed template bytes
may supply them; the final composite must still contain measurable role/backing
pixels. Legacy scrims deliberately have no invented fixed background.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from graphics.template_contract import COMPOSITIONS_DIR, declared_variables
from producer_config import MOTION

_ROLES = re.compile(r"data-contrast-roles='([^']*)'")
_HEX = re.compile(r"#[0-9a-fA-F]{6}\Z")


def _object(value: object, keys: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("text contrast declarations have unexpected fields")
    return value


def _role(value: object, declared: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("text contrast role is not an object")
    color_key = "foregroundVariable" if "foregroundVariable" in value else "foreground"
    row = _object(value, {"id", "selector", "copyVariable", color_key,
                          "background", "fullOpacityAt"})
    if not all(isinstance(row[key], str) and row[key] for key in
               ("id", "selector", "copyVariable", color_key, "background")):
        raise ValueError("text contrast role has invalid strings")
    if row["copyVariable"] not in declared or not _HEX.fullmatch(row["background"]):
        raise ValueError("text contrast role has unknown copy or background")
    if color_key == "foregroundVariable" and row[color_key] not in declared:
        raise ValueError("text contrast role has an unknown foreground variable")
    if color_key == "foreground" and not _HEX.fullmatch(row[color_key]):
        raise ValueError("text contrast role has an invalid foreground")
    at = row["fullOpacityAt"]
    if isinstance(at, bool) or not isinstance(at, (float, int)) or not math.isfinite(at) or at < 0:
        raise ValueError("text contrast role has an invalid visibility time")
    return row


def text_plate_contract(kind: str) -> dict | None:
    """Read exact reviewed source; absence means no supported plate contract."""
    expected = MOTION["contrast"].get("text_plate_sources", {}).get(kind)
    if expected is None:
        return None
    source = (Path(COMPOSITIONS_DIR) / f"{kind}.html").read_bytes()
    if len(source) > 1024 * 1024 or hashlib.sha256(source).hexdigest() != expected:
        raise ValueError(f"{kind} text contrast template hash is not qualified")
    html = source.decode("utf-8", errors="strict")
    matches = _ROLES.findall(html)
    if len(matches) != 1:
        raise ValueError("text contrast requires one source declaration")
    row = _object(json.loads(matches[0]), {"schemaVersion", "treatment", "roles", "exit"})
    if type(row["schemaVersion"]) is not int or row["schemaVersion"] != 1 or row["treatment"] != "plates":
        raise ValueError("unsupported text contrast declaration version/treatment")
    declared = declared_variables(html)
    roles = row["roles"]
    if not isinstance(roles, list) or not 1 <= len(roles) <= 8:
        raise ValueError("text contrast has invalid role count")
    clean = [_role(role, declared) for role in roles]
    if len({role["id"] for role in clean}) != len(clean):
        raise ValueError("text contrast has duplicate roles")
    exit_row = _object(row["exit"], {"maximumSeconds", "durationFraction", "frameReserveSeconds"})
    if any(type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 1
           for value in exit_row.values()):
        raise ValueError("text contrast has invalid exit timing")
    return {**row, "roles": clean, "declared": declared, "templateSha256": expected}


def effective_text_roles(graphic: dict, contract: dict) -> list[dict]:
    """Resolve actual declared defaults only when an authored value is absent."""
    spec = graphic.get("spec") or {}
    if not isinstance(spec, dict):
        raise ValueError("text contrast spec is not an object")
    roles = []
    for role in contract["roles"]:
        key = role["copyVariable"]
        text = spec.get(key, contract["declared"][key].get("default"))
        if not isinstance(text, str):
            raise ValueError(f"text contrast {key} must be text")
        if not text.strip():
            continue
        key = role.get("foregroundVariable")
        foreground = role.get("foreground") if key is None else spec.get(
            key, contract["declared"][key].get("default"))
        if not isinstance(foreground, str) or not _HEX.fullmatch(foreground):
            raise ValueError(f"text contrast {role['id']} requires explicit #RRGGBB evidence")
        roles.append({**role, "foreground": foreground, "copy": text})
    return roles


def text_treatment(graphic: dict, contract: dict) -> str:
    """Omitted readability retains the source's legacy scrim semantics."""
    spec = graphic.get("spec") or {}
    if not isinstance(spec, dict):
        raise ValueError("text contrast spec is not an object")
    value = spec.get("readability", contract["declared"]["readability"]["default"])
    if value not in ("scrim", "plates"):
        raise ValueError("text contrast has an unsupported readability treatment")
    return value
