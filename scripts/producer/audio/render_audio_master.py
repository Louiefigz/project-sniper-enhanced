"""Ordinary final picture plus measured float audio, encoded to AAC only once."""
from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

from audio.audio_mix_delivery import _observe_final_audio, render_qualified_mix
from audio.audio_mix_picture import observe_picture_source, verify_picture_copy
from audio.program_audio_clock import aac_audio_clock as _audio_clock
from audio.master import (MASTERING_POLICY_VERSION, MasterSpec, select_pass2_filter,
                          encode_picture_only, finalize_master)
from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2, run_audio, seal_audio_record
from audio.render_audio_bus import SourceAudioBus, verify_source_bus
from fingerprints import file_sha256
from producer_config import ENCODE
from guided_source_color_consumption_hooks import (
    capture_master, check_master_inputs, check_master_publication,
    finish_master_consumption, observe_master_consumption, prepare_master_publication,
)
from guided_source_color_consumption_publication import retain_publication, complete_publication


def _encode_audio(candidate: str, context: tuple) -> dict:
    """Copy the completed picture's exact native clock while mastering float."""
    spec, bus, plan, picture = context
    try:
        verify_source_bus(bus, plan)
        measured, code, error = _observe_final_audio(bus.path)
        if code or measured is None:
            raise RuntimeError("source-float premaster full decode failed: " + error)
        selected = select_pass2_filter(bus.path, None, measured)
        # Compensated mastering must preserve the held sample count. Trim only
        # oversampling-filter flush; no `async` or guessed AAC priming removal.
        audio_filter = f"{selected.chain},aresample=48000,atrim=end_sample={bus.samples},asetpts=PTS-STARTPTS"
        run_audio([bus.admission.tools["ffmpeg"]["path"], "-nostdin", "-v", "error", "-xerror",
            "-err_detect", "explode", "-n", "-i", picture.path, "-i", bus.path,
            "-map", "0:v:0", "-c:v", "copy", "-map", "1:a:0", "-af", audio_filter,
            "-c:a", "aac", "-b:a", ENCODE["audio_bitrate"], "-ar", "48000", "-ac", "2",
            "-video_track_timescale", str(picture.time_base.denominator),
            "-movie_timescale", "48000", "-movflags", ENCODE["movflags"], candidate])
        proof = verify_picture_copy(picture, candidate)
        clock = _audio_clock(candidate, bus)
        verify_source_bus(bus, plan)
        return {"ok": True, "stderr": "", "mastering_note": selected.note, "filter": audio_filter,
                "mastering_decision": selected.evidence,
                "mastering_policy_version": MASTERING_POLICY_VERSION,
                "picture": proof, "audioClock": clock}
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
        return {"ok": False, "stderr": str(exc), "mastering_note": None,
                "mastering_policy_version": MASTERING_POLICY_VERSION}


def _master_picture(spec: MasterSpec, bus: SourceAudioBus, context: tuple) -> object:
    """Retain original spec, actual picture-only encode and its existing observed packets."""
    picture_guard, consumption = context
    check_master_inputs(consumption)
    picture_path = str(Path(bus.directory) / "picture-master.mp4")
    picture_spec = replace(spec, out=picture_path, cover=None)
    encoded = encode_picture_only(picture_spec) if picture_guard is None else encode_picture_only(picture_spec, picture_guard)
    if not encoded["ok"]:
        raise RuntimeError("source-float picture master failed: " + encoded["stderr"])
    picture = observe_picture_source(picture_path, float(Fraction(bus.frames, 1) / Fraction(bus.frame_rate)))
    observe_master_consumption(consumption, picture)
    return picture


def master_source_bus(spec: MasterSpec, bus: SourceAudioBus, plan: dict,
                      picture_guard: Callable[[], None] | None = None) -> dict:
    """Keep failed owned publication sticky without changing absent-recorder behavior."""
    consumption = capture_master(spec, picture_guard)
    if consumption is None:
        return _master_source_bus(spec, bus, plan, (picture_guard, None))
    try:
        return _master_source_bus(spec, bus, plan, (picture_guard, consumption))
    except BaseException:
        consumption.recorder.failed()
        raise


def _master_source_bus(spec: MasterSpec, bus: SourceAudioBus, plan: dict, context: tuple) -> dict:
    """Use ordinary picture settings, then promote only qualified exact-clock AAC."""
    picture_guard, consumption = context
    if picture_guard is not None:
        picture_guard()
    verify_source_bus(bus, plan)
    if spec.frame_count != bus.frames:
        raise RuntimeError("source-float final picture no longer matches executed cut frames")
    picture = _master_picture(spec, bus, (picture_guard, consumption))
    result = render_qualified_mix(spec.out, lambda candidate: _encode_audio(candidate, (spec, bus, plan, picture)))
    if not result["ok"]:
        failure = {"schemaVersion": 1, "kind": "ordinary-source-float-master-failed",
                   "audioClockPolicy": bus.admission.policy, "busReceiptHash": bus.receipt["receiptHash"],
                   "result": result, "approved": False}
        seal_audio_record(str(Path(bus.directory) / "master-failed.json"), failure)
        raise RuntimeError("source-float final unqualified; prior output preserved: " + result["stderr"])
    if picture_guard is not None:
        picture_guard()
    if consumption is not None:
        finish_master_consumption(consumption, picture, result["picture"])
    receipt_path = str(Path(bus.directory) / "master-receipt.json")
    payload = {
        "schemaVersion": 2 if bus.admission.policy == SOURCE_FLOAT_POLICY_V2 else 1,
        "kind": "ordinary-source-float-master", "approved": False,
        "audioClockPolicy": bus.admission.policy, "busReceiptHash": bus.receipt["receiptHash"],
        "masteringPolicyVersion": MASTERING_POLICY_VERSION, "planHash": bus.admission.plan_hash,
        "path": os.path.abspath(spec.out), "sha256": file_sha256(spec.out),
        "picture": result["picture"], "audioClock": result["audioClock"],
        "filter": result["filter"], "delivery": result["delivery"],
        "audiblePathAacEncodes": 1, "legacyPictureTransportAacStillExecuted": True}
    prepare_master_publication(consumption, receipt_path, payload)
    if picture_guard is not None:
        picture_guard()
    if consumption is not None:
        check_master_publication(consumption, picture, result["picture"])
    receipt = seal_audio_record(receipt_path, payload)
    if consumption is not None:
        retain_publication(consumption.recorder, receipt)
    completed = _completed_master(spec, result, (bus, receipt))
    if consumption is not None:
        complete_publication(consumption.recorder, completed)
    if picture_guard is not None:
        picture_guard()
    if consumption is not None:
        check_master_publication(consumption, picture, result["picture"])
    return completed


def _completed_master(spec: MasterSpec, result: dict, context: tuple) -> dict:
    """Keep the existing finalizer/return bytes while retaining original publication separately."""
    bus, receipt = context
    warnings = [result["mastering_note"]] if result["mastering_note"] else []
    return {**finalize_master(spec, warnings), "audio_clock_policy": bus.admission.policy,
            "mastering_decision": result["mastering_decision"],
            "source_audio_receipt": str(Path(bus.directory) / "master-receipt.json"),
            "source_audio_receipt_hash": receipt["receiptHash"], "delivery": result["delivery"]}
