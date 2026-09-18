"""Canonical source trim, channel, tempo and edge treatment for cut audio."""
from __future__ import annotations

from dataclasses import dataclass

from audio.channel_normalization import ChannelAuthority
from producer_config import AUDIO, ENCODE


@dataclass(frozen=True)
class CutAudioFilter:
    """A source-clock span; unity preservation is an explicit processing policy."""

    source_start: float
    output_length: float
    speed: float
    authority: ChannelAuthority | bool | None
    input_index: int = 0
    silence_index: int = 1
    preserve_unity: bool = False
    source_end: float | None = None


def fade_suffix(out_len: float, fade_s: float) -> str:
    """Canonical equal-power edge declick, without overlap duration drift."""
    duration = min(fade_s, out_len / 2.0)
    if duration <= 0:
        return ""
    return (f",afade=t=in:st=0:d={duration:.4f}:curve=qsin"
            f",afade=t=out:st={out_len - duration:.6f}:d={duration:.4f}:curve=qsin")


def exact_window_fade(samples: int, rate: int = 48_000) -> str:
    """Declick the LAST samples of an exact, already-trimmed window (sample-accurate).

    The nominal edge fade in ``fade_suffix`` is placed on the cut's nominal
    length; a picture-quantized window can end up to one frame shorter, which
    cut that fade off entirely (adversarial review 2026-09-06: measured seams
    ending at 102 % of peak). Apply this AFTER the trim, where the window is
    exact; it is a no-op over padded silence and idempotent over a kept fade.
    """
    fade = min(int(rate * AUDIO["join_crossfade_ms"] / 1000), samples // 2)
    if fade <= 0:
        return ""
    return f",afade=t=out:ss={samples - fade}:ns={fade}:curve=qsin"


def source_filter(spec: CutAudioFilter, label: str) -> str:
    """Build the exact own/lead chain; the legacy policy keeps its old strings."""
    rate = ENCODE["audio_rate"]
    if spec.authority:
        channel = (spec.authority.filter_for("stereo")
                   if isinstance(spec.authority, ChannelAuthority)
                   else "aformat=channel_layouts=stereo")
        # The new bus preserves headroom before any channel rematrix. Legacy
        # transport remains byte-policy compatible until its separate migration.
        floating = "aformat=sample_fmts=fltp," if spec.preserve_unity else ""
        tempo = "" if spec.preserve_unity and spec.speed == 1 else f"atempo={spec.speed},"
        end = (spec.source_end if spec.source_end is not None
               else spec.source_start + spec.output_length * spec.speed)
        head = (f"[{spec.input_index}:a]{floating}{channel},"
                f"atrim=start={spec.source_start:.6f}:end={end:.6f},"
                f"asetpts=PTS-STARTPTS,{tempo}aresample={rate}")
    else:
        head = (f"[{spec.silence_index}:a]atrim=0:{spec.output_length:.6f},"
                "asetpts=PTS-STARTPTS")
    fade = fade_suffix(spec.output_length, AUDIO["join_crossfade_ms"] / 1000.0)
    return (f"{head},aformat=sample_fmts=fltp:sample_rates={rate}:"
            f"channel_layouts=stereo{fade}[{label}]")
