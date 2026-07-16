#!/usr/bin/env python3
"""broll_insert — the RECEIPTS engine: b-roll rides ON TOP, never touches audio.

Research (INTRO_MACHINE_VS_PRO_AUDIT.md §2, REFERENCE_STYLE_STUDY.md R17,
EDIT_DECISION_STUDY.md, 2026-07-05): the pro cuts to RECEIPTS — his real
channel page, his old clips, his product sites — for 1-4s while HIS SPEECH
AUDIO CONTINUES UNINTERRUPTED underneath. B-roll is a VIDEO-ONLY replacement
track: for each insert window the base video's frames are replaced by the
asset's frames, and the base audio passes through UNTOUCHED for the whole file
(audio stream-copy — bit-identical, provable by stream md5).

How it renders: one filter graph. The base is ``[0:v]``; each asset becomes an
input, trimmed at ``assetStart``, retimed onto the output clock at its window
(``setpts`` shift after an ``fps`` resample to the base cadence), fitted to the
base geometry, and overlaid OPAQUE via ``overlay=enable='between(t,s,e)'``
(the punch_in/transitions overlay-on-base pattern; an opaque full-frame
overlay IS a replacement). Overlay emits one frame per base frame, so the
output preserves the base's frame count EXACTLY (asserted, tolerance 0, like
transitions.py). Video re-encodes at the mezzanine spec.

Fit: receipts fill the frame — scale-to-cover + center-crop — unless the
asset's aspect is far from the base's (portrait screen-recording into a
landscape long-form), where cover would gut the receipt: those fall back to
scale-to-fit over a dark blurred pad of themselves (reframe.py's blurpad
idiom, applied per branch).

Hard sanity enforced here (ValueError): windows sorted + non-overlapping,
>= ``EDGE_MARGIN_S`` inside the timeline edges, duration in
[``MIN_INSERT_S``, the mode preset's ``broll_insert_max_s``]; assetId resolved
against the manifest ``broll`` catalog (paths may be relative to the manifest
file's dir, the render.py transcriptPath convention); an asset shorter than
``assetStart`` + the window is a hard error — never loop or freeze-frame
silently (no-fallbacks doctrine). Editorial rules (insert count cap, required
``reason``, title-card collisions) are plan_lint._check_broll's job.

IMAGE-FOCUS OPS (LIAM-4-MOVES move 3, additive): an insert may carry a
``focusOps`` array (region highlight wipe, darken/blur-surround, signed hue
shift per ``MOTION["hue_shift_semantics"]``) rendered INTO its branch by
``broll/focus_ops.py`` — all 1:1 filters, so the exact-frame-count contract
and the untouched-audio guarantee are unchanged. Times are relative to the
insert's ``outStart``; validation is ``focus_ops.parse_ops`` (the same
function ``plan_lint_broll.check_focus_ops`` gates with — no drift).

CLI:
    broll_insert.py <base.mp4> <out.mp4> --inserts <json|inline>
                    --manifest <asset_manifest.json> [--mode short|longform]
where each insert is:
    {"assetId": "receipt-a", "outStart": 4.0, "outEnd": 6.5, "assetStart": 0.0,
     "focusOps": [...]}
(``assetStart`` = offset into the asset, default 0.0; ``focusOps`` optional —
see broll/focus_ops.py for the op vocabulary.)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broll import focus_ops as fops  # noqa: E402
from cut_speed import (display_dims, has_audio, probe_duration,  # noqa: E402
                       probe_video, probe_video_frames, run_ff)
from producer_config import ENCODE, MODES  # noqa: E402

EDGE_MARGIN_S = 0.5     # a receipt needs the timeline to exist both sides
MIN_INSERT_S = 0.8      # shorter reads as a glitch, not a receipt
# Cover-crop tolerates this much aspect mismatch (4:3 into 16:9 = 1.33x loses
# 25% and still reads); beyond it (portrait into landscape = 3.16x) the crop
# would gut the receipt -> blurpad fit instead.
COVER_ASPECT_TOL = 1.5
# Trim this much extra asset tail past the window (when the asset has it) so
# fps-resample rounding can't leave the window's last frame uncovered.
TAIL_SLACK_S = 0.25
FRAME_TOL = 0           # overlay is 1:1 — the frame count must not move at all


@dataclass(frozen=True)
class BrollInsert:
    """One receipt: an output-time window whose frames the asset replaces.

    ``asset_start`` is the offset INTO the asset where its material begins;
    ``path`` is the manifest-resolved absolute file path (filled by
    :func:`resolve_assets` — empty until then). ``focus_ops`` are the
    insert's parsed image-focus operators (LIAM move 3; () = none).
    """

    asset_id: str
    out_start: float
    out_end: float
    asset_start: float = 0.0
    path: str = ""
    focus_ops: tuple = ()

    @property
    def dur(self) -> float:
        """The window length in output seconds."""
        return self.out_end - self.out_start


def emit(**fields) -> None:
    """One JSON status object per line on stdout (NDJSON, like the sibling stages)."""
    print(json.dumps(fields), flush=True)


def _one_insert(i: int, b: object, duration: float,
                max_insert_s: float) -> BrollInsert:
    """Validate a single raw insert entry (raises ValueError on bad input)."""
    if not isinstance(b, dict):
        raise ValueError(f"insert[{i}] must be an object")
    try:
        s, e = float(b["outStart"]), float(b["outEnd"])
        a0 = float(b.get("assetStart", 0.0))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"insert[{i}] needs numeric outStart/outEnd: {exc}") from exc
    aid = b.get("assetId")
    if not isinstance(aid, str) or not aid:
        raise ValueError(f"insert[{i}]: assetId must be a non-empty string")
    if a0 < 0.0:
        raise ValueError(f"insert[{i}]: assetStart must be >= 0")
    if not (EDGE_MARGIN_S <= s < e <= duration - EDGE_MARGIN_S):
        raise ValueError(
            f"insert[{i}]: window [{s},{e}] must sit >= {EDGE_MARGIN_S}s inside "
            f"the timeline edges (duration {duration:.2f}s)")
    if e - s < MIN_INSERT_S:
        raise ValueError(f"insert[{i}]: {e - s:.2f}s is under the "
                         f"{MIN_INSERT_S}s minimum insert")
    if e - s > max_insert_s + 1e-6:
        raise ValueError(f"insert[{i}]: {e - s:.2f}s exceeds the mode's "
                         f"broll_insert_max_s {max_insert_s}s")
    try:
        ops = fops.parse_ops(b.get("focusOps"), e - s)
    except ValueError as exc:
        raise ValueError(f"insert[{i}]: {exc}") from exc
    return BrollInsert(aid, s, e, a0, focus_ops=ops)


def parse_inserts(raw: object, duration: float,
                  max_insert_s: float) -> list[BrollInsert]:
    """Validate a raw insert list into sorted ``BrollInsert``s (raises on bad).

    Enforced: non-empty array; per-entry schema + window bounds
    (:func:`_one_insert`); windows sorted and non-overlapping on the output
    timeline. Extra keys (``reason``, ``rationale``) are ignored — the plan
    lint owns them.
    """
    if not isinstance(raw, list) or not raw:
        raise ValueError("inserts must be a non-empty JSON array")
    ordered = sorted((_one_insert(i, b, duration, max_insert_s)
                      for i, b in enumerate(raw)), key=lambda x: x.out_start)
    for a, b in zip(ordered, ordered[1:]):
        if b.out_start < a.out_end - 1e-6:
            raise ValueError(f"b-roll windows overlap: [{a.out_start},{a.out_end}]"
                             f" then [{b.out_start},{b.out_end}]")
    return ordered


def resolve_assets(inserts: list[BrollInsert],
                   manifest: dict) -> list[BrollInsert]:
    """Resolve each assetId to a probed, long-enough asset file path.

    Manifest ``broll`` entries carry ``{id, path, ...}``; relative paths
    resolve against the manifest file's dir via ``manifest["_path"]`` (the
    render.py transcriptPath convention). An asset that cannot cover
    ``assetStart`` + the window is a hard ValueError — never loop or
    freeze-frame silently (no-fallbacks doctrine).
    """
    manifest_dir = os.path.dirname(os.path.abspath(manifest.get("_path", "")))
    catalog = {b.get("id"): b for b in manifest.get("broll", [])}
    resolved: list[BrollInsert] = []
    for i, ins in enumerate(inserts):
        entry = catalog.get(ins.asset_id)
        if entry is None:
            raise ValueError(f"insert[{i}]: assetId {ins.asset_id!r} not in "
                             "manifest broll")
        if entry.get("kind") == "image":
            raise ValueError(f"insert[{i}]: asset {ins.asset_id!r} is a still "
                             "image — this stage inserts video receipts only")
        rel = entry.get("path")
        if not rel:
            raise ValueError(f"insert[{i}]: manifest broll entry "
                             f"{ins.asset_id!r} has no path")
        path = rel if os.path.isabs(rel) else os.path.join(manifest_dir, rel)
        if not os.path.exists(path):
            raise ValueError(f"insert[{i}]: asset file missing: {path}")
        adur, need = probe_duration(path), ins.asset_start + ins.dur
        if need > adur + 1e-3:
            raise ValueError(
                f"insert[{i}]: asset {ins.asset_id!r} too short — needs "
                f"{need:.2f}s (assetStart {ins.asset_start} + window "
                f"{ins.dur:.2f}s) but the asset is {adur:.2f}s")
        resolved.append(replace(ins, path=path))
    return resolved


def _fit_mode(asset_dims: tuple[int, int], base_dims: tuple[int, int]) -> str:
    """"cover" (fill + center-crop) or "blurpad" (fit over a blurred pad)."""
    a = asset_dims[0] / asset_dims[1]
    b = base_dims[0] / base_dims[1]
    return "cover" if max(a / b, b / a) <= COVER_ASPECT_TOL else "blurpad"


def _branch_parts(idx: int, ins: BrollInsert, prof: dict,
                  asset_dims: tuple[int, int]) -> list[str]:
    """Filter parts turning input ``idx+1`` into the window-timed ``[b{idx}]``.

    The asset is trimmed at ``assetStart`` (+ tail slack when it has it),
    zero-based, resampled to the base cadence so the enable window is covered
    frame-for-frame, then PTS-shifted onto its output window and fitted to the
    base geometry (cover-crop, or reframe.py's blurpad idiom for odd aspects).
    Focus ops (LIAM move 3) chain AFTER the fit — their regions are frame
    coordinates on the fitted (base-canvas) insert, and the branch is already
    on the output clock, so their enable windows are absolute output time.
    """
    a0 = ins.asset_start
    a1 = a0 + ins.dur + TAIL_SLACK_S
    pre = (f"[{idx + 1}:v]trim=start={a0:.6f}:end={a1:.6f},setpts=PTS-STARTPTS,"
           f"fps={prof['fps']},setpts=PTS+{ins.out_start:.6f}/TB")
    w, h = prof["w"], prof["h"]
    fit = f"b{idx}" if not ins.focus_ops else f"fit{idx}"
    if _fit_mode(asset_dims, (w, h)) == "cover":
        parts = [f"{pre},scale={w}:{h}:force_original_aspect_ratio=increase:"
                 f"flags=bicubic,crop={w}:{h},setsar=1[{fit}]"]
    else:
        parts = [f"{pre},setsar=1,split=2[bg{idx}][fg{idx}]",
                 f"[bg{idx}]scale={w}:{h}:force_original_aspect_ratio=increase,"
                 f"crop={w}:{h},boxblur=20:2,eq=brightness=-0.12[bgb{idx}]",
                 f"[fg{idx}]scale={w}:{h}:force_original_aspect_ratio=decrease:"
                 f"flags=bicubic[fgs{idx}]",
                 f"[bgb{idx}][fgs{idx}]overlay=(W-w)/2:(H-h)/2,setsar=1[{fit}]"]
    if ins.focus_ops:
        parts += fops.branch_parts(ins.focus_ops, (w, h, ins.out_start),
                                   fit, f"b{idx}")
    return parts


def build_filter(inserts: list[BrollInsert], prof: dict,
                 asset_dims: list[tuple[int, int]]) -> str:
    """filter_complex: base + one fitted branch per insert, each overlaid
    OPAQUE only inside its window. ``eof_action=pass`` hands the frame back to
    the base once a branch ends; overlay preserves the base frame count."""
    parts = ["[0:v]setsar=1[v0]"]
    cur = "v0"
    for i, (ins, dims) in enumerate(zip(inserts, asset_dims)):
        parts += _branch_parts(i, ins, prof, dims)
        parts.append(f"[{cur}][b{i}]overlay=eof_action=pass:enable="
                     f"'between(t,{ins.out_start:.6f},{ins.out_end:.6f})'[o{i}]")
        cur = f"o{i}"
    parts.append(f"[{cur}]format={ENCODE['pix_fmt']}[vout]")
    return ";".join(parts)


def apply_broll_inserts(base_path: str, inserts: list[BrollInsert],
                        out_path: str) -> dict:
    """Render the resolved inserts over ``base_path`` into ``out_path``.

    Video re-encodes at mezzanine CRF; the base audio is STREAM-COPIED —
    bit-identical, the R17 speech-continues guarantee. Asserts the output
    frame count equals the base's exactly (``FRAME_TOL`` = 0).
    """
    stream = probe_video(base_path)
    w, h = display_dims(stream)
    prof = {"w": w, "h": h, "fps": stream["r_frame_rate"]}
    in_frames = probe_video_frames(base_path)
    asset_dims = [display_dims(probe_video(ins.path)) for ins in inserts]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", base_path]
    for ins in inserts:
        cmd += ["-i", ins.path]
    cmd += ["-filter_complex", build_filter(inserts, prof, asset_dims),
            "-map", "[vout]", "-map", "0:a?",
            "-c:v", "libx264", "-crf", str(ENCODE["mezzanine_crf"]),
            "-preset", ENCODE["mezzanine_preset"], "-pix_fmt", ENCODE["pix_fmt"],
            "-fps_mode", "passthrough", "-c:a", "copy",
            "-movflags", "+faststart", out_path]
    run_ff(cmd)
    out_frames = probe_video_frames(out_path)
    if abs(out_frames - in_frames) > FRAME_TOL:
        raise RuntimeError(f"broll_insert changed frame count: in {in_frames} "
                           f"-> out {out_frames}")
    modes = [_fit_mode(d, (w, h)) for d in asset_dims]
    return {"width": w, "height": h, "inserts": len(inserts),
            "cover": modes.count("cover"), "blurpad": modes.count("blurpad"),
            "focusOps": sum(len(i.focus_ops) for i in inserts),
            "audioCopied": has_audio(base_path),
            "inFrames": in_frames, "outFrames": out_frames}


def _load_inserts(spec: str) -> object:
    """Inserts are either a path to a JSON file or an inline JSON string."""
    if os.path.exists(spec):
        with open(spec) as f:
            return json.load(f)
    return json.loads(spec)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="PRODUCER receipts engine: b-roll frame replacement over "
                    "untouched (stream-copied) speech audio")
    ap.add_argument("base")
    ap.add_argument("out")
    ap.add_argument("--inserts", required=True,
                    help="JSON file path OR inline JSON array of b-roll inserts")
    ap.add_argument("--manifest", required=True,
                    help="asset_manifest.json carrying the broll catalog")
    ap.add_argument("--mode", default="short", choices=sorted(MODES),
                    help="mode preset supplying broll_insert_max_s (default short)")
    args = ap.parse_args()
    try:
        with open(args.manifest) as f:
            manifest = json.load(f)
        manifest.setdefault("_path", os.path.abspath(args.manifest))
        inserts = parse_inserts(_load_inserts(args.inserts),
                                probe_duration(args.base),
                                MODES[args.mode]["broll_insert_max_s"])
        inserts = resolve_assets(inserts, manifest)
        emit(stage="broll_insert", status="start", inserts=len(inserts))
        result = apply_broll_inserts(args.base, inserts, args.out)
        emit(stage="broll_insert", status="done", **result)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        emit(error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
