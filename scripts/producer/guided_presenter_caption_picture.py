"""Live opening caption clearance and its distinct actual-picture binding.

The original inspector report remains precomposition evidence with
pictureProofBound:false. This adapter rejects before encoding, rechecks under
the same owner afterward, and binds that unchanged report to returned picture
records. Neither the report nor its hash projector grants execution or QC.
"""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json

from cut_preview_io import digest
from guided_caption_projection import HeldCaptionProjection
from guided_opening_inputs import OpeningInputs, closed
from guided_opening_presenter import OpeningPresenterContext
from guided_presenter_caption_clearance import (
    POLICY, PresenterCaptionClearanceContext, _caption_identities,
    inspect_presenter_caption_clearance, verify_presenter_caption_clearance,
)
from guided_presenter_capture_inputs import capture_input_binding
from guided_presenter_execution import OwnedPresenterExecution
from opening_prefix_contract import canonical_hash


@dataclass(frozen=True)
class PreparedPresenterCaptionPicture:
    """Internal live phase state, never a serialized clearance capability."""

    context: PresenterCaptionClearanceContext
    presenter: OpeningPresenterContext
    report: dict
    original: tuple


def _caption_binding_hash(held: HeldCaptionProjection) -> str:
    """Retain Python metadata spelling; this is a live guard, not a receipt hash."""
    raw = json.dumps(asdict(held), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _context(presenter: OpeningPresenterContext, captions: HeldCaptionProjection,
             authority: dict) -> PresenterCaptionClearanceContext:
    """Require independently held original inputs, not a new plan-only identity."""
    if type(presenter) is not OpeningPresenterContext or type(presenter.owner) is not OwnedPresenterExecution \
            or type(presenter.inputs) is not OpeningInputs or type(captions) is not HeldCaptionProjection:
        raise RuntimeError("captioned presenter needs original opening inputs and live caption/presenter owners")
    inputs = presenter.inputs
    if digest(inputs.documents["candidatePlan"]) != digest(presenter.plan) \
            or digest(inputs.documents["authority"]) != digest(authority):
        raise RuntimeError("presenter caption picture differs from original input plan or authority")
    return PresenterCaptionClearanceContext(inputs, captions, presenter.owner, deepcopy(authority["review"]))


def _unchanged(prepared: PreparedPresenterCaptionPicture) -> None:
    """No callbacks here: bind metadata and actual caption identities after owner checks."""
    context, presenter = prepared.context, prepared.presenter
    authority, input_hash, authority_hash, report_hash, captions = prepared.original
    held, held_hash, identities = captions
    if presenter.inputs is not context.inputs or presenter.owner is not context.presenter \
            or capture_input_binding(context.inputs) != input_hash or digest(authority) != authority_hash \
            or digest(presenter.plan) != context.inputs.documents["authority"]["candidatePlanHash"] \
            or canonical_hash(prepared.report) != report_hash \
            or context.held is not held or _caption_binding_hash(held) != held_hash \
            or context.coverage != authority["review"] or _caption_identities(held) != identities:
        raise RuntimeError("presenter caption picture original inputs or clearance changed")


def prepare_presenter_caption_picture(presenter: OpeningPresenterContext | None,
                                      captions: HeldCaptionProjection | None,
                                      authority: dict) -> PreparedPresenterCaptionPicture | None:
    """Inspect before encode; absent presenter and genuinely uncaptioned paths stay exact."""
    if presenter is None:
        return None
    if type(presenter) is not OpeningPresenterContext:
        raise RuntimeError("opening presenter context is malformed")
    plan = presenter.plan
    requested = "captionsTrack" in plan or (type(plan.get("captions")) is dict and plan["captions"].get("burn") is True)
    if captions is None and not requested:
        return None
    context = _context(presenter, captions, authority)
    caption_binding = (captions, _caption_binding_hash(captions), _caption_identities(captions))
    original = (authority, capture_input_binding(context.inputs), digest(authority), caption_binding)
    report = inspect_presenter_caption_clearance(context, presenter.owner.assert_current)
    prepared = PreparedPresenterCaptionPicture(context, presenter, report,
        (original[0], original[1], original[2], canonical_hash(report), original[3]))
    _unchanged(prepared)
    return prepared


def presenter_caption_picture_guard(prepared: PreparedPresenterCaptionPicture | None,
                                    guard: Callable[[], None]) -> Callable[[], None]:
    """Add only phase/encode-boundary checks, never a raw-observation hash per cue/frame."""
    if prepared is None:
        return guard

    def check() -> None:
        """Recheck live ownership first, then the held report and caption files."""
        guard()
        _unchanged(prepared)

    return check


def _picture_links(report: dict, pictures: dict) -> tuple[dict, dict, dict]:
    """Verify exact shared hash links; callers separately authenticate report and pixels."""
    if type(report) is not dict or report.get("kind") != "presenter-caption-clearance" \
            or report.get("policy") != POLICY or report.get("state") not in ("screened-no-overlap", "not-applicable") \
            or any(report.get(key) is not False for key in ("pictureProofBound", "qcPassed", "creativeApproved", "deliveryApproved")):
        raise RuntimeError("presenter caption picture needs its unchanged precomposition report")
    binding, layers, captions = report["binding"], pictures["presenterLayers"], pictures["captionLayers"]
    closed(captions, {"kind", "captionTail", "projectionHash", "combinedGraphHash", "pageIds"}, "presenter caption layers")
    graph, ranges = layers["graph"], pictures["ranges"]
    expected = {"candidatePlanHash": binding["candidatePlanHash"], "authorityHash": binding["authorityHash"],
                "fullPresenterGraphHash": binding["presenterGraphHash"], "pictureRangesHash": digest(ranges)}
    if any(layers.get(key) != value for key, value in expected.items()) \
            or layers["graphHash"] != canonical_hash(graph) or captions["projectionHash"] != binding["captionProjectionHash"] \
            or captions["combinedGraphHash"] != digest(graph["clips"]) or captions["captionTail"] != graph["captionTail"] \
            or {key: ranges["review"][key] for key in ("startFrame", "endFrameExclusive")} != binding["coverage"]:
        raise RuntimeError("presenter caption clearance does not bind the actual picture ranges and layers")
    return binding, layers, captions


def presenter_caption_picture_record(report: dict, pictures: dict) -> dict:
    """Pure shared hash projector; independently validated live or cold evidence is required."""
    binding, layers, captions = _picture_links(report, pictures)
    return {"schemaVersion": 1, "kind": "presenter-caption-picture-clearance-binding",
        "scope": "actual-opening-picture-bound-manual-envelope-not-qc-or-approval",
        "executionInputHash": binding["executionInputHash"], "candidatePlanHash": binding["candidatePlanHash"],
        "authorityHash": binding["authorityHash"], "coverage": deepcopy(binding["coverage"]),
        "captionProjectionHash": binding["captionProjectionHash"], "captionLayersHash": digest(captions),
        "pictureRangesHash": digest(pictures["ranges"]), "presenterLayersHash": digest(layers),
        "openingPresenterGraphHash": layers["graphHash"], "fullPresenterGraphHash": layers["fullPresenterGraphHash"],
        "precompositionReport": deepcopy(report), "precompositionReportHash": canonical_hash(report),
        "pictureEvidenceBound": True, "qcPassed": False, "creativeApproved": False, "deliveryApproved": False}


def finish_presenter_caption_picture(prepared: PreparedPresenterCaptionPicture | None,
                                     pictures: dict, guard: Callable[[], None]) -> dict | None:
    """Reinspect after actual range composition; preserve the original report unchanged."""
    if prepared is None:
        return None
    original = digest(pictures)
    guard()
    _unchanged(prepared)
    verify_presenter_caption_clearance(prepared.context, prepared.report, prepared.context.presenter.assert_current)
    guard()
    _unchanged(prepared)
    result = presenter_caption_picture_record(prepared.report, pictures)
    if digest(pictures) != original:
        raise RuntimeError("presenter caption picture evidence changed during final verification")
    _unchanged(prepared)
    return result
