"""Production owner projection and admission for explicitly screened captions.

Only actual held captions and bound original graphic rows enter this adapter.
Declared native clear regions are policy intent; actual sealed all-frame CSS
observations remain indispensable. No renderer/caption/default-plan mutation.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from cut_preview_io import digest
from guided_caption_dependencies import Guard
from guided_caption_layout_v2 import inspect_covered_layout
from guided_caption_profile import screened_caption_profile
from guided_caption_projection import HeldCaptionProjection, read_caption_projection
from guided_opening_frames import executable_frames, full_program_frames
from guided_opening_inputs import OpeningInputs


@dataclass(frozen=True)
class CaptionScreenContext:
    """Exact original execution, whole-program caption clock and selected coverage."""

    inputs: OpeningInputs
    held: HeldCaptionProjection
    rows: tuple[dict, ...]
    coverage: dict
    owner_phase: str = "opening"


def supported_layout(row: dict, authority: dict) -> bool:
    """Only explicitly authored agenda/pipeline classes with measured native shape."""
    from guided_caption_graphic_observation import native_observation_class
    entry, target = row["entry"], authority["target"]
    frames = row["endFrameExclusive"] - row["startFrame"]
    rate = Fraction(authority["frameRate"])
    return native_observation_class(entry) is not None \
        and (target["width"], target["height"]) == (1920, 1080) \
        and 0 < rate <= 60 and 1 <= frames <= 3600 and Fraction(frames, 1) / rate <= 60


def screen_intent_preflight(inputs: OpeningInputs, rows: list[dict]) -> None:
    """Refuse only known unsupported explicit observation intent before base work.

    Other kinds may occur in genuine cue gaps; their simultaneity is decided
    from the actual original caption projection, never a guessed speech span.
    """
    if not screened_caption_profile(inputs.value.get("profile")):
        return
    for row in rows:
        entry = row["entry"]
        if entry.get("kind") in ("agenda-slide", "module-pipeline") \
                and (entry.get("spec") or {}).get("layout") == "caption-safe-upper-v1" \
                and not supported_layout(row, inputs.documents["authority"]):
            raise RuntimeError("explicit caption layout exceeds the supported native observation class")


def screen_context(inputs: OpeningInputs, held: HeldCaptionProjection | None, body: bool) -> CaptionScreenContext | None:
    """Derive selected original orders/coverage, never accept a request-supplied range."""
    if not screened_caption_profile(inputs.value.get("profile")):
        return None
    if held is None:
        raise RuntimeError("screened caption profile lacks its actual held caption projection")
    authority = inputs.documents["authority"]
    end = authority["totalFrames"] if body else authority["review"]["endFrameExclusive"]
    rows = full_program_frames(inputs) if body else executable_frames(inputs)
    return CaptionScreenContext(inputs, held, tuple(rows), {"startFrame": 0, "endFrameExclusive": end},
                                "body" if body else "opening")


def _clock(context: CaptionScreenContext) -> dict:
    """Prove full-program identity before any graphic-local frame projection."""
    inputs, held = context.inputs, context.held
    authority, refs = inputs.documents["authority"], inputs.value["documents"]
    rate = Fraction(authority["frameRate"])
    expected = authority["frameRate"], authority["totalFrames"], authority["target"]["width"], authority["target"]["height"]
    if held.binding.frame_clock != expected or held.binding.execution_input_hash != inputs.value["executionInputHash"] \
            or held.binding.plan.path != refs["candidatePlan"]["path"] \
            or held.binding.plan.sha256 != refs["candidatePlan"]["sha256"] \
            or held.binding.manifest.path != refs["manifest"]["path"] \
            or held.binding.manifest.sha256 != refs["manifest"]["sha256"]:
        raise RuntimeError("caption screen is not the original whole-program held authority")
    return {"frameRate": f"{rate.numerator}/{rate.denominator}", "totalFrames": expected[1],
            "width": expected[2], "height": expected[3]}


def held_cues(context: CaptionScreenContext, guard: Guard) -> list[dict]:
    """Use exact whole-cue alpha bounds, including portions across range endpoints."""
    _clock(context)
    held = context.held
    read_caption_projection(held, held.binding, guard)
    inventory = {row.path: row for row in held.files}
    result = []
    for row in held.data["shards"]["entries"]:
        path = str(Path(held.root) / row["media"]["name"])
        media = inventory[path]
        if media.sha256 != row["media"]["sha256"]:
            raise RuntimeError("caption screen shard is not the original held rendered bytes")
        result.append({"cueId": row["cueId"], "startFrame": row["startFrame"],
            "endFrameExclusive": row["endFrameExclusive"], "media": {"path": path, "sha256": media.sha256},
            "shapedSafeBounds": row["proof"]["shapedSafeBounds"]})
    return result


def needs_observation(row: dict, cues: list[dict], coverage: dict) -> bool:
    """Genuine half-open cue gaps do not become false caption conflicts."""
    return any(max(cue["startFrame"], row["startFrame"], coverage["startFrame"]) < min(
        cue["endFrameExclusive"], row["endFrameExclusive"], coverage["endFrameExclusive"]) for cue in cues)


def admit_screen(context: CaptionScreenContext | None, guard: Guard) -> set[int]:
    """Before first graphic spawn, reject exact unsupported simultaneous intent."""
    if context is None:
        return set()
    cues = held_cues(context, guard)
    orders = set()
    for row in context.rows:
        if not needs_observation(row, cues, context.coverage):
            continue
        if not supported_layout(row, context.inputs.documents["authority"]):
            raise RuntimeError(f"caption layout unqualified for simultaneous graphic {row['graphicId']} ({row['entry']['kind']})")
        orders.add(row["order"])
    guard()
    return orders


def screen_result(context: CaptionScreenContext | None, evidence: list[dict], guard: Guard) -> dict | None:
    """Construct screening only through fresh strongly bound actual observations."""
    if context is None:
        if any("captionLayoutObservation" in row for row in evidence):
            raise RuntimeError("historical graphic acquired a new caption observation")
        return None
    from guided_caption_screen_read import graphic_projection, observation_reader
    guard()
    if len(evidence) != len(context.rows):
        raise RuntimeError("caption screen omitted an original selected graphic")
    clock, cues = _clock(context), held_cues(context, guard)
    graphics, declarations, records = [], [], {}
    for row, proof in zip(context.rows, evidence, strict=True):
        graphic, declaration, request = graphic_projection((context, clock), row, proof, guard)
        graphics.append(graphic)
        needed = needs_observation(row, cues, context.coverage)
        if needed and declaration is None:
            raise RuntimeError("simultaneous graphic lacks a supported native layout declaration")
        if needed:
            declarations.append(declaration)
        records[row["graphicId"]] = proof, request
    value = {"schemaVersion": 2, "kind": "held-caption-layout-input", "clock": clock,
        "coverage": context.coverage, "captionProjectionHash": context.held.data_hash,
        "cues": cues, "graphics": graphics, "declarations": declarations}
    result = inspect_covered_layout(value, observation_reader(records, guard), guard)
    read_caption_projection(context.held, context.held.binding, guard)
    for row, proof, original in zip(context.rows, evidence, graphics, strict=True):
        current, _declaration, _request = graphic_projection((context, clock), row, proof, guard)
        if digest(current) != digest(original):
            raise RuntimeError("caption screening original graphic sources changed at final read")
    from guided_opening_graphic_proof import verify_graphics_unchanged
    verify_graphics_unchanged(evidence)
    guard()
    return result


def require_screen(result: dict | None) -> None:
    """No unmeasured/conflicting screen grants candidate publication credit."""
    if result is not None and result["state"] not in ("not-applicable", "screened-no-overlap"):
        raise RuntimeError("caption/graphic screening did not qualify: " + result["state"])
