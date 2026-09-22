#!/usr/bin/env python3
"""Visible-completeness rules for long-form motion templates.

Rendering a valid file is not enough.  A planned window must contain a real
identity where the layout promises one and must remain on screen after its
last content reveal long enough to read before its exit animation begins.
"""
from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Any
from graphics.template_layout_contract import native_layout_errors

_BRAND_COLOR_ASSETS = {
    "openai": "openai-color.svg",
    "claude": "claude-color.svg",
    "gemini": "gemini-color.svg",
}

# kind -> (absolute floor, reveal settle, readable dwell, exit runway)
_TIMING_POLICY = {
    "glass-rail": (3.0, 0.46, 1.25, 0.42),
    "icon-badge-wide": (3.0, 0.16, 1.25, 0.42),
    "statement-card": (2.5, 0.45, 1.25, 0.15),
    "module-rail": (4.0, 0.45, 1.25, 0.0),
    "module-bullet-bars": (4.0, 0.50, 1.25, 0.0),
    "avatar-bio-card": (5.0, 0.70, 1.50, 0.0),
    "whiteboard-connector": (3.0, 0.30, 1.25, 0.42),
    "module-ledger-dark": (4.0, 0.50, 1.25, 0.0),
    "module-scoreboard": (0.0, 0.20, 1.25, 0.0),
    "module-pipeline": (0.0, 0.20, 1.25, 0.0),
}


def _constant(source: str, name: str) -> float:
    """Require one finite literal in the actual renderer source, never guess."""
    prefix = r"(?:\b(?:const|var) " + name + r"\s*=|\b" + name + r"\s*:)"
    rows = re.findall(prefix + r"\s*([0-9.]+)\s*[,;]", source)
    if len(rows) != 1 or not math.isfinite(float(rows[0])):
        raise ValueError(f"template timing source no longer declares exactly one {name}")
    return float(rows[0])


def _timing_tokens(relative: str, names: tuple[str, ...]) -> dict[str, float]:
    """Use the same pipeline root as the template contract and sealed build."""
    root = Path(os.environ.get("SNIPER_PIPELINE_ROOT", str(Path(__file__).resolve().parents[3])))
    motion = root / "templates/motion"
    source = (motion / relative).read_text()
    shared = (motion / "motion-tokens.js").read_text()
    return {**{name: _constant(source, name) for name in names},
            **{name: _constant(shared, name) for name in ("TEXT_RAMP_S", "EYEBROW_LEAD_S", "EXIT_BLUR_S")}}


def _scoreboard_tokens() -> dict[str, float]:
    """Keep the established scoreboard source/token observation entrypoint."""
    names = ("LAND_DEFAULT_START_S", "LAND_DEFAULT_GAP_S", "CTX_STAGGER_S", "TILE_STAGGER_S", "CHIP_SWEEP_S")
    return _timing_tokens("compositions/module-scoreboard.html", names)


def _parts(spec: dict, key: str) -> list[str]:
    """Count present pipe-delimited rows, matching the template's pruning."""
    return [part.strip() for part in str(spec.get(key) or "").split("|") if part.strip()]


def parse_module_lands(raw: object) -> list[float]:
    """Read the template's explicit schedule without partial numeric coercion."""
    values = re.split(r"[|,]", raw) if isinstance(raw, str) else raw
    if not isinstance(values, list) or not values or any(isinstance(value, bool) for value in values):
        raise ValueError("moduleLands requires a non-empty array or delimited string of finite times")
    decimal = r"[ \t\r\n]*[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?[ \t\r\n]*"
    if any(not isinstance(value, (str, int, float)) or
           isinstance(value, str) and not re.fullmatch(decimal, value) for value in values):
        raise ValueError("moduleLands requires complete ASCII decimal times")
    try:
        result = [float(value) for value in values]
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("moduleLands contains an invalid time") from error
    if any(not math.isfinite(value) or value < 0 for value in result) or result != sorted(set(result)):
        raise ValueError("moduleLands must be finite, nonnegative and strictly increasing")
    return result


def _module_lands(raw: object, count: int, tokens: dict, label: str) -> list[float]:
    """Validate every explicit land; malformed schedules cannot become defaults."""
    if raw is None or raw == "":
        return [tokens["LAND_DEFAULT_START_S"] + index * tokens["LAND_DEFAULT_GAP_S"] for index in range(count)]
    result = parse_module_lands(raw)
    if len(result) != count:
        raise ValueError(f"{label} moduleLands requires exactly {count} finite times")
    return result


def module_land_variables(spec: dict, declared: dict) -> dict:
    """Serialize an authored numeric array to the template's declared string."""
    raw = spec.get("moduleLands")
    if not isinstance(raw, list) or declared.get("moduleLands", {}).get("type") != "string":
        return spec
    return {**spec, "moduleLands": "|".join(str(value) for value in parse_module_lands(raw))}


def scoreboard_timing(spec: dict) -> tuple[float, float, float]:
    """Last actual ramp, duration and exit runway; not subjective readability."""
    tokens = _scoreboard_tokens()
    eyebrow = bool(str(spec.get("eyebrow") or "").strip())
    counts = {"head": len(_parts(spec, "contextChips")), "tiles": len(_parts(spec, "tiles")),
              "strip": len(_parts(spec, "stripChips"))}
    present = {"head": eyebrow or counts["head"] > 0, "hero": bool(str(spec.get("heroValue") or "").strip()),
               "tiles": counts["tiles"] > 0, "strip": counts["strip"] > 0,
               "limit": bool(str(spec.get("limitText") or "").strip())}
    modules = [name for name, exists in present.items() if exists]
    if not modules:
        raise ValueError("scoreboard has no explicit visible modules; preview sample is not editorial content")
    lands = dict(zip(modules, _module_lands(spec.get("moduleLands"), len(modules), tokens, "scoreboard"), strict=True))
    tails = dict(lands)
    if counts["head"]:
        tails["head"] += (tokens["EYEBROW_LEAD_S"] if eyebrow else 0) + (counts["head"] - 1) * tokens["CTX_STAGGER_S"]
    for name, stagger in (("tiles", "TILE_STAGGER_S"), ("strip", "CHIP_SWEEP_S")):
        if counts[name]:
            tails[name] += (counts[name] - 1) * tokens[stagger]
    exit_s = tokens["EXIT_BLUR_S"] if spec.get("exit") == "blur-recede" else 0.0
    return max(tails.values()), tokens["TEXT_RAMP_S"], exit_s


def pipeline_timing(spec: dict) -> tuple[float, float, float]:
    """Account for the actual last headline/node/foot ramp before readable dwell."""
    names = ("LAND_DEFAULT_START_S", "LAND_DEFAULT_GAP_S", "LINE_STAGGER_S", "NODE_STAGGER_S")
    tokens = _timing_tokens("module-pipeline.js", names)
    eyebrow, explainer, foot = (bool(str(spec.get(key) or "").strip())
                                for key in ("eyebrow", "explainer", "footChip"))
    heads, nodes = (str(spec.get(key) or "").strip().split("|") if spec.get(key) else []
                    for key in ("headlineLines", "nodes"))
    if any(not row.strip() for row in [*heads, *nodes]) or len(heads) > 2:
        raise ValueError("pipeline headline/node rows must be explicit and headline has at most two lines")
    if nodes and (not 2 <= len(nodes) <= 8 or any(len(row.split("~")) != 2 or
            any(not field.strip() for field in row.split("~")) for row in nodes)):
        raise ValueError("pipeline requires two to eight complete num~label nodes")
    present = {"head": eyebrow or bool(heads) or explainer, "chain": bool(nodes), "foot": foot}
    modules = [name for name, exists in present.items() if exists]
    if not modules:
        raise ValueError("pipeline has no explicit content; preview sample is not editorial content")
    lands = dict(zip(modules, _module_lands(spec.get("moduleLands"), len(modules), tokens, "pipeline"), strict=True))
    tails = dict(lands)
    if heads or explainer:
        tails["head"] += (tokens["EYEBROW_LEAD_S"] if eyebrow else 0)
        tails["head"] += max(0, len(heads) - 1) * tokens["LINE_STAGGER_S"]
        tails["head"] += tokens["LINE_STAGGER_S"] if explainer else 0
    if nodes:
        tails["chain"] += (len(nodes) - 1) * tokens["NODE_STAGGER_S"]
    exit_s = tokens["EXIT_BLUR_S"] if spec.get("exit") == "blur-recede" else 0.0
    return max(tails.values()), tokens["TEXT_RAMP_S"], exit_s


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _series(value: Any) -> list[float]:
    if isinstance(value, (list, tuple)):
        values = list(value)
    elif isinstance(value, str):
        values = [part.strip() for part in re.split(r"[|,]", value)]
    else:
        values = []
    result = []
    for item in values:
        try:
            parsed = float(item)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            result.append(parsed)
    return result


def _paired_at_values(spec: dict) -> list[float]:
    values = []
    for key, value in spec.items():
        match = re.fullmatch(r"at(\d+)", str(key))
        parsed = _number(value)
        if match is None or parsed is None:
            continue
        index = match.group(1)
        paired = next((spec.get(f"{prefix}{index}")
                       for prefix in ("icon", "item", "title", "line")
                       if f"{prefix}{index}" in spec), None)
        if paired is None or str(paired).strip():
            values.append(parsed)
    return values


def _latest_reveal(spec: dict) -> float:
    values = _paired_at_values(spec)
    if spec.get("moduleLands") not in (None, ""):
        values.extend(parse_module_lands(spec["moduleLands"]))
    for key in ("rowLands", "statementLands"):
        values.extend(_series(spec.get(key)))
    if str(spec.get("line2", "")).strip():
        value = _number(spec.get("at3", spec.get("at2")))
        if value is not None:
            values.append(value)
    if str(spec.get("payoff", "")).strip():
        value = _number(spec.get("payoffAt"))
        if value is not None:
            values.append(value)
    return max(values, default=0.0)


def _brand_errors(kind: str, spec: dict) -> list[str]:
    if kind != "icon-badge-wide":
        return []
    errors = []
    for key in ("icon1", "icon2", "icon3"):
        selected = str(spec.get(key, "") or "").strip()
        stem = os.path.splitext(os.path.basename(selected))[0]
        brand = stem.removesuffix("-color")
        required = _BRAND_COLOR_ASSETS.get(brand)
        if required and os.path.basename(selected) != required:
            errors.append(
                f"spec.{key} names {brand} but uses {selected!r}; named brand "
                f"identities require the distinct approved asset {required!r}")
    return errors


def _identity_errors(kind: str, spec: dict) -> list[str]:
    if kind != "avatar-bio-card" or any(str(spec.get(key) or "").strip() for key in ("avatarSrc", "initials")):
        return []
    return ["avatar-bio-card requires explicit spec.avatarSrc or spec.initials; "
            "an empty portrait circle is not a completed credibility graphic"]


def _copy_geometry_errors(kind: str, spec: dict) -> list[str]:
    """Keep credential copy inside the two-line arc-safe text region."""
    if kind != "avatar-bio-card":
        return []
    line2 = " ".join(str(spec.get("line2", "") or "").split())
    if len(line2) <= 64:
        return []
    return ["avatar-bio-card spec.line2 exceeds the 64-character two-line "
            "safe region; shorten the credential or use a text-led template"]


def visible_timing(kind: str, spec: dict) -> tuple[float, float, float, float, float] | None:
    """Shared actual reveal and minimum hold for lint, catalog and TEST authoring."""
    policy = _TIMING_POLICY.get(kind)
    if policy is None:
        return None
    floor, settle, dwell, exit_runway = policy
    reveal = _latest_reveal(spec)
    if kind == "module-scoreboard":
        reveal, settle, exit_runway = scoreboard_timing(spec)
    if kind == "module-pipeline":
        reveal, settle, exit_runway = pipeline_timing(spec)
    return max(floor, reveal + settle + dwell + exit_runway), reveal, settle, dwell, exit_runway


def _timing_errors(entry: dict, kind: str, spec: dict) -> list[str]:
    try:
        timing = visible_timing(kind, spec)
    except (OSError, ValueError) as error:
        return [f"visible-completion schedule cannot be verified: {error}"]
    if timing is None:
        return []
    try:
        hold = float(entry["outEnd"]) - float(entry["outStart"])
    except (KeyError, TypeError, ValueError):
        return []
    required, reveal, settle, dwell, exit_runway = timing
    if hold + 1e-6 >= required:
        return []
    return [
        f"visible hold {hold:.2f}s is shorter than the {required:.2f}s "
        f"completion floor for {kind} (last reveal {reveal:.2f}s + "
        f"{settle:.2f}s settle + {dwell:.2f}s readable dwell + "
        f"{exit_runway:.2f}s exit runway)"
    ]


def visual_entry_errors(entry: dict) -> list[str]:
    """Return deterministic identity and visible-timing defects."""
    kind = str(entry.get("kind", ""))
    spec = entry.get("spec")
    if not isinstance(spec, dict):
        return []
    return [*_brand_errors(kind, spec), *_identity_errors(kind, spec), *_copy_geometry_errors(kind, spec),
            *native_layout_errors(entry, spec), *_timing_errors(entry, kind, spec)]
