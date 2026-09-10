"""Prepare an honest, native-capability subset for a Palmier work checkpoint."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from graphics.graphics_render import (
    render_entry_at_rate as render_entry,
    timeline_padded_entry,
)
from graphics.exit_on_cut import apply_exit_on_cut
from motion.punch_in import parse_windows
from motion.recompose import apply_recompose, requires_recompose, stamp_face_bbox
from palmier.mcp_client import PalmierError, emit
from palmier.parity import analyze_parity
from palmier.transition_preview import (render_transition_preview,
                                        supported_transition_kinds)


@dataclass(frozen=True)
class PreparedCheckpointPlan:
    """A disposable translation view plus explicit fidelity limitations."""

    plan: dict
    graphics: dict[int, str]
    omissions: list[dict]
    limitations: list[dict]
    parity: dict


def _present(value: object) -> bool:
    return value not in (None, False, "", [], {})


def _positive_fact(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and value > 0


def _omit(plan: dict, key: str, lane: str, reason: str,
          omissions: list[dict]) -> None:
    value = plan.get(key)
    if not _present(value):
        plan.pop(key, None)
        return
    count = len(value) if isinstance(value, list) else 1
    omissions.append({"lane": lane, "count": count, "reason": reason})
    plan.pop(key, None)


def _motion_error(row: object) -> str | None:
    if not isinstance(row, dict):
        return "motion row is not an object"
    kind = str(row.get("kind", "")).lower()
    if row.get("bracket") or kind == "bracket":
        return "bracket motion has no faithful Palmier keyframe mapping"
    if kind in {"ramp", "aliveness"} and "ramp" not in row:
        return f"{kind} motion is missing its ramp object"
    if any(key in row for key in ("ratePctPerS", "direction")):
        return "legacy top-level ramp vocabulary is not translatable"
    try:
        (window,) = parse_windows([row])
    except (KeyError, TypeError, ValueError) as exc:
        return str(exc)
    if window.is_ramp and window.ease != "smooth":
        return "ramp must carry ease:'smooth' for faithful Palmier keyframes"
    if not window.is_ramp and not window.is_push:
        return "static punch hold semantics are not proven by Palmier readback"
    return None


def _filter_punches(plan: dict) -> None:
    rows = plan.get("punchIns")
    if not isinstance(rows, list):
        return
    for index, row in enumerate(rows):
        issue = _motion_error(row)
        if issue:
            raise PalmierError(
                f"required motion punchIns[{index}] cannot reach Palmier: {issue}")


def _output_duration(plan: dict) -> float:
    return sum((float(row["end"]) - float(row["start"]))
               / float(row.get("speed", 1.0) or 1.0)
               for row in plan.get("cutTrack") or [])


def _apply_required_recompose(plan: dict, source_path: str | None = None) -> None:
    rails = [row for row in plan.get("graphicsTrack") or []
             if isinstance(row, dict) and requires_recompose(row)]
    if not rails:
        return
    # Mirror render.py's recompose_stage: MEASURE the face from the source when the
    # plan carries none, so a valid longform-with-rails plan recenters in the
    # working preview too instead of hard-aborting the checkpoint. Idempotent — a
    # no-op once faceBBoxNorm is stamped (the pre-gate authoring step usually did).
    if source_path and not plan.get("faceBBoxNorm"):
        stamp_face_bbox(plan, source_path, _output_duration(plan))
    try:
        apply_recompose(plan, _output_duration(plan))
    except (KeyError, TypeError, ValueError) as exc:
        raise PalmierError(
            f"required rail recompose could not be measured: {exc}") from exc


def _strip_grade(plan: dict, omissions: list[dict]) -> None:
    look = plan.get("baselineLook")
    if not isinstance(look, dict) or look.get("grade") in (None, "", "none"):
        return
    omissions.append({
        "lane": "color", "count": 1,
        "reason": "the Sniper grade has no measured native Palmier mapping",
    })
    plan["baselineLook"] = {**look, "grade": "none"}


def _render_graphics(plan: dict, cache_dir: str | None,
                     omissions: list[dict], fps: float | None) -> dict[int, str]:
    rows = plan.get("graphicsTrack")
    if not isinstance(rows, list):
        return {}
    kept: list[dict] = []
    paths: dict[int, str] = {}
    for original_index, row in enumerate(rows):
        try:
            render_row = timeline_padded_entry(row, fps) if fps else row
            result = render_entry(render_row, cache_dir, fps or 30.0)
        except Exception as exc:
            emit(status="checkpoint_graphic_failed", index=original_index,
                 reason=str(exc), required=True)
            raise PalmierError(
                f"required graphicsTrack[{original_index}] could not be "
                f"proved for Palmier: {exc}") from exc
        proof = result.get("proof")
        if not isinstance(proof, dict) or proof.get("schemaVersion") != 1:
            raise PalmierError(
                f"required graphicsTrack[{original_index}] has no rendered "
                "asset proof")
        index = len(kept)
        kept.append(row)
        paths[index] = result["path"]
        emit(status="checkpoint_graphic_ready", index=original_index,
             cached=result["cached"], path=result["path"],
             proofPath=proof.get("sidecar"))
    plan["graphicsTrack"] = kept
    return paths


def _transition_omission(kind: str) -> str:
    if kind == "zoom-pull":
        return ("zoom-pull needs blur-masked, cross-cut keyframes; applying "
                "scale alone could overwrite authored punch motion")
    return f"transition kind {kind!r} has no verified Palmier preview mapping"


def _render_transition_previews(plan: dict, graphics: dict[int, str],
                                cache_dir: str | None, fps: float,
                                width: int, height: int,
                                omissions: list[dict],
                                limitations: list[dict]) -> None:
    rows = plan.pop("transitions", None)
    if not isinstance(rows, list) or not rows:
        return
    supported = set(supported_transition_kinds())
    track = plan.get("graphicsTrack")
    if not isinstance(track, list):
        track = []
        plan["graphicsTrack"] = track
    unsupported: dict[str, int] = {}
    for original_index, row in enumerate(rows):
        kind = row.get("kind") if isinstance(row, dict) else "malformed"
        if kind not in supported:
            reason = _transition_omission(str(kind))
            unsupported[reason] = unsupported.get(reason, 0) + 1
            continue
        try:
            preview = render_transition_preview(
                row, fps, width, height, cache_dir)
        except Exception as exc:
            emit(status="checkpoint_transition_failed", index=original_index,
                 kind=kind, reason=str(exc), required=True)
            raise PalmierError(
                f"required transitions[{original_index}] could not be "
                f"rendered and proved for Palmier: {exc}") from exc
        index = len(track)
        track.append(preview.entry)
        graphics[index] = preview.path
        limitations.append({"lane": "transitions", "count": 1,
                            "kind": kind, "fidelity": preview.fidelity,
                            "reason": preview.limitation})
        if row.get("sfx"):
            omissions.append({
                "lane": "sfx", "count": 1,
                "reason": ("transition visual is present in Palmier; its SFX "
                           "remains in the governed final render")})
        emit(status="checkpoint_transition_ready", index=original_index,
             kind=kind, fidelity=preview.fidelity, path=preview.path,
             proofPath=preview.proof.get("sidecar"))
    omissions.extend({"lane": "transitions", "count": count,
                      "reason": reason}
                     for reason, count in unsupported.items())


def prepare_checkpoint_plan(plan: dict, cache_dir: str | None = None,
                            render_graphics: bool = True,
                            fps: float | None = None,
                            width: int | None = None,
                            height: int | None = None,
                            source_path: str | None = None) -> PreparedCheckpointPlan:
    """Return only lanes the current native executor can represent honestly.

    ``source_path`` (the primary source MP4) lets a longform-with-rails plan that
    carries no ``faceBBoxNorm`` MEASURE the face here instead of aborting — the
    same measure-when-absent as the main render. Omit it (tests, no video) and the
    recompose still fails closed on an un-measured plan."""
    working = deepcopy(plan)
    omissions: list[dict] = []
    limitations: list[dict] = []
    unsupported = (
        ("brollTrack", "broll", "b-roll trims/focus operations are not translated"),
        ("reframe", "reframe", "crop, tracking, and split layouts are not translated"),
        ("captions", "captions", "caption cue and word timing are not translated"),
        ("music", "music", "the working view does not reproduce the mastered audio bed"),
        ("audioEnhance", "audio", "dialogue enhancement exists only in the render bus"),
        ("audioGain", "audio", "gain automation exists only in the render bus"),
        ("chapters", "chapters", "chapter markers are not created in Palmier"),
    )
    for key, lane, reason in unsupported:
        _omit(working, key, lane, reason, omissions)
    _apply_required_recompose(working, source_path)
    _filter_punches(working)
    _strip_grade(working, omissions)
    effective_graphics, _clamped = apply_exit_on_cut(working)
    if working.get("graphicsTrack"):
        working["graphicsTrack"] = effective_graphics
    graphics = _render_graphics(working, cache_dir, omissions, fps) \
        if render_graphics else {}
    if render_graphics and all(_positive_fact(value)
                               for value in (fps, width, height)):
        _render_transition_previews(
            working, graphics, cache_dir, float(fps), int(width), int(height),
            omissions, limitations)
    else:
        _omit(working, "transitions", "transitions",
              "transition preview rendering requires canvas/fps facts", omissions)
        if not render_graphics and working.get("graphicsTrack"):
            _omit(working, "graphicsTrack", "graphics",
                  "graphics rendering was disabled for this checkpoint", omissions)
    return PreparedCheckpointPlan(
        working, graphics, omissions, limitations, analyze_parity(plan))
