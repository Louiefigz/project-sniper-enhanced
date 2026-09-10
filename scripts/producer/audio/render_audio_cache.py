"""Exact retained source-float v2 authority across ordinary base/assemble runs."""
from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from typing import Protocol

from audio.render_audio_authority import (
    SOURCE_FLOAT_POLICY_V2, AudioAdmission, admit_audio, channel_authorities, run_audio,
)
from audio.render_audio_bus import SourceAudioBus, verify_source_bus
from cut_manifestation_authority import verify_manifestation
from cut_preview_io import bound_json, digest, file_hash, real_directory
from fingerprint_io import write_json_atomic

SOURCE_BUS_POINTER = "source_audio_bus.v2.json"
_POINTER_KEYS = {"schemaVersion", "kind", "audioClockPolicy", "receiptPath",
                 "receiptHash", "receiptFileSha256", "busSha256", "baseSha256"}
_RECEIPT_KEYS = {"schemaVersion", "kind", "audioClockPolicy", "planHash", "manifestHash",
    "sourceSetDigest", "cutManifestationHash", "sampleRate", "channels", "codec",
    "sampleFormat", "masteringApplied", "frameRate", "totalSamples", "videoFrames",
    "parts", "sourceFacts", "channelReceipts", "path", "sha256", "tools", "code",
    "audioInputHash", "manifestSourceHash", "receiptHash"}
_PART_KEYS = {"index", "sourceId", "srcStart", "srcEnd", "speed", "nextAudioLeadS",
    "videoFrames", "startSample", "endSample", "quantizationFitSamples", "path", "sha256"}


class _PcmDigest(Protocol):
    """Only the streaming digest operation needed by ordered PCM verification."""

    def update(self, data: bytes) -> None:
        """Append exact bytes to the digest."""


def _hash(value: object) -> str:
    """Reject noncanonical hashes before they become cache authority."""
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise RuntimeError("source-float cache hash is malformed")
    return value


def _inside(value: object, root: Path) -> Path:
    """Allow only an exact retained artifact below this ordinary output root."""
    if type(value) is not str:
        raise RuntimeError("source-float cache path is missing")
    path = Path(value)
    if not path.is_absolute() or path.resolve(strict=True) != path or not path.is_relative_to(root):
        raise RuntimeError("source-float cache artifact escaped its output root")
    real_directory(path.parent)
    return path


def write_source_bus_pointer(base: str, directory: str, bus: SourceAudioBus,
                             picture_guard: Callable[[], None] | None = None) -> dict:
    """Select a real immutable bus only after its matching base has completed."""
    if bus.admission.policy != SOURCE_FLOAT_POLICY_V2:
        raise RuntimeError("only a new v2 source bus may become reusable")
    root = Path(directory).resolve(strict=True)
    receipt_path = _inside(str(Path(bus.directory) / "bus-receipt.json"), root)
    receipt = bound_json(receipt_path)
    if receipt != bus.receipt or file_hash(Path(bus.path)) != bus.sha256:
        raise RuntimeError("source-float bus changed before pointer publication")
    pointer = {"schemaVersion": 2, "kind": "ordinary-source-float-pointer",
        "audioClockPolicy": SOURCE_FLOAT_POLICY_V2, "receiptPath": str(receipt_path),
        "receiptHash": receipt["receiptHash"], "receiptFileSha256": file_hash(receipt_path),
        "busSha256": bus.sha256, "baseSha256": file_hash(Path(base).absolute())}
    pointer_path = str(root / SOURCE_BUS_POINTER)
    if picture_guard is not None:
        picture_guard()
    write_json_atomic(pointer_path, pointer)
    return pointer


def _read_pointer(root: Path, base: str) -> tuple[dict, dict]:
    """The selected exact base bytes, never a matching filename, authorize reuse."""
    pointer = bound_json(root / SOURCE_BUS_POINTER)
    if set(pointer) != _POINTER_KEYS or pointer["schemaVersion"] != 2 \
            or pointer["kind"] != "ordinary-source-float-pointer" \
            or pointer["audioClockPolicy"] != SOURCE_FLOAT_POLICY_V2:
        raise RuntimeError("source-float pointer is malformed or predates v2")
    for key in ("receiptHash", "receiptFileSha256", "busSha256", "baseSha256"):
        _hash(pointer[key])
    if file_hash(Path(base).absolute()) != pointer["baseSha256"]:
        raise RuntimeError("source-float pointer does not bind the current base")
    receipt_path = _inside(pointer["receiptPath"], root)
    return pointer, bound_json(receipt_path, pointer["receiptFileSha256"])


def _validate_receipt(receipt: dict, pointer: dict, admission: AudioAdmission, plan: dict) -> None:
    """Separate immutable full-origin provenance from the new exact reuse domain."""
    if set(receipt) != _RECEIPT_KEYS or receipt["schemaVersion"] != 2 \
            or receipt["kind"] != "ordinary-source-float-bus" \
            or receipt["audioClockPolicy"] != SOURCE_FLOAT_POLICY_V2 \
            or receipt["masteringApplied"] is not False:
        raise RuntimeError("source-float receipt is not an unmastered v2 bus")
    if digest({key: value for key, value in receipt.items() if key != "receiptHash"}) != receipt["receiptHash"] \
            or receipt["receiptHash"] != pointer["receiptHash"] or receipt["sha256"] != pointer["busSha256"]:
        raise RuntimeError("source-float receipt/media identity changed")
    expected = {"audioInputHash": admission.audio_input_hash, "manifestSourceHash": admission.manifest_source_hash,
        "sourceSetDigest": admission.source_set_digest, "sourceFacts": list(admission.sources),
        "tools": admission.tools, "code": list(admission.code), "sampleRate": 48000,
        "channels": 2, "codec": "pcm_f32le", "sampleFormat": "flt"}
    if any(receipt[key] != value for key, value in expected.items()):
        raise RuntimeError("source-float consumed inputs or runtime authority changed")
    for key in ("planHash", "manifestHash", "cutManifestationHash", "audioInputHash", "manifestSourceHash"):
        _hash(receipt[key])
    channels = channel_authorities(admission, receipt["channelReceipts"])
    used = {row["sourceId"] for row in plan["cutTrack"]}
    required = {row["path"] for row in admission.sources if row["id"] in used and row["audioStreamIndex"] is not None}
    if set(channels) != required:
        raise RuntimeError("source-float cached channel receipts do not exactly cover audible cut sources")


def _validate_parts(receipt: dict, context: tuple[Path, dict, dict]) -> None:
    """Require exact cut/frame/sample coverage and every retained float part."""
    root, plan, manifestation = context
    parts = receipt["parts"]
    if type(parts) is not list or len(parts) != len(manifestation["parts"]):
        raise RuntimeError("source-float cached parts do not cover the cut")
    rate, frames, sample = Fraction(manifestation["frameRate"]), 0, 0
    for index, (part, sealed) in enumerate(zip(parts, manifestation["parts"])):
        if type(part) is not dict or set(part) != _PART_KEYS:
            raise RuntimeError("source-float cached part is malformed")
        frames += sealed["partFrames"]
        end = round(Fraction(frames * 48000, 1) / rate)
        following = plan["cutTrack"][index + 1] if index + 1 < len(parts) else {}
        expected = {"index": index, "sourceId": sealed["sourceId"], "srcStart": sealed["srcStart"],
            "srcEnd": sealed["srcEnd"], "speed": sealed["speed"], "videoFrames": sealed["partFrames"],
            "startSample": sample, "endSample": end, "nextAudioLeadS": following.get("audioLeadMs", 0) / 1000}
        if any(part[key] != value for key, value in expected.items()):
            raise RuntimeError("source-float cached source/frame/sample window changed")
        artifact = _inside(part["path"], root)
        if artifact.stat().st_size != (end - sample) * 8 or file_hash(artifact) != _hash(part["sha256"]):
            raise RuntimeError("source-float cached part bytes changed")
        if type(part["quantizationFitSamples"]) is not int \
                or abs(part["quantizationFitSamples"]) > -(-48000 // rate) + 1:
            raise RuntimeError("source-float cached frame adjustment is unproved")
        sample = end
    if receipt["totalSamples"] != sample or receipt["videoFrames"] != frames \
            or receipt["frameRate"] != manifestation["frameRate"]:
        raise RuntimeError("source-float cached aggregate clock changed")


def _append_pcm_hash(path: Path, combined: _PcmDigest) -> None:
    """Hash one bounded unchanged float part into the ordered program digest."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= 2 * 1024 ** 3:
            raise RuntimeError("source-float cached PCM part is unsafe")
        remaining = before.st_size
        while remaining:
            data = os.read(descriptor, min(remaining, 1024 * 1024))
            if not data:
                raise RuntimeError("source-float cached PCM part truncated")
            combined.update(data)
            remaining -= len(data)
        after, current = os.fstat(descriptor), path.lstat()
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink")
        if any(getattr(before, key) != getattr(after, key) or getattr(before, key) != getattr(current, key) for key in fields):
            raise RuntimeError("source-float cached PCM part changed during ordered verification")
    finally:
        os.close(descriptor)


def _verify_pcm_concat(bus: SourceAudioBus) -> None:
    """Prove the retained WAV decodes to the exact ordered cut-part samples."""
    expected = hashlib.sha256()
    for part in bus.receipt["parts"]:
        _append_pcm_hash(Path(part["path"]), expected)
    result = run_audio([bus.admission.tools["ffmpeg"]["path"], "-nostdin", "-v", "error",
        "-xerror", "-err_detect", "explode", "-i", bus.path, "-map", "0:a:0",
        "-c:a", "pcm_f32le", "-f", "hash", "-hash", "sha256", "-"])
    if result.decode("ascii").strip() != "SHA256=" + expected.hexdigest():
        raise RuntimeError("source-float retained WAV does not contain its exact ordered PCM parts")


def load_source_bus(plan: dict, manifest: dict, location: tuple[str, str],
                    expected_receipt_hash: str | None = None) -> SourceAudioBus:
    """Reopen only current proved source dialogue; no old AAC/path-only fallback."""
    if expected_receipt_hash is None:
        raise RuntimeError("source-float cache lacks separately held source execution authority")
    directory, base = location
    root = Path(directory).resolve(strict=True)
    pointer, receipt = _read_pointer(root, base)
    if pointer["receiptHash"] != _hash(expected_receipt_hash):
        raise RuntimeError("source-float cache lacks separately held source execution authority")
    admission = admit_audio(plan, manifest, (SOURCE_FLOAT_POLICY_V2, False))
    if admission is None:
        raise RuntimeError("source-float cache lost explicit source admission")
    _validate_receipt(receipt, pointer, admission, plan)
    manifestation = verify_manifestation(str(root), plan)
    if manifestation["receiptHash"] != receipt["cutManifestationHash"]:
        raise RuntimeError("source-float cached cut manifestation changed")
    _validate_parts(receipt, (root, plan, manifestation))
    media = _inside(receipt["path"], root)
    receipt_path = _inside(pointer["receiptPath"], root)
    bus = SourceAudioBus(str(media), receipt["sha256"], receipt["totalSamples"], receipt["frameRate"],
        receipt["videoFrames"], str(receipt_path.parent), receipt, admission, str(root))
    verify_source_bus(bus, plan)
    _verify_pcm_concat(bus)
    verify_source_bus(bus, plan)
    return bus
