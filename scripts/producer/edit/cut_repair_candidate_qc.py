#!/usr/bin/env python3
"""Produce candidate-bound automated QC receipts for a prepared full plan."""
from __future__ import annotations

import argparse
import json
import os
import tempfile

from edit.cut_repair_candidate_qc_contract import load_candidate_authority
from edit.cut_repair_candidate_qc_bundle import (
    load_automated_qc_bundle,
    persist_automated_qc_bundle,
)
from edit.cut_repair_candidate_qc_media import (
    target_document,
    transcribe,
)
from edit.cut_repair_candidate_qc_receipts import (
    alignment_lane,
    retranscription_lane,
    run_manifest,
    seam_lane,
    vad_lane,
)
from edit.cut_repair_candidate_qc_store import (
    ReceiptStore,
    create_qc_run,
    publish_lanes,
    publish_json,
)
from edit.cut_repair_candidate_qc_tools import (
    load_qc_tools,
    reobserve_tools,
)
from edit.cut_repair_candidate_qc_types import (
    CandidateQcContractError,
)
from edit.cut_repair_candidate_qc_visual import visual_observation
from edit.cut_repair_candidate_qc_waveform import (
    extract_dirty_wave,
    extract_source_target_wave,
    waveform_observation,
)
from edit.cut_repair_context_sources import (
    canonical_bytes,
    stable_file_digest,
)


def _implementation_hash() -> str:
    return stable_file_digest(
        os.path.realpath(__file__), "candidate QC controller implementation")


def _write_temp_json(path: str, value: dict) -> None:
    with open(path, "xb") as stream:
        stream.write(canonical_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


def _observe(run, work: str) -> dict[str, dict]:
    wave_path = os.path.join(work, "dirty-window.wav")
    reference_path = os.path.join(work, "source-target.wav")
    target_path = os.path.join(work, "alignment-target.json")
    alignment_path = os.path.join(work, "alignment-observation.json")
    transcript_prefix = os.path.join(work, "whisper-observation")
    extract_dirty_wave(run.authority, run.tools, wave_path)
    extract_source_target_wave(
        run.authority, run.tools, reference_path)
    wave_hashes = (
        stable_file_digest(wave_path, "candidate alignment WAV"),
        stable_file_digest(reference_path, "reference alignment WAV"),
    )
    _write_temp_json(
        target_path, target_document(run.authority, wave_hashes))
    waveform = waveform_observation(wave_path, run.authority, run.tools)
    transcript = transcribe(
        wave_path, transcript_prefix, run.authority, run.tools)
    visual = visual_observation(run)
    store = ReceiptStore(run)
    return {
        "alignment": alignment_lane(
            run, (
                wave_path, reference_path, target_path, alignment_path),
            store),
        "vad": vad_lane(run, waveform, store),
        "retranscription": retranscription_lane(run, transcript, store),
        "seam": seam_lane(run, waveform, store, visual),
    }


def run_candidate_qc(
    producer: str,
    preparation_hash: str,
    tool_manifest_path: str,
) -> dict:
    """Produce immutable automated receipts; never create operator approval."""
    authority = load_candidate_authority(producer, preparation_hash)
    tools = load_qc_tools(authority.producer, tool_manifest_path)
    run = create_qc_run(authority, tools, _implementation_hash())
    with tempfile.TemporaryDirectory(
            prefix=".candidate-qc-", dir=os.path.dirname(run.directory)) as work:
        lanes = _observe(run, work)
    reobserve_tools(tools)
    reopened = load_candidate_authority(producer, preparation_hash)
    if reopened != authority:
        raise CandidateQcContractError(
            "candidate authority changed during automated QC")
    lanes = publish_lanes(run, lanes)
    blockers = {
        lane: value["blocker"] for lane, value in lanes.items()
        if value["status"] == "blocked"
    }
    bundle = None if blockers else persist_automated_qc_bundle(run, lanes)
    manifest = run_manifest(run, lanes)
    manifest_path = os.path.join(run.directory, "automated-qc.json")
    manifest_hash = publish_json(manifest_path, manifest)
    result = {
        "ok": not blockers,
        "status": manifest["status"],
        "manifestHash": manifest_hash,
        "manifestPath": manifest_path,
        "qcDirectory": run.directory,
        "blockers": blockers,
        "operatorAuditionProduced": False,
        "preparationHash": authority.preparation_hash,
        "candidateDescriptorHash":
            authority.package["reviewCandidateDescriptorHash"],
        "operationHash": authority.descriptor["operationHash"],
        "candidateCompositeSha256": authority.candidate_sha256,
    }
    if bundle:
        value, bundle_hash, bundle_path = bundle
        result.update({
            "automatedQcBundleHash": bundle_hash,
            "automatedQcBundlePath": bundle_path,
            **{lane: value[lane] for lane in (
                "alignment", "vad", "retranscription", "seam")},
        })
    return result


def reopen_candidate_qc(producer: str, preparation_hash: str) -> dict:
    """Return the immutable passing bundle without running any observer."""
    value, bundle_hash, bundle_path = load_automated_qc_bundle(
        producer, preparation_hash)
    return {
        "ok": True,
        "status": "automated-qc-passed",
        "preparationHash": preparation_hash,
        "candidateDescriptorHash": value["candidateDescriptorHash"],
        "operationHash": value["operationHash"],
        "candidateCompositeSha256": value["candidateCompositeSha256"],
        "automatedQcBundleHash": bundle_hash,
        "automatedQcBundlePath": bundle_path,
        **{lane: value[lane] for lane in (
            "alignment", "vad", "retranscription", "seam")},
        "operatorAuditionProduced": False,
    }


def _run_args(args: argparse.Namespace) -> dict:
    producer = os.path.abspath(args.producer_dir)
    if args.reopen:
        return reopen_candidate_qc(producer, args.preparation_hash)
    if args.tool_manifest_path:
        return run_candidate_qc(
            producer, args.preparation_hash,
            os.path.abspath(args.tool_manifest_path))
    raise ValueError("tool_manifest_path is required unless --reopen")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("producer_dir")
    parser.add_argument("preparation_hash")
    parser.add_argument("tool_manifest_path", nargs="?")
    parser.add_argument("--reopen", action="store_true")
    args = parser.parse_args()
    try:
        result = _run_args(args)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        message = str(exc)
        code = ("TOOL_DRIFT" if "TOOL_DRIFT" in message
                else "CANDIDATE_QC_INPUT_REJECTED")
        print(json.dumps({
            "ok": False, "status": "candidate-qc-rejected",
            "blocker": {"code": code, "message": message},
        }, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
