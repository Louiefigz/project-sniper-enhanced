"""Shared sample-exact dialogue cleanup and gain, before either route masters audio."""
from __future__ import annotations

import array
import re
from dataclasses import dataclass
from pathlib import Path

from audio.audio_gain import build_filter as gain_filter
from audio.audio_mix_bed import AFMT
from audio.program_audio_clock import exact_float_audio_clock
from audio.program_finish_contract import FinishRequest
from audio.render_audio_authority import run_audio
from cut_preview_io import file_hash

PROBE_SECONDS = 2
IMPULSE_SAMPLE = 48_000
MAX_LATENCY_SAMPLES = 48_000
MIN_PROBE_PEAK = 0.05
ENVELOPE_FRAME = 256
TAIL_GUARD_SAMPLES = 4800
_MODEL_RE = re.compile(r"arnndn=m=([^,:]+)")


@dataclass(frozen=True)
class DialogueSource:
    """Caller-owned normalized float audio and its exact tools/sample clock."""

    path: str
    samples: int
    ffmpeg: str
    ffprobe: str


def measure_chain_latency(ffmpeg: str, chain: str) -> int:
    """Locate a unit click after the exact chain; reject a lost click or moved clock."""
    total = PROBE_SECONDS * 48_000
    click = f"if(eq(n,{IMPULSE_SAMPLE}),0.9,0)"
    raw = run_audio([ffmpeg, "-nostdin", "-v", "error", "-xerror", "-f", "lavfi", "-i",
        f"aevalsrc='{click}|{click}':s=48000:d={PROBE_SECONDS}",
        "-af", f"{chain},{AFMT}", "-c:a", "pcm_f32le", "-f", "f32le", "-"])
    samples = array.array("f")
    samples.frombytes(raw)
    if len(samples) != 2 * total:
        raise RuntimeError("cleanup chain changed the probe sample count; it cannot keep the program clock")
    left = [abs(samples[2 * index]) for index in range(total)]
    peak = max(range(total), key=left.__getitem__)
    lag = peak - IMPULSE_SAMPLE
    if left[peak] < MIN_PROBE_PEAK or not 0 <= lag <= MAX_LATENCY_SAMPLES:
        raise RuntimeError("cleanup chain latency could not be established "
                           f"(peak {left[peak]:.3f} at {lag:+d} samples)")
    return lag


def _dialogue_filter(request: FinishRequest, latency: int, samples: int) -> str:
    """Cleanup, delay removal, then the existing trapezoid gain windows at the bus clock.

    The chain input is padded by the measured delay plus a guard so the filter
    also emits the processed final ``latency`` samples instead of leaving that
    tail silent, and no end-of-input block handling touches the program range."""
    parts = []
    if request.enhance_chain:
        parts.append(f"apad=pad_len={latency + TAIL_GUARD_SAMPLES}")
        parts.append(request.enhance_chain)
        parts.append(f"atrim=start_sample={latency},asetpts=N/SR/TB")
    parts.append(AFMT)
    if request.gain:
        parts.append(f"asetnsamples=n={ENVELOPE_FRAME}:p=0,{gain_filter(list(request.gain))}")
    parts.append(f"apad=whole_len={samples},atrim=end_sample={samples},asetpts=N/SR/TB")
    return ",".join(parts)


def render_clean_dialogue(source: DialogueSource, request: FinishRequest,
                          directory: Path) -> tuple[str, int]:
    """Reuse the same cleanup/gain DSP without inventing a source-bus authority."""
    before = file_hash(Path(source.path))
    exact_float_audio_clock(source.path, source.ffprobe, source.samples)
    latency = measure_chain_latency(source.ffmpeg, request.enhance_chain) if request.enhance_chain else 0
    target = directory / "dialogue-finished.wav"
    run_audio([source.ffmpeg, "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode", "-n",
        "-i", source.path, "-map", "0:a:0", "-af", _dialogue_filter(request, latency, source.samples),
        "-ac", "2", "-c:a", "pcm_f32le", str(target)])
    exact_float_audio_clock(str(target), source.ffprobe, source.samples)
    if file_hash(Path(source.path)) != before:
        raise RuntimeError("Dialogue source changed during cleanup")
    return str(target), latency


def cleanup_model_binding(chain: str | None) -> dict | None:
    """Bind the vendored RNNoise model bytes when the chain consumes one."""
    match = _MODEL_RE.search(chain or "")
    if match is None:
        return None
    path = Path(match.group(1))
    return {"path": str(path), "sha256": file_hash(path)}
