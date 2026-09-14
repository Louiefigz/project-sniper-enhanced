"""One retained, measured full-program float master for delivery and excerpts."""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from audio.audio_mix_delivery import AUDIO_DELIVERY_POLICY_VERSION, measure_delivery
from audio.master import MASTERING_POLICY_VERSION
from audio.float_master import FloatMasterInput, render_float_master
from audio.music_stage import resolve_music_track
from audio.program_audio_clock import float_audio_clock
from audio.program_finish_bus import assert_finishing_stable, finishing_identity, verify_finishing
from audio.program_mix_bus import ProgramMix, build_program_mix
from audio.render_audio_authority import (SOURCE_FLOAT_POLICY_V2, audio_policy_reason,
                                          seal_audio_record)
from audio.render_audio_bus import SourceAudioBus, verify_source_bus
from cut_preview_io import bound_json, digest, file_hash
from producer_config import AUDIO_MIX_POLICY_VERSION


@dataclass(frozen=True)
class ProgramMaster:
    """Qualified full-program PCM; not an approval or independently mixed intro."""

    path: str
    directory: str
    receipt: dict
    source_bus: SourceAudioBus


def _mix_stable(mix: ProgramMix, bus: SourceAudioBus) -> None:
    """Bind the exact premaster and music inputs across mastering/measurement."""
    if file_hash(Path(mix.path)) != mix.sha256:
        raise RuntimeError("full-program premaster bytes changed")
    if mix.music and file_hash(Path(mix.music["path"])) != mix.music["sha256"]:
        raise RuntimeError("full-program music source bytes changed")
    if mix.music and resolve_music_track(mix.music["settings"], None, bus.admission.manifest_path) != mix.music["path"]:
        raise RuntimeError("full-program music manifest selection changed")
    assert_finishing_stable(mix.finishing)


def audio_program_input_hash(bus: SourceAudioBus, mix: ProgramMix) -> str:
    """Every full-program finishing/mix/master change invalidates dependent evidence."""
    music = ({key: value for key, value in mix.music.items() if key != "bedPath"}
             if mix.music else None)
    detector = ({key: value for key, value in mix.detector_reference.items() if key != "path"}
                if mix.detector_reference else None)
    return digest({"domain": "ordinary-full-program-master-input-v2",
        "sourceBusReceiptHash": bus.receipt["receiptHash"], "premasterSha256": mix.sha256,
        "music": music, "detectorReference": detector, "finishing": finishing_identity(mix.finishing),
        "masteringPolicyVersion": MASTERING_POLICY_VERSION,
        "audioDeliveryPolicyVersion": AUDIO_DELIVERY_POLICY_VERSION,
        "audioMixPolicyVersion": AUDIO_MIX_POLICY_VERSION,
        "tools": bus.admission.tools, "code": list(bus.admission.code)})


def _render_master(bus: SourceAudioBus, mix: ProgramMix, directory: Path) -> tuple[Path, str, str | None]:
    """Reuse shared mastering dispatch; materialize float once, with no AAC here."""
    float_audio_clock(mix.path, bus)
    source = FloatMasterInput(mix.path, bus.samples, mix.measured,
                              bus.admission.tools["ffmpeg"]["path"])
    return render_float_master(source, directory)


def build_program_master(bus: SourceAudioBus, plan: dict) -> ProgramMaster:
    """Retain an exact full master, refusing unqualified sound without promotion."""
    if bus.admission.policy != SOURCE_FLOAT_POLICY_V2:
        raise RuntimeError("full-program master requires new source-float-v2 authority")
    reason = audio_policy_reason(plan, SOURCE_FLOAT_POLICY_V2)
    if reason:
        raise RuntimeError(reason)   # the explicit finishing/policy reason, before any media work
    directory = Path(tempfile.mkdtemp(prefix=".program-master-v2-", dir=bus.directory))
    mix = build_program_mix(bus, plan, directory)
    _mix_stable(mix, bus)
    path, chain, note = _render_master(bus, mix, directory)
    before = file_hash(path)
    clock = float_audio_clock(str(path), bus)
    measured = measure_delivery(str(path))
    _mix_stable(mix, bus)
    verify_source_bus(bus, plan)
    if file_hash(path) != before or not measured["qualified"]:
        seal_audio_record(str(directory / "master-failed.json"), {"schemaVersion": 2,
            "kind": "ordinary-program-master-failed", "approved": False,
            "path": str(path), "measuredSha256": before, "measurement": measured})
        raise RuntimeError(f"full-program master unqualified; retained candidate: {path}; {measured}")
    body = {"schemaVersion": 2, "kind": "ordinary-program-master",
        "scope": "full-program-audio-not-delivery-approval", "audioClockPolicy": SOURCE_FLOAT_POLICY_V2,
        "sourceBusReceiptHash": bus.receipt["receiptHash"],
        "audioProgramInputHash": audio_program_input_hash(bus, mix),
        "masteringPolicyVersion": MASTERING_POLICY_VERSION,
        "audioDeliveryPolicyVersion": AUDIO_DELIVERY_POLICY_VERSION,
        "audioMixPolicyVersion": AUDIO_MIX_POLICY_VERSION,
        "frameRate": bus.frame_rate, "videoFrames": bus.frames, "totalSamples": bus.samples,
        "masteringFilter": chain, "masteringNote": note, "detectorReference": mix.detector_reference,
        "music": mix.music, "finishing": mix.finishing, "premaster": {"path": mix.path, "sha256": mix.sha256},
        "masteredAudio": {"path": str(path), "sha256": before, "sizeBytes": path.stat().st_size, **clock},
        "wholeProgramMeasurement": measured}
    receipt = seal_audio_record(str(directory / "master-receipt.json"), body)
    return ProgramMaster(str(path), str(directory), receipt, bus)


def verify_program_master(master: ProgramMaster, plan: dict) -> None:
    """Reobserve held exact receipts and bytes; a path/mtime never proves parity."""
    verify_source_bus(master.source_bus, plan)
    current = bound_json(Path(master.directory) / "master-receipt.json")
    if current != master.receipt or digest({key: value for key, value in current.items()
                                         if key != "receiptHash"}) != current["receiptHash"]:
        raise RuntimeError("full-program master receipt changed")
    if file_hash(Path(master.path)) != current["masteredAudio"]["sha256"]:
        raise RuntimeError("full-program master bytes changed")
    requested = plan.get("music") or {}
    expected = current["music"]["settings"] if current["music"] else None
    if (requested if requested.get("enabled") else None) != expected:
        raise RuntimeError("full-program master music settings changed")
    if current["music"] and file_hash(Path(current["music"]["path"])) != current["music"]["sha256"]:
        raise RuntimeError("full-program master music source changed")
    if current["music"] and resolve_music_track(expected, None,
            master.source_bus.admission.manifest_path) != current["music"]["path"]:
        raise RuntimeError("full-program master music manifest selection changed")
    verify_finishing(current["finishing"], master.source_bus, plan)
    float_audio_clock(master.path, master.source_bus)
