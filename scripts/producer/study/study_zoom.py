#!/usr/bin/env python3
"""study_zoom — the ZOOM MAP: detect every punch-in / animated push on a cut.

Orchestrates the zoom study of an edited talking-head video against its cut list:
face-area series (``study_zoom_faces``) classifies each inter-cut shot; a
whole-frame ORB scale probe (``zoom_scale``) measures the actual zoom; the pure
detector (``zoom_detect``) turns those into PUNCH-IN CUTS (scale step across a
matched cut) and ANIMATED RAMPS (scale change within one shot). Each event is
tagged with WHAT IS BEING SAID at that moment from the transcript, so the payoff
table can extract the editor's zoom RULES. See docs/studies/LONGFORM_VISUAL_STUDY.md.

CLI:
    study_zoom.py <video.mp4> <frames_dir> <face_series.json> <out_dir>
                  [--transcript t.json] [--fps 5] [--scdet 8] [--cut-gap 0.2]
Writes ``<out_dir>/zoom_map.json`` + ``<out_dir>/zoom_map.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from study import zoom_detect as zd  # noqa: E402
from study.study_cuts import detect_cuts  # noqa: E402
from study.zoom_report import render_zoom_md  # noqa: E402
from study.zoom_scale import estimate_scale_paths, frame_index  # noqa: E402


def _load_face_series(path: str) -> tuple[list, float]:
    """(samples, fps) from a study_zoom_faces JSON."""
    data = json.load(open(path))
    return data["samples"], float(data.get("fps", 5.0))


def _cut_times(video: str, out_dir: str, scdet: float) -> list[float]:
    """scdet cut times, cached next to the outputs (re-run is expensive)."""
    cache = os.path.join(out_dir, "cut_times.json")
    if os.path.exists(cache):
        return json.load(open(cache))
    times = [c.time for c in detect_cuts(video, scdet)]
    json.dump(times, open(cache, "w"))
    return times


def _make_probes(frames_dir: str, fps: float, gap: float, cfg: dict):
    """Build (across-cut, shot-trajectory) ORB scale probes over the frame JPGs."""
    index = frame_index(frames_dir)
    guard, min_inl, segs = cfg["edge_guard_s"], cfg["min_inliers"], 6

    def _path(t: float) -> "str | None":
        seq = int(round(max(0.0, t) * fps)) + 1
        return index.get(seq) or index.get(seq - 1) or index.get(seq + 1)

    def _scale(t_a: float, t_b: float) -> tuple[float, int, bool]:
        pa, pb = _path(t_a), _path(t_b)
        if not pa or not pb:
            return 1.0, 0, False
        est = estimate_scale_paths(pa, pb)
        return est.scale, est.inliers, est.ok

    def across(t_end: float, t_start: float) -> tuple[float, int, bool]:
        return _scale(t_start - gap, t_start + gap)   # framing each side of the cut

    def scan(shot) -> zd.ShotScan:
        a, b = shot.start + guard, shot.end - guard
        pts = [a + (b - a) * i / segs for i in range(segs + 1)]
        return _scan_segments(pts, _scale, min_inl)

    return across, scan


def _scan_segments(pts: list[float], scale_fn, min_inl: int) -> "zd.ShotScan":
    """Per-segment scales along a shot → cumulative scale + step concentration."""
    seg, inl = [], []
    for i in range(len(pts) - 1):
        s, n, ok = scale_fn(pts[i], pts[i + 1])
        seg.append(s if (ok and n >= min_inl) else None)
        if ok and n >= min_inl:
            inl.append(n)
    trusted = [s for s in seg if s is not None]
    if len(trusted) < len(seg) - 1:
        s, n, ok = scale_fn(pts[0], pts[-1])
        return zd.ShotScan(s, n, ok, 0.0, (pts[0] + pts[-1]) / 2, s)
    cumulative = 1.0
    for s in trusted:
        cumulative *= s
    devs = [(abs(s - 1.0) if s is not None else 0.0) for s in seg]
    total = sum(devs) or 1e-9
    j = max(range(len(seg)), key=lambda i: devs[i])
    return zd.ShotScan(round(cumulative, 4), min(inl) if inl else 0, True,
                       round(devs[j] / total, 3), round((pts[j] + pts[j + 1]) / 2, 3),
                       round(seg[j] or 1.0, 4))


def _words(transcript_path: "str | None") -> list[dict]:
    """Flat word list [{word,start,end}] from a Deepgram-style transcript."""
    if not transcript_path or not os.path.exists(transcript_path):
        return []
    data = json.load(open(transcript_path))
    return [w for seg in data.get("transcript", []) for w in seg.get("words", [])]


def _said_at(words: list[dict], t: float, pre: float = 0.6, post: float = 2.0) -> tuple[str, float]:
    """(phrase spoken in [t-pre, t+post], time of the first of those words)."""
    hit = [w for w in words if t - pre <= w["start"] <= t + post]
    if not hit:
        return "", 0.0
    return " ".join(w["word"] for w in hit), round(hit[0]["start"], 2)


def _attach_transcript(events: list, words: list[dict]) -> None:
    """Fill said / said_t on each event in place."""
    for ev in events:
        ev.said, ev.said_t = _said_at(words, ev.t)


def _cadence(events: list, shots: list, duration: float) -> dict:
    """events/min, in:out ratio, magnitude distribution, framing-cut count."""
    mins = duration / 60.0
    ins = [e for e in events if e.direction == "in"]
    outs = [e for e in events if e.direction == "out"]
    punches = [e for e in events if e.kind == "punch_in_cut"]
    ramps = [e for e in events if e.kind == "ramp"]
    mags = sorted(abs(e.scale_pct) for e in events)
    return {
        "events": len(events), "eventsPerMin": round(len(events) / mins, 2),
        "punchInCuts": len(punches), "ramps": len(ramps),
        "in": len(ins), "out": len(outs),
        "inOutRatio": round(len(ins) / len(outs), 2) if outs else None,
        "scalePctMin": mags[0] if mags else 0.0,
        "scalePctMedian": round(median(mags), 1) if mags else 0.0,
        "scalePctMax": mags[-1] if mags else 0.0,
        "talkingHeadShots": sum(1 for s in shots if s.kind == "talking-head"),
        "cutawayShots": sum(1 for s in shots if s.kind == "cutaway"),
    }


def run(opts: argparse.Namespace) -> dict:
    """Full zoom study → zoom_map.json + zoom_map.md; returns the map dict."""
    video, frames_dir, out_dir = opts.video, opts.frames_dir, opts.out_dir
    os.makedirs(out_dir, exist_ok=True)
    samples, fps = _load_face_series(opts.series)
    duration = max(s["t"] for s in samples) + 1.0 / fps
    cut_times = _cut_times(video, out_dir, opts.scdet)
    cfg = dict(zd.DEFAULT_CFG)
    for key, val in (("ramp_scale_min", opts.ramp_min),
                     ("punch_scale_min", opts.punch_min),
                     ("min_inliers", opts.min_inliers)):
        if val is not None:
            cfg[key] = val
    across, scan = _make_probes(frames_dir, opts.fps, opts.cut_gap, cfg)
    shots = zd.build_shots(samples, cut_times, duration, cfg)
    in_shot = zd.detect_ramps(shots, scan, cfg)   # ramps + scdet-missed punches
    ramps = [e for e in in_shot if e.kind == "ramp"]
    punches = zd.detect_punch_cuts(shots, across, cfg) + [
        e for e in in_shot if e.kind == "punch_in_cut"]
    punches = zd.dedupe_events(punches, cfg["dedupe_window_s"])
    events = sorted(punches + ramps, key=lambda e: e.t)
    _attach_transcript(events, _words(opts.transcript))
    zoom_map = {
        "video": os.path.abspath(video), "duration": round(duration, 2),
        "fps": opts.fps, "scdet": opts.scdet, "cutCount": len(cut_times),
        "config": cfg, "cadence": _cadence(events, shots, duration),
        "events": zd.events_to_dicts(events),
        "cutaways": zd.cutaway_segments(shots),
        "shots": [vars(s) for s in shots],
    }
    json.dump(zoom_map, open(os.path.join(out_dir, "zoom_map.json"), "w"), indent=2)
    open(os.path.join(out_dir, "zoom_map.md"), "w").write(render_zoom_md(zoom_map))
    print(json.dumps({"status": "done", **zoom_map["cadence"]}, indent=2))
    return zoom_map


def main() -> int:
    p = argparse.ArgumentParser(description="ZOOM MAP for an edited talking-head video")
    p.add_argument("video")
    p.add_argument("frames_dir")
    p.add_argument("series")
    p.add_argument("out_dir")
    p.add_argument("--transcript")
    p.add_argument("--fps", type=float, default=5.0)
    p.add_argument("--scdet", type=float, default=8.0)
    p.add_argument("--cut-gap", type=float, default=0.2, dest="cut_gap")
    p.add_argument("--ramp-min", type=float, default=None, dest="ramp_min",
                   help="override ramp gate (|scale-1| linear); raise on noisier footage")
    p.add_argument("--punch-min", type=float, default=None, dest="punch_min",
                   help="override punch-in cut gate (|scale-1| linear)")
    p.add_argument("--min-inliers", type=int, default=None, dest="min_inliers",
                   help="override ORB inlier trust gate")
    run(p.parse_args())
    return 0


if __name__ == "__main__":
    sys.exit(main())
