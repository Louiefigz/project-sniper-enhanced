#!/usr/bin/env python3
"""Synthesize the bundled starter music bed, ``assets/music/default-bed.mp3``.

    python3 scripts/producer/audio/default_bed.py [--out PATH]

The bed is generated here from sine tones and filtered noise, so it carries no
third-party rights. It replaces an earlier bed that measured a stable 111 Hz hum
(39 dB prominence) with the product's own ``audio_tonal_hum`` check.

Design constraints, all measurable:
- every tone is at or above 261.63 Hz (C4), and the mix is high-passed at
  250 Hz, so nothing sits in the hum check's 40–240 Hz band;
- the chord changes every 4 s with 1 s raised-cosine crossfades, so no line is
  a steady drone;
- 60 s, 48 kHz stereo, loudness-normalized to about -22 LUFS like the bed it
  replaces; the music stage sets its level under dialogue.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DURATION_S = 60
CHORD_S = 4.0
FADE_S = 1.0
# C major 7, A minor 9 (voiced high), F major 7, G6 — all at or above C4.
CHORDS = (
    (261.63, 329.63, 392.00, 493.88),
    (440.00, 523.25, 659.25, 783.99),
    (349.23, 440.00, 523.25, 659.25),
    (392.00, 493.88, 587.33, 659.25),
)


def _chord_gain(index: int) -> str:
    """Raised-cosine window for chord ``index`` repeating every len(CHORDS) slots."""
    period = CHORD_S * len(CHORDS)
    start = CHORD_S * index
    phase = f"mod(t-{start}+{period},{period})"
    rise = f"0.5-0.5*cos(PI*{phase}/{FADE_S})"
    fall = f"0.5-0.5*cos(PI*({CHORD_S + FADE_S}-{phase})/{FADE_S})"
    return (f"if(lt({phase},{FADE_S}),{rise},"
            f"if(lt({phase},{CHORD_S}),1,if(lt({phase},{CHORD_S + FADE_S}),{fall},0)))")


def _voice(channel: int) -> str:
    """One channel: every chord's tones, each under its own crossfade window."""
    terms = []
    for index, chord in enumerate(CHORDS):
        tones = "+".join(f"sin(2*PI*{f * (1.0 + 0.0007 * channel):.4f}*t)" for f in chord)
        terms.append(f"({_chord_gain(index)})*({tones})")
    tremolo = f"(0.85+0.15*sin(2*PI*0.2*t+{channel}))"
    return f"0.045*{tremolo}*({'+'.join(terms)})"


def build(out: Path) -> None:
    """Render the bed with ffmpeg; raise on any encoder failure."""
    pad = f"aevalsrc=exprs='{_voice(0)}|{_voice(1)}':s=48000:d={DURATION_S}"
    air = f"anoisesrc=color=pink:amplitude=0.02:d={DURATION_S}:r=48000"
    graph = (f"[0:a]aformat=channel_layouts=stereo[pad];"
             f"[1:a]highpass=f=600,lowpass=f=4000,aformat=channel_layouts=stereo[air];"
             f"[pad][air]amix=inputs=2:weights='1 0.35':normalize=0,"
             f"highpass=f=250:poles=2,afade=t=in:d=2,afade=t=out:st={DURATION_S - 3}:d=3,"
             f"loudnorm=I=-22:TP=-2:LRA=7")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", pad, "-f", "lavfi", "-i", air,
                    "-filter_complex", graph, "-ar", "48000", "-c:a", "libmp3lame",
                    "-b:a", "128k", "-map_metadata", "-1", "-fflags", "+bitexact",
                    str(out)], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO / "assets" / "music" / "default-bed.mp3")
    build(parser.parse_args().out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
