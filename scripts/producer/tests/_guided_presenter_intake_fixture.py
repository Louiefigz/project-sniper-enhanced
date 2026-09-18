"""Pure V8 profile declarations and parser-shaped TEST refs, not admitted inputs."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from _guided_presenter_capture_fixture import PresenterCaptureFixture, bind_capture_documents
from _guided_proposal_music_fixture import values as music_values
from _guided_proposal_presenter_fixture import asset, operation
from cut_preview_io import digest
from guided_opening_inputs import DOCUMENTS, OpeningInputs
from guided_presenter_profile import PRESENTER_CAPTION_SHORT_PROFILE, presenter_profile_for_plan
from guided_proposal_presenter import guided_presenter_policy
from opening_prefix_contract import PrefixClock
from test_guided_proposal_reframe_guards import cut_inputs


def profile_inputs(fixture: PresenterCaptureFixture, short: bool, captioned: bool) -> OpeningInputs:
    """Derive each exact metadata class without a tool, source decode or audio waiver."""
    docs = deepcopy(fixture.inputs.documents)
    accepted, candidate = docs["acceptedPlan"], docs["candidatePlan"]
    for plan in (accepted, candidate):
        plan["captions"] = {"burn": captioned}
        if short:
            plan["target"].update(mode="short", width=1080, height=1920)
            plan["reframe"] = {"layout": "fill", "crop": [0, 0, 1, 1], "track": False}
        if captioned:
            plan["captionsTrack"] = {"schemaVersion": 1, "source": "kept-transcript",
                                     "defaultPolicy": "line", "groups": []}
    evidence, authority = docs["readinessPacket"]["evidence"], docs["authority"]
    evidence.update(target=deepcopy(accepted["target"]), presenterPolicy=guided_presenter_policy(accepted, docs["manifest"]))
    authority["target"] = deepcopy(accepted["target"])
    bind_capture_documents(docs)
    clock = PrefixClock(authority["frameRate"], authority["totalFrames"], authority["target"]["width"], authority["target"]["height"])
    profile = presenter_profile_for_plan(candidate, clock)
    authority["profile"] = profile
    return replace(fixture.inputs, value={**fixture.inputs.value, "profile": profile}, documents=docs)


def invocation(profile: object) -> dict:
    """Closed invocation syntax; fake refs cannot authenticate a 14-document project."""
    value = {"schemaVersion": 1, "kind": "guided-opening-media-input", "profile": profile,
        "executionId": "11112222-3333-4444-8555-666677778888", "pipeline": {"TEST": "not an actual pipeline"},
        "documents": {key: {"path": f"/TEST/{key}.json", "sha256": "a" * 64} for key in DOCUMENTS}}
    value["executionInputHash"] = digest(value)
    return value


def authority_inputs(inputs: OpeningInputs) -> OpeningInputs:
    """Supply closed TEST authority syntax solely to exercise the real negative gate."""
    docs = deepcopy(inputs.documents)
    keys = {"schemaVersion", "kind", "scope", "profile", "runId", "previewAttempt", "contextHash",
        "cutDecisionHash", "acceptedRevisionHash", "requestHash", "pictureLockHash", "projectionHash",
        "sourceSetDigest", "manifestHash", "timelineMapHash", "rawAdmissionHash", "proposalHash", "readinessHash",
        "draftRevisionHash", "candidatePlanHash", "frameBindingsHash", "occurrenceEvidenceHash", "clockHash",
        "generationStartedAt", "frameRate", "totalFrames", "target", "core", "review"}
    role = {key: "TEST-not-an-approval" for key in keys}
    role.update(docs["authority"])
    role.update(schemaVersion=2, kind="guided-opening-media-authority",
        scope="private-opening-execution-not-opening-approval-body-or-delivery")
    docs.update(authority=role, cutRequest={})
    return replace(inputs, documents=docs, value=invocation(inputs.value["profile"]))


def requested_crop_inputs(profile: str = PRESENTER_CAPTION_SHORT_PROFILE) -> OpeningInputs:
    """Actual V8 crop/caption/presenter metadata, without authentic cut consent or media."""
    plan, candidate, packet, manifest = music_values(crop=True)
    for target in (plan["target"], candidate["target"]):
        target.update(scope="produced", lanes={"captions": "auto", "graphics": "off"})
    packet["proposal"]["schemaVersion"] = packet["evidence"]["schemaVersion"] = 8
    for row in packet["proposal"]["operations"]:
        row["presenterLayout"] = None
    presenter = operation()
    presenter.update(startAnchor=0, endAnchorExclusive=1)
    presenter["presenterLayout"].update(sourceIds=["raw-1"], enterFrames=1, exitFrames=1)
    index = len(packet["proposal"]["operations"])
    packet["proposal"]["operations"].append(presenter)
    packet["proposal"]["clauses"][0]["operationIndices"].append(index)
    manifest["broll"] = [asset()]
    packet["evidence"].update(target=deepcopy(plan["target"]), frameRate="30/1", totalFrames=258, anchors=[0, 258],
        segments=[{"index": 0, "sourceId": "raw-1", "startFrame": 0, "endFrameExclusive": 258}],
        presenterPolicy=guided_presenter_policy(plan, manifest))
    candidate["presenterLayouts"] = [{"operationIndex": index, "startFrame": 0, "endFrameExclusive": 258,
        "layout": deepcopy(presenter["presenterLayout"])}]
    inputs = cut_inputs(plan, candidate, packet, profile)
    inputs.documents["manifest"] = manifest
    return inputs
