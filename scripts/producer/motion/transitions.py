#!/usr/bin/env python3
"""transitions — seam-cover engine: white flashes + light-leak washes + whoosh SFX.

Doctrine (REFERENCE_STYLE_STUDY.md R15; audit record in
INTRO_MACHINE_VS_PRO_AUDIT.md §3/§5): a change of world may carry a seam
cover so it reads as deliberate — no naked butt joints between worlds. This
stage renders the seam-cover grammar deterministically:

* WHITE FLASH — ~3 frames total at the video's NATIVE fps, centered on the
  seam: one frame ramping toward white (~60%), one FULL-white frame on the
  seam, then instantly out (the next frame is the new shot, clean). Rendered
  frame-exactly with a ``geq`` screen-to-white ramp keyed on ``eq(N, seam)``.
* LIGHT-LEAK WASH — ~375 ms (9 frames @24fps, inside the measured 150-400ms
  band) warm wash that rises FAST and decays SLOW (attack 40% of the window,
  decay 60%), peaking ~78% opacity exactly on the seam. Luma uses screen-blend
  math (``255-(255-Y)*(255-L)/255``) so highlights blow out like a real leak;
  chroma drifts orange→pink across the wash (the leak reads orange first,
  pink on the tail). Envelope + drift are pure functions of T — no random.
* WHOOSH SFX — the audit measured transitions as AUDIOVISUAL: flash/wash
  moments carry −11..−15 dB whoosh peaks against a −40 dB speech-gap floor.
  One whoosh is synthesized from SEEDED pink noise through three descending
  bandpass taps crossfaded over ~0.45 s (a falling sweep), normalized to
  −15 dBFS peak, and delayed so the swell LANDS on the seam (it starts ~0.3 s
  before ``outTime``). Mixed with ``amix=normalize=0`` so the dialogue is NOT
  attenuated; ``duration=first`` pins the audio length to the source. SFX ≠
  music — the no-music-by-default rule stands; whooshes ride transitions only.

Video preserves the input frame count EXACTLY (``geq`` is 1:1; asserted like
punch_in.py) and re-encodes at the mezzanine spec. Audio is aac 192k when SFX
are mixed, stream-copied when every event carries ``sfx: false``. Editorial
density (max events/min) is the plan lint's job — ``MOTION["transitions"]`` —
this primitive only enforces hard sanity (sorted, spaced, in-range).

The ffmpeg-xfade family (stock fades/wipes/slides) was REMOVED 2026-07-11 —
operator-rejected on sight (FAILURE_LEDGER LL-014). Longform seams use ONLY
Sniper's seam grammar (panel sweeps, face-bridged recomposition, under-panel
cuts, blur-recede, seam-role zoom-pulls — MODULE_STUDY.md §2,
EDITCRAFT_LESSONS.md §2.7); flash/leak stay only at their seam role.

* ZOOM-PULL (kind "zoom-pull", continuity mechanism CM-1) — an EASED digital
  zoom bridging the seam, three variants (punch-cut / whip / settle)
  rendered by ``motion/zoom_pull.py`` (punch-engine expression reuse; the
  punch-cut's sequential light-leak/flash cover rides the same event).
  Longform-only at the lint gate; budget-counted with the other seams.

CLI:
    transitions.py <in.mp4> <out.mp4> --events <events.json | inline-json>
where each event is:
    {"outTime": 8.0, "kind": "white-flash" | "light-leak" | "zoom-pull",
     "sfx": true | false | "<pack-name>"}  (+ zoom_pull.py's variant fields)
(``sfx`` defaults false; sound is opt-in. A NAME resolves through
audio/sfx_library to a vendored one-shot whose hit is delayed onto the seam).
Events must be sorted, >= 1.0s apart, and inside the duration with a 0.5s
edge margin — validated, ValueError otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audio.sfx_library import probe_peak_dbfs  # noqa: E402
from audio.sfx_library import resolve as resolve_sfx  # noqa: E402
from audio.channel_normalization import (  # noqa: E402
    ChannelAuthority,
    observe_channel_authority,
    system_program_request,
)
from cut_speed import (has_audio, probe_duration, probe_video,  # noqa: E402
                       probe_video_frames, run_ff)
from motion import zoom_pull as zp  # noqa: E402
from producer_config import ENCODE  # noqa: E402

KINDS = ("white-flash", "light-leak", "zoom-pull")
MIN_SPACING_S = 1.0          # hard floor between seams (lint may be stricter)
EDGE_MARGIN_S = 0.5          # a seam needs room for its wash/whoosh both sides
FLASH_WASH_ALPHA = 0.6       # the pre-seam frame ramps ~60% toward white
LEAK_DUR_S = 0.375           # 9 frames @24fps — inside the 330-420ms band
LEAK_ATTACK_FRAC = 0.40      # fast rise (40% of window), slower decay (60%)
LEAK_PEAK = 0.78             # peak opacity at the seam (70-85% measured band)
LEAK_LUMA = 210.0            # leak brightness fed to the screen blend
# Leak chroma drift, BT.601: orange (255,140,50) → pink (255,105,180).
LEAK_U0, LEAK_U1 = 64.0, 140.0
LEAK_V0, LEAK_V1 = 193.0, 197.0
WHOOSH_DUR_S = 0.45          # 0.35-0.5s band
WHOOSH_LEAD_S = 0.30         # whoosh starts this far BEFORE the seam (swell peak)
SFX_PEAK_DBFS = -15.0        # audit §3: −11..−15 dB transition peaks
SFX_AUDIO_BITRATE = "192k"   # remix bitrate when whooshes are mixed in
NOISE_SEED = 4242            # seeded anoisesrc → bit-identical whoosh every run
FRAME_TOL = 0                # geq is 1:1 — the frame count must not move at all
AUDIO_DUR_TOL_S = 0.05       # AAC re-encode priming/padding slack


@dataclass(frozen=True)
class TransitionEvent:
    """One seam to cover: output time, treatment kind, SFX slot.

    ``sfx``: True = synthesized whoosh, False = silent, "<name>" = a
    vendored one-shot from audio/sfx_library (hit delayed onto the seam).
    ``zoom``: the resolved ``zoom_pull.ZoomPullSpec`` for kind "zoom-pull"
    (None for flash/leak).
    """

    out_time: float
    kind: str
    sfx: bool | str = False
    zoom: "zp.ZoomPullSpec | None" = None


@dataclass(frozen=True)
class _TransitionAudio:
    inputs: tuple[str, ...]
    filter_suffix: str
    map_args: tuple[str, ...]
    whoosh_peak_dbfs: float | None
    authority: ChannelAuthority | None


def emit(**fields) -> None:
    """One JSON status object per line on stdout (NDJSON, like the sibling stages)."""
    print(json.dumps(fields), flush=True)


def parse_events(raw: object, duration: float) -> list[TransitionEvent]:
    """Validate a raw event list into ``TransitionEvent``s (raises on bad input).

    Enforced: non-empty array of objects, known ``kind``, boolean ``sfx``,
    ``outTime`` inside ``[EDGE_MARGIN_S, duration - EDGE_MARGIN_S]``, and the
    list SORTED with >= ``MIN_SPACING_S`` between consecutive seams.
    """
    if not isinstance(raw, list) or not raw:
        raise ValueError("events must be a non-empty JSON array")
    events: list[TransitionEvent] = []
    for i, ev in enumerate(raw):
        if not isinstance(ev, dict):
            raise ValueError(f"event[{i}] must be an object")
        try:
            t = float(ev["outTime"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"event[{i}] needs a numeric outTime: {exc}") from exc
        # A visual seam is silent unless the plan explicitly asks for sound.
        # This keeps routine transitions from becoming a distracting SFX bed.
        kind, sfx = ev.get("kind"), ev.get("sfx", False)
        if isinstance(kind, str) and kind.startswith("xfade:"):
            raise ValueError(
                f"event[{i}]: kind {kind!r} — operator-rejected (LL-014): "
                "use Sniper's longform transition grammar (panel sweeps, "
                "face-bridged recomposition, under-panel cuts, blur-recede, "
                "seam-role zoom-pulls), never stock wipes/slides/dissolves")
        if kind not in KINDS:
            raise ValueError(f"event[{i}]: kind {kind!r} not in {KINDS}")
        if isinstance(sfx, str):
            resolve_sfx(sfx)        # ValueError for an unknown/unbuilt name
        elif not isinstance(sfx, bool):
            raise ValueError(f"event[{i}]: sfx must be a boolean or a pack "
                             "name (audio/sfx_library)")
        if not (EDGE_MARGIN_S <= t <= duration - EDGE_MARGIN_S):
            raise ValueError(f"event[{i}]: outTime {t} outside [{EDGE_MARGIN_S}, "
                             f"{duration - EDGE_MARGIN_S:.2f}] (duration {duration:.2f}s)")
        zoom = zp.parse_event(i, ev, duration) if kind == "zoom-pull" else None
        events.append(TransitionEvent(t, kind, sfx, zoom))
    for a, b in zip(events, events[1:]):
        if b.out_time - a.out_time < MIN_SPACING_S:
            raise ValueError(f"events must be sorted and >= {MIN_SPACING_S}s apart: "
                             f"outTime {a.out_time} then {b.out_time}")
    zooms = [e.zoom for e in events if e.zoom is not None]
    for a, b in zip(zooms, zooms[1:]):
        if b.span[0] < a.span[1] - 1e-6:
            raise ValueError(f"zoom-pull footprints overlap: seam {a.out_time}"
                             f" spans {a.span}, seam {b.out_time} spans {b.span}")
    return events


def _fps_float(raw: str) -> float:
    """r_frame_rate string ("30/1", "24000/1001") → float fps (raises if unusable)."""
    num, den = (raw.split("/") + ["1"])[:2]
    fps = int(num) / max(1, int(den))
    if fps <= 0:
        raise RuntimeError(f"unusable r_frame_rate {raw!r}")
    return fps


def _flash_geq(events: list[TransitionEvent], fps: float) -> str | None:
    """One ``geq`` covering ALL white flashes: per-frame ramp toward white.

    The seam frame index is ``round(outTime * fps)``; the envelope is
    ``FLASH_WASH_ALPHA`` on the frame before it and 1.0 exactly on it — the
    frame after is untouched (the "new shot" leg of the 3-frame grammar).
    """
    seams = [round(e.out_time * fps) for e in events if e.kind == "white-flash"]
    if not seams:
        return None
    env = "+".join(f"({FLASH_WASH_ALPHA}*eq(N,{n - 1})+eq(N,{n}))" for n in seams)
    enable = "+".join(f"between(n,{n - 1},{n})" for n in seams)
    return (f"geq=lum='lum(X,Y)+({env})*(255-lum(X,Y))'"
            f":cb='cb(X,Y)+({env})*(128-cb(X,Y))'"
            f":cr='cr(X,Y)+({env})*(128-cr(X,Y))'"
            f":enable='{enable}'")


def _leak_geq(e: TransitionEvent) -> str:
    """One ``geq`` for one light-leak: asymmetric envelope + orange→pink drift.

    Envelope rises over the attack (40% of the window) to ``LEAK_PEAK`` at the
    seam, decays over the rest. Luma is screen-blended toward ``LEAK_LUMA`` so
    highlights blow out; chroma mixes toward the drifting leak U/V.
    """
    att = LEAK_DUR_S * LEAK_ATTACK_FRAC
    dec = LEAK_DUR_S - att
    ls, le = e.out_time - att, e.out_time + dec
    env = (f"({LEAK_PEAK}*min(clip((T-{ls:.6f})/{att:.6f},0,1),"
           f"clip(({le:.6f}-T)/{dec:.6f},0,1)))")
    drift = f"clip((T-{ls:.6f})/{LEAK_DUR_S:.6f},0,1)"
    u = f"({LEAK_U0}+{LEAK_U1 - LEAK_U0:.1f}*{drift})"
    v = f"({LEAK_V0}+{LEAK_V1 - LEAK_V0:.1f}*{drift})"
    return (f"geq=lum='255-(255-lum(X,Y))*(255-{LEAK_LUMA}*{env})/255'"
            f":cb='cb(X,Y)+{env}*({u}-cb(X,Y))'"
            f":cr='cr(X,Y)+{env}*({v}-cr(X,Y))'"
            f":enable='between(t,{ls:.6f},{le:.6f})'")


def _cover_events(events: list[TransitionEvent]) -> list[TransitionEvent]:
    """Synthesized flash/leak covers for punch-cut zoom-pulls (CM-1,
    EDITCRAFT_LESSONS §2.7: the zoom completes BEFORE the seam; the cut
    itself is covered — zoom and
    cover are sequential, one event). SFX rides the parent event."""
    return [TransitionEvent(e.out_time, e.zoom.cover, False)
            for e in events
            if e.zoom is not None and e.zoom.cover]


def build_video_filter(events: list[TransitionEvent], fps: float,
                       dims: tuple[int, int] = (0, 0)) -> str:
    """The [0:v]→[vout] chain: zoom-pulls (scale+crop), flashes, leaks.

    Every stage is 1:1 (``geq`` per-pixel, ``scale``/``crop`` per-frame) and
    ``enable``/z(t)=1 gates the cost to the covered frames only — the frame
    count is preserved exactly. Punch-cut zoom-pulls contribute their seam
    cover (leak/flash) to the same chain via :func:`_cover_events`.
    """
    chain = [f"format={ENCODE['pix_fmt']}", "setsar=1"]
    covered = events + _cover_events(events)
    for e in events:
        if e.zoom is not None:
            chain += zp.chain_filters(e.zoom, *dims)
    flash = _flash_geq(covered, fps)
    if flash:
        chain.append(flash)
    chain += [_leak_geq(e) for e in covered if e.kind == "light-leak"]
    return "[0:v]" + ",".join(chain) + "[vout]"


def probe_audio_duration(path: str) -> float:
    """First audio stream's duration in seconds (raises if there is none)."""
    out = run_ff(["ffprobe", "-v", "error", "-select_streams", "a:0",
                  "-show_entries", "stream=duration",
                  "-of", "default=noprint_wrappers=1:nokey=1", path])
    return float(out.strip().splitlines()[0])


def synth_whoosh(wav_path: str) -> float:
    """Synthesize the deterministic whoosh; returns its normalized peak dBFS.

    Seeded pink noise splits into three bandpass taps (1600→800→380 Hz) whose
    volume envelopes hand off high→low across the clip — a falling sweep — under
    an overall swell that peaks at ``WHOOSH_LEAD_S`` (the seam once delayed).
    Two passes: render, measure the true peak, re-render normalized to target.
    """
    d, rise = WHOOSH_DUR_S, WHOOSH_LEAD_S
    fc = (f"[0:a]asplit=3[h][m][l];"
          f"[h]bandpass=f=1600:w=900,volume=eval=frame:"
          f"volume='clip(1-t/{d / 2:.3f},0,1)'[hb];"
          f"[m]bandpass=f=800:w=450,volume=eval=frame:"
          f"volume='1-abs(2*t/{d:.3f}-1)'[mb];"
          f"[l]bandpass=f=380:w=240,volume=eval=frame:"
          f"volume='clip((t-{0.35 * d:.3f})/{0.65 * d:.3f},0,1)'[lb];"
          f"[hb][mb][lb]amix=inputs=3:normalize=0,"
          f"afade=t=in:st=0:d={rise:.3f}:curve=qsin,"
          f"afade=t=out:st={rise:.3f}:d={d - rise:.3f}:curve=qsin[a]")
    raw = wav_path + ".raw.wav"
    run_ff(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
            "-i", f"anoisesrc=color=pink:r={ENCODE['audio_rate']}:"
                  f"amplitude=0.8:seed={NOISE_SEED}:d={d}",
            "-filter_complex", fc, "-map", "[a]", "-ac", "2", raw])
    gain = SFX_PEAK_DBFS - probe_peak_dbfs(raw)
    run_ff(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", raw,
            "-af", f"volume={gain:.4f}dB", wav_path])
    os.unlink(raw)
    return probe_peak_dbfs(wav_path)


def _sfx_key(e: TransitionEvent) -> object:
    """Group key for an event's SFX source: a pack name, or True (synth)."""
    return e.sfx if isinstance(e.sfx, str) else True


def build_audio_graph(sfx_events: list[TransitionEvent],
                      sources: dict[object, tuple[int, float]],
                      normalization_filter: str = "anull") -> str:
    """Delay each event's SFX copy so its HIT lands on the seam; mix onto the
    dialogue untouched.

    ``sources`` maps a group key (True = synth whoosh, or a pack name) to its
    ffmpeg input index + lead seconds. ``normalize=0`` keeps the input audio
    at unity (no 1/N attenuation); ``duration=first`` pins the output length
    to the source audio.
    """
    parts: list[str] = []
    delayed: list[str] = []
    for key, (idx, lead) in sources.items():
        evs = [e for e in sfx_events if _sfx_key(e) == key]
        taps = [f"[{idx}:a]"]
        if len(evs) > 1:
            taps = [f"[i{idx}s{j}]" for j in range(len(evs))]
            parts.append(f"[{idx}:a]asplit={len(evs)}" + "".join(taps))
        for tap, e in zip(taps, evs):
            ms = max(0, int(round((e.out_time - lead) * 1000)))
            lbl = f"[d{len(delayed)}]"
            parts.append(f"{tap}adelay={ms}|{ms}{lbl}")
            delayed.append(lbl)
    parts.append(f"[0:a]{normalization_filter}[program]")
    parts.append("[program]" + "".join(delayed) +
                 f"amix=inputs={len(delayed) + 1}:duration=first:normalize=0[aout]")
    return ";".join(parts)


def _assert_preserved(src_path: str, out_path: str, in_frames: int,
                      check_audio: bool) -> dict:
    """Hard-error if the frame count moved at all or audio duration drifted."""
    out_frames = probe_video_frames(out_path)
    if abs(out_frames - in_frames) > FRAME_TOL:
        raise RuntimeError(f"transitions changed frame count: in {in_frames} -> "
                           f"out {out_frames}")
    fields = {"inFrames": in_frames, "outFrames": out_frames}
    if check_audio:
        a_in, a_out = probe_audio_duration(src_path), probe_audio_duration(out_path)
        fields.update(audioInS=round(a_in, 4), audioOutS=round(a_out, 4))
        if abs(a_out - a_in) > AUDIO_DUR_TOL_S:
            raise RuntimeError(f"transitions changed audio duration: "
                               f"{a_in:.3f}s -> {a_out:.3f}s")
    return fields


def _transition_audio(
    src_path: str,
    work: str,
    sfx_events: list[TransitionEvent],
) -> _TransitionAudio:
    """Prepare SFX inputs and the normalized program-audio graph."""
    if not sfx_events:
        return _TransitionAudio(
            (), "", ("-map", "0:a?", "-c:a", "copy"), None, None)
    authority = observe_channel_authority(system_program_request(src_path))
    inputs: list[str] = []
    sources: dict[object, tuple[int, float]] = {}
    whoosh_peak = None
    if any(event.sfx is True for event in sfx_events):
        wav = os.path.join(work, "whoosh.wav")
        whoosh_peak = synth_whoosh(wav)
        inputs.extend(["-i", wav])
        sources[True] = (len(sources) + 1, WHOOSH_LEAD_S)
    names = sorted({
        event.sfx for event in sfx_events
        if isinstance(event.sfx, str)
    })
    for name in names:
        path, lead = resolve_sfx(name)
        inputs.extend(["-i", path])
        sources[name] = (len(sources) + 1, lead)
    graph = ";" + build_audio_graph(
        sfx_events, sources, authority.filter_for("stereo"))
    mapping = (
        "-map", "[aout]", "-c:a", ENCODE["acodec"],
        "-b:a", SFX_AUDIO_BITRATE, "-ar", str(ENCODE["audio_rate"]),
        "-ac", str(ENCODE["audio_channels"]),
    )
    return _TransitionAudio(
        tuple(inputs), graph, mapping, whoosh_peak, authority)


def apply_transitions(src_path: str, raw_events: object, out_path: str) -> dict:
    """Validate the events against ``src_path`` and render them into ``out_path``.

    Video re-encodes at mezzanine CRF (frame count asserted unchanged). Audio:
    aac 192k with the whoosh mix when any event wants SFX (and the source has
    audio), stream-copy otherwise. Returns the NDJSON-ready result dict.
    """
    duration = probe_duration(src_path)
    stream = probe_video(src_path)
    fps = _fps_float(stream["r_frame_rate"])
    dims = (int(stream["width"]), int(stream["height"]))
    events = parse_events(raw_events, duration)
    in_frames = probe_video_frames(src_path)
    src_audio = has_audio(src_path)
    sfx_events = [e for e in events if e.sfx] if src_audio else []
    if not src_audio and any(e.sfx for e in events):
        emit(stage="transitions", status="warn",
             reason="input has no audio stream; sfx skipped")
    work = tempfile.mkdtemp(prefix="producer-transitions-")
    try:
        audio = _transition_audio(src_path, work, sfx_events)
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-i", src_path, *audio.inputs]
        fc = build_video_filter(events, fps, dims) + audio.filter_suffix
        cmd += ["-filter_complex", fc, "-map", "[vout]", *audio.map_args,
                "-c:v", "libx264", "-crf", str(ENCODE["mezzanine_crf"]),
                "-preset", ENCODE["mezzanine_preset"],
                "-pix_fmt", ENCODE["pix_fmt"], "-fps_mode", "passthrough",
                "-movflags", "+faststart", out_path]
        run_ff(cmd)
        if audio.authority is not None:
            audio.authority.assert_stable()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    result = {"fps": round(fps, 3), "events": len(events),
              "flashes": sum(1 for e in events if e.kind == "white-flash"),
              "leaks": sum(1 for e in events if e.kind == "light-leak"),
              "zoomPulls": sum(1 for e in events if e.kind == "zoom-pull"),
              "sfx": len(sfx_events),
              "whooshPeakDbfs": audio.whoosh_peak_dbfs}
    if audio.authority is not None:
        result["channelNormalization"] = audio.authority.receipt
    result.update(_assert_preserved(src_path, out_path, in_frames,
                                    check_audio=src_audio))
    return result


def _load_events(spec: str) -> object:
    """Events are either a path to a JSON file or an inline JSON string."""
    if os.path.exists(spec):
        with open(spec) as f:
            return json.load(f)
    return json.loads(spec)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="PRODUCER seam-cover engine: white flashes + light-leak "
                    "washes with whoosh SFX (per output-time event)")
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--events", required=True,
                    help="JSON file path OR inline JSON array of transition events")
    args = ap.parse_args()
    try:
        raw = _load_events(args.events)
        emit(stage="transitions", status="start")
        result = apply_transitions(args.src, raw, args.out)
        emit(stage="transitions", status="done", **result)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        emit(error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
