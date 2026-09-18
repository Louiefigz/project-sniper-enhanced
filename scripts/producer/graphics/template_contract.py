#!/usr/bin/env python3
"""Fail-closed contracts between planned graphics and Hyperframes templates.

Template defaults are preview conveniences, not editorial intent.  A plan must
name the content-bearing variables that the selected grammar actually reads.
The same functions are used by plan lint, the renderer, and the catalog CLI so
GUI/native authoring cannot invent a second, looser template contract.
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
from typing import Any

from graphics.template_content import (
    content_contract,
    content_value_errors,
    default_copy_errors,
    planned_copy_values,
)
from graphics.template_assets import (
    asset_contract,
    effective_asset_spec,
    resolved_selectors,
    selector_errors,
)
from graphics.template_catalog_contract import (
    catalog_entry_errors,
    image_asset_rows,
)
from graphics.template_hw_contract import hw_entry_errors
from graphics.template_visual_contract import visual_entry_errors

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_ROOT = os.environ.get(
    "SNIPER_PIPELINE_ROOT",
    os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "..")))
COMPOSITIONS_DIR = os.path.join(PIPELINE_ROOT, "templates", "motion",
                                "compositions")

_VARIABLES_RE = re.compile(
    r"data-composition-variables=(?P<quote>['\"])(?P<body>.*?)(?P=quote)",
    re.DOTALL)
_ROOT_RE = re.compile(r'<[^>]*data-composition-id="[^"]*"[^>]*>')
_DIM_RE = re.compile(r'data-(width|height)="(\d+)"')
_STATEMENT_KIND = "statement-card"
_VARIANTS = ("classic", "module")
# Module-only statement variables.  The MEASURED catalog declares all three
# with empty-string defaults, and an authoring surface that must round-trip
# every declared default key (guided candidate compilation) therefore has to
# emit them.  An exact empty string carries no content and drops nothing, so
# only a populated value is a real classic/module grammar collision.
_CLASSIC_UNREAD_KEYS = ("headlineLines", "statements", "statementLands")


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _carries_content(value: Any) -> bool:
    """True unless the value is an explicit blank equal to the measured default."""
    return str(value).strip() != ""


def declared_variables(comp_html: str) -> dict[str, dict]:
    """Return the template's declared variable rows keyed by id."""
    match = _VARIABLES_RE.search(comp_html)
    if match is None:
        raise ValueError("template has no data-composition-variables catalog")
    rows = json.loads(match.group("body"))
    if not isinstance(rows, list):
        raise ValueError("template variable catalog is not an array")
    return {str(row["id"]): row for row in rows if isinstance(row, dict)
            and isinstance(row.get("id"), str)}


def composition_dimensions(comp_html: str) -> tuple[int, int]:
    """Read the declared delivery canvas from the composition root."""
    root = _ROOT_RE.search(comp_html)
    if root is None:
        raise ValueError("template has no data-composition-id root element")
    dims = {key: int(value) for key, value in _DIM_RE.findall(root.group(0))}
    if dims.get("width", 0) <= 0 or dims.get("height", 0) <= 0:
        raise ValueError("template root needs positive data-width/data-height")
    return dims["width"], dims["height"]


def _statement_lands(value: Any) -> list[float] | None:
    """Parse the template's comma-separated statement swap times."""
    parts = [value] if isinstance(value, (int, float)) and not isinstance(
        value, bool) else str(value).split(",") if isinstance(value, str) else []
    try:
        lands = [float(part.strip() if isinstance(part, str) else part)
                 for part in parts if str(part).strip()]
    except (TypeError, ValueError):
        return None
    return lands if lands and all(math.isfinite(value) for value in lands) else None


def _classic_errors(spec: dict) -> list[str]:
    errors = []
    if not _nonempty(spec.get("text")):
        errors.append("classic requires explicit non-empty spec.text; the "
                      "template's demo default is not planned content")
    incompatible = [key for key in _CLASSIC_UNREAD_KEYS
                    if key in spec and _carries_content(spec[key])]
    if incompatible:
        errors.append("classic does not read " + ", ".join(
            f"spec.{key}" for key in incompatible))
    return errors


def _module_source_errors(spec: dict) -> tuple[list[str], str | None]:
    sources = [key for key in ("text", "headlineLines", "statements")
               if _nonempty(spec.get(key))]
    errors: list[str] = []
    if len(sources) != 1:
        errors.append("module requires exactly one explicit content source: "
                      "spec.text, spec.headlineLines, or spec.statements")
    unused = [key for key in ("text", "headlineLines", "statements")
              if key in spec and key not in sources]
    if unused:
        errors.append("unused/empty content fields are forbidden: " +
                      ", ".join(f"spec.{key}" for key in unused))
    return errors, sources[0] if len(sources) == 1 else None


def _module_errors(spec: dict, duration: float | None) -> list[str]:
    errors, source = _module_source_errors(spec)
    if spec.get("splitText") in (True, "true", "True", 1):
        errors.append("spec.splitText is classic-only")
    if source == "headlineLines":
        lines = [line.strip() for line in spec["headlineLines"].split("|")]
        if len(lines) != 2 or not all(lines):
            errors.append("spec.headlineLines requires exactly two non-empty lines")
    if source != "statements" and "statementLands" in spec:
        errors.append("spec.statementLands is only read with spec.statements")
    if source == "statements":
        errors.extend(_statement_sequence_errors(spec, duration))
    return errors


def _statement_sequence_errors(spec: dict, duration: float | None) -> list[str]:
    statements = [part.strip() for part in spec["statements"].split("|")]
    if not statements or not all(statements):
        return ["spec.statements contains an empty statement"]
    if len(statements) == 1:
        return (["single spec.statements entry must not declare statementLands"]
                if "statementLands" in spec else [])
    lands = _statement_lands(spec.get("statementLands"))
    if lands is None or len(lands) != len(statements) - 1:
        return [f"spec.statementLands needs {len(statements) - 1} explicit "
                "finite time(s), one for each replacement"]
    errors = []
    if any(value <= 0 for value in lands) or any(
            right <= left for left, right in zip(lands, lands[1:])):
        errors.append("spec.statementLands must be positive and strictly increasing")
    if duration is not None and any(value + 0.3 > duration + 1e-6 for value in lands):
        errors.append("spec.statementLands must leave 0.3s for the final text ramp")
    return errors


def statement_card_errors(entry: dict) -> list[str]:
    """Validate the mutually exclusive classic/module content grammars."""
    spec = entry.get("spec")
    if not isinstance(spec, dict):
        return ["spec must be an object"]
    variant = spec.get("variant")
    if variant not in _VARIANTS:
        return ["spec.variant must be explicitly 'classic' or 'module'; "
                "template defaults are not planning intent"]
    duration = None
    try:
        duration = float(entry["outEnd"]) - float(entry["outStart"])
    except (KeyError, TypeError, ValueError):
        pass
    return _classic_errors(spec) if variant == "classic" else \
        _module_errors(spec, duration)


def planned_copy(entry: dict, comp_html: str | None = None) -> list[str]:
    """Visible copy owed by validated explicit inputs, without relying on OCR."""
    kind = str(entry.get("kind", ""))
    if comp_html is None:
        path = os.path.join(COMPOSITIONS_DIR, f"{kind}.html")
        if not kind or not os.path.isfile(path):
            return []
        with open(path, encoding="utf-8") as handle:
            comp_html = handle.read()
    try:
        declared = declared_variables(comp_html)
    except (ValueError, json.JSONDecodeError):
        return []
    return planned_copy_values(entry.get("spec") or {}, declared)


def _value_errors(spec: dict, declared: dict[str, dict]) -> list[str]:
    """Validate variable shapes whose template metadata is unambiguous."""
    errors: list[str] = []
    for key, value in spec.items():
        row = declared.get(key)
        if row is None:
            continue
        kind = row.get("type")
        if kind == "enum":
            options = [option.get("value") for option in row.get("options", [])
                       if isinstance(option, dict)]
            if value not in options:
                errors.append(f"spec.{key} {value!r} is not in {options}")
        elif kind == "number" and (isinstance(value, bool) or not isinstance(
                value, (int, float)) or not math.isfinite(float(value))):
            errors.append(f"spec.{key} must be a finite number")
        elif kind == "boolean" and not isinstance(value, bool):
            errors.append(f"spec.{key} must be a boolean")
        elif kind == "color" and (not isinstance(value, str) or not re.fullmatch(
                r"#[0-9a-fA-F]{6}", value)):
            errors.append(f"spec.{key} must be a #RRGGBB color")
    return errors


def entry_errors(entry: dict, comp_html: str | None = None) -> list[str]:
    """Return every template/spec incompatibility for one planned graphic."""
    kind = str(entry.get("kind", ""))
    errors = statement_card_errors(entry) if kind == _STATEMENT_KIND else \
        hw_entry_errors(entry) + catalog_entry_errors(entry)
    if comp_html is None:
        path = os.path.join(COMPOSITIONS_DIR, f"{kind}.html")
        if not kind or not os.path.isfile(path):
            return errors + [f"no registered composition for kind {kind!r}"]
        with open(path, encoding="utf-8") as handle:
            comp_html = handle.read()
    try:
        allowed = declared_variables(comp_html)
    except (ValueError, json.JSONDecodeError) as exc:
        return errors + [f"invalid template variable catalog: {exc}"]
    spec = entry.get("spec")
    if not isinstance(spec, dict):
        return errors + ([] if errors else ["spec must be an object"])
    unknown = sorted(set(spec) - set(allowed))
    if unknown:
        errors.append("template does not read " + ", ".join(
            f"spec.{key}" for key in unknown))
    errors.extend(_value_errors(spec, allowed))
    errors.extend(content_value_errors(spec, allowed))
    errors.extend(default_copy_errors(kind, spec, allowed))
    errors.extend(selector_errors(kind, spec, allowed))
    errors.extend(visual_entry_errors(entry))
    return errors


def validate_entry(entry: dict, comp_html: str | None = None) -> None:
    """Raise before rendering when a plan would fall through to defaults."""
    errors = entry_errors(entry, comp_html)
    if errors:
        raise ValueError(f"{entry.get('kind', 'graphic')} template contract: " +
                         "; ".join(errors))


def template_catalog() -> dict[str, dict]:
    """JSON-safe catalog for GUI/native planners; sorted and source-derived."""
    catalog: dict[str, dict] = {}
    for path in sorted(glob.glob(os.path.join(COMPOSITIONS_DIR, "*.html"))):
        if os.path.basename(path).startswith("_gs-"):
            continue
        with open(path, encoding="utf-8") as handle:
            html = handle.read()
        kind = os.path.splitext(os.path.basename(path))[0]
        variables = declared_variables(html)
        schema = {key: {field: row[field] for field in ("type", "default", "options")
                        if field in row}
                  for key, row in sorted(variables.items())}
        catalog[kind] = {"dimensions": list(composition_dimensions(html)),
                         "variables": schema,
                         "contentContract": content_contract(variables),
                         "assetContract": asset_contract(kind, variables)}
    catalog.get(_STATEMENT_KIND, {}).update({
        "contentContract": {**catalog[_STATEMENT_KIND]["contentContract"],
                            "variants": list(_VARIANTS)}})
    return catalog


def resolved_assets(entry: dict, comp_html: str | None = None) -> list[dict]:
    """Identity-checked icon inputs for hashing and rendered proof."""
    kind = str(entry.get("kind", ""))
    if comp_html is None:
        path = os.path.join(COMPOSITIONS_DIR, f"{kind}.html")
        if not kind or not os.path.isfile(path):
            return []
        with open(path, encoding="utf-8") as handle:
            comp_html = handle.read()
    declared = declared_variables(comp_html)
    spec = effective_asset_spec(entry.get("spec") or {}, declared)
    return resolved_selectors(spec, declared) + image_asset_rows(spec, declared)
