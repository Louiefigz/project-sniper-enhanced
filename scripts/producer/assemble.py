#!/usr/bin/env python3
"""assemble — the incremental-graphics COMPOSITE pass (render → lock → composite).

Port of the video-editor's incremental-graphics loop (workflows/incremental-
graphics.md) into PROJECT_SNIPER. The monolithic render composites graphics
MID-pipeline, so every graphic tweak re-runs the master encode (~minutes).
Instead, a two-step loop:

  1. `render.py --skip-graphics <plan> <manifest> <base_dir>` masters everything
     EXCEPT the graphics composite once → base_dir/final.mp4 (the BASE) +
     base.fingerprint.json. Because punch-in runs BEFORE graphics, our graphics
     are output-space overlays — the base is complete and stable across a
     graphics-only edit.
  2. `assemble.py <base.mp4> <plan> <out.mp4>` renders each graphicsTrack entry to
     its cached transparent clip and overlays them onto the base in ONE ffmpeg
     pass (audio stream-copied from the mastered base). Edit a graphic → re-render
     just that clip (content-hash cache) → re-assemble (~seconds). No base
     re-render.

Guardrails ported from the reference:
  - eof_action=pass on every overlay (the 1-in-4 duplicate-frame stutter trap).
  - a YDIF duplicate-frame ratio check — FAIL if >= _YDIF_DUP_FAIL (the smoothness
    "never again"). The probe rides INSIDE the composite pass (an inline
    signalstats tap on the pre-encode frames — see graphics_stage._composite_pass)
    so it costs no extra decode; `_ydif_dup_ratio` remains for the no-composite
    paths (passthrough / standalone checks).
  - a base staleness check: if the plan's non-graphics fields no longer match the
    base's fingerprint, the base is stale (cuts/zoom/audio changed) — re-render it.

Fingerprints are SPLIT (fingerprints.py): videoFingerprint (cuts/zoom/
transitions/captions/…) vs audioFingerprint ({audioEnhance, audioGain}). An
audio-only edit dispatches to the AUDIO-ONLY fast path (audio/base_audio.py):
the base keeps its video stream and only the audio bus is rebuilt (-c:v copy),
and when the existing final.mp4's composite is provably fresh (the
.assembled.json sidecar) the new audio is muxed straight onto it — no
recomposite. Music (plan.music) stays an assemble-time stage
(audio/music_stage.py) excluded from all base fingerprints.

After a successful assemble a scrub-friendly final.proxy.mp4 is written next
to the output (preview_proxy.py — WARN-and-continue on failure, the one
documented exception: the deliverable already succeeded).

CLI: assemble.py <base.mp4> <plan.json> <out.mp4> [--cache-dir DIR]
       [--fingerprint base.fingerprint.json] [--auto-base] [--manifest m.json]

--auto-base is the SMART RE-RENDER dispatch (the editor's one button):
current → composite only; audio-only edit → audio bus rebuild (~seconds);
missing/stale → full `render.py --skip-graphics` rebuild (manifest from
--manifest or the manifestPath recorded in base.fingerprint.json).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass

from assemble_lock import acquire_lock
from fingerprints import (_NON_BASE_KEYS, audio_fingerprint,  # noqa: F401 — re-exported
                          base_fingerprint, graphics_fingerprint,
                          recorded_fingerprints,
                          invalidate_assembled_sidecar, video_fingerprint,
                          write_assembled_sidecar)
from edit.refit_authority import (commit_pending, make_receipt,
                                  resolve_refit_source, stage_receipt)
from graphics.composite_smoothness import (
    YDIF_DUP_FAIL as _YDIF_DUP_FAIL,
    duplicate_ratio as _dup_ratio,
    read_inline_ydif as _read_inline_ydif,
)
from preview_proxy import write_proxy
from template_usage_approval import (approval_required as template_approval_required,
                                     require_current as require_template_usage_approval)

def emit(**fields) -> None:
    """One NDJSON status line on stdout (matches the render stages)."""
    print(json.dumps(fields), flush=True)


def _probe_fps(path: str) -> float:
    """Output frame rate (``r_frame_rate``) of a rendered file, as a float."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", path],
        capture_output=True, text=True)
    raw = (proc.stdout or "").strip().splitlines()[0] if proc.stdout.strip() else ""
    if "/" in raw:
        num, den = raw.split("/", 1)
        return float(num) / float(den) if float(den) else 0.0
    return float(raw) if raw else 0.0


def _own_screen_frame_ranges(plan: dict, fps: float) -> list[tuple[int, int]]:
    """Output-frame ``[start, end)`` spans of own-screen takeover graphics.

    A full-frame takeover card legitimately holds still — its footage is
    REPLACED, not stuttering — exactly the holds Audit B's ``glitch_black`` /
    ``glitch_freeze`` already treat as intentional. The eof_action stutter this
    gate hunts is a FOOTAGE-visible artifact, so duplicate frames inside a
    takeover window are not that bug; exclude them from the ratio (mirroring the
    other QC gates) so a static takeover doesn't false-fail the smoothness check."""
    ranges: list[tuple[int, int]] = []
    if not fps or fps <= 0:
        return ranges
    for g in plan.get("graphicsTrack") or []:
        if not isinstance(g, dict) or g.get("anchor") != "own-screen":
            continue
        try:
            start = int(round(float(g["outStart"]) * fps))
            end = int(round(float(g["outEnd"]) * fps))
        except (KeyError, TypeError, ValueError):
            continue
        if end > start:
            ranges.append((start, end))
    return ranges


def _ydif_dup_ratio(path: str,
                    exempt: list[tuple[int, int]] | None = None) -> float:
    """STANDALONE smoothness probe: full decode of ``path`` through signalstats.

    Kept for the paths without an inline tap — the no-graphics passthrough and
    any CLI/standalone check. The composite path reads the tap file instead
    (same signalstats semantics, zero extra decode). ``exempt`` = own-screen
    takeover frame spans, excluded from the ratio.
    """
    proc = subprocess.run(
        ["ffmpeg", "-i", path, "-vf",
         "signalstats,metadata=print:key=lavfi.signalstats.YDIF:file=-",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True)
    lines = [ln for ln in (proc.stdout + proc.stderr).splitlines() if "YDIF=" in ln]
    if proc.returncode != 0 or not lines:
        # Returning 0.0 here would pass the smoothness gate exactly when the
        # output is unreadable — fail loudly instead.
        detail = (f"ffmpeg exited {proc.returncode}" if proc.returncode != 0
                  else "ffmpeg emitted no YDIF lines")
        raise RuntimeError(f"YDIF smoothness probe failed on {path}: {detail} "
                           "— output unreadable, cannot verify smoothness")
    return _dup_ratio(lines, exempt)


def _check_staleness(plan: dict, fingerprint_path: str | None) -> None:
    """Warn loudly if the base was rendered from a different (non-graphics) plan."""
    if not fingerprint_path or not os.path.exists(fingerprint_path):
        return
    recorded = recorded_fingerprints(fingerprint_path).get("fingerprint")
    now = base_fingerprint(plan)
    if recorded and recorded != now:
        emit(status="base_stale", recorded=recorded, current=now,
             warning="the plan's non-graphics fields changed since the base was "
                     "rendered — re-run `render.py --skip-graphics` before assembling")


def _base_state(base: str, plan: dict, fingerprint_path: str | None) -> str:
    """'current' | 'audio_stale' | 'stale' | 'missing' | 'unverifiable'.

    audio_stale = the VIDEO fingerprint still matches but the audio bus fields
    ({audioEnhance, audioGain}) changed — the audio-only fast path candidate.
    Legacy fingerprint files derive their split prints from the base_plan.json
    snapshot (fingerprints.recorded_fingerprints).
    """
    if not os.path.exists(base):
        return "missing"
    if not fingerprint_path or not os.path.exists(fingerprint_path):
        return "unverifiable"
    rec = recorded_fingerprints(fingerprint_path)
    if rec.get("fingerprint") == base_fingerprint(plan):
        return "current"
    if rec.get("videoFingerprint") and \
            rec["videoFingerprint"] == video_fingerprint(plan):
        return "audio_stale"
    return "stale"


def _refit_for_rebuild(plan_path: str, plan: dict,
                       fingerprint_path: str) -> tuple[dict, str | None]:
    """Refit output-time tracks to the edited cutTrack before rebuilding.

    A cut edit changes the output timebase; the base_plan.json snapshot (the
    plan the current base was rendered from) supplies the OLD timebase, and
    edit/plan_refit.py remaps every window deterministically. Without the
    snapshot we proceed unrefitted — the embedded lint gate still protects.

    TRANSACTIONAL: the refitted plan is staged to a sibling temp file (the
    returned path), NEVER over ``plan_path`` — ensure_base promotes it via
    os.replace only AFTER the rebuild succeeds. A failed rebuild leaves the
    operator's plan untouched, so a retry re-runs the IDENTICAL refit from
    the same old snapshot (idempotent — no double window shift).
    """
    old_path = os.path.join(os.path.dirname(fingerprint_path), "base_plan.json")
    if not os.path.exists(old_path):
        emit(status="refit_skipped",
             warning="no base_plan.json snapshot — windows not remapped")
        return plan, None
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from edit.plan_refit import refit_plan
    with open(old_path) as f:
        base_plan = json.load(f)
    out_dir = os.path.dirname(fingerprint_path)
    decision, old_plan = resolve_refit_source(
        out_dir, plan_path, plan, base_plan)
    if decision == "already-applied":
        emit(status="refit_already_applied",
             note="timed lanes already use the current cut timebase")
        return plan, None
    if decision == "unchanged":
        return plan, None
    if old_plan is None:
        raise RuntimeError("refit authority returned no proven source timebase")
    refitted, report = refit_plan(old_plan, plan)
    for row in report:
        emit(status="refit", **row)
    # The rebuild subprocess reads a FILE. Always stage a changed cut timebase,
    # even when there are no timed lanes, so the paired receipt can prove that
    # later review/rebuild calls must not apply this transform again.
    staged = plan_path + ".refit.json"
    with open(staged, "w") as f:
        json.dump(refitted, f, indent=1)
    receipt = make_receipt(old_plan.get("cutTrack"),
                           refitted.get("cutTrack"), staged, plan_path, report)
    stage_receipt(out_dir, receipt)
    return refitted, staged


def _settle_audio_intent(base: str, fingerprint_path: str | None) -> None:
    """Resolve a crashed audio-only base swap BEFORE any base-records read.

    A worker killed between the base replace and the records update leaves
    NEW audio bytes beside OLD records; without settlement, eligibility would
    pass again on resume and the audio effect would be applied a SECOND time
    onto the already-processed base. The intent sidecar's content hash
    (audio/base_audio.recover_audio_intent) proves which side of the replace
    the crash hit — matches-new finalizes the records, anything else discards
    the intent for an honest redo.
    """
    if not fingerprint_path:
        return
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from audio.base_audio import recover_audio_intent
    action = recover_audio_intent(base, fingerprint_path)
    if action:
        emit(status=f"audio_intent_{action}", path=base)


def _audio_only_rebuild(base: str, plan: dict, fingerprint_path: str) -> bool:
    """Try the AUDIO-ONLY fast path; False = caller takes the full rebuild.

    Eligibility (audio/base_audio.audio_fast_path_block) is honest about what
    the base audio can reproduce: pristine bus only, and never audioEnhance
    over baked-in whoosh SFX — those fall back LOUDLY to the full rebuild.
    The base swap + records update commit through the crash-safe intent
    protocol (audio/base_audio.commit_audio_base) — no kill window may leave
    new bytes with old records or vice versa unrecovered.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from audio.base_audio import (audio_fast_path_block, commit_audio_base,
                                  rebuild_audio_bus)
    snap = os.path.join(os.path.dirname(fingerprint_path), "base_plan.json")
    old_plan = None
    if os.path.exists(snap):
        with open(snap) as f:
            old_plan = json.load(f)
    reason = audio_fast_path_block(old_plan, plan)
    if reason:
        emit(status="audio_fast_path_skipped", reason=reason)
        return False
    emit(status="audio_bus_rebuild_start",
         note="video fingerprint unchanged — rebuilding the audio bus only")
    work = os.path.join(os.path.dirname(os.path.abspath(base)), "base_work")
    new_base, steps = rebuild_audio_bus(base, plan, work)
    commit_audio_base(base, new_base, plan, fingerprint_path)
    emit(status="audio_bus_rebuilt", path=base, **steps)
    return True


def _render_sidecars(base_dir: str, out_dir: str) -> list[tuple[str, str]]:
    """Validate and return the base render's required QC authority files."""
    required = ("timeline_map.json", "cover.png", "render_report.json")
    optional = ("captions.srt", "chapters.txt")
    missing = [name for name in required
               if not os.path.isfile(os.path.join(base_dir, name))]
    if missing:
        raise RuntimeError(f"base rebuild omitted required artifact(s): {', '.join(missing)}")
    names = required + tuple(name for name in optional
                             if os.path.isfile(os.path.join(base_dir, name)))
    return [(os.path.join(base_dir, name), os.path.join(out_dir, name)) for name in names]


def ensure_base(base: str, plan_path: str, plan: dict,
                fingerprint_path: str | None,
                manifest: str | None) -> tuple[dict, str]:
    """Smart re-render dispatch: rebuild (only) what the plan outgrew.

    current → reuse; audio-only mismatch → audio bus rebuild (seconds);
    stale/missing → refit the plan's output-time windows to the edited
    cutTrack (``_refit_for_rebuild`` — staged, transactional) then re-run
    `render.py --skip-graphics` (manifest from --manifest or the recorded
    manifestPath; neither = fail loudly). Returns (plan to assemble with,
    resolved state) — state 'audio_only' lets assemble() skip a fresh
    composite when the existing one is provably current.
    """
    _settle_audio_intent(base, fingerprint_path)
    state = _base_state(base, plan, fingerprint_path)
    if state == "current":
        emit(status="base_current", path=base)
        return plan, state
    if state == "unverifiable":
        # A pre-fingerprint base: can't prove staleness, don't block the editor.
        emit(status="base_unverifiable", path=base,
             warning="no base.fingerprint.json — assembling onto the existing "
                     "base; re-render the base once to enable smart dispatch")
        return plan, state
    if state == "audio_stale" and fingerprint_path:
        if _audio_only_rebuild(base, plan, fingerprint_path):
            return plan, "audio_only"
        state = "stale"   # fell back loudly — full rebuild below
    if not manifest and fingerprint_path and os.path.exists(fingerprint_path):
        with open(fingerprint_path) as f:
            manifest = json.load(f).get("manifestPath")
    if not manifest or not os.path.exists(manifest):
        raise RuntimeError(
            "base is missing/stale and no manifest is known — pass --manifest "
            "or re-render the base once so base.fingerprint.json records it")
    staged = None
    if state == "stale" and fingerprint_path:
        plan, staged = _refit_for_rebuild(plan_path, plan, fingerprint_path)
    base_dir = os.path.join(os.path.dirname(os.path.abspath(base)), "base_work")
    os.makedirs(base_dir, exist_ok=True)
    emit(status="base_rebuild_start", manifest=manifest,
         note="timeline/audio fields changed — rebuilding the graphics-free base")
    render_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "render.py")
    proc = subprocess.Popen(
        [sys.executable, render_py, staged or plan_path, manifest, base_dir,
         "--skip-graphics", "--approval-dir", os.path.dirname(os.path.abspath(base))],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    for line in proc.stdout or []:
        if line.strip():
            print(line, end="", flush=True)   # already NDJSON — pass through
    if proc.wait() != 0:
        # plan_path is untouched (refit only staged) — a retry re-runs the
        # identical refit from the same base_plan.json snapshot.
        raise RuntimeError("base rebuild failed (render.py --skip-graphics)")
    sidecars = _render_sidecars(base_dir, os.path.dirname(os.path.abspath(base)))
    if staged:
        os.replace(staged, plan_path)          # promote the refit on success only
        commit_pending(os.path.dirname(fingerprint_path), plan_path)
        emit(status="refit_written", path=plan_path)
    os.replace(os.path.join(base_dir, "final.mp4"), base)
    for source, destination in sidecars:
        os.replace(source, destination)
    if fingerprint_path:
        os.replace(os.path.join(base_dir, "base.fingerprint.json"), fingerprint_path)
        with open(os.path.join(os.path.dirname(fingerprint_path),
                               "base_plan.json"), "w") as f:
            json.dump(plan, f, indent=1)
    emit(status="base_rebuilt", path=base)
    return plan, "rebuilt"


@dataclass
class AssembleJob:
    """One assemble run (keeps ``assemble`` ≤4 params — house limit)."""

    base: str
    plan: dict
    out: str
    cache_dir: str | None
    fingerprint_path: str | None = None
    manifest: str | None = None
    audio_only: bool = False   # ensure_base resolved an audio-only base rebuild


def _reuse_composite(job: AssembleJob) -> bool:
    """May an audio-only run keep the existing composite (mux, no overlay)?

    Requires the out file AND its .assembled.json sidecar proving it was
    composited from THIS videoFingerprint + graphicsTrack — an edit that
    changed a graphic alongside the audio must recomposite (never silently
    ship a stale graphic).
    """
    if not job.audio_only or not os.path.exists(job.out):
        return False
    sidecar = job.out + ".assembled.json"
    if not os.path.exists(sidecar):
        emit(status="audio_only_recomposite",
             reason="no .assembled.json sidecar for the existing output")
        return False
    with open(sidecar) as f:
        rec = json.load(f)
    ok = (rec.get("videoFingerprint") == video_fingerprint(job.plan)
          and rec.get("graphicsFingerprint") == graphics_fingerprint(job.plan))
    if not ok:
        emit(status="audio_only_recomposite",
             reason="graphics/video changed since the last assemble")
    return ok


def _composite(job: AssembleJob) -> dict:
    """Graphics composite + the YDIF smoothness gate (inline tap when it ran)."""
    from graphics.exit_on_cut import apply_exit_on_cut
    from graphics.graphics_stage import GraphicsJob, run_graphics_stage
    # THE EXIT LAW (G4): same deterministic clamp as render.py's graphics
    # stage — an exitOnCut entry dies exactly ON the next cutTrack seam.
    track, clamped = apply_exit_on_cut(job.plan)
    if clamped:
        emit(status="exit_on_cut_clamped", entries=clamped)
    ydif_file = job.out + ".ydif.txt"
    gjob = GraphicsJob(video_in=job.base, video_out=job.out,
                       track=track,
                       cache_dir=job.cache_dir, eof_pass=True,
                       ydif_file=ydif_file,
                       # Eye-trace placements sidecar beside the output —
                       # Audit B reads the final.mp4 dir (LIAM move 4).
                       placements_out=os.path.join(
                           os.path.dirname(os.path.abspath(job.out)),
                           "graphics_placements.json"))
    summary = run_graphics_stage(gjob)
    # Own-screen takeover holds are legitimately static (footage replaced, not
    # stuttering) — exempt their frames so the eof_action stutter gate measures
    # only the footage-visible frames it is actually meant to police.
    exempt = _own_screen_frame_ranges(job.plan, _probe_fps(job.base))
    exempt_frames = sum(end - start for start, end in exempt)
    # The inline tap exists only when a composite pass ran; the no-graphics
    # passthrough stream-copies the base, so the standalone probe covers it.
    dup = (_read_inline_ydif(ydif_file, exempt) if summary.get("passes")
           else _ydif_dup_ratio(job.out, exempt))
    summary["ydif_dup_ratio"] = round(dup, 4)
    emit(status="smoothness", ydif_dup_ratio=round(dup, 4),
         threshold=_YDIF_DUP_FAIL, ok=dup < _YDIF_DUP_FAIL,
         ownScreenFramesExempt=exempt_frames)
    if dup >= _YDIF_DUP_FAIL:
        raise RuntimeError(
            f"assembled output judders: {dup:.1%} duplicate frames "
            f">= {_YDIF_DUP_FAIL:.0%} (the eof_action stutter trap)")
    return summary


def assemble(job: AssembleJob) -> dict:
    """Composite (or audio-only mux) → music → sidecar → proxy; return a summary.

    ``job.manifest`` also resolves music.assetId, so a run with a manifest in
    hand never dies on a missing --fingerprint AFTER the composite burned.
    Lazy-imports the heavy stages so ``base_fingerprint`` stays a cheap import
    for render.py (no cv2/hyperframes pulled in just to hash a plan).
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from audio.music_stage import apply_music
    _settle_audio_intent(job.base, job.fingerprint_path)
    _check_staleness(job.plan, job.fingerprint_path)
    reuse = _reuse_composite(job)
    invalidate_assembled_sidecar(job.out)
    if reuse:
        from audio.base_audio import mux_audio
        mux_audio(job.out, job.base, job.out)
        emit(status="audio_only_mux", out=job.out,
             note="video + graphics unchanged — new base audio muxed onto the "
                  "existing composite (its YDIF gate already passed)")
        summary = {"audio_only_mux": True, "out": job.out}
    else:
        summary = _composite(job)
    mix = apply_music(job.plan, job.out, job.fingerprint_path, job.manifest)
    if mix is not None:
        summary["music"] = {"applied": True, "final_lufs": mix.get("final_lufs"),
                            "duck_depth": mix.get("duck_depth")}
    provenance = write_assembled_sidecar(job.out, job.plan)
    summary["planHash"] = provenance["planHash"]
    summary["authorityHash"] = provenance["authorityHash"]
    proxy = write_proxy(job.out)   # WARN-and-continue inside (documented exception)
    if proxy:
        summary["proxy"] = proxy["path"]
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="PRODUCER incremental-graphics assemble")
    ap.add_argument("base", help="the mastered graphics-free base (render.py --skip-graphics)")
    ap.add_argument("plan_path")
    ap.add_argument("out")
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--fingerprint", default=None,
                    help="base.fingerprint.json to check the base isn't stale")
    ap.add_argument("--auto-base", action="store_true",
                    help="smart re-render: rebuild the base first if it is "
                         "missing or stale (needs --fingerprint; manifest from "
                         "--manifest or the fingerprint file); audio-only "
                         "edits rebuild just the audio bus")
    ap.add_argument("--manifest", default=None,
                    help="asset manifest for --auto-base rebuilds AND for "
                         "resolving music.assetId (wins over the fingerprint's "
                         "recorded manifestPath)")
    args = ap.parse_args()
    default_cache = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "..", "..", "templates", "motion", "renders", "cache")
    lock_path = os.path.join(os.path.dirname(os.path.abspath(args.out)),
                             ".assemble.lock")
    if not acquire_lock(lock_path):
        sys.exit(1)   # a LIVE run holds the dir — never remove its lock
    try:
        with open(args.plan_path) as f:
            plan = json.load(f)
        manifest = args.manifest
        if not manifest and args.fingerprint and os.path.exists(args.fingerprint):
            with open(args.fingerprint) as handle:
                manifest = json.load(handle).get("manifestPath")
        if manifest:
            require_template_usage_approval(
                args.plan_path, manifest, os.path.dirname(os.path.abspath(args.out)),
                os.path.dirname(os.path.abspath(manifest)))
        elif template_approval_required(os.path.dirname(os.path.abspath(args.out))):
            raise RuntimeError("produced/full assemble requires --manifest to verify template history")
        audio_only = False
        if args.auto_base:
            plan, state = ensure_base(args.base, args.plan_path, plan,
                                      args.fingerprint, args.manifest)
            audio_only = state == "audio_only"
        job = AssembleJob(base=args.base, plan=plan, out=args.out,
                          cache_dir=args.cache_dir or default_cache,
                          fingerprint_path=args.fingerprint,
                          manifest=args.manifest, audio_only=audio_only)
        summary = assemble(job)
        emit(status="done", **summary)
    except (OSError, json.JSONDecodeError, KeyError, ValueError, RuntimeError) as exc:
        emit(error=str(exc))
        sys.exit(1)
    finally:
        # We hold the lock (acquire returned True) — remove on success AND failure.
        if os.path.exists(lock_path):
            os.remove(lock_path)


if __name__ == "__main__":
    main()
