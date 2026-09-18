"""Strict retained full-program master read path, without granting approval."""
from __future__ import annotations

from pathlib import Path

from audio.audio_mix_delivery import AUDIO_DELIVERY_POLICY_VERSION
from audio.master import MASTERING_POLICY_VERSION
from audio.program_finish_bus import validate_finishing_record
from audio.program_master_bus import ProgramMaster, audio_program_input_hash, verify_program_master
from audio.program_mix_bus import ProgramMix
from audio.render_audio_bus import SourceAudioBus
from audio.render_audio_cache import _inside
from cut_preview_io import bound_json, file_hash
from producer_config import AUDIO_MIX_POLICY_VERSION

_KEYS = {"schemaVersion", "kind", "scope", "audioClockPolicy", "sourceBusReceiptHash",
    "audioProgramInputHash", "masteringPolicyVersion", "audioDeliveryPolicyVersion", "frameRate",
    "videoFrames", "totalSamples", "masteringFilter", "masteringNote", "detectorReference", "music",
    "premaster", "masteredAudio", "wholeProgramMeasurement", "receiptHash", "audioMixPolicyVersion",
    "finishing"}
_AUDIO_KEYS = {"path", "sha256", "sizeBytes", "codec", "sampleFormat", "sampleRate", "channels",
               "startPts", "timeBase", "samples"}


def _bound_artifact(value: dict, bus: SourceAudioBus) -> Path:
    """No media path may escape the selected retained source-bus generation."""
    path = _inside(value.get("path"), Path(bus.directory))
    if file_hash(path) != value.get("sha256"):
        raise RuntimeError("program master retained artifact bytes changed")
    return path


def _validate_record(record: dict, bus: SourceAudioBus) -> None:
    """Validate exact role/clock/policy fields, not just a self-computable digest."""
    expected = {"schemaVersion": 2, "kind": "ordinary-program-master",
        "scope": "full-program-audio-not-delivery-approval", "audioClockPolicy": "source-float-v2",
        "sourceBusReceiptHash": bus.receipt["receiptHash"], "frameRate": bus.frame_rate,
        "videoFrames": bus.frames, "totalSamples": bus.samples,
        "masteringPolicyVersion": MASTERING_POLICY_VERSION,
        "audioDeliveryPolicyVersion": AUDIO_DELIVERY_POLICY_VERSION,
        "audioMixPolicyVersion": AUDIO_MIX_POLICY_VERSION}
    if set(record) != _KEYS or any(record[key] != value for key, value in expected.items()):
        raise RuntimeError("program master role, sample clock or policy is stale")
    audio = record["masteredAudio"]
    if type(audio) is not dict or set(audio) != _AUDIO_KEYS \
            or audio["samples"] != bus.samples or audio["sampleRate"] != 48000 \
            or audio["channels"] != 2 or audio["startPts"] != 0 or audio["timeBase"] != "1/48000" \
            or audio["codec"] != "pcm_f32le" or audio["sampleFormat"] != "flt":
        raise RuntimeError("program master float clock metadata is malformed")
    path = _bound_artifact(audio, bus)
    if audio["sizeBytes"] != path.stat().st_size:
        raise RuntimeError("program master retained audio size changed")
    if type(record["premaster"]) is not dict or set(record["premaster"]) != {"path", "sha256"}:
        raise RuntimeError("program premaster identity is malformed")
    _bound_artifact(record["premaster"], bus)


def _validate_mix(record: dict, bus: SourceAudioBus) -> None:
    """Retain every mix input and bind the same new-version input domain."""
    music, detector, finishing = record["music"], record["detectorReference"], record["finishing"]
    if finishing is not None:
        validate_finishing_record(finishing, bus, lambda value: _bound_artifact(value, bus))
    program = {"path": bus.path, "sha256": bus.sha256} if finishing is None else finishing["program"]
    if music is None:
        if detector is not None or record["premaster"] != program:
            raise RuntimeError("plain program master no longer uses its dialogue program")
    else:
        _bound_artifact({"path": music.get("bedPath"), "sha256": music.get("bedSha256")}, bus)
    if detector is not None:
        _bound_artifact(detector, bus)
        if detector.get("appliedTo") != "sidechain-only":
            raise RuntimeError("program detector is not a sidechain-only reference")
    mix = ProgramMix(record["premaster"]["path"], record["premaster"]["sha256"], music, detector, {}, finishing)
    if audio_program_input_hash(bus, mix) != record["audioProgramInputHash"]:
        raise RuntimeError("program master exact mix input hash changed")


def load_program_master(bus: SourceAudioBus, plan: dict, selection: tuple[str, str]) -> ProgramMaster:
    """Read a selected generation; caller must bind selection to execution/graph authority."""
    receipt_path, expected_hash = selection
    path = _inside(receipt_path, Path(bus.directory))
    if path.name != "master-receipt.json":
        raise RuntimeError("program master receipt name is not owned")
    record = bound_json(path)
    if record.get("receiptHash") != expected_hash:
        raise RuntimeError("program master receipt does not match held execution authority")
    _validate_record(record, bus)
    _validate_mix(record, bus)
    master = ProgramMaster(record["masteredAudio"]["path"], str(path.parent), record, bus)
    verify_program_master(master, plan)
    return master
