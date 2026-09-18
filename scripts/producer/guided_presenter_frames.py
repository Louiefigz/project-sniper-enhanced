"""Exact actual V8/V2 full-program bindings, not render or profile authority.

This is an internal metadata prerequisite. The caller separately admits the
explicit presenter profile, owns source/asset observations, and proves actual
composition and QC. No legacy plan or binding is rewritten into a new class.
"""
from __future__ import annotations

from audio.program_master_excerpt import sample_range
from cut_preview_io import digest
from guided_opening_frames import _binding
from guided_opening_inputs import OpeningInputs, closed
from guided_proposal_presenter import validate_requested_presenter
from guided_proposal_reframe import proposal_trim

_KEYS = {"schemaVersion", "kind", "scope", "frameRate", "totalFrames", "targetHash",
         "candidatePlanHash", "occurrenceEvidenceHash", "graphics", "unboundInheritedGraphicIds", "presenterLayouts"}


def _ranges(authority: dict) -> None:
    """Keep the complete original origin and exact positive review/core endpoints."""
    core, review = authority["core"], authority["review"]
    for span in (core, review):
        closed(span, {"startFrame", "endFrameExclusive"}, "presenter frame range")
        sample_range((span["startFrame"], span["endFrameExclusive"]),
                     (authority["frameRate"], authority["totalFrames"]))
    if core["startFrame"] != 0 or review["startFrame"] != 0 or core["endFrameExclusive"] > review["endFrameExclusive"]:
        raise RuntimeError("presenter opening ranges must keep their complete original origin")


def _packet(inputs: OpeningInputs) -> tuple[dict, list]:
    """Reconstruct the header and actual windows from original unmodified documents."""
    docs = inputs.documents
    authority, plan, packet = docs["authority"], docs["candidatePlan"], docs["readinessPacket"]
    requested = validate_requested_presenter(docs["acceptedPlan"], plan, packet, docs["manifest"])
    if requested is None or not requested.windows:
        raise RuntimeError("presenter frame reader requires nonempty actual V8 intent")
    if any(digest(authority.get(key)) != digest(packet["evidence"].get(key))
           for key in ("target", "frameRate", "totalFrames")):
        raise RuntimeError("presenter frame authority differs from actual V8 canvas/clock")
    bindings = closed(docs["frameBindings"], _KEYS, "presenter V2 frame bindings")
    if type(bindings["schemaVersion"]) is not int or bindings["schemaVersion"] != 2:
        raise RuntimeError("presenter frame bindings require actual integer V2")
    occurrence = {key: packet["evidence"][key] for key in ("anchors", "occurrences", "segments")}
    expected = {"kind": "guided-frame-presentation-bindings",
        "scope": "controller-frames-and-declared-presentation-not-rendered-proof",
        "frameRate": authority["frameRate"], "totalFrames": authority["totalFrames"],
        "targetHash": digest(authority["target"]), "candidatePlanHash": digest(plan),
        "occurrenceEvidenceHash": digest(occurrence), "unboundInheritedGraphicIds": [],
        "presenterLayouts": list(requested.windows)}
    if any(digest(bindings[key]) != digest(value) for key, value in expected.items()):
        raise RuntimeError("presenter whole-program V2 frame bindings changed")
    if (digest(packet["candidate"]) != digest(plan) or digest(docs["occurrences"]) != digest(occurrence)
            or authority["candidatePlanHash"] != expected["candidatePlanHash"]
            or authority["occurrenceEvidenceHash"] != expected["occurrenceEvidenceHash"]
            or authority["frameBindingsHash"] != digest(bindings)
            or digest(packet["executionBindings"]) != digest(bindings)):
        raise RuntimeError("presenter frame packet differs from original authority/documents")
    _ranges(authority)
    track = plan.get("graphicsTrack")
    if type(track) is not list or type(bindings["graphics"]) is not list \
            or len(bindings["graphics"]) != len(track) or len(track) > 128:
        raise RuntimeError("presenter graphics lack exact whole-candidate coverage")
    return bindings, track


def presenter_program_frames(inputs: OpeningInputs) -> list[dict]:
    """Return ALL original graphics after order, operation, entry and presentation checks."""
    if type(inputs) is not OpeningInputs:
        raise RuntimeError("presenter frames require original opening inputs")
    bindings, track = _packet(inputs)
    rows = [_binding(row, (index, track[index], inputs, True))
            for index, row in enumerate(bindings["graphics"])]
    operations = inputs.documents["readinessPacket"]["proposal"]["operations"]
    expected = [index for index, row in enumerate(operations) if row["type"] == "catalog-graphic"]
    ids = [row["graphicId"] for row in rows]
    if ([row["operationIndex"] for row in rows] != expected
            or any(type(value) is not str or not proposal_trim(value) or len(value) > 200 for value in ids)
            or len(set(ids)) != len(ids)):
        raise RuntimeError("presenter graphics lack unique original operation coverage")
    return rows
