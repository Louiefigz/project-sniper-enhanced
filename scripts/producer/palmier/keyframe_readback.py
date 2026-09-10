"""Fail-closed compatibility for Palmier keyframe readback.

Palmier emits numeric values at three decimal places and may omit the expected
trailing easing string. A half-step (0.0005) is therefore the only tolerated
numeric drift; every container, property, row, frame, and value column remains
structurally exact.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from palmier.mcp_client import PalmierError


QUANTIZATION_DECIMAL_PLACES = 3
QUANTIZATION_MAX_ABS_DIFFERENCE = Decimal("0.0005")


@dataclass(frozen=True)
class KeyframeReadbackEvidence:
    """Observed compatibility facts for one keyframe property."""

    easing_omitted: bool
    max_abs_difference: Decimal

    def as_dict(self) -> dict:
        """Return JSON-safe evidence without hiding the compatibility bound."""
        difference = float(self.max_abs_difference)
        return {
            "easing": "not_exposed" if self.easing_omitted else "verified",
            "numericQuantization": {
                "decimalPlaces": QUANTIZATION_DECIMAL_PLACES,
                "allowedMaxAbsDifference": float(
                    QUANTIZATION_MAX_ABS_DIFFERENCE),
                "observedMaxAbsDifference": difference,
                "status": "within_bound" if difference else "exact",
            },
        }


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PalmierError(f"{label} is not numeric")
    number = Decimal(str(value))
    if not number.is_finite():
        raise PalmierError(f"{label} is not finite")
    return number


def _row_parts(row: object, label: str) -> tuple[Decimal, list[Decimal], str | None]:
    if not isinstance(row, list) or len(row) < 2:
        raise PalmierError(f"{label} is not a keyframe row")
    frame = _decimal(row[0], f"{label} frame")
    if frame != frame.to_integral_value():
        raise PalmierError(f"{label} frame is not an integer")
    payload = list(row[1:])
    easing = payload.pop() if payload and isinstance(payload[-1], str) else None
    if not payload:
        raise PalmierError(f"{label} has no numeric value columns")
    values = [_decimal(value, f"{label} value {index}")
              for index, value in enumerate(payload)]
    return frame, values, easing


def _easing_state(found: str | None, expected: str | None,
                  label: str) -> bool:
    if expected is None:
        if found is not None:
            raise PalmierError(f"{label} has unexpected easing {found!r}")
        return False
    if found is None:
        return True
    if found != expected:
        raise PalmierError(
            f"{label} easing {found!r} does not match {expected!r}")
    return False


def _value_difference(found: list[Decimal], expected: list[Decimal],
                      label: str) -> Decimal:
    if len(found) != len(expected):
        raise PalmierError(f"{label} numeric value column count differs")
    maximum = Decimal(0)
    for index, (actual, wanted) in enumerate(zip(found, expected, strict=True)):
        difference = abs(actual - wanted)
        if difference > QUANTIZATION_MAX_ABS_DIFFERENCE:
            raise PalmierError(
                f"{label} value {index} exceeds Palmier's 3-decimal "
                "quantization bound")
        maximum = max(maximum, difference)
    return maximum


def compare_keyframe_rows(found: object,
                          expected: object) -> KeyframeReadbackEvidence:
    """Prove exact row/frame shape with Palmier's bounded value quantization."""
    if not isinstance(found, list) or not isinstance(expected, list):
        raise PalmierError("keyframe rows are not arrays")
    if len(found) != len(expected):
        raise PalmierError("keyframe row count differs")
    omitted_states: set[bool] = set()
    maximum = Decimal(0)
    for index, (actual, wanted) in enumerate(zip(found, expected, strict=True)):
        actual_frame, actual_values, actual_easing = _row_parts(
            actual, f"readback row {index}")
        wanted_frame, wanted_values, wanted_easing = _row_parts(
            wanted, f"expected row {index}")
        if actual_frame != wanted_frame:
            raise PalmierError(f"keyframe frame differs at row {index}")
        omitted_states.add(_easing_state(
            actual_easing, wanted_easing, f"keyframe row {index}"))
        maximum = max(maximum, _value_difference(
            actual_values, wanted_values, f"keyframe row {index}"))
    if len(omitted_states) > 1:
        raise PalmierError("keyframe rows have inconsistent easing exposure")
    return KeyframeReadbackEvidence(True in omitted_states, maximum)


def _dict_keyframe_map(raw: dict) -> dict[str, list]:
    result = {}
    for prop, value in raw.items():
        rows = (value.get("rows", value.get("keyframes"))
                if isinstance(value, dict) else value)
        if not isinstance(rows, list):
            raise PalmierError(
                "timeline verification: malformed keyframe rows")
        result[str(prop)] = rows
    return result


def _list_keyframe_map(raw: list) -> dict[str, list]:
    result = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise PalmierError(
                "timeline verification: malformed keyframe entry")
        prop = entry.get("property") or entry.get("name")
        rows = entry.get("rows", entry.get("keyframes"))
        if not isinstance(prop, str) or not isinstance(rows, list):
            raise PalmierError(
                "timeline verification: malformed keyframe entry")
        if prop in result:
            raise PalmierError(
                f"timeline verification: duplicate keyframe property {prop}")
        result[prop] = rows
    return result


def keyframe_map(clip: dict) -> dict[str, list] | None:
    """Normalize Palmier's two documented keyframe container shapes."""
    if "keyframes" not in clip:
        return None
    raw = clip["keyframes"]
    if isinstance(raw, dict):
        return _dict_keyframe_map(raw)
    if isinstance(raw, list):
        return _list_keyframe_map(raw)
    raise PalmierError(
        "timeline verification: keyframes has unknown shape")


def _expected_keyframes(lanes: dict, executor: Any) -> dict[str, dict]:
    expected: dict[str, dict[str, list]] = {}
    for step in lanes.get("keyframes") or []:
        clip_id = executor.cut_clip_ids[step["clip"]]
        expected.setdefault(clip_id, {})[step["property"]] = step["rows"]
    return expected


def _verify_property_sets(found: dict, expected: dict, clip_id: str) -> None:
    if set(found) == set(expected):
        return
    missing = sorted(set(expected) - set(found))
    if len(missing) == 1 and not set(found) - set(expected):
        raise PalmierError(
            f"timeline verification: {missing[0]} keyframes differ on "
            f"{clip_id}: property missing")
    raise PalmierError(
        f"timeline verification: keyframe properties differ on {clip_id}")


def _compare_properties(found: dict, expected: dict,
                        clip_id: str) -> list[KeyframeReadbackEvidence]:
    _verify_property_sets(found, expected, clip_id)
    comparisons = []
    for prop, rows in expected.items():
        try:
            comparisons.append(compare_keyframe_rows(found[prop], rows))
        except PalmierError as exc:
            raise PalmierError(
                f"timeline verification: {prop} keyframes differ on "
                f"{clip_id}: {exc}") from exc
    return comparisons


def verify_keyframes(lanes: dict, executor: Any,
                     actual: dict[str, dict]) -> dict:
    """Verify all expected clips/properties and return compatibility evidence."""
    expected = _expected_keyframes(lanes, executor)
    if not expected:
        return {"status": "not_applicable", "expectedProperties": 0}
    exposed = {clip_id: found for clip_id, clip in actual.items()
               if (found := keyframe_map(clip))}
    if not exposed:
        count = sum(len(properties) for properties in expected.values())
        raise PalmierError(
            f"timeline verification: {count} required keyframe properties "
            "were not exposed by Palmier readback")
    if set(exposed) != set(expected):
        raise PalmierError(
            "timeline verification: keyframe clip identities differ")
    comparisons = []
    for clip_id, properties in expected.items():
        comparisons.extend(_compare_properties(
            exposed[clip_id], properties, clip_id))
    maximum = max(row.max_abs_difference for row in comparisons)
    easing_omitted = any(row.easing_omitted for row in comparisons)
    evidence = KeyframeReadbackEvidence(easing_omitted, maximum).as_dict()
    return {"status": ("verified-values"
                       if easing_omitted or maximum else "verified"),
            **evidence,
            "properties": sum(len(properties) for properties in expected.values())}
