#!/usr/bin/env python3
"""sfx_library — the starter SFX pack: catalog, resolver, deterministic builder.

The transitions SFX slot vocabulary is ``sfx: true | false | "<name>"``:
``true`` keeps the engine's seeded synthesized whoosh (transitions.py),
``false`` is silent, and a NAME resolves here to a vendored one-shot in
``PROJECT_SNIPER/assets/sfx/`` plus its ``lead_s`` — how far the file's
perceptual HIT sits from its start, so the renderer delays it to land the hit
exactly on the seam (whooshes swell in, clicks hit immediately).

Provenance (license hygiene, like audio/models/): every asset is SYNTHESIZED
in-repo by ``build`` — seeded ffmpeg noise sweeps + sine/chirp envelopes, the
same technique as transitions.synth_whoosh and the music bed. No third-party
audio is vendored, so there is no upstream license to carry; the record lives
in ``assets/sfx/PROVENANCE.md``. Network-fetched CC0 packs (Kenney) were
deliberately skipped: synthesis is reproducible bit-for-bit and needs no
attribution audit. Peaks are normalized to ``MOTION["transitions"]
["sfx_peak_dbfs"]`` (−15 dBFS — the measured transition-peak band).

CLI:
    sfx_library.py list                # catalog + on-disk status
    sfx_library.py resolve <name>      # print the resolved path + lead
    sfx_library.py build [name ...]    # (re)synthesize the pack (all by default)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cut_speed import run_ff              # noqa: E402
from producer_config import ENCODE, MOTION  # noqa: E402

_AUDIO_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(_AUDIO_DIR, "..", "..", ".."))
SFX_DIR = os.path.join(REPO_ROOT, "assets", "sfx")
PEAK_DBFS = MOTION["transitions"]["sfx_peak_dbfs"]
_RATE = ENCODE["audio_rate"]

# The pack catalog (data — O(1) lookup, exempt from logic line limits).
# ``lead_s`` = seconds from file start to the perceptual hit; the renderer
# starts playback at ``seam - lead_s``. ``sweep`` taps run FIRST→LAST, so a
# high→low order falls (whoosh) and low→high rises (swish). ``seed`` keys the
# pink-noise generator — every build is bit-identical. ``rise`` = the swell
# peak as a fraction of the duration (== lead_s / dur).
PACK: dict[str, dict] = {
    "whoosh-soft": {"family": "sweep", "dur": 0.55, "taps": (1200, 600, 300),
                    "rise": 0.60, "seed": 1101, "lead_s": 0.33,
                    "desc": "gentle falling air sweep (default-feel whoosh)"},
    "whoosh-hard": {"family": "sweep", "dur": 0.32, "taps": (2400, 1100, 480),
                    "rise": 0.62, "seed": 1102, "lead_s": 0.20,
                    "desc": "fast bright whoosh for hard world-changes"},
    "swish-up": {"family": "sweep", "dur": 0.42, "taps": (420, 900, 1900),
                 "rise": 0.70, "seed": 1103, "lead_s": 0.29,
                 "desc": "rising swish (reveals / upward wipes)"},
    "click": {"family": "tone", "dur": 0.12, "lead_s": 0.01,
              "expr": "(0.6*sin(2*PI*2400*t)+0.4*sin(2*PI*5200*t))*exp(-90*t)",
              "desc": "dry UI click (card lands, checkmarks)"},
    "pop": {"family": "tone", "dur": 0.18, "lead_s": 0.01,
            "expr": "sin(2*PI*(140*t+23.636*(1-exp(-22*t))))*exp(-16*t)",
            "desc": "bubble pop, 660→140 Hz chirp (playful reveals)"},
    "thud": {"family": "tone", "dur": 0.28, "lead_s": 0.01,
             "expr": "(0.8*sin(2*PI*85*t)+0.2*sin(2*PI*170*t))*exp(-14*t)",
             "desc": "soft low thud (statement cards, section drops)"},
}


def available() -> list[str]:
    """Sorted catalog names the SFX slot accepts."""
    return sorted(PACK)


def sfx_path(name: str) -> str:
    """Absolute path where ``name`` lives once built."""
    return os.path.join(SFX_DIR, f"{name}.wav")


def resolve(name: str) -> tuple[str, float]:
    """Resolve a named SFX to ``(abs_path, lead_s)``. NEVER fuzzy: an unknown
    name or a missing file raises ``ValueError`` with the fix spelled out."""
    if not isinstance(name, str) or name not in PACK:
        raise ValueError(f"unknown sfx {name!r} — the pack has: "
                         f"{', '.join(available())}")
    path = sfx_path(name)
    if not os.path.isfile(path):
        raise ValueError(f"sfx '{name}' is not built at {path} — run "
                         f"audio/sfx_library.py build")
    return path, float(PACK[name]["lead_s"])


def probe_peak_dbfs(path: str) -> float:
    """Overall peak level (dBFS) via astats (moved here from transitions.py so
    both the engine whoosh and the pack builder share one probe)."""
    res = subprocess.run(["ffmpeg", "-hide_banner", "-i", path,
                          "-af", "astats=metadata=0", "-f", "null", "-"],
                         capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"astats probe failed for {path}")
    for line in reversed(res.stderr.splitlines()):  # last block = Overall
        if "Peak level dB" in line:
            return float(line.split(":")[-1])
    raise RuntimeError(f"{path}: no astats peak in output")


def normalize_peak(raw: str, out: str, peak_dbfs: float = PEAK_DBFS) -> float:
    """Second pass: measure the true peak, re-render to the target, return it."""
    gain = peak_dbfs - probe_peak_dbfs(raw)
    run_ff(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", raw,
            "-af", f"volume={gain:.4f}dB", out])
    return probe_peak_dbfs(out)


def _sweep_fc(spec: dict) -> str:
    """Three bandpass taps hand off FIRST→LAST across the clip under a qsin
    swell peaking at ``rise * dur`` — the transitions.synth_whoosh recipe,
    parameterized (tap order sets fall vs rise)."""
    d, rise = spec["dur"], spec["rise"]
    f1, f2, f3 = spec["taps"]
    return (f"[0:a]asplit=3[h][m][l];"
            f"[h]bandpass=f={f1}:w={0.55 * f1:.0f},volume=eval=frame:"
            f"volume='clip(1-t/{d / 2:.3f},0,1)'[hb];"
            f"[m]bandpass=f={f2}:w={0.55 * f2:.0f},volume=eval=frame:"
            f"volume='1-abs(2*t/{d:.3f}-1)'[mb];"
            f"[l]bandpass=f={f3}:w={0.55 * f3:.0f},volume=eval=frame:"
            f"volume='clip((t-{0.35 * d:.3f})/{0.65 * d:.3f},0,1)'[lb];"
            f"[hb][mb][lb]amix=inputs=3:normalize=0,"
            f"afade=t=in:st=0:d={rise * d:.3f}:curve=qsin,"
            f"afade=t=out:st={rise * d:.3f}:d={(1 - rise) * d:.3f}:curve=qsin[a]")


def _synth_raw(name: str, raw: str) -> None:
    """Render the un-normalized asset for ``name`` (deterministic sources)."""
    spec = PACK[name]
    if spec["family"] == "sweep":
        run_ff(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i",
                f"anoisesrc=color=pink:r={_RATE}:amplitude=0.8:"
                f"seed={spec['seed']}:d={spec['dur']}",
                "-filter_complex", _sweep_fc(spec), "-map", "[a]", "-ac", "2", raw])
        return
    expr = spec["expr"]
    run_ff(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            f"aevalsrc={expr}|{expr}:s={_RATE}:d={spec['dur']}",
            "-ac", "2", raw])


def build(names: list[str] | None = None) -> dict[str, float]:
    """(Re)synthesize the pack into ``assets/sfx/``; returns {name: peak dBFS}.

    Two passes per asset (render → measure → normalize), like synth_whoosh.
    Unknown names raise via ``resolve``'s vocabulary (fail loud, no skip).
    """
    targets = names or available()
    unknown = [n for n in targets if n not in PACK]
    if unknown:
        raise ValueError(f"unknown sfx names {unknown} — the pack has: "
                         f"{', '.join(available())}")
    os.makedirs(SFX_DIR, exist_ok=True)
    peaks: dict[str, float] = {}
    for name in targets:
        out = sfx_path(name)
        raw = out + ".raw.wav"
        _synth_raw(name, raw)
        peaks[name] = normalize_peak(raw, out)
        os.unlink(raw)
    return peaks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PRODUCER starter SFX pack")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="catalog + build status")
    p_res = sub.add_parser("resolve", help="print the resolved path + lead")
    p_res.add_argument("name")
    p_build = sub.add_parser("build", help="(re)synthesize the pack")
    p_build.add_argument("names", nargs="*", help="subset (default: all)")
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            for n in available():
                status = "built" if os.path.isfile(sfx_path(n)) else "MISSING"
                print(f"{n:<14} lead={PACK[n]['lead_s']:.2f}s [{status}] "
                      f"{PACK[n]['desc']}")
        elif args.command == "resolve":
            path, lead = resolve(args.name)
            print(f"{path} lead_s={lead}")
        else:
            for n, peak in build(args.names or None).items():
                print(f"built {n} -> {sfx_path(n)} (peak {peak:.1f} dBFS)")
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
