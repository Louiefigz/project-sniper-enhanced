"""Pure edit-plan fidelity report for the current Palmier translator.

The report describes what a user can still edit *inside Palmier*. It does not
call Palmier, render media, read files, or decide whether a saved export is
current. ``fullyEditable`` remains the honest native-capability verdict. Visual
mirror eligibility is separate: baked/approximate/unsupported edit vocabulary
may mirror through the approved flattened master, while malformed or unknown
plan structure fails closed through ``mirrorReady``/``mirrorBlockers``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Literal

Parity = Literal["exact", "approximate", "baked", "unsupported"]
STATUSES: tuple[Parity, ...] = ("exact", "approximate", "baked", "unsupported")
_PALMIER_COLOR_KEYS = {
    "reset",
    "exposure", "contrast", "highlights", "shadows", "whites", "blacks",
    "temperature", "tint", "saturation", "vibrance",
}

_HANDLED = {
    "cutTrack", "baselineLook", "graphicsTrack", "punchIns", "reframe",
    "titleCards", "captions", "transitions", "brollTrack", "music",
    "audioEnhance", "audioGain", "chapters",
}
# Non-visual metadata / rationale sidecars — they carry NO pixels or audio into
# the mirror (cutDecisions justify the cut spine; graphicsDecisions and
# transitionRationale explain the visual choices). They must NOT be treated as
# unknown lanes that block the visual mirror — the master already bakes every
# visual choice; these are provenance only.
_METADATA = {"target", "planVersion", "faceBBoxNorm", "treatmentMap",
             "cutDecisions", "graphicsDecisions", "transitionRationale"}
@dataclass(frozen=True)
class Finding:
    """One stable, JSON-safe parity verdict for a present plan element."""

    id: str
    lane: str
    status: Parity
    label: str
    message: str
    count: int = 1
    blocksSync: bool = False
def _present(value: object) -> bool:
    """Whether a field declares content instead of a semantic absence."""
    return value is not None and value is not False and value not in ({}, [], "")
def _number(value: object, *, positive: bool = False) -> bool:
    """Validate a finite number while rejecting bools."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return isfinite(float(value)) and (not positive or float(value) > 0)
def _item_id(lane: str, index: int, item: object) -> str:
    """Prefer a persisted plan id, with deterministic index fallback."""
    if isinstance(item, dict):
        value = item.get("id")
        if isinstance(value, str) and value.strip():
            return f"{lane}:{value.strip()}"
    return f"{lane}:{index}"
def _malformed(lane: str, ident: str, label: str, message: str) -> Finding:
    return Finding(ident, lane, "unsupported", label, message, blocksSync=True)
def _timed(item: dict) -> bool:
    """Validate one positive output-time window."""
    start, end = item.get("outStart"), item.get("outEnd")
    return _number(start) and _number(end) and float(end) > float(start)
def _cuts(value: object) -> list[Finding]:
    if not isinstance(value, list) or not value:
        return [_malformed("cuts", "cuts:malformed", "Source cuts",
                           "cutTrack is present but is not a non-empty list.")]
    valid = [isinstance(row, dict) and isinstance(row.get("sourceId"), str)
             and _number(row.get("start")) and _number(row.get("end"))
             and float(row["end"]) > float(row["start"])
             and _number(row.get("speed", 1), positive=True) for row in value]
    sources = {row["sourceId"] for row, ok in zip(value, valid) if ok}
    lane_ok = all(valid) and len(sources) == 1
    findings = []
    for index, row in enumerate(value):
        ident = _item_id("cuts", index, row)
        if lane_ok:
            findings.append(Finding(ident, "cuts", "exact", f"Source cut {index + 1}",
                                    "Native Palmier clip with source trim, position, and speed."))
        elif all(valid):
            findings.append(Finding(
                ident, "cuts", "unsupported", f"Source cut {index + 1}",
                "Multi-source native reconstruction is unavailable; the approved "
                "visual master still mirrors as one clip."))
        else:
            findings.append(_malformed(
                "cuts", ident, f"Source cut {index + 1}",
                "The cut or another cut in this lane is malformed."))
    return findings
def _baseline(value: object) -> list[Finding]:
    if not isinstance(value, dict):
        return [_malformed("motion", "baseline:malformed", "Baseline look",
                           "baselineLook must be an object.")]
    findings: list[Finding] = []
    transform_keys = ("zoom", "centerX", "centerY")
    if any(key in value for key in transform_keys):
        ok = _number(value.get("zoom", 1), positive=True)
        ok = ok and all(_number(value[key]) for key in ("centerX", "centerY") if key in value)
        findings.append(Finding(
            "baseline:transform", "motion", "exact" if ok else "unsupported",
            "Baseline zoom and position",
            "Native Palmier clip transform." if ok else "Baseline transform values are malformed.",
            blocksSync=not ok))
    grade = value.get("grade")
    if grade not in (None, "", "none"):
        findings.append(Finding(
            "baseline:grade", "color", "unsupported", "Baseline color grade",
            "Non-none grades are not translated; Palmier receives no equivalent color effect."))
    native_color = value.get("palmierColor")
    if native_color is not None:
        reset = native_color.get("reset") if isinstance(native_color, dict) else None
        knobs = {key: item for key, item in native_color.items() if key != "reset"} \
            if isinstance(native_color, dict) else {}
        valid = isinstance(native_color, dict) and bool(native_color) \
            and set(native_color).issubset(_PALMIER_COLOR_KEYS) \
            and reset in (None, True, False) \
            and all(_number(item) for item in knobs.values())
        findings.append(Finding(
            "baseline:palmier-color", "color", "exact" if valid else "unsupported",
            "Native Palmier color",
            "Native editable Palmier color controls."
            if valid else "palmierColor settings are empty, unknown, or malformed.",
            blocksSync=not valid))
    recognized = {"grade", "zoom", "centerX", "centerY", "palmierColor"}
    if not findings and value and value != {"grade": "none"} \
            and set(value) - recognized:
        findings.append(_malformed("motion", "baseline:unknown", "Baseline look",
                                   "baselineLook contains no recognized transform or grade."))
    return findings
def _graphics(value: object) -> list[Finding]:
    if not isinstance(value, list):
        return [_malformed("graphics", "graphics:malformed", "Graphics",
                           "graphicsTrack must be a list.")]
    findings = []
    for index, row in enumerate(value):
        ident = _item_id("graphics", index, row)
        if not isinstance(row, dict) or not isinstance(row.get("kind"), str) or not _timed(row):
            findings.append(_malformed("graphics", ident, f"Graphic {index + 1}",
                                       "Graphic kind or output-time window is malformed."))
            continue
        limits = ["copy, shapes, and internal animation are flattened"]
        if row.get("placement") is not None:
            limits.append("manual placement/scale is not translated")
        if row.get("takeoverBase") or row.get("anchor") == "focus-shift" or row.get("pipHole"):
            limits.append("base/PIP treatment is not translated")
        findings.append(Finding(ident, "graphics", "baked", row["kind"],
                                "Separate overlay clip; " + "; ".join(limits) + "."))
    return findings
def _punches(value: object) -> list[Finding]:
    if not isinstance(value, list):
        return [_malformed("motion", "punches:malformed", "Punch-ins",
                           "punchIns must be a list.")]
    findings = []
    for index, row in enumerate(value):
        ident = _item_id("punch", index, row)
        if not isinstance(row, dict) or not _timed(row):
            findings.append(_malformed("motion", ident, f"Punch-in {index + 1}",
                                       "Punch-in window is malformed."))
            continue
        kind = str(row.get("kind", "")).lower()
        bracket = bool(row.get("bracket")) or kind == "bracket"
        ramp = "ramp" in row or kind in {"ramp", "aliveness"}
        legacy = any(key in row for key in ("ratePctPerS", "direction"))
        if bracket or legacy or (ramp and row.get("ease", "linear") != "smooth"):
            findings.append(Finding(ident, "motion", "unsupported", f"Motion {index + 1}",
                                    "Bracket or non-smooth motion has no faithful Palmier translation."))
        elif ramp:
            findings.append(Finding(
                ident, "motion", "approximate", f"Motion {index + 1}",
                "Native scale/position keyframes preserve smooth ramp endpoints."))
        elif _number(row.get("zoom"), positive=True):
            status = "approximate" if _number(row.get("attackS"), positive=True) \
                else "unsupported"
            message = ("Native sampled scale/position keyframes preserve the "
                       "renderer-derived push trajectory."
                       if status == "approximate" else
                       "Static hold semantics are not proven by Palmier readback.")
            findings.append(Finding(
                ident, "motion", status, f"Punch-in {index + 1}", message))
        else:
            findings.append(_malformed("motion", ident, f"Punch-in {index + 1}",
                                       "Unknown punch kind or missing positive zoom."))
    return findings
def _reframe(value: object, blocks: bool = False) -> list[Finding]:
    if isinstance(value, dict):
        active = {key: item for key, item in value.items()
                  if item not in (None, False, "", "none")}
        if not active:
            return []
    message = "Crop, face tracking, and split layouts are not translated to Palmier."
    if blocks:
        # Shortform reframe is load-bearing: it keeps the subject centred when
        # 16:9 footage is recomposed to 9:16. Losing it on a native push ships an
        # off-centre subject, so a short must NOT native-push without it.
        message += (" A 9:16 short cannot native-push without face centring "
                    "— deliver it via the rendered mirror.")
    return [Finding("reframe", "reframe", "unsupported", "Reframe layout",
                    message, blocksSync=blocks)]
def _timed_lane(value: object, lane: str, label: str, message: str,
                status: Parity = "unsupported", blocks: bool = False) -> list[Finding]:
    if not isinstance(value, list):
        return [_malformed(lane, f"{lane}:malformed", label, f"{lane} must be a list.")]
    findings = []
    for index, row in enumerate(value):
        ident = _item_id(lane, index, row)
        if not isinstance(row, dict) or not _timed(row):
            findings.append(_malformed(lane, ident, f"{label} {index + 1}",
                                       f"{label} window is malformed."))
        else:
            findings.append(Finding(ident, lane, status, f"{label} {index + 1}",
                                    message, blocksSync=blocks))
    return findings
def _titles(value: object) -> list[Finding]:
    if not isinstance(value, list):
        return [_malformed("titleCards", "titleCards:malformed", "Title cards",
                           "titleCards must be a list.")]
    findings = []
    for index, row in enumerate(value):
        ident = _item_id("titleCards", index, row)
        if not isinstance(row, dict) or not _timed(row) \
                or not isinstance(row.get("text"), str):
            findings.append(_malformed("titleCards", ident, f"Title card {index + 1}",
                                       "Title card text or output-time window is malformed."))
        else:
            findings.append(Finding(
                ident, "titleCards", "approximate", f"Title card {index + 1}",
                "Native text timing, but styling and animation are approximated."))
    return findings
def _transitions(value: object) -> list[Finding]:
    if not isinstance(value, list):
        return [_malformed("transitions", "transitions:malformed", "Transitions",
                           "transitions must be a list.")]
    findings = []
    for index, row in enumerate(value):
        ident = _item_id("transition", index, row)
        if not isinstance(row, dict) or not _number(row.get("outTime")) \
                or not isinstance(row.get("kind"), str):
            findings.append(_malformed("transitions", ident, f"Transition {index + 1}",
                                       "Transition time or kind is malformed."))
            continue
        kind = row["kind"]
        if kind == "white-flash":
            findings.append(Finding(
                ident, "transitions", "baked", kind,
                "Verified three-frame alpha overlay; visual-equivalent but not "
                "a native editable Palmier transition."))
        elif kind == "light-leak":
            findings.append(Finding(
                ident, "transitions", "approximate", kind,
                "Verified alpha-overlay preview; the final luma-screen/chroma "
                "blend remains render-only."))
        else:
            findings.append(Finding(
                ident, "transitions", "unsupported", kind,
                "No verified Palmier transition mapping; zoom-pull also needs "
                "blur-safe cross-cut keyframe merging."))
        if _present(row.get("sfx")):
            findings.append(Finding(f"sfx:{ident}", "sfx", "unsupported",
                                    f"Transition SFX {index + 1}",
                                    "SFX is not placed as a separate Palmier audio clip."))
    return findings
def _single(value: object, ident: str, lane: str, label: str,
            message: str) -> list[Finding]:
    return [Finding(ident, lane, "unsupported", label, message)] if _present(value) else []
def _optional_lanes(plan: dict) -> list[Finding]:
    findings: list[Finding] = []
    music = plan.get("music")
    if "music" in plan and music is not None and not isinstance(music, dict):
        if music is not False:
            findings.append(_malformed("music", "music:malformed", "Music",
                                       "music must be an object."))
    elif isinstance(music, dict) and music.get("enabled"):
        findings += _single(music, "music", "music", "Music bed",
                            "No Palmier music lane; the verified delivery audio bakes the bed.")
    findings += _single(
        plan.get("audioEnhance"), "audio:enhance", "audio", "Dialogue enhancement",
        "Not an editable Palmier effect; baked into delivery audio.")
    if "audioGain" in plan and plan["audioGain"] not in (None, []):
        findings += _timed_lane(plan["audioGain"], "audioGain", "Gain window",
                                "Not editable in Palmier; baked into delivery audio.")
    if _present(plan.get("chapters")):
        findings += _single(plan["chapters"], "chapters", "chapters", "Chapters",
                            "Chapter markers are not created in Palmier.")
    return findings
def _summary(findings: list[Finding]) -> dict:
    by_status = {}
    for status in STATUSES:
        rows = [row for row in findings if row.status == status]
        by_status[status] = {"findings": len(rows), "entries": sum(row.count for row in rows)}
    return {"findings": len(findings), "entries": sum(row.count for row in findings),
            "byStatus": by_status}


def _plan_findings(plan: dict) -> list[Finding]:
    findings: list[Finding] = []
    handlers = {
        "cutTrack": _cuts, "baselineLook": _baseline, "graphicsTrack": _graphics,
        "punchIns": _punches, "transitions": _transitions,
    }
    for key, handler in handlers.items():
        if key not in plan or plan[key] is None:
            continue
        empty_optional = key != "cutTrack" and plan[key] == []
        if not empty_optional:
            findings += handler(plan[key])
    # Reframe is aspect-aware: shortform reframe loss BLOCKS a native push (face
    # centring is load-bearing at 9:16); longform reframe:'none' is a harmless
    # no-op and stays non-blocking.
    if "reframe" in plan and plan["reframe"] not in (None, {}):
        blocks = (plan.get("target") or {}).get("mode") == "short"
        findings += _reframe(plan["reframe"], blocks)
    if "titleCards" in plan and plan["titleCards"] not in (None, []):
        findings += _titles(plan["titleCards"])
    if "captions" in plan and plan["captions"] not in (None, {}):
        captions = plan["captions"]
        if not isinstance(captions, dict):
            findings.append(_malformed("captions", "captions:malformed", "Captions",
                "captions must be an object."))
        else:
            findings += _single(captions, "captions", "captions", "Captions",
                "Caption cues and word timing are not translated to Palmier.")
    if "brollTrack" in plan and plan["brollTrack"] not in (None, []):
        findings += _timed_lane(plan["brollTrack"], "broll", "B-roll",
            "B-roll trims and focus operations are not natively translated.")
    findings += _optional_lanes(plan)
    for key in sorted(set(plan) - _HANDLED - _METADATA):
        if not key.startswith("_") and _present(plan[key]):
            findings.append(Finding(f"unknown:{key}", key, "unsupported", key,
                "Unknown plan lane; visual mirror safety cannot be guaranteed.",
                blocksSync=True))
    return findings


def analyze_parity(plan: object) -> dict:
    """Return a deterministic, JSON-serializable Palmier editability report."""
    findings = (_plan_findings(plan) if isinstance(plan, dict) else [
        _malformed("plan", "plan:malformed", "Edit plan",
                   "Edit plan must be a JSON object.")])
    findings.sort(key=lambda row: row.id)
    blockers = [row for row in findings if row.status != "exact"]
    mirror_blockers = [row for row in findings if row.blocksSync]
    mirror_ready = bool(findings) and not mirror_blockers
    return {
        "schemaVersion": 1,
        "fullyEditable": bool(findings) and not blockers,
        "mirrorReady": mirror_ready,
        "mirrorMode": "visual-master" if mirror_ready else "blocked",
        "findings": [asdict(row) for row in findings],
        "summary": _summary(findings),
        "blockers": [asdict(row) for row in blockers],
        "mirrorBlockers": [asdict(row) for row in mirror_blockers],
        "syncBlockers": [asdict(row) for row in mirror_blockers],
        "capability": {
            "visibleTimeline": "single-approved-master-clip",
            "visualAndAudioFidelity": "byte-identical-master",
            "componentAssets": "best-effort-non-visible-library-imports",
            "componentTimelineEditability": False,
            "nativeReconstructionFullyEditable": bool(findings) and not blockers,
        },
    }
