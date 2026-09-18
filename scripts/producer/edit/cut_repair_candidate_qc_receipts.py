"""Build exact promotion-gate-compatible automated QC lane receipts."""
from __future__ import annotations

from edit.cut_repair_candidate_qc_media import (
    CandidateQcLaneBlocker,
    align,
)
from edit.cut_repair_candidate_qc_store import ReceiptStore
from edit.cut_repair_candidate_qc_types import QcRun
from edit.cut_repair_visual_lip_sync_contract import visual_seam_closure


def _common(run: QcRun, kind: str, status: str) -> dict:
    return {
        "schemaVersion": 1,
        "kind": kind,
        "status": status,
        "operationHash": run.authority.descriptor["operationHash"],
        "candidateCompositeSha256": run.authority.candidate_sha256,
    }


def blocked(code: str, message: str, method: str) -> dict:
    """Return one stable machine-readable lane blocker."""
    return {
        "status": "blocked",
        "method": method,
        "blocker": {"code": code, "message": message},
    }


def alignment_lane(
    run: QcRun,
    paths: tuple[str, str, str, str],
    store: ReceiptStore,
) -> dict:
    """Issue bounded source-waveform evidence from approved pinned bytes."""
    method = "deterministic-source-waveform-v1"
    try:
        observed = align(paths, run.authority, run.tools)
    except CandidateQcLaneBlocker as blocker:
        return blocked(blocker.code, blocker.message, method)
    if observed.occurrence_count != 1 \
            or not observed.source_span_boundary_match \
            or observed.best_score_ppm < observed.minimum_score_ppm \
            or observed.match_start_sample is None:
        return blocked(
            "ALIGNMENT_BOUNDARY_NOT_UNIQUE",
            "The independent waveform adapter did not locate exactly one "
            "complete transcript-bound source span.", method)
    tool = run.tools.aligner
    assert tool is not None
    receipt = {
        **_common(run, "cut-repair-alignment-qc", "bounded-pass"),
        "alignmentProtocol": tool.protocol,
        "evidenceSemantics":
            "transcript-bound-source-waveform-presence-not-audibility",
        "runtimeSha256": tool.runtime.sha256,
        "implementationSha256": tool.implementation.sha256,
        "policySha256": tool.policy.sha256,
        "sourceMediaSha256": run.authority.source_media_sha256,
        "candidateWaveSha256": observed.candidate_wave_sha256,
        "referenceWaveSha256": observed.reference_wave_sha256,
        "targetWordIds": list(run.authority.target_word_ids),
        "observedOccurrenceCount": 1,
        "sourceSpanBoundaryMatch": True,
        "bestScorePpm": observed.best_score_ppm,
        "minimumScorePpm": observed.minimum_score_ppm,
        "matchStartSampleInCandidateWindow": observed.match_start_sample,
        "boundaryToleranceSamples": observed.boundary_tolerance_samples,
        "referenceSampleCount": observed.reference_sample_count,
    }
    return store.passed("alignment", receipt, method)


def vad_lane(run: QcRun, waveform, store: ReceiptStore) -> dict:
    """Bind bounded program-waveform continuity to candidate bytes."""
    method = "bounded-program-waveform-envelope-v1"
    if waveform.unintended_gap_count:
        return blocked(
            "PROGRAM_WAVEFORM_GAP_DETECTED",
            "The bounded program waveform contains a >=150 ms low-energy gap.",
            method)
    receipt = {
        **_common(run, "cut-repair-vad-qc", "bounded-pass"),
        "runtimeSha256": waveform.runtime_sha256,
        "speechContinuityPassed": True,
        "unintendedSpeechGapCount": 0,
    }
    return store.passed("vad", receipt, method)


def retranscription_lane(run: QcRun, observed, store: ReceiptStore) -> dict:
    """Bind exactly one bounded target-phrase observation."""
    method = "bounded-whisper-cpu-v1"
    if observed.occurrence_count != 1:
        code = ("RETRANSCRIPTION_TARGET_MISSING"
                if observed.occurrence_count == 0
                else "RETRANSCRIPTION_TARGET_AMBIGUOUS")
        return blocked(
            code, "Pinned Whisper must observe the target phrase exactly "
            "once inside the bounded dirty window.", method)
    receipt = {
        **_common(run, "cut-repair-retranscription-qc", "bounded-pass"),
        "runtimeSha256": run.tools.whisper.sha256,
        "modelSha256": run.tools.whisper_model.sha256,
        "targetPhraseHash": observed.target_phrase_hash,
        "observedOccurrenceCount": 1,
        "wordOrderPreserved": observed.word_order_preserved,
    }
    return store.passed("retranscription", receipt, method)


def seam_lane(
    run: QcRun,
    waveform,
    store: ReceiptStore,
    visual: dict,
) -> dict:
    """Combine waveform seam checks with governed visual proof when required."""
    method = ("bounded-program-waveform-and-selected-source-av-v1"
              if run.authority.picture_dirty
              else "bounded-program-waveform-seams-v1")
    failed = [
        name for name, value in (
            ("click", waveform.click_free),
            ("duplicate", waveform.duplicate_free),
            ("room-tone", waveform.room_tone_continuous),
        ) if not value
    ]
    if failed:
        return blocked(
            "SEAM_WAVEFORM_CHECK_FAILED",
            f"Bounded seam checks failed: {','.join(failed)}.", method)
    visual_closure = {}
    lip_sync = "not-applicable-audio-only"
    if run.authority.picture_dirty:
        blocker = visual.get("blocker")
        if visual.get("status") == "blocked" and isinstance(blocker, dict):
            return blocked(
                str(blocker.get("code")), str(blocker.get("message")), method)
        receipt = visual.get("receipt")
        if visual.get("status") != "bounded-pass" \
                or not isinstance(receipt, dict):
            return blocked(
                "LIP_SYNC_ORACLE_UNAVAILABLE",
                "Picture-changing repair has no governed visual proof.",
                method)
        visual_closure = visual_seam_closure(receipt)
        lip_sync = "passed"
    receipt = {
        **_common(run, "cut-repair-seam-qc", "bounded-pass"),
        "runtimeSha256": waveform.runtime_sha256,
        "clickFree": True,
        "duplicateFree": True,
        "roomToneContinuous": True,
        "lipSyncDisposition": lip_sync,
        **visual_closure,
    }
    return store.passed("seam", receipt, method)


def run_manifest(run: QcRun, lanes: dict[str, dict]) -> dict:
    """Enclose automated lanes without manufacturing operator approval."""
    blocked_lanes = [lane for lane, value in lanes.items()
                     if value["status"] == "blocked"]
    window = run.authority.window
    return {
        "schemaVersion": 1,
        "kind": "cut-repair-automated-qc-run",
        "status": ("automated-qc-blocked" if blocked_lanes
                   else "automated-qc-passed"),
        "preparationHash": run.authority.preparation_hash,
        "candidateDescriptorHash":
            run.authority.package["reviewCandidateDescriptorHash"],
        "operationHash": run.authority.descriptor["operationHash"],
        "candidateCompositeSha256": run.authority.candidate_sha256,
        "toolManifestHash": run.tools.manifest_hash,
        "invocationHash": run.invocation_hash,
        "dirtyWindow": {
            "firstFrame": window.first_frame,
            "endFrameExclusive": window.end_frame_exclusive,
            "startSample": window.start_sample,
            "endSampleExclusive": window.end_sample_exclusive,
            "sampleRate": window.sample_rate,
        },
        "lanes": lanes,
        "operatorAuditionProduced": False,
    }
