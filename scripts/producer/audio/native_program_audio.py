"""Owned complete-program float premaster for native Short/Long projects.

This adapter reuses the ordinary source-float cut clock and program mixer.  It
produces technical execution authority only; it does not approve sound, picture,
editorial quality, export, or delivery.
"""
from __future__ import annotations

import os
import stat
from copy import deepcopy
from pathlib import Path

from audio.program_audio_clock import float_audio_clock
from audio.program_finish_bus import assert_finishing_stable, finishing_identity, verify_finishing
from audio.program_master_bus import audio_program_input_hash
from audio.program_mix_bus import ProgramMix, build_program_mix
from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2
from audio.render_audio_bus import SourceAudioBus, verify_source_bus
from cut_preview_io import MAX_MEDIA, digest, file_hash
from fingerprints import file_sha256
from ingest_execution_authority import verify_execution_media_authority
from render import RenderCtx, render
from render_effect_registry import validate_render_documents

SCOPE = "complete-program-native-premaster-not-review-or-delivery"
STATUS = "native-program-audio-prepared"
_MAX_AUDIO = MAX_MEDIA


def _identity(value: os.stat_result) -> tuple[int, ...]:
    """Fields that must remain fixed while an admitted premaster is copied."""
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns, value.st_mode, value.st_nlink)


def _write_all(descriptor: int, payload: bytes) -> None:
    """Finish a bounded write without permitting a zero-progress loop."""
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise RuntimeError("Native program premaster publication stalled")
        view = view[written:]


def _copy_bytes(source: int, target: int, size: int) -> None:
    """Copy exactly the measured byte count from the held descriptor."""
    remaining = size
    while remaining:
        chunk = os.read(source, min(remaining, 1024 * 1024))
        if not chunk:
            raise RuntimeError("Native program premaster truncated during copy")
        _write_all(target, chunk)
        remaining -= len(chunk)


def _context(request: dict, root: Path) -> RenderCtx:
    """Build the same source-float base context from held canonical documents."""
    manifest = {**request["manifest"], "_path": request["manifestPath"]}
    base = root / "base"
    base.mkdir(mode=0o700)
    (base / "work").mkdir(mode=0o700)
    return RenderCtx(deepcopy(request["plan"]), manifest, str(base),
        str(base / "work"), skip_graphics=True, producer_dir=request["project"],
        plan_path=request["planPath"], audio_clock_policy=SOURCE_FLOAT_POLICY_V2)


def publish_float_copy(source: Path, target: Path, expected: str) -> str:
    """Publish one unchanged regular premaster without following or sharing links."""
    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    target_fd = -1
    try:
        before = os.fstat(source_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 \
                or not 0 < before.st_size <= _MAX_AUDIO:
            raise RuntimeError("Native program premaster source is unsafe")
        target_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        _copy_bytes(source_fd, target_fd, before.st_size)
        os.fsync(target_fd)
        after = os.fstat(source_fd)
        if _identity(before) != _identity(after) \
                or _identity(before) != _identity(source.lstat()) \
                or file_hash(source) != expected:
            raise RuntimeError("Native program premaster changed during publication")
    finally:
        os.close(source_fd)
        if target_fd >= 0:
            os.close(target_fd)
    observed = file_hash(target)
    if observed != expected:
        raise RuntimeError("Published native program premaster bytes differ")
    return observed


def _music_identity(mix: ProgramMix) -> dict | None:
    """Remove staging paths while retaining every consumed music byte and setting."""
    if mix.music is None:
        return None
    return {key: value for key, value in mix.music.items() if key != "bedPath"}


def _detector_identity(mix: ProgramMix) -> dict | None:
    """Bind detector facts without treating its private path as public media."""
    if mix.detector_reference is None:
        return None
    return {key: value for key, value in mix.detector_reference.items() if key != "path"}


def _record(request: dict, bus: SourceAudioBus, mix: ProgramMix, target: Path) -> dict:
    """Seal the exact cut, mix, clock, tools, code, and published WAV identity."""
    clock = float_audio_clock(str(target), bus)
    body = {"schemaVersion": 1, "kind": "native-program-audio-authority",
        "status": STATUS, "scope": SCOPE, "humanListeningApproved": False,
        "nativeExportApproved": False, "project": request["project"],
        "plan": {"path": request["planPath"], "sha256": file_sha256(request["planPath"])},
        "manifest": {"path": request["manifestPath"], "sha256": file_sha256(request["manifestPath"]),
            "sourceSetDigest": bus.admission.source_set_digest},
        "sourceBusReceiptHash": bus.receipt["receiptHash"],
        "audioProgramInputHash": audio_program_input_hash(bus, mix),
        "finishing": finishing_identity(mix.finishing), "music": _music_identity(mix),
        "detectorReference": _detector_identity(mix),
        "audio": {"path": str(target), "sha256": mix.sha256,
            "sizeBytes": target.stat().st_size, **clock},
        "frameRate": bus.frame_rate, "videoFrames": bus.frames,
        "tools": bus.admission.tools, "code": list(bus.admission.code)}
    return {**body, "receiptHash": digest(body)}


def prepare_native_program_audio(request: dict, root: Path) -> dict:
    """Render one exact source-float cut and publish its unmastered program mix."""
    ctx = _context(request, root)
    validate_render_documents(ctx.plan, ctx.manifest)
    verify_execution_media_authority(ctx.plan, ctx.manifest, request["manifestPath"])
    render(ctx, audit=False)
    if ctx.plan != request["plan"] or ctx.source_audio_bus is None:
        raise RuntimeError("Native program preparation changed its plan or omitted source audio")
    bus = ctx.source_audio_bus
    mix_dir = root / "mix"
    mix_dir.mkdir(mode=0o700)
    mix = build_program_mix(bus, ctx.plan, mix_dir)
    verify_source_bus(bus, ctx.plan)
    verify_finishing(mix.finishing, bus, ctx.plan)
    assert_finishing_stable(mix.finishing)
    target = root / "program.wav"
    publish_float_copy(Path(mix.path), target, mix.sha256)
    return _record(request, bus, mix, target)
