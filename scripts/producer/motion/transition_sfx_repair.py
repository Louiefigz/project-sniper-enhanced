#!/usr/bin/env python3
"""Repair only transition SFX while stream-copying proved transition picture.

The visual transition renderer and the SFX mixer intentionally share the
event grammar in :mod:`motion.transitions`.  A sound-only edit must not send
the already-approved picture back through libx264.  This module validates
that the before/after event sets differ only in ``sfx``, rebuilds program
audio from the pristine upstream source, and muxes it beside a byte-reused
video stream from the approved transition render.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass

from cut_speed import has_audio, probe_duration, probe_video, probe_video_frames, run_ff
from motion.transitions import (
    _assert_preserved,
    _transition_audio,
    parse_events,
)


@dataclass(frozen=True)
class TransitionSfxRepairRequest:
    """Closed inputs for one sound-only transition repair."""

    program_source: str
    visual_source: str
    before_events: object
    after_events: object
    output_path: str


def _picture_surface(events: list) -> tuple:
    """Transition identity excluding the independently editable SFX slot."""
    return tuple((event.out_time, event.kind, event.zoom) for event in events)


def _sfx_surface(events: list) -> tuple:
    return tuple(event.sfx for event in events)


def _video_facts(path: str) -> tuple:
    stream = probe_video(path)
    return (
        int(stream["width"]),
        int(stream["height"]),
        stream["r_frame_rate"],
        probe_video_frames(path),
    )


def _packet_hash(path: str) -> str:
    """SHA-256 of the encoded video elementary stream."""
    output = run_ff([
        "ffmpeg", "-nostdin", "-v", "error", "-i", path,
        "-map", "0:v:0", "-c", "copy", "-f", "hash",
        "-hash", "sha256", "-",
    ]).strip()
    prefix = "SHA256="
    if not output.startswith(prefix):
        raise RuntimeError("video packet hash command returned no SHA-256")
    digest = output[len(prefix):].lower()
    if len(digest) != 64:
        raise RuntimeError("video packet hash has invalid length")
    return digest


def _source_hash(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validate(request: TransitionSfxRepairRequest) -> tuple[list, list, int]:
    duration = probe_duration(request.program_source)
    before = parse_events(request.before_events, duration)
    after = parse_events(request.after_events, duration)
    if _picture_surface(before) != _picture_surface(after):
        raise ValueError("SFX-only repair cannot change transition picture")
    if _sfx_surface(before) == _sfx_surface(after):
        raise ValueError("SFX-only repair must change at least one SFX slot")
    if not has_audio(request.program_source):
        raise ValueError("SFX-only repair requires authoritative program audio")
    program_facts = _video_facts(request.program_source)
    visual_facts = _video_facts(request.visual_source)
    if program_facts != visual_facts:
        raise ValueError(
            "approved transition picture differs from program video clock")
    return before, after, program_facts[3]


def repair_transition_sfx(request: TransitionSfxRepairRequest) -> dict:
    """Rebuild only transition audio and stream-copy approved picture."""
    parse_events(request.before_events, 0)
    parse_events(request.after_events, 0)
    before, after, in_frames = _validate(request)
    before_packet_hash = _packet_hash(request.visual_source)
    program_hash = _source_hash(request.program_source)
    sfx_events = [event for event in after if event.sfx]
    work = tempfile.mkdtemp(prefix="producer-transition-sfx-repair-")
    try:
        audio = _transition_audio(request.program_source, work, sfx_events)
        visual_index = 1 + len(audio.inputs) // 2
        command = [
            "ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", request.program_source, *audio.inputs,
            "-i", request.visual_source,
        ]
        if audio.filter_suffix:
            command.extend(("-filter_complex", audio.filter_suffix[1:]))
        command.extend((
            "-map", f"{visual_index}:v:0", *audio.map_args,
            "-c:v", "copy", "-movflags", "+faststart", request.output_path,
        ))
        run_ff(command)
        if audio.authority is not None:
            audio.authority.assert_stable()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    fields = _assert_preserved(
        request.program_source, request.output_path, in_frames, True)
    after_packet_hash = _packet_hash(request.output_path)
    if after_packet_hash != before_packet_hash:
        raise RuntimeError("SFX-only repair changed encoded transition picture")
    return {
        **fields,
        "programSourceSha256": program_hash,
        "picturePacketSha256": after_packet_hash,
        "pictureReused": True,
        "changedSfxSlots": sum(
            left.sfx != right.sfx for left, right in zip(before, after)),
        "sfx": len(sfx_events),
        "whooshPeakDbfs": audio.whoosh_peak_dbfs,
        "channelNormalization": (
            None if audio.authority is None else audio.authority.receipt),
    }
