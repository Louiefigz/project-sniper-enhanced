"""First private executable profile and exact occurrence/presentation bindings."""
from __future__ import annotations

from fractions import Fraction

from audio.program_master_excerpt import sample_range
from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2, audio_policy_reason
from cut_preview_io import digest
from guided_opening_inputs import OpeningInputs, closed
from graphics.frame_quantization import rounded_frame_index
from graphics.pip_hole import entry_has_hole
from producer_config import MODES
from guided_media_profile import (OPENING_PROFILE, SHORT_PROFILE, opening_profile, manual_short_plan,
                                  manual_caption_short_plan, manual_profile, assert_no_presenter_layouts)
from guided_caption_profile import caption_profile, caption_preset_plan
from guided_caption_layers import caption_page_bound
from opening_prefix_contract import PrefixClock
from guided_proposal_presenter import validate_requested_presenter


def _profile(plan: dict, profile: str = OPENING_PROFILE) -> None:
    """Unsupported requested work blocks this development class; never delete intent."""
    assert_no_presenter_layouts(plan)
    reason = audio_policy_reason(plan, SOURCE_FLOAT_POLICY_V2)
    if reason:
        raise RuntimeError(reason)
    captioned = caption_profile(profile)
    if captioned:
        caption_preset_plan(plan)
    # audioEnhance/audioGain finish in the shared program master (audio/program_finish_bus);
    # the opening excerpt is a slice of that same finished program. transitions stay
    # unqualified here until their visual seam covers are qualified for this profile.
    unsupported = (() if captioned else ("captionsTrack",)) + ("titleCards", "brollTrack", "baselineLook", "punchIns",
                   "transitions")
    active = [key for key in unsupported if plan.get(key)]
    manual = manual_profile(opening_profile(profile))
    if manual:
        (manual_caption_short_plan if captioned else manual_short_plan)(plan)
    reframe = plan.get("reframe") or {}
    if not manual and (reframe not in ({}, {"strategy": "none"}) \
            or reframe.get("strategy", MODES[plan["target"]["mode"]]["reframe_default"]) != "none"):
        active.append("reframe")
    if not captioned and (plan.get("captions") or {}).get("burn", plan.get("target", {}).get("mode") == "short"):
        active.append("captions.burn")
    if active:
        raise RuntimeError("private opening profile has not qualified requested lanes: " + ", ".join(active))
    for cut in plan.get("cutTrack", []):
        if cut.get("speed", 1) != 1 or cut.get("audioLeadMs", 0) != 0:
            raise RuntimeError("private opening semantic execution has not qualified speed/J-cut leads")


def _presentation(binding: dict, entry: dict) -> None:
    """Only explicit normal full-canvas own-screen presentation is qualified initially."""
    presentation = closed(binding["presentation"], {"schemaVersion", "anchor", "placement", "compositeMode",
        "baseTreatment", "rationale"}, "graphic presentation")
    expected = {"schemaVersion": 1, "anchor": "own-screen", "placement": "full-canvas",
        "compositeMode": "normal", "baseTreatment": "preserve"}
    if any(type(presentation[key]) is not type(value) or presentation[key] != value for key, value in expected.items()) \
            or type(presentation["rationale"]) is not str or not presentation["rationale"].strip():
        raise RuntimeError("private opening has not qualified requested graphic presentation")
    if entry.get("anchor") != "own-screen" or entry.get("takeoverBase") is not None \
            or entry.get("exitOnCut") or entry.get("placement") or entry_has_hole(entry):
        raise RuntimeError("private opening has not qualified this graphic's additional placement/effect intent")


def _binding(row: dict, context: tuple[int, dict, OpeningInputs, bool]) -> dict:
    """Recompute each order/entry/anchor binding from the exact reviewed full packet.

    Placement/effect intent is qualified only for graphics this opening executes
    (``executes`` = the binding starts before the review range ends); a body-only
    graphic keeps its exact identity/endpoint binding here and is the body
    compositor's to qualify (it may be a hole comp the private opening never
    composites).
    """
    index, entry, inputs, executes = context
    closed(row, {"graphicId", "operationIndex", "order", "startFrame", "endFrameExclusive", "presentation", "entryHash"},
           "graphic frame binding")
    authority, occurrence = inputs.documents["authority"], inputs.documents["occurrences"]
    operations = inputs.documents["readinessPacket"]["proposal"]["operations"]
    operation_index = row["operationIndex"]
    if type(row["order"]) is not int or row["order"] != index or row["graphicId"] != entry.get("id") \
            or row["entryHash"] != digest(entry) or type(operation_index) is not int \
            or not 0 <= operation_index < len(operations):
        raise RuntimeError("opening graphic order/identity differs from reviewed candidate")
    operation = operations[operation_index]
    if operation["type"] != "catalog-graphic" or row["startFrame"] != occurrence["anchors"][operation["startAnchor"]] \
            or row["endFrameExclusive"] != occurrence["anchors"][operation["endAnchorExclusive"]] \
            or digest(row["presentation"]) != digest(operation["presentation"]):
        raise RuntimeError("opening graphic lost its exact reviewed occurrence endpoints")
    sample_range((row["startFrame"], row["endFrameExclusive"]), (authority["frameRate"], authority["totalFrames"]))
    rate = float(Fraction(authority["frameRate"]))
    if rounded_frame_index(entry["outStart"], rate) != row["startFrame"] \
            or rounded_frame_index(entry["outEnd"], rate) != row["endFrameExclusive"]:
        raise RuntimeError("opening graphic seconds do not execute its exact reviewed frame endpoints")
    if executes:
        _presentation(row, entry)
    return {**row, "entry": entry}


def _binding_version(inputs: OpeningInputs) -> int:
    """Actual V8 without a layout keeps V2; no persisted document is downgraded."""
    docs, bindings = inputs.documents, inputs.documents["frameBindings"]
    packet = docs["readinessPacket"]
    if type(bindings) is not dict or type(packet) is not dict or type(packet.get("proposal")) is not dict:
        raise RuntimeError("opening frame bindings require actual packet objects")
    version = bindings.get("schemaVersion")
    proposal_version = packet.get("proposal", {}).get("schemaVersion")
    if type(version) is not int or version not in (1, 2):
        raise RuntimeError("opening frame bindings require actual integer version1 or2")
    if version == 1:
        if type(proposal_version) is int and proposal_version == 8:
            raise RuntimeError("actual V8 frame bindings cannot be downgraded to V1")
        return 1
    if type(proposal_version) is not int or proposal_version != 8 \
            or type(bindings.get("presenterLayouts")) is not list or bindings["presenterLayouts"]:
        raise RuntimeError("existing opening profiles require actual V8 with empty presenter bindings")
    result = validate_requested_presenter(docs["acceptedPlan"], docs["candidatePlan"], packet, docs["manifest"])
    if result is None or result.windows or "presenterLayouts" in docs["candidatePlan"]:
        raise RuntimeError("existing opening profile has no presenterLayouts execution owner")
    return 2


def _frame_packet(inputs: OpeningInputs) -> tuple[dict, dict, list]:
    """Check the shared whole-program header before selecting an execution range."""
    docs, authority = inputs.documents, inputs.documents["authority"]
    plan, bindings = docs["candidatePlan"], docs["frameBindings"]
    _profile(plan, inputs.value.get("profile", OPENING_PROFILE))
    version = _binding_version(inputs)
    closed(bindings, {"schemaVersion", "kind", "scope", "frameRate", "totalFrames", "targetHash", "candidatePlanHash",
        "occurrenceEvidenceHash", "graphics", "unboundInheritedGraphicIds"}
        | ({"presenterLayouts"} if version == 2 else set()), "frame bindings")
    expected = {"schemaVersion": version, "kind": "guided-frame-presentation-bindings",
        "scope": "controller-frames-and-declared-presentation-not-rendered-proof", "frameRate": authority["frameRate"],
        "totalFrames": authority["totalFrames"], "targetHash": digest(authority["target"]),
        "candidatePlanHash": authority["candidatePlanHash"], "occurrenceEvidenceHash": authority["occurrenceEvidenceHash"],
        "unboundInheritedGraphicIds": []}
    if any(digest(bindings[key]) != digest(value) for key, value in expected.items()):
        raise RuntimeError("opening full-program frame binding authority changed")
    if authority["candidatePlanHash"] != digest(plan) \
            or authority["occurrenceEvidenceHash"] != digest(docs["occurrences"]):
        raise RuntimeError("opening frame packet differs from its candidate/occurrence bytes")
    core, review = authority["core"], authority["review"]
    for span in (core, review):
        closed(span, {"startFrame", "endFrameExclusive"}, "frame range")
        sample_range((span["startFrame"], span["endFrameExclusive"]), (authority["frameRate"], authority["totalFrames"]))
    if core["startFrame"] != 0 or review["startFrame"] != 0 or core["endFrameExclusive"] > review["endFrameExclusive"]:
        raise RuntimeError("initial opening core/context must share exact full-program origin")
    track = plan.get("graphicsTrack") or []
    if type(track) is not list or type(bindings["graphics"]) is not list \
            or len(bindings["graphics"]) != len(track) or len(track) > 128:
        raise RuntimeError("opening graphics lack exact whole-candidate coverage")
    return authority, bindings, track


def _bound_frames(inputs: OpeningInputs, all_presentations: bool) -> list[dict]:
    """Preserve one-to-one reviewed operation order, not only matching timestamps."""
    from guided_presenter_intake import is_presenter_profile, presenter_metadata_frames

    if is_presenter_profile(inputs.value.get("profile")):
        return presenter_metadata_frames(inputs)
    authority, bindings, track = _frame_packet(inputs)

    def executes(row: dict) -> bool:
        """Preserve the legacy distinction between opening and all-body presentation checks."""
        return all_presentations or (type(row.get("startFrame")) is int
                                    and row["startFrame"] < authority["review"]["endFrameExclusive"])

    rows = [_binding(row, (index, track[index], inputs, executes(row))) for index, row in enumerate(bindings["graphics"])]
    operations = inputs.documents["readinessPacket"]["proposal"]["operations"]
    indexes = [index for index, operation in enumerate(operations) if operation["type"] == "catalog-graphic"]
    ids = [row["graphicId"] for row in rows]
    if type(operations) is not list or len(operations) > 128 \
            or [row["operationIndex"] for row in rows] != indexes \
            or any(type(value) is not str or not value.strip() or len(value) > 200 for value in ids) \
            or len(set(ids)) != len(ids):
        raise RuntimeError("opening graphics lack unique ordered operation coverage")
    return rows


def executable_frames(inputs: OpeningInputs) -> list[dict]:
    """Return only bound intersecting originals; later presentations stay unqualified."""
    rows = _bound_frames(inputs, False)
    _caption_workload(inputs, rows)
    authority = inputs.documents["authority"]
    selected = [row for row in rows if row["startFrame"] < authority["review"]["endFrameExclusive"]]
    if len(selected) > 8 or Fraction(authority["frameRate"]) <= 0:
        raise RuntimeError("private opening exceeds its initial eight-graphic admission bound")
    return selected


def full_program_frames(inputs: OpeningInputs) -> list[dict]:
    """Check ALL body presentations, including those absent from opening playback.

    Metadata-only prerequisite for a future held-body worker, not media evidence
    or permission to render. Caller still owes current authenticated inputs,
    explicit opening approval, original budget/resource ownership, actual sealed
    graphic proof, complete-output QC and opening parity before any selection.
    No unsupported lane is removed or rewritten to fit this profile.
    """
    rows = _bound_frames(inputs, True)
    _caption_workload(inputs, rows)
    return rows


def _caption_workload(inputs: OpeningInputs, rows: list[dict]) -> None:
    """All prospective full pages count before materialization, not only opening cues."""
    if not caption_profile(inputs.value.get("profile")):
        return
    authority = inputs.documents["authority"]
    clock = PrefixClock(authority["frameRate"], authority["totalFrames"],
                        authority["target"]["width"], authority["target"]["height"])
    end = authority["review"]["endFrameExclusive"]
    caption_page_bound(clock, (len(rows), sum(row["startFrame"] < end for row in rows)), end)
