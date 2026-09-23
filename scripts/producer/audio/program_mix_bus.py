"""Unmastered whole-program float mix with a separate sidechain reference."""
from __future__ import annotations

import math
import copy
from dataclasses import dataclass
from pathlib import Path

from audio.audio_mix import DUCK, _MIX, duck_bed, measure_duck_depth
from audio.audio_mix_bed import fit_length, prep_bed
from audio.audio_mix_delivery import _observe_final_audio
from audio.music_stage import resolve_music_track
from audio.program_audio_clock import float_audio_clock
from audio.program_finish_bus import render_finishing
from audio.program_finish_contract import finishing_request
from audio.render_audio_authority import run_audio
from audio.render_audio_bus import SourceAudioBus, verify_source_bus
from cut_preview_io import file_hash
from producer_config import AUDIO


@dataclass(frozen=True)
class ProgramMix:
    """A pristine dialogue bus or exact float sum, not a mastered delivery."""

    path: str
    sha256: str
    music: dict | None
    detector_reference: dict | None
    measured: dict
    finishing: dict | None = None


def observe_program(path: str) -> dict:
    """Reject partial decoder statistics before any normalization decision."""
    measured, code, error = _observe_final_audio(path)
    if code or measured is None:
        raise RuntimeError("full-program audio decode failed: " + error)
    return measured


def _integrated(measured: dict) -> float | None:
    """Keep explicit silence distinct from a missing audio stream or receipt."""
    value = float(measured["input_i"])
    return value if math.isfinite(value) else None


def _render_float(bus: SourceAudioBus, source: str, target: Path, chain: str) -> None:
    """Retain float headroom while fitting a bed/detector to the exact bus clock."""
    run_audio([bus.admission.tools["ffmpeg"]["path"], "-nostdin", "-v", "error",
        "-xerror", "-err_detect", "explode", "-n", "-i", source, "-map", "0:a:0",
        "-af", f"{chain},aresample=48000,apad=whole_len={bus.samples},"
        f"atrim=end_sample={bus.samples},asetpts=PTS-STARTPTS",
        "-ac", "2", "-c:a", "pcm_f32le", str(target)])


def _detector(bus: SourceAudioBus, directory: Path, measured: dict, key: str) -> tuple[str, dict]:
    """Reference only the detector; the audible dialogue is never normalized here.

    ``key`` is the finished dialogue without SFX when finishing is requested,
    otherwise the raw bus: ducking follows the voice the listener hears."""
    integrated = _integrated(measured)
    gain = AUDIO["lufs_target"] - integrated if integrated is not None else 0.0
    target = directory / "detector-reference.wav"
    _render_float(bus, key, target, f"volume={gain:.8f}dB:precision=double")
    return str(target), {"referenceIntegratedLufs": AUDIO["lufs_target"],
        "measuredDialogueIntegratedLufs": integrated, "gainDb": gain,
        "appliedTo": "sidechain-only", "silentDialogue": integrated is None,
        "keySource": "raw-dialogue" if key == bus.path else "finished-dialogue-without-sfx",
        "keySha256": file_hash(Path(key)),
        "path": str(target), "sha256": file_hash(target), "duckParameters": dict(DUCK)}


def _require_step(result: dict, name: str) -> dict:
    """A failed bed stage cannot become an unreported fallback or partial mix."""
    if not result.get("ok"):
        raise RuntimeError(f"source-float music {name} failed: {result}")
    return result


def _music_settings(plan: dict, bus: SourceAudioBus) -> tuple[dict, float]:
    """Keep existing music semantics and reject nonfinite/out-of-range settings."""
    music = copy.deepcopy(plan.get("music") or {})
    gap = music.get("gapDb", sum(AUDIO["music_gap_db"]) / 2)
    if type(gap) not in {int, float} or not math.isfinite(gap) or not 0 <= gap <= 60:
        raise RuntimeError("source-float music gapDb must be finite in [0,60]")
    if type(music.get("duck", True)) is not bool:
        raise RuntimeError("source-float music duck must be boolean")
    used = {row["sourceId"] for row in plan["cutTrack"]}
    has_stream = any(row["id"] in used and row["audioStreamIndex"] is not None
                     for row in bus.admission.sources)
    if has_stream and not music.get("duck", True):
        raise RuntimeError("source-float dialogue programs require music ducking")
    return music, float(gap)


def _prepared_bed(context: tuple, measured: dict) -> tuple[str, dict, dict | None]:
    """Reuse existing bed/duck DSP with exact float output and explicit reference."""
    bus, plan, directory, key = context
    music, gap = _music_settings(plan, bus)
    source = resolve_music_track(music, None, bus.admission.manifest_path)
    source_hash = file_hash(Path(source))
    observe_program(source)
    integrated = _integrated(measured)
    reference = AUDIO["lufs_target"] if integrated is None else integrated
    base, fitted = directory / "bed-base.wav", directory / "bed-fit.wav"
    prep = _require_step(prep_bed(source, reference - gap, str(base)), "prepare")
    fit = _require_step(fit_length(str(base), bus.samples / 48000, str(fitted)), "fit")
    exact = directory / "bed-exact.wav"
    _render_float(bus, str(fitted), exact, "anull")
    float_audio_clock(str(exact), bus)
    detector, depth, result = None, None, str(exact)
    if music.get("duck", True):
        reference_key, detector = _detector(bus, directory, measured, key)
        result = str(directory / "bed-ducked.wav")
        _require_step(duck_bed(reference_key, str(exact), result, bus.samples), "duck")
        float_audio_clock(result, bus)
        depth = measure_duck_depth(reference_key, result)
    if file_hash(Path(source)) != source_hash:
        raise RuntimeError("source-float music bytes changed during bed preparation")
    return result, {"path": source, "sha256": source_hash, "settings": music,
        "gapDb": gap, "prepare": prep, "fit": fit, "duckDepth": depth,
        "bedPath": result, "bedSha256": file_hash(Path(result))}, detector


def build_program_mix(bus: SourceAudioBus, plan: dict, directory: Path) -> ProgramMix:
    """Finish dialogue, add SFX, sum the prepared bed in float; apply no master here.

    Without finishing the premaster is the pristine raw bus, exactly as before.
    With finishing the audible program is cleanup -> gain -> SFX
    (``program_finish_bus``) and the duck detector keys on the finished dialogue."""
    finishing_request(plan, bus.samples / 48_000)
    verify_source_bus(bus, plan)
    finished = render_finishing(bus, plan, directory)
    dialogue = finished.dialogue_path if finished else bus.path
    program = finished.program_path if finished else bus.path
    finishing = finished.receipt if finished else None
    measured = observe_program(dialogue)
    if not (plan.get("music") or {}).get("enabled"):
        program_measured = measured if program == dialogue else observe_program(program)
        return ProgramMix(program, file_hash(Path(program)), None, None, program_measured, finishing)
    bed, music, detector = _prepared_bed((bus, plan, directory, dialogue), measured)
    target = directory / "program-premaster.wav"
    graph = f"{_MIX};[mix]atrim=end_sample={bus.samples},asetpts=PTS-STARTPTS[out]"
    run_audio([bus.admission.tools["ffmpeg"]["path"], "-nostdin", "-v", "error",
        "-xerror", "-err_detect", "explode", "-n", "-i", program, "-i", bed,
        "-filter_complex", graph, "-map", "[out]", "-c:a", "pcm_f32le", str(target)])
    verify_source_bus(bus, plan)
    return ProgramMix(str(target), file_hash(target), music, detector, observe_program(str(target)), finishing)
