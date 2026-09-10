"""Browser A/V encoding of exact excerpts of a qualified full-program master.

The excerpt never receives independent loudness normalization, fades or gain.
Its LUFS is descriptive only; complete decode, exact presentation samples and
the shared true-peak ceiling remain mandatory. Picture packets remain exact.
"""
from __future__ import annotations

import math
from fractions import Fraction
from pathlib import Path

from audio.audio_mix_delivery import _observe_final_audio
from audio.audio_mix_picture import observe_picture_source, verify_picture_copy
from audio.program_audio_clock import exact_aac_audio_clock
from audio.render_audio_authority import run_audio
from cut_preview_io import file_hash
from producer_config import AUDIO, ENCODE


def _measure(path: Path) -> dict:
    """Measure actual encoded excerpt, without forcing its LUFS to a global target."""
    measured, code, error = _observe_final_audio(str(path))
    if code or measured is None:
        raise RuntimeError("opening complete AAC decode failed: " + error)
    peak, integrated = float(measured["input_tp"]), float(measured["input_i"])
    if math.isnan(peak) or peak > AUDIO["true_peak_dbtp"]:
        raise RuntimeError(f"opening encoded AAC exceeds the unchanged true-peak ceiling: {peak}")
    return {"audioDecodeSucceeded": True, "truePeakWithinCeiling": True,
        "truePeakCeilingDbtp": AUDIO["true_peak_dbtp"], "truePeakDbtp": peak if math.isfinite(peak) else None,
        "integratedLufs": integrated if math.isfinite(integrated) else None,
        "silentDecodedExcerpt": peak == -math.inf, "excerptLufsIsInformational": True,
        "independentNormalization": False}


def _mux(path: Path, picture: dict, audio: dict, tools: dict) -> dict:
    """Encode audio once and prove actual native picture PTS/payload copy."""
    for item in (picture, audio):
        if file_hash(Path(item["path"])) != item["sha256"]:
            raise RuntimeError("opening held picture/PCM bytes changed before mux")
    source = observe_picture_source(picture["path"], float(Fraction(picture["frames"], 1)
                                    / Fraction(picture["frameRate"])), picture["sha256"])
    run_audio([tools["ffmpeg"]["path"], "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode", "-n",
        "-i", picture["path"], "-i", audio["path"], "-map", "0:v:0", "-c:v", "copy", "-map", "1:a:0",
        "-af", f"atrim=end_sample={audio['samples']},asetpts=PTS-STARTPTS", "-c:a", "aac",
        "-b:a", ENCODE["audio_bitrate"], "-ar", "48000", "-ac", "2", "-video_track_timescale",
        str(source.time_base.denominator), "-movie_timescale", "48000", "-movflags", ENCODE["movflags"], str(path)])
    before = file_hash(path)
    copied = verify_picture_copy(source, str(path))
    clock = exact_aac_audio_clock(str(path), tools["ffprobe"]["path"], audio["samples"])
    measured = _measure(path)
    if file_hash(path) != before or file_hash(Path(audio["path"])) != audio["sha256"]:
        raise RuntimeError("opening A/V or PCM bytes changed during mux qualification")
    return {"path": str(path), "sha256": before, "sizeBytes": path.stat().st_size,
        "picture": copied, "audioClock": clock, "audioMeasurement": measured,
        "sourcePcmSha256": audio["pcmSha256"], "audiblePathAacEncodes": 1}


def mux_ranges(root: Path, pictures: dict, audio: dict, tools: dict) -> dict:
    """Reuse only identical core/context ranges from the same held actual outputs."""
    completed, result = {}, {}
    for name in ("core", "review"):
        picture, pcm = pictures["ranges"][name], audio[name]
        identity = (picture["sha256"], pcm["sha256"], pcm["startFrame"], pcm["endFrameExclusive"],
                    pcm["startSample"], pcm["endSampleExclusive"])   # same key the TS selector requires
        if identity not in completed:
            completed[identity] = _mux(root / f"{name}.mp4", picture, pcm, tools)
        result[name] = {**completed[identity], "startFrame": pcm["startFrame"],
            "endFrameExclusive": pcm["endFrameExclusive"], "startSample": pcm["startSample"],
            "endSampleExclusive": pcm["endSampleExclusive"]}
    return result
