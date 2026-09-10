"""Closed receipt projection for selected-source visual lip-sync evidence."""
from __future__ import annotations

import hashlib
from typing import Sequence

from edit.cut_repair_context_sources import digest
from edit.cut_repair_visual_lip_sync_types import (
    DecodedEvidence,
    OracleRequest,
)


def _trace_hash(rows: Sequence[bytes] | Sequence[int]) -> str:
    value = hashlib.sha256()
    for row in rows:
        if isinstance(row, bytes):
            value.update(row)
        else:
            value.update(int(row).to_bytes(2, "little", signed=True))
    return value.hexdigest()


def _ranges(request: OracleRequest) -> dict:
    value = request.selection
    return {
        "sourceFrameRange": {
            "firstFrame": value.source_frames.first,
            "endFrameExclusive": value.source_frames.end_exclusive,
            "fpsNumerator": value.source_rate.numerator,
            "fpsDenominator": value.source_rate.denominator,
        },
        "sourceSampleRange": {
            "startSample": value.source_samples.start,
            "endSampleExclusive": value.source_samples.end_exclusive,
            "sampleRate": value.source_samples.rate,
        },
        "outputFrameRange": {
            "firstFrame": value.output_frames.first,
            "endFrameExclusive": value.output_frames.end_exclusive,
            "fpsNumerator": value.output_rate.numerator,
            "fpsDenominator": value.output_rate.denominator,
        },
        "outputSampleRange": {
            "startSample": value.output_samples.start,
            "endSampleExclusive": value.output_samples.end_exclusive,
            "sampleRate": value.output_samples.rate,
        },
    }


def _bindings(request: OracleRequest) -> dict:
    selected = request.selection
    return {
        "preparationHash": selected.preparation_hash,
        "operationHash": selected.operation_hash,
        "candidateCompositeSha256": request.candidate.sha256,
        "alternateTakeSelectionReceiptHash": selected.receipt_hash,
        "candidateSetHash": selected.candidate_set_hash,
        "selectionHash": selected.selection_hash,
        "selectedCandidateId": selected.selected_candidate_id,
        "sourceId": selected.source_id,
        "sourceMediaSha256": selected.source_sha256,
        **_ranges(request),
        "visualSpeechRegionPpm": {
            "x": selected.visual_region.x,
            "y": selected.visual_region.y,
            "width": selected.visual_region.width,
            "height": selected.visual_region.height,
        },
    }


def _toolchain(request: OracleRequest, policy: dict) -> dict:
    return {
        "toolManifestHash": request.tool_manifest_hash,
        "ffmpegSha256": request.tools.ffmpeg_sha256,
        "runtimeSha256": request.tools.runtime_sha256,
        "implementationSha256": request.tools.implementation_sha256,
        "implementationScope": request.tools.implementation_scope,
        "implementationNonClaims":
            list(request.tools.implementation_nonclaims),
        "implementationClosureHash":
            request.tools.implementation_closure_hash,
        "implementationFileHashes": [
            {"role": role, "sha256": value_hash}
            for role, _, value_hash in request.tools.implementation_files
        ],
        "policySha256": request.tools.policy_sha256,
        "policyHash": digest(policy),
    }


def _traces(evidence: DecodedEvidence) -> dict:
    return {
        "sourceVisualTraceSha256": _trace_hash(evidence.source_frames),
        "candidateVisualTraceSha256": _trace_hash(evidence.candidate_frames),
        "sourcePcmSha256": _trace_hash(evidence.source_pcm),
        "candidatePcmSha256": _trace_hash(evidence.candidate_pcm),
    }


def build_visual_receipt(
    request: OracleRequest,
    evidence: DecodedEvidence,
    policy: dict,
    measurements: dict,
) -> dict:
    """Project only exact authority, tool, trace, and measured-offset facts."""
    return {
        "schemaVersion": 1,
        "kind": "cut-repair-visual-lip-sync-qc",
        "status": "bounded-pass",
        "protocol": policy["protocol"],
        "evidenceSemantics":
            "caller-supplied-roi-source-av-temporal-mapping-"
            "not-face-mouth-or-phoneme-proof",
        **_bindings(request),
        **_toolchain(request, policy),
        **_traces(evidence),
        **measurements,
        "maximumMappingOffsetFrames": policy["maximumMappingOffsetFrames"],
        "maximumAvOffsetFrames": policy["maximumAvOffsetFrames"],
        "lipSyncDisposition": "passed",
    }
