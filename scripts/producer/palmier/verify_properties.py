"""Expected and observed native clip-property checks for Palmier sync."""
from __future__ import annotations

from math import isclose

from palmier.mcp_client import PalmierError

_TRANSFORM_DEFAULTS = {
    "width": 1.0,
    "height": 1.0,
    "centerX": 0.5,
    "centerY": 0.5,
    "flipHorizontal": False,
    "flipVertical": False,
}

# Palmier converts source-second trims onto its integer project timebase when
# add_clips lands.  That conversion may expose the adjacent frame at a
# fractional boundary (observed with a 23.976 source conformed to 24 fps), even
# though the placed clip duration and timeline seam remain correct. Keep this
# tolerance local to source trims; speed, media identity, transforms, output
# placement, and total duration still verify exactly elsewhere.
_TRIM_FRAME_TOLERANCE = 1.0


def cut_properties(entry: dict, media_seconds: float, fps: float,
                   transform: dict | None) -> dict:
    """Native properties one translated source cut must expose on readback."""
    source_start, source_end = map(float, entry["source"])
    return {
        "mediaRef": entry["mediaKey"],
        "speed": float(entry["speed"]),
        "trimStartFrame": round(source_start * fps),
        "trimEndFrame": round(max(0.0, media_seconds - source_end) * fps),
        "transform": transform,
    }


def verify_properties(actual: dict, expected: dict, label: str) -> None:
    """Fail when a native property is missing, changed, or flattened."""
    if actual.get("mediaRef") != expected.get("mediaRef"):
        raise PalmierError(f"timeline verification: {label} references wrong media")
    _verify_number(actual, expected, "speed", 1.0, label)
    _verify_number(actual, expected, "trimStartFrame", 0, label)
    _verify_number(actual, expected, "trimEndFrame", 0, label)
    _verify_transform(actual.get("transform"), expected.get("transform"), label)


def verify_text(actual: dict, expected: str, label: str) -> None:
    """Require Palmier to expose the exact native text content."""
    content = actual.get("textContent", actual.get("content"))
    if content != expected:
        raise PalmierError(f"timeline verification: {label} has wrong text content")


def _verify_number(actual: dict, expected: dict, key: str,
                   default: float, label: str) -> None:
    wanted = expected.get(key, default)
    found = actual.get(key, default)
    if isinstance(found, bool) or not isinstance(found, (int, float)):
        raise PalmierError(f"timeline verification: {label} {key} is not numeric")
    tolerance = _TRIM_FRAME_TOLERANCE if key in (
        "trimStartFrame", "trimEndFrame") else 1e-6
    if not isclose(float(found), float(wanted), abs_tol=tolerance):
        raise PalmierError(
            f"timeline verification: {label} {key} {found}, expected {wanted}")


def _verify_transform(actual: object, expected: object, label: str) -> None:
    if expected is None:
        return
    if actual is None:
        actual = {}
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        raise PalmierError(f"timeline verification: {label} transform is malformed")
    for key, wanted in expected.items():
        found = actual.get(key, _TRANSFORM_DEFAULTS.get(key))
        if isinstance(wanted, (int, float)) and isinstance(found, (int, float)):
            matches = isclose(float(found), float(wanted), abs_tol=1e-4)
        else:
            matches = found == wanted
        if not matches:
            raise PalmierError(
                f"timeline verification: {label} transform.{key} "
                f"{found}, expected {wanted}")
