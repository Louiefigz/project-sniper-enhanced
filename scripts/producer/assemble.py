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

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graphics.owned_execution import OwnedGraphicsExecution

from assemble_lock import acquire_lock
from cut_delivery_authority import (
    DELIVERY_NAME, seal_assembled_delivery, seal_render_delivery,
)
from cut_manifestation_authority import MANIFESTATION_NAME
from fingerprints import (_NON_BASE_KEYS, audio_fingerprint,  # noqa: F401 — re-exported
                          base_fingerprint, caption_fingerprint,
                          graphics_fingerprint,
                          recorded_fingerprints,
                          invalidate_assembled_sidecar, video_fingerprint,
                          write_assembled_sidecar)
from edit.refit_authority import (make_receipt,
                                  resolve_refit_source, stage_receipt)
from graphics.composite_smoothness import (
    YDIF_DUP_FAIL as _YDIF_DUP_FAIL,
    duplicate_ratio as _dup_ratio,
    read_inline_ydif as _read_inline_ydif,
)
from ingest_execution_authority import verify_execution_media_authority
from preview_proxy import write_proxy
from render_effect_registry import validate_render_documents
from stage_timing import span_for_base
from template_usage_approval import (approval_required as template_approval_required,
                                     require_current as require_template_usage_approval)

def emit(**fields) -> None:
    """One NDJSON status line on stdout (matches the render stages)."""
    print(json.dumps(fields), flush=True)


def _probe_fps(path: str) -> float:
    """Output frame rate (``r_frame_rate``) of a rendered file, as a float."""
    from media_probe import _fps_fraction, probe_video
    return float(_fps_fraction(probe_video(path)["r_frame_rate"]))


def _own_screen_frame_ranges(plan: dict, fps: float) -> list[tuple[int, int]]:
    """Output-frame ``[start, end)`` spans of own-screen takeover graphics."""
    # A full-frame takeover card legitimately holds still — its footage is
    # REPLACED, not stuttering — exactly the holds Audit B's glitch_black /
    # glitch_freeze already treat as intentional. The eof_action stutter this
    # gate hunts is a FOOTAGE-visible artifact, so duplicate frames inside a
    # takeover window are not that bug; exclude them from the ratio (mirroring
    # the other QC gates) so a static takeover doesn't false-fail smoothness.
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

    Kept for the paths without an inline tap (no-graphics passthrough, CLI
    checks); the composite path reads the tap file instead. ``exempt`` =
    own-screen takeover frame spans, excluded from the ratio.
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


def _base_state(base: str, plan: dict, fingerprint_path: str | None,
                audio_clock_policy: str = "legacy-v1") -> str:
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
    from audio.master import MASTERING_POLICY_VERSION
    if type(rec.get("masteringPolicyVersion")) is not int \
            or rec["masteringPolicyVersion"] != MASTERING_POLICY_VERSION:
        return "stale"
    if rec.get("audioClockPolicy", "legacy-v1") != audio_clock_policy:
        return "stale"
    if rec.get("fingerprint") == base_fingerprint(plan):
        return "current"
    if audio_clock_policy == "source-float-v2" and _finishing_invariant_current(plan, fingerprint_path):
        return "current"
    if rec.get("videoFingerprint") and \
            rec["videoFingerprint"] == video_fingerprint(plan):
        return "audio_stale"
    return "stale"


def _finishing_invariant_current(plan: dict, fingerprint_path: str) -> bool:
    """source-float-v2: finishing lives in the program master, never in the base.

    ``audioEnhance``/``audioGain`` and ``transitions[].sfx`` shape neither the v2
    base picture nor its retained raw dialogue bus, so a finishing-only edit keeps
    the base current and assemble rebuilds only the program master. The retained
    base_plan.json is the exact plan the base was rendered from.
    """
    from audio.program_finish_contract import finishing_free_plan
    snapshot = os.path.join(os.path.dirname(fingerprint_path), "base_plan.json")
    if not os.path.exists(snapshot):
        return False
    with open(snapshot) as handle:
        recorded = json.load(handle)
    return base_fingerprint(finishing_free_plan(recorded)) == base_fingerprint(finishing_free_plan(plan))


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
    from edit.plan_refit import bump_plan_version, refit_plan
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
    # Every plan WRITE increments planVersion (stale-plan detection); the bump
    # rides in the staged bytes so the paired receipt hash-binds it too.
    refitted = bump_plan_version(refitted)
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
    directory = os.path.dirname(os.path.abspath(base))
    if os.path.exists(os.path.join(directory, MANIFESTATION_NAME)):
        seal_render_delivery(directory, base, plan, True)
    emit(status="audio_bus_rebuilt", path=base, **steps)
    return True


def _render_sidecars(base_dir: str, out_dir: str,
                     audio_clock_policy: str = "legacy-v1") -> list[tuple[str, str]]:
    """Validate and return the base render's required QC authority files."""
    required = ("timeline_map.json", "cover.png", "render_report.json")
    if audio_clock_policy == "source-float-v2":
        from audio.render_audio_cache import SOURCE_BUS_POINTER
        required += (SOURCE_BUS_POINTER,)
    optional = (
        "captions.srt", "chapters.txt", MANIFESTATION_NAME, DELIVERY_NAME,
    )
    missing = [name for name in required
               if not os.path.isfile(os.path.join(base_dir, name))]
    if missing:
        raise RuntimeError(f"base rebuild omitted required artifact(s): {', '.join(missing)}")
    names = required + tuple(name for name in optional
                             if os.path.isfile(os.path.join(base_dir, name)))
    return [(os.path.join(base_dir, name), os.path.join(out_dir, name)) for name in names]


@dataclass(frozen=True)
class BaseManifest:
    """Explicit opt-in policy with the existing manifest argument/legacy API."""

    path: str | None
    audio_clock_policy: str = "legacy-v1"


def ensure_base(base: str, plan_path: str, plan: dict,
                fingerprint_path: str | None,
                manifest: str | BaseManifest | None) -> tuple[dict, str]:
    """Smart re-render dispatch: rebuild (only) what the plan outgrew.

    current → reuse; audio-only mismatch → audio bus rebuild (seconds);
    stale/missing → refit the plan's output-time windows to the edited
    cutTrack (``_refit_for_rebuild`` — staged, transactional) then re-run
    `render.py --skip-graphics` (manifest from --manifest or the recorded
    manifestPath; neither = fail loudly). Returns (plan to assemble with,
    resolved state) — state 'audio_only' lets assemble() skip a fresh
    composite when the existing one is provably current.
    """
    options = manifest if isinstance(manifest, BaseManifest) else BaseManifest(manifest)
    manifest = options.path
    if options.audio_clock_policy == "legacy-v1":
        _settle_audio_intent(base, fingerprint_path)
    state = _base_state(base, plan, fingerprint_path, options.audio_clock_policy)
    if state == "current":
        emit(status="base_current", path=base)
        return plan, state
    if state == "unverifiable":
        emit(status="base_unverifiable", path=base,
             warning="no base.fingerprint.json — rebuilding; existing audio "
                     "has no current mastering-policy proof")
        state = "stale"
    if state == "audio_stale" and fingerprint_path and options.audio_clock_policy == "legacy-v1":
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
    from assemble_base_rebuild import BaseRebuild, rebuild_base
    return rebuild_base(BaseRebuild(base, plan_path, plan, fingerprint_path,
                                   manifest, options.audio_clock_policy, state))


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
    audio_clock_policy: str = "legacy-v1"
    plan_path: str | None = None
    source_bus_receipt_hash: str | None = None
    held_program_selection: tuple[str, str] | None = None
    graphic_frame_clock: tuple[str, int] | None = None  # Internal held-program opt-in only.
    owned_graphics: OwnedGraphicsExecution | None = None  # Internal live owner.


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
          and rec.get("graphicsFingerprint") == graphics_fingerprint(job.plan)
          and rec.get("captionFingerprint") == caption_fingerprint(job.plan))
    caption_path = os.path.join(
        os.path.dirname(os.path.abspath(job.out)), "caption_authority.json")
    if ok and caption_fingerprint(job.plan) is not None:
        try:
            with open(caption_path, encoding="utf-8") as handle:
                caption_authority = json.load(handle)
            ok = (rec.get("captionAuthorityHash")
                  == caption_authority.get("authorityHash"))
        except (OSError, json.JSONDecodeError, AttributeError):
            ok = False
    if not ok:
        emit(status="audio_only_recomposite",
             reason="graphics/video changed since the last assemble")
    return ok


def _composite(job: AssembleJob) -> dict:
    """Graphics composite + the YDIF smoothness gate (inline tap when it ran)."""
    from graphics.exit_on_cut import apply_exit_on_cut
    from graphics.graphics_stage import GraphicsJob, run_graphics_stage
    from graphics.placement_verify import occlusion_windows
    from planner.occupancy import plan_band_offset
    # THE EXIT LAW (G4): same deterministic clamp as render.py's graphics
    # stage — an exitOnCut entry dies exactly ON the next cutTrack seam.
    track, clamped = apply_exit_on_cut(job.plan)
    if clamped:
        emit(status="exit_on_cut_clamped", entries=clamped)
    ydif_file = job.out + ".ydif.txt"
    out_dir = os.path.dirname(os.path.abspath(job.out))
    gjob = GraphicsJob(video_in=job.base, video_out=job.out,
                       track=track,
                       cache_dir=job.cache_dir, eof_pass=True,
                       graphic_frame_clock=job.graphic_frame_clock,
                       owned_graphics=job.owned_graphics,
                       ydif_file=ydif_file,
                       # Eye-trace placements sidecar beside the output —
                       # Audit B reads the final.mp4 dir (eye-trace CM-4).
                       placements_out=os.path.join(
                           out_dir, "graphics_placements.json"),
                       # Verify allow-vocabulary + the A3 calibration loop:
                       # the output dir is the producer dir in the GUI/skill
                       # flow (final.mp4 beside geometry_predictions.json).
                       occlusions=occlusion_windows(job.plan),
                       producer_dir=out_dir,
                       band_y_offset_px=plan_band_offset(job.plan))
    with span_for_base(job.out if job.held_program_selection else job.base, "graphics"):
        summary = run_graphics_stage(gjob)
    # Own-screen takeover holds are legitimately static (footage replaced, not
    # stuttering) — exempt their frames so the eof_action stutter gate measures
    # only the footage-visible frames it is actually meant to police.
    exempt = _own_screen_frame_ranges(job.plan, _probe_fps(job.base))
    exempt_frames = sum(end - start for start, end in exempt)
    # The inline tap exists only when a composite pass ran; the no-graphics
    # passthrough stream-copies the base, so the standalone probe covers it.
    dup = (_read_inline_ydif(ydif_file, exempt) if summary.get("passes") and job.owned_graphics is None
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


def _finalize_assemble(job: AssembleJob, summary: dict) -> dict:
    """Apply the optional music bed, publish provenance, and build a proxy."""
    from audio.music_stage import apply_music
    with span_for_base(job.base, "music"):
        mix = apply_music(
            job.plan, job.out, job.fingerprint_path, job.manifest)
    if mix is not None:
        summary["music"] = {
            "applied": True, "final_lufs": mix.get("final_lufs"),
            "duck_depth": mix.get("duck_depth"),
        }
    provenance = write_assembled_sidecar(job.out, job.plan)
    summary["planHash"] = provenance["planHash"]
    summary["authorityHash"] = provenance["authorityHash"]
    lineage = seal_assembled_delivery(job.base, job.out, job.plan)
    if lineage is not None:
        summary["cutDeliveryReceiptHash"] = lineage["receiptHash"]
    with span_for_base(job.base, "proxy"):
        proxy = write_proxy(job.out)
    if proxy:
        summary["proxy"] = proxy["path"]
    return summary


def _assemble_captioned(job: AssembleJob) -> dict:
    """Reuse or build the caption-free picture, then project timed text."""
    from graphics.owned_execution import current
    owned = current(job)
    if owned is not None and owned.captions is not None:
        owned.captions.assert_plan(job.plan, job.plan_path)
        owned.captions.stage(job.out)
        with span_for_base(job.out, "composite"):
            summary = _composite(job)
        summary["captions"] = owned.captions.finish(job.out)
        return summary
    from captions.caption_assemble import (
        checkpoint_caption_free_composite,
        project_caption_track,
        restore_caption_free_composite,
    )
    restored = restore_caption_free_composite(job)
    if restored:
        summary = {"caption_composite_reused": True, "out": job.out}
        emit(status="caption_composite_reused", out=job.out,
             note="upstream picture/graphics authority is unchanged")
    else:
        with span_for_base(job.out if job.held_program_selection else job.base, "composite"):
            summary = _composite(job)
        checkpoint_caption_free_composite(job)
    with span_for_base(job.out if job.held_program_selection else job.base, "captions"):
        captions = project_caption_track(job, emit)
    if captions is not None:
        summary["captions"] = captions
    return summary


def assemble(job: AssembleJob) -> dict:
    """Composite (or audio-only mux) → music → sidecar → proxy; return a summary.

    ``job.manifest`` also resolves music.assetId, so a run with a manifest in
    hand never dies on a missing --fingerprint AFTER the composite burned.
    Lazy-imports the heavy stages so ``base_fingerprint`` stays a cheap import
    for render.py (no cv2/hyperframes pulled in just to hash a plan).
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from graphics.owned_execution import require_held_assembly
    require_held_assembly(job)
    if job.graphic_frame_clock is not None and (job.held_program_selection is None
                                              or job.audio_clock_policy != "source-float-v2"):
        raise RuntimeError("exact graphic frame clock requires held source-float-v2 assembly")
    if job.held_program_selection is not None and job.audio_clock_policy == "legacy-v1":
        raise RuntimeError("held program preparation cannot use legacy assembly")
    if job.audio_clock_policy != "legacy-v1":
        from audio.assemble_source_audio import assemble_source_audio
        return assemble_source_audio(job)
    _settle_audio_intent(job.base, job.fingerprint_path)
    _check_staleness(job.plan, job.fingerprint_path)
    reuse = _reuse_composite(job)
    invalidate_assembled_sidecar(job.out)
    if reuse:
        from audio.base_audio import mux_audio
        with span_for_base(job.base, "audio_mux"):
            mux_audio(job.out, job.base, job.out)
        emit(status="audio_only_mux", out=job.out,
             note="video + graphics unchanged — new base audio muxed onto the "
                  "existing composite (its YDIF gate already passed)")
        summary = {"audio_only_mux": True, "out": job.out}
    else:
        summary = _assemble_captioned(job)
    return _finalize_assemble(job, summary)


def delivery_authority_dir(plan_path: str) -> str:
    """Resolve project authority from the plan, never a private output path."""
    return os.path.dirname(os.path.abspath(plan_path))


def main() -> None:
    """Run the admitted ordinary assembler while owning exactly one output lock."""
    from assemble_arguments import default_cache_directory, load_documents, parse_arguments
    args = parse_arguments()
    lock_path = os.path.join(os.path.dirname(os.path.abspath(args.out)),
                             ".assemble.lock")
    if not acquire_lock(lock_path):
        sys.exit(1)   # a LIVE run holds the dir — never remove its lock
    try:
        plan, manifest = load_documents(args)
        audio_only = False
        if args.auto_base:
            with span_for_base(args.base, "base_check"):
                plan, state = ensure_base(args.base, args.plan_path, plan,
                    args.fingerprint, BaseManifest(args.manifest, args.audio_clock_policy))
            audio_only = state == "audio_only"
        job = AssembleJob(base=args.base, plan=plan, out=args.out,
                          cache_dir=args.cache_dir or default_cache_directory(),
                          fingerprint_path=args.fingerprint,
                          manifest=manifest, audio_only=audio_only, audio_clock_policy=args.audio_clock_policy,
                          plan_path=args.plan_path, source_bus_receipt_hash=args.source_bus_receipt_hash)
        summary = assemble(job)
        emit(status="done", **summary)
    except (OSError, json.JSONDecodeError, KeyError, ValueError, RuntimeError) as exc:
        emit(error=str(exc))
        # Mirror the typed error to STDERR too: belt-and-suspenders with the
        # worker's combined stdout+stderr tail (chain.ts runAssemble) — the
        # NoLegalRegion re-plan route (geometry-replan.ts) keys on the token
        # surviving in that tail whichever stream carried it.
        print(json.dumps({"error": str(exc)}), file=sys.stderr, flush=True)
        sys.exit(1)
    finally:
        # We hold the lock (acquire returned True) — remove on success AND failure.
        if os.path.exists(lock_path):
            os.remove(lock_path)


if __name__ == "__main__":
    main()
