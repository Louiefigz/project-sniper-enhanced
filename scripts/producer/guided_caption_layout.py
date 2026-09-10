"""Conservative held caption/graphic layout screening, never QC approval.

The owner must strongly read the original caption projection and full frame
bindings before projecting this closed input. Native declarations are NOT DOM
observations. ``read_observation`` is a future owned sealed-render reader, not a
JSON loader: it must authenticate actual completion, exact receipt bytes, source
closure and rendered graphic bytes. No such observer is implemented by this file.
An externally supplied rectangle/self-hash cannot replace that owner boundary.
"""
from __future__ import annotations

from collections.abc import Callable
from fractions import Fraction
from pathlib import PurePosixPath

from cut_preview_io import digest

POLICY = "native-caption-layout-screen-v1"
SCOPE = "held-envelope-screen-not-pixel-legibility-or-creative-approval"
_BINDING = {"graphicId", "entryHash", "specHash", "template", "sources",
            "executionInputHash", "graphicRequestHash", "graphicMediaSha256",
            "frameRate", "totalFrames", "width", "height"}
_MAX_PAIRS = 32768
Guard = Callable[[], None]
ObservationReader = Callable[[dict, dict], tuple[dict, dict] | None]


def _closed(value: object, keys: set[str], label: str) -> dict:
    """Reject unknown/missing structural fields, without normalizing evidence."""
    if type(value) is not dict or set(value) != keys:
        raise ValueError(f"{label}: unknown or missing fields")
    return value


def _integer(value: object, lower: int, upper: int) -> int:
    """Require exact bounded integer geometry and frame values."""
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError("layout integer is malformed or out of bounds")
    return value


def _name(value: object) -> str:
    """Bound role/graphic/cue identifiers without changing their spelling."""
    if type(value) is not str or not value.strip() or len(value) > 200 \
            or any(ord(char) < 32 for char in value):
        raise ValueError("layout identity is malformed")
    return value


def _sha(value: object) -> str:
    """Require lowercase raw-file/domain SHA text; a hash is not authority."""
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("layout hash is malformed")
    return value


def _reference(value: object) -> dict:
    """Validate an externally held file reference, without reading that file."""
    row = _closed(value, {"path", "sha256"}, "layout reference")
    name = row["path"]
    if type(name) is not str or len(name) > 4096 or "\\" in name \
            or any(ord(char) < 32 for char in name) \
            or PurePosixPath(name).anchor != "/" or not PurePosixPath(name).name \
            or str(PurePosixPath(name)) != name:
        raise ValueError("layout reference is not a canonical absolute path")
    if ".." in PurePosixPath(name).parts:
        raise ValueError("layout reference escapes its exact path")
    _sha(row["sha256"])
    return row


def _clock(value: object) -> dict:
    """Keep exact native canvas and canonical rational rate; never resize."""
    row = _closed(value, {"frameRate", "totalFrames", "width", "height"}, "layout clock")
    rate = row["frameRate"]
    parsed = Fraction(rate) if type(rate) is str else Fraction(0)
    if not 0 < parsed <= 60 or rate != f"{parsed.numerator}/{parsed.denominator}":
        raise ValueError("layout frame rate is not canonical")
    _integer(row["totalFrames"], 1, 432000)
    if (row["width"], row["height"]) not in ((1920, 1080), (1080, 1920)):
        raise ValueError("layout native geometry is unsupported")
    _integer(row["width"], 1, 1920)
    _integer(row["height"], 1, 1920)
    return row


def _span(row: dict, total: int) -> tuple[int, int]:
    """Frames are full-program half-open endpoints, never page-local times."""
    start = _integer(row["startFrame"], 0, total - 1)
    return start, _integer(row["endFrameExclusive"], start + 1, total)


def _rectangle(value: object, clock: dict) -> tuple[int, int, int, int]:
    """Pixel rectangles are half-open and entirely in-frame; no clipping."""
    if type(value) is not list or len(value) != 4:
        raise ValueError("layout rectangle requires four integer endpoints")
    x0, y0, x1, y1 = value
    _integer(x0, 0, clock["width"] - 1)
    _integer(y0, 0, clock["height"] - 1)
    _integer(x1, x0 + 1, clock["width"])
    _integer(y1, y0 + 1, clock["height"])
    return x0, y0, x1, y1


def _binding(value: object, clock: dict) -> dict:
    """Compare declarations/observations to separately held rendered identities."""
    row = _closed(value, _BINDING, "layout binding")
    _name(row["graphicId"])
    for key in ("entryHash", "specHash", "executionInputHash", "graphicRequestHash", "graphicMediaSha256"):
        _sha(row[key])
    _reference(row["template"])
    sources = row["sources"]
    if type(sources) is not list or not 1 <= len(sources) <= 4096:
        raise ValueError("layout source closure is missing/unbounded")
    paths = [_reference(item)["path"] for item in sources]
    if len(set(paths)) != len(paths) or row["template"] not in sources:
        raise ValueError("layout source closure duplicates or omits template")
    if any(type(row[key]) is not type(item) or row[key] != item for key, item in clock.items()):
        raise ValueError("layout binding clock differs")
    return row


def _cue(value: object, clock: dict) -> dict:
    """Project the real shard's inclusive alpha maxima to a half-open box."""
    row = _closed(value, {"cueId", "startFrame", "endFrameExclusive", "media", "shapedSafeBounds"}, "held cue")
    _name(row["cueId"])
    start, end = _span(row, clock["totalFrames"])
    _reference(row["media"])
    bounds = _closed(row["shapedSafeBounds"], {"minX", "minY", "maxX", "maxY", "framesMeasured"}, "shard bounds")
    for item in bounds.values():
        _integer(item, 0, 432000)
    if bounds["framesMeasured"] != end - start:
        raise ValueError("caption shard lacks whole-cue frame coverage")
    box = _rectangle([bounds["minX"], bounds["minY"], bounds["maxX"] + 1, bounds["maxY"] + 1], clock)
    return {**row, "box": box}


def _graphic(value: object, clock: dict) -> dict:
    """Use original occurrence endpoints and exact full-canvas presentation."""
    row = _closed(value, {"graphicId", "order", "startFrame", "endFrameExclusive", "entryHash", "binding"}, "held graphic")
    _name(row["graphicId"])
    _integer(row["order"], 0, 127)
    _span(row, clock["totalFrames"])
    binding = _binding(row["binding"], clock)
    if binding["graphicId"] != row["graphicId"] or binding["entryHash"] != row["entryHash"]:
        raise ValueError("graphic occurrence and rendered binding differ")
    return row


def _declaration(value: object, graphic: dict, clock: dict) -> dict:
    """A source-bound native declaration cannot make unobserved layout pass."""
    row = _closed(value, {"schemaVersion", "kind", "binding", "captionClearRect", "gutterPx", "protectedRoles"}, "native declaration")
    _binding(row["binding"], clock)
    if type(row["schemaVersion"]) is not int or row["schemaVersion"] != 1 \
            or row["kind"] != "native-caption-layout-declaration" or row["binding"] != graphic["binding"]:
        raise ValueError("native declaration version/binding differs")
    _rectangle(row["captionClearRect"], clock)
    _integer(row["gutterPx"], 0, 128)
    roles = row["protectedRoles"]
    if type(roles) is not list or not 1 <= len(roles) <= 64 \
            or len({_name(item) for item in roles}) != len(roles):
        raise ValueError("native declaration role coverage is malformed")
    return row


def _observation(value: tuple[dict, dict], context: tuple) -> tuple[dict, list[dict]]:
    """Check facts returned by the future strong owner reader, never self-seal."""
    graphic, declaration, clock = context
    if type(value) is not tuple or len(value) != 2:
        raise ValueError("owned geometry reader returned no held receipt")
    reference, raw = value
    _reference(reference)
    row = _closed(raw, {"schemaVersion", "kind", "binding", "declarationHash", "startFrame", "endFrameExclusive", "framesObserved", "roles"}, "owned geometry")
    _binding(row["binding"], clock)
    start, end = _span(row, clock["totalFrames"])
    if type(row["schemaVersion"]) is not int or row["schemaVersion"] != 1 \
            or row["kind"] != "native-caption-layout-observation" or row["binding"] != graphic["binding"] \
            or row["declarationHash"] != digest(declaration) \
            or (start, end) != _span(graphic, clock["totalFrames"]):
        raise ValueError("owned geometry has stale identity or animation range")
    if _integer(row["framesObserved"], 1, 432000) != end - start:
        raise ValueError("owned geometry does not cover every animation frame")
    roles = row["roles"]
    if type(roles) is not list or len(roles) != len(declaration["protectedRoles"]):
        raise ValueError("owned geometry omitted protected roles")
    for item in roles:
        _closed(item, {"id", "bounds", "overflow"}, "observed role")
        _rectangle(item["bounds"], clock)
        if item["overflow"] is not False:
            raise ValueError("observed role is overflowing or unmeasured")
    if [item["id"] for item in roles] != declaration["protectedRoles"]:
        raise ValueError("owned geometry role order/coverage differs")
    return reference, roles


def _overlap(left: tuple | list, right: tuple | list, gutter: int = 0) -> bool:
    """Conservative envelope proximity; touching boxes do not overlap at zero gutter."""
    return left[0] < right[2] + gutter and right[0] < left[2] + gutter \
        and left[1] < right[3] + gutter and right[1] < left[3] + gutter


def _screen(cue: dict, declaration: dict, roles: list[dict]) -> list[str]:
    """Report conservative conflicts, not proven glyph-on-glyph pixel defects."""
    box, clear = cue["box"], declaration["captionClearRect"]
    errors = [] if clear[0] <= box[0] and clear[1] <= box[1] \
        and box[2] <= clear[2] and box[3] <= clear[3] else ["caption-outside-declared-clear-region"]
    errors.extend(item["id"] for item in roles if _overlap(box, item["bounds"], declaration["gutterPx"]))
    return errors


def _one(graphic: dict, cues: list[dict], context: tuple) -> dict:
    """Uncovered/unmeasured simultaneous intervals cannot be screening successes."""
    declarations, clock, reader, guard = context
    pairs = [cue for cue in cues if cue["startFrame"] < graphic["endFrameExclusive"]
             and graphic["startFrame"] < cue["endFrameExclusive"]]
    base = {"graphicId": graphic["graphicId"], "intersections": [
        {"cueId": cue["cueId"], "startFrame": max(cue["startFrame"], graphic["startFrame"]),
         "endFrameExclusive": min(cue["endFrameExclusive"], graphic["endFrameExclusive"])} for cue in pairs]}
    if not pairs:
        return {**base, "state": "not-applicable", "reason": "no-simultaneous-caption"}
    try:
        guard()
        declaration = _declaration(declarations[graphic["graphicId"]], graphic, clock)
        observed = reader(graphic["binding"], declaration)
        if observed is None:
            return {**base, "state": "unqualified", "reason": "no-owned-geometry-observation"}
        observed_hash = digest(list(observed))
        reference, roles = _observation(observed, (graphic, declaration, clock))
        rows = [{"cueId": cue["cueId"], "startFrame": max(cue["startFrame"], graphic["startFrame"]),
                 "endFrameExclusive": min(cue["endFrameExclusive"], graphic["endFrameExclusive"]),
                 "conflicts": _screen(cue, declaration, roles)} for cue in pairs]
        guard()
        final = reader(graphic["binding"], declaration)
        if type(final) is not tuple or digest(list(final)) != observed_hash:
            raise ValueError("owned geometry changed at final strong read")
        return {**base, "intersections": rows, "observation": reference,
                "state": "envelope-conflict" if any(row["conflicts"] for row in rows) else "screened-no-overlap"}
    except (KeyError, ValueError, TypeError, OSError) as error:
        return {**base, "state": "unqualified", "reason": str(error)[:1000]}


def inspect_layout(value: dict, read_observation: ObservationReader, guard: Guard) -> dict:
    """Screen a closed owner-held projection, preserving clock/bytes and all rows.

    Malformed inputs raise. Missing/unmeasured native layout returns unqualified.
    Reader/runtime/guard errors never become success. No disk/media access,
    mutation, approval, historical upgrade, or default readiness hook occurs.
    """
    guard()
    before = digest(value)
    _closed(value, {"schemaVersion", "kind", "clock", "captionProjectionHash", "cues", "graphics", "declarations"}, "layout input")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 or value["kind"] != "held-caption-layout-input":
        raise ValueError("layout input version differs")
    if value["captionProjectionHash"] is not None or value["cues"]:
        _sha(value["captionProjectionHash"])
    clock = _clock(value["clock"])
    if any(type(value[key]) is not list for key in ("cues", "graphics", "declarations")) \
            or len(value["cues"]) > 4096 or len(value["graphics"]) > 128 \
            or len(value["declarations"]) > 128 or len(value["cues"]) * len(value["graphics"]) > _MAX_PAIRS:
        raise ValueError("layout input exceeds bounded list/workload policy")
    cues = [_cue(row, clock) for row in value["cues"]]
    graphics = [_graphic(row, clock) for row in value["graphics"]]
    if len({row["cueId"] for row in cues}) != len(cues) or len({row["graphicId"] for row in graphics}) != len(graphics) \
            or [row["order"] for row in graphics] != list(range(len(graphics))):
        raise ValueError("layout input loses unique original occurrence ordering")
    declarations = {row["binding"]["graphicId"]: row for row in value["declarations"]}
    if len(declarations) != len(value["declarations"]) or set(declarations) - {row["graphicId"] for row in graphics}:
        raise ValueError("layout declarations duplicate or transplant graphic identities")
    rows = [_one(row, cues, (declarations, clock, read_observation, guard)) for row in graphics]
    guard()
    if digest(value) != before:
        raise ValueError("held layout input changed while reading observations")
    states = {row["state"] for row in rows}
    state = next((item for item in ("unqualified", "envelope-conflict", "screened-no-overlap") if item in states), "not-applicable")
    return {"schemaVersion": 1, "policy": POLICY, "scope": SCOPE, "state": state, "graphics": rows,
            "qcPassed": False, "creativeApproved": False, "deliveryApproved": False}
