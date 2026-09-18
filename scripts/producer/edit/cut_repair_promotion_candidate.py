"""Immutable candidate and operation authority for cut-repair promotion."""
from __future__ import annotations

import os
from dataclasses import dataclass

from edit.cut_repair_candidate_qc_contract import load_candidate_authority
from edit.cut_repair_candidate_qc_types import CandidateAuthority
from edit.cut_repair_context_sources import (
    require_hash,
    require_keys,
    stable_file_digest,
    stable_json,
)

_RENDERED_KEYS = {
    "schemaVersion", "kind", "status", "operationHash",
    "reviewPlanObjectHash", "reviewPlanContentHash", "reviewTimelineMapHash",
    "reviewRenderGraphHash", "reviewRenderGraphReceiptHash",
    "reviewRenderGraphCandidatePointerHash", "candidatePath",
    "candidateSha256",
}


class PromotionGateError(ValueError):
    """A post-render receipt set cannot authorize candidate promotion."""


@dataclass(frozen=True)
class PromotionCandidate:
    """Candidate bytes plus immutable operation-kind authority."""

    operation_hash: str
    composite_sha256: str
    staging_root: str
    picture_dirty: bool
    selection_receipt_hash: str | None
    visual_binding: dict | None


def _visual_binding(authority: CandidateAuthority) -> dict:
    selected = authority.alternate_take_selection
    if not isinstance(selected, dict):
        raise PromotionGateError(
            "picture candidate has no alternate-take selection")
    frames = selected.get("outputFrameRange")
    region = selected.get("visualSpeechRegion")
    if not isinstance(frames, dict) or not isinstance(region, dict):
        raise PromotionGateError(
            "alternate-take output or visual region is absent")
    first = frames.get("firstFrame")
    end = frames.get("endFrameExclusive")
    if type(first) is not int or type(end) is not int:
        raise PromotionGateError("alternate-take output range is malformed")
    window = authority.window
    output_frames = {
        **frames,
        "fpsNumerator": window.fps_numerator,
        "fpsDenominator": window.fps_denominator,
    }
    output_samples = {
        "startSample": first * window.fps_denominator
        * window.sample_rate // window.fps_numerator,
        "endSampleExclusive": end * window.fps_denominator
        * window.sample_rate // window.fps_numerator,
        "sampleRate": window.sample_rate,
    }
    return {
        "preparationHash": authority.preparation_hash,
        "candidateSetHash": selected.get("candidateSetHash"),
        "selectionHash": selected.get("selectionHash"),
        "selectedCandidateId": selected.get("selectedCandidateId"),
        "sourceId": selected.get("sourceId"),
        "sourceMediaSha256": selected.get("sourceMediaSha256"),
        "sourceFrameRange": selected.get("sourceFrameRange"),
        "sourceSampleRange": selected.get("sourceSampleRange"),
        "outputFrameRange": output_frames,
        "outputSampleRange": output_samples,
        "visualSpeechRegionPpm": {
            "x": region.get("xPpm"), "y": region.get("yPpm"),
            "width": region.get("widthPpm"), "height": region.get("heightPpm"),
        },
    }


def inside_staging(path: str, root: str, label: str) -> str:
    """Require one canonical path below cut-repair staging."""
    lexical = os.path.abspath(path)
    resolved = os.path.realpath(lexical)
    if lexical != path or resolved != path \
            or os.path.commonpath([root, resolved]) != root:
        raise PromotionGateError(
            f"{label} is outside canonical cut-repair staging")
    return resolved


def _media(candidate: dict, root: str) -> tuple[str, str]:
    media_path = candidate.get("candidatePath")
    expected = require_hash(
        candidate.get("candidateSha256"), "rendered candidate media hash")
    if not isinstance(media_path, str):
        raise PromotionGateError("rendered candidate media path is absent")
    inside_staging(media_path, root, "rendered candidate media")
    if stable_file_digest(media_path, "rendered candidate media") != expected:
        raise PromotionGateError("rendered candidate media bytes are stale")
    return media_path, expected


def _rendered(
    producer: str,
    candidate_path: str,
    candidate: dict,
    preparation_hash: str | None,
) -> PromotionCandidate:
    if not isinstance(preparation_hash, str):
        raise PromotionGateError(
            "rendered candidate promotion requires preparation authority")
    authority = load_candidate_authority(producer, preparation_hash)
    require_keys(candidate, _RENDERED_KEYS, _RENDERED_KEYS,
                 "rendered-plan candidate")
    expected = (1, "cut-repair-rendered-plan-candidate", "candidate-proved")
    observed = (
        candidate.get("schemaVersion"), candidate.get("kind"),
        candidate.get("status"))
    if observed != expected or candidate != authority.descriptor \
            or candidate_path != authority.package.get(
                "reviewCandidateDescriptorPath"):
        raise PromotionGateError(
            "rendered candidate is not bound to preparation authority")
    for name in (
            "operationHash", "reviewPlanObjectHash", "reviewPlanContentHash",
            "reviewTimelineMapHash", "reviewRenderGraphHash",
            "reviewRenderGraphReceiptHash",
            "reviewRenderGraphCandidatePointerHash"):
        require_hash(candidate.get(name), f"candidate {name}")
    root = os.path.realpath(os.path.join(
        producer, ".sniper-cut-repair-staging"))
    _, media_hash = _media(candidate, root)
    return PromotionCandidate(
        candidate["operationHash"], media_hash, root,
        authority.picture_dirty, authority.alternate_take_selection_hash,
        _visual_binding(authority) if authority.picture_dirty else None)


def _legacy(candidate: dict, root: str) -> PromotionCandidate:
    operation = require_hash(
        candidate.get("operationHash"), "candidate operation hash")
    if candidate.get("schemaVersion") != 1 \
            or candidate.get("kind") != "cut-repair-candidate" \
            or candidate.get("status") != "candidate-proved":
        raise PromotionGateError("candidate is not Python-proved")
    fragment = candidate.get("fragmentReceipt")
    if not isinstance(fragment, dict) \
            or fragment.get("operationHash") != operation \
            or fragment.get("method") != "audio-lj-overlap":
        raise PromotionGateError(
            "legacy promotion is limited to bound audio-only repairs")
    composite = candidate.get("compositeReceipt")
    if not isinstance(composite, dict):
        raise PromotionGateError("candidate has no composite receipt")
    output = composite.get("output")
    if not isinstance(output, dict) or composite.get(
            "operationHash") != operation:
        raise PromotionGateError("composite receipt is not candidate-bound")
    media_path = output.get("path")
    expected = require_hash(output.get("sha256"), "candidate composite hash")
    if not isinstance(media_path, str):
        raise PromotionGateError("candidate composite path is absent")
    inside_staging(media_path, root, "candidate composite")
    if stable_file_digest(media_path, "candidate composite") != expected:
        raise PromotionGateError("candidate composite bytes are stale")
    return PromotionCandidate(operation, expected, root, False, None, None)


def load_promotion_candidate(
    producer: str,
    candidate_path: str,
    preparation_hash: str | None,
) -> PromotionCandidate:
    """Reopen candidate bytes and derive picture status from authority."""
    staging = os.path.join(producer, ".sniper-cut-repair-staging")
    root = os.path.realpath(staging)
    inside_staging(candidate_path, root, "candidate receipt")
    candidate, _ = stable_json(candidate_path, "cut repair candidate")
    if candidate.get("kind") == "cut-repair-rendered-plan-candidate":
        return _rendered(
            producer, candidate_path, candidate, preparation_hash)
    if preparation_hash is not None:
        raise PromotionGateError(
            "legacy candidate cannot substitute preparation authority")
    return _legacy(candidate, root)
