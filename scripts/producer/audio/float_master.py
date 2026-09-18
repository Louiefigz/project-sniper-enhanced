"""Shared measured mastering of intended float programs before their first AAC encode.

Callers own source-cut authority, channel selection and the exact input clock.
This module owns only the existing mastering dispatch and its float output.
Callers must still verify the output clock, loudness and encoded delivery.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from audio.audio_mix_delivery import _observe_final_audio
from audio.mastering_filter import MasterFilterInput, build_master_filter
from audio.mastering_profile import LEGACY_MASTERING_PROFILE, MasteringProfile
from audio.render_audio_authority import run_audio


@dataclass(frozen=True)
class FloatMasterInput:
    """Exact premaster and its complete, strict-decoder measurement."""

    path: str
    samples: int
    measured: dict
    ffmpeg: str
    profile: MasteringProfile = LEGACY_MASTERING_PROFILE


def measured_chain(path: str, samples: int, chain: str) -> float | None:
    """Measure the same exact program clock during static-gain dry runs."""
    measured, code, error = _observe_final_audio(path,
        f"{chain},aresample=48000,atrim=end_sample={samples},asetpts=PTS-STARTPTS")
    if code or measured is None:
        raise RuntimeError("whole-program mastering dry run failed: " + error)
    integrated = float(measured["input_i"])
    return integrated if math.isfinite(integrated) else None


def render_float_master(source: FloatMasterInput, directory: Path) -> tuple[Path, str, str | None]:
    """Materialize shared measured mastering as float; never encode AAC here."""
    if type(source.samples) is not int or source.samples < 1:
        raise ValueError("Float master requires an exact positive sample clock")
    request = MasterFilterInput(None, source.measured,
        partial(measured_chain, source.path, source.samples), source.profile)
    chain, note = build_master_filter(request)
    chain += f",aresample=48000,atrim=end_sample={source.samples},asetpts=PTS-STARTPTS"
    path = directory / "program-master.wav"
    run_audio([source.ffmpeg, "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode",
        "-n", "-i", source.path, "-map", "0:a:0", "-af", chain,
        "-c:a", "pcm_f32le", str(path)])
    return path, chain, note
