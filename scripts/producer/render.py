#!/usr/bin/env python3
"""render — the PRODUCER pipeline orchestrator (Phase 1).

Chains the deterministic stages over a linted ``edit_plan.json``:

    lint → compile (timeline_map) → cut_speed (mezzanine)
         → [face_track → reframe]           (shorts / 9:16)
         → [captions]                        (burned, from kept words)
         → master (loudnorm + final encode + cover)

The lint gate is embedded and non-bypassable: a plan that fails lint is not
rendered. Face stages need OpenCV and run as subprocesses under the repo venv
(``.venv/bin/python3``); everything else is imported flat, same as siblings.

CLI: render.py <edit_plan.json> <asset_manifest.json> <out_dir>
               [--workdir DIR] [--resume]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional

from motion.baseline_look import apply_baseline_look, parse_spec as parse_baseline_spec
from broll.broll_insert import (apply_broll_inserts, parse_inserts as parse_broll_inserts,
                          resolve_assets as resolve_broll_assets)
from captions.caption_corrections import apply_corrections, unmatched_keys
from captions.captions_ass import build_ass, caption_cfg_for_aspect
from captions.longform_outputs import build_chapters, write_srt
from compile_timeline import TimelineMap, compile_plan, remap_words
from cut_speed import probe_duration, probe_video, probe_video_frames, render_cut_speed
from edit_scope import lane_required
from graphics.exit_on_cut import apply_exit_on_cut
from graphics.graphics_stage import suppress_captions
from audio.master import MasterSpec, dead_channel_prefix, master
from captions.overlays import build_card_png, apply_cards
from plan_lint import lint
from fingerprints import (fingerprint_record, invalidate_assembled_sidecar,
                          stage_fingerprint, stage_receipt_current,
                          write_assembled_sidecar, write_stage_receipt)
from producer_config import CAPTIONS, CAPTION_AUTO_CORRECTIONS, MODES
from motion.punch_in import apply_punch_ins, parse_windows as parse_punch_windows
from motion.recompose import (apply_recompose, requires_recompose,
                              stamp_entry_face_bboxes)
from motion.transitions import apply_transitions
from template_usage_approval import require_current as require_template_usage_approval

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Repo-vendored brand fonts (PROJECT_SNIPER/assets/fonts/): make libass find Inter for
# caption burn without a system install. Explicit env still wins.
_FONTS_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "assets", "fonts"))
if os.path.isdir(_FONTS_DIR):
    os.environ.setdefault("PRODUCER_FONTS_DIR", _FONTS_DIR)


def emit(**fields) -> None:
    """Emit one JSON status line on stdout (NDJSON, like the sibling stages)."""
    print(json.dumps(fields), flush=True)


def venv_python() -> str:
    """Repo venv interpreter for cv2-dependent stages, else this python."""
    candidate = os.path.join(SCRIPT_DIR, "..", "..", ".venv", "bin", "python3")
    return os.path.abspath(candidate) if os.path.exists(candidate) else sys.executable


@dataclass
class RenderCtx:
    """Everything one render run needs (keeps stage functions ≤4 params)."""

    plan: dict
    manifest: dict
    out_dir: str
    work_dir: str
    resume: bool = False
    skip_graphics: bool = False   # base render: composite graphics later in assemble

    def stage_path(self, name: str) -> str:
        """Absolute path to a named intermediate inside the work dir."""
        return os.path.join(self.work_dir, name)

    def skip(self, path: str, stage: str) -> bool:
        """True when --resume and this stage's output already exists."""
        if self.resume and os.path.exists(path):
            emit(status="stage_skipped", stage=stage, out=path)
            return True
        return False


def gate(ctx: RenderCtx) -> None:
    """Run plan_lint in-process; refuse to render a failing plan."""
    from graphics_planner import output_words  # local: keep module import light
    manifest_path = ctx.manifest.get("_path", os.path.join(ctx.out_dir, "x"))
    words = output_words(ctx.plan, os.path.dirname(manifest_path), ctx.manifest)
    rep = lint(ctx.plan, ctx.manifest, words)
    if rep.errors:
        raise RuntimeError("plan failed lint: " + "; ".join(rep.errors))
    for w in rep.warnings:
        emit(status="lint_warning", warning=w)


def compile_stage(ctx: RenderCtx) -> TimelineMap:
    """Compile the plan and persist timeline_map.json next to the outputs."""
    tmap = compile_plan(ctx.plan)
    map_path = os.path.join(ctx.out_dir, "timeline_map.json")
    with open(map_path, "w") as f:
        json.dump(tmap.to_dict(), f, indent=2)
    emit(status="compiled", segments=len(tmap.segments),
         outputDuration=round(tmap.output_duration, 3))
    return tmap


def cut_stage(ctx: RenderCtx) -> str:
    """Stage 1: cut+speed mezzanine."""
    mezz = ctx.stage_path("mezzanine.mp4")
    if not ctx.skip(mezz, "cut_speed"):
        parts_dir = os.path.join(ctx.work_dir, "cut-parts")
        os.makedirs(parts_dir, exist_ok=True)
        render_cut_speed(ctx.plan, ctx.manifest, mezz, parts_dir)
        emit(status="stage_done", stage="cut_speed", out=mezz)
    return mezz


def _strip_rationale(entries: list[dict]) -> list[dict]:
    """Plan entries may carry a human ``rationale`` — the primitives don't."""
    return [{k: v for k, v in e.items() if k != "rationale"} for e in entries]


def channels_stage(ctx: RenderCtx, mezz: str) -> str:
    """Stage 1.2 (C16 part 1): dual-mono a dead source channel EARLY.

    Must run before any stage that mixes audio (transitions' whooshes land on
    both channels and would make a dead channel look alive to master's
    detector — found the hard way on the v2 intro render). Video is
    stream-copied; only the audio re-encodes.
    """
    pan, warning = dead_channel_prefix(mezz)
    if pan is None:
        return mezz
    out = ctx.stage_path("channels.mp4")
    if not ctx.skip(out, "audio_channels"):
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-i", mezz, "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
               "-af", pan, "-c:a", "aac", "-b:a", "256k", out]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError("audio_channels failed: "
                               + proc.stderr.strip()[-300:])
        emit(status="stage_done", stage="audio_channels", warning=warning)
    return out


def baseline_stage(ctx: RenderCtx, mezz: str) -> str:
    """Stage 1.5 (R16): whole-video baseline look — tight recrop + grade.

    Reads ``plan.baselineLook``; absent = passthrough (raw framing). Runs
    before every compositing stage so captions/graphics/punches land in final
    output coordinates.
    """
    look = ctx.plan.get("baselineLook")
    if not look:
        return mezz
    out = ctx.stage_path("baselined.mp4")
    if not ctx.skip(out, "baseline_look"):
        spec = parse_baseline_spec({k: v for k, v in look.items()
                                    if k != "rationale"})
        result = apply_baseline_look(mezz, spec, out)
        emit(status="stage_done", stage="baseline_look",
             cropWindow=result.get("cropWindow"), outRes=result.get("outRes"))
    return out


def recompose_stage(ctx: RenderCtx, video: str, out_dur: float) -> None:
    """Stage 2.4 (longform): stamp beside-face recompose windows into punchIns.

    A longform rail placed beside the speaker needs the footage to glide-recenter
    under it or the face sits off-centre. That recenter is carried by
    ``role:"recompose"`` windows in ``plan.punchIns`` — but the brain only folds
    them in when it remembers to run motion/recompose.py. Stamp them here (before
    punch_stage consumes punchIns) so the mastered footage — and therefore the
    Palmier mirror — ALWAYS recenters under an occluding rail. Longform grammar
    only; idempotent (apply_recompose replaces existing recompose windows);
    a no-op when no rail requires it. Like palmier/checkpoint_plan
    _apply_required_recompose, but it additionally MEASURES the face on ``video``
    when the plan carries no faceBBoxNorm (``_ensure_face_bbox``), so the main
    render delivers the recenter instead of aborting on an un-measured plan.
    """
    if ctx.plan["target"]["mode"] != "longform":
        return
    rails = [row for row in ctx.plan.get("graphicsTrack") or []
             if isinstance(row, dict) and requires_recompose(row)]
    if not rails:
        return
    try:
        measured = stamp_entry_face_bboxes(ctx.plan, video)
        summary = apply_recompose(ctx.plan, out_dur)
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        # Fail closed: a rail that REQUIRES recompose but has no measurable face
        # (no cv2 / no face on screen) must not ship an off-centre face.
        raise RuntimeError(
            f"required rail recompose could not be measured: {exc}") from exc
    emit(status="stage_done", stage="recompose",
         windows=summary["windows"], stamped=summary["stamped"],
         facesMeasured=measured)


def punch_stage(ctx: RenderCtx, video: str) -> str:
    """Stage 2.5 (R13/R16): the zoom track — punches, ramps, brackets.

    Reads ``plan.punchIns`` (already validated by the lint gate). Runs before
    overlays/captions/graphics so composited elements stay fixed while the
    footage reframes under them (the pro's checklist stays put through his
    punch-outs — INTRO_MACHINE_VS_PRO_AUDIT §3).
    """
    wins = ctx.plan.get("punchIns") or []
    if not wins:
        return video
    out = ctx.stage_path("punched.mp4")
    inputs = [video, os.path.join(SCRIPT_DIR, "motion", "punch_in.py")]
    signature = stage_fingerprint(_strip_rationale(wins), inputs)
    current = ctx.resume and stage_receipt_current(out, signature)
    if current:
        emit(status="stage_skipped", stage="punch_in", out=out,
             reason="current stage fingerprint")
    else:
        windows = parse_punch_windows(_strip_rationale(wins))
        result = apply_punch_ins(video, windows, out)
        write_stage_receipt(out, signature)
        emit(status="stage_done", stage="punch_in", windows=len(windows),
             frames=result.get("outFrames"))
    return out


def broll_stage(ctx: RenderCtx, video: str) -> str:
    """Stage 2.7 (audit §2 / R17): b-roll receipts — frames replaced, audio untouched.

    Reads ``plan.brollTrack`` (validated by the lint gate); resolves assets via
    the manifest's broll catalog. Runs after punch_stage and before
    overlays_stage: receipts replace the footage itself, so graphics/captions
    must composite on top of them, and the speech audio passes through
    stream-copied (EDIT_DECISION_STUDY: b-roll rides ON TOP, never replaces audio).
    """
    track = ctx.plan.get("brollTrack") or []
    if not track:
        return video
    out = ctx.stage_path("brolled.mp4")
    if not ctx.skip(out, "broll"):
        mode = ctx.plan["target"]["mode"]
        inserts = parse_broll_inserts(_strip_rationale(track), probe_duration(video),
                                      MODES[mode]["broll_insert_max_s"])
        inserts = resolve_broll_assets(inserts, ctx.manifest)
        result = apply_broll_inserts(video, inserts, out)
        emit(status="stage_done", stage="broll", inserts=len(inserts),
             cover=result.get("cover"), blurpad=result.get("blurpad"),
             frames=result.get("outFrames"))
    return out


def transitions_stage(ctx: RenderCtx, video: str, out_dur: float) -> str:
    """Stage 4.7 (R15/R19): seam-cover transitions — flash/leak + whoosh.

    Runs AFTER graphics so a flash covers graphic entrances/exits too, AFTER
    enhance so dialogue cleanup never touches the amixed whoosh SFX, and
    before gain/master so loudnorm measures the mixed program.
    """
    events = ctx.plan.get("transitions") or []
    if not events:
        return video
    out = ctx.stage_path("transitioned.mp4")
    if not ctx.skip(out, "transitions"):
        result = apply_transitions(video, _strip_rationale(events), out)
        emit(status="stage_done", stage="transitions", events=len(events),
             frames=result.get("outFrames"))
    return out


def _run_stage_cli(script: str, args: list[str], stage: str) -> None:
    """Run a cv2-dependent sibling CLI under the venv interpreter.

    ``script`` is package-relative (e.g. ``motion/face_track.py``). Stages run
    by path get their own subdir as ``sys.path[0]``, so PYTHONPATH pins the
    producer package root to keep ``from motion.x import`` resolvable.
    """
    env = {**os.environ, "PYTHONPATH": SCRIPT_DIR
           + os.pathsep + os.environ.get("PYTHONPATH", "")}
    cmd = [venv_python(), os.path.join(SCRIPT_DIR, script), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-5:]
        raise RuntimeError(f"{stage} failed: " + " | ".join(tail))
    emit(status="stage_done", stage=stage)


def _reframe_manual_stage(ctx: RenderCtx, mezz: str, framed: str) -> str:
    """Manual-geometry reframe (layout 'split' or a fill crop override).

    Deterministic geometry from the plan — motion/reframe_split.py denorms +
    even-snaps the normalized crops; face_track is skipped entirely (no
    detection runs). Lint has already validated the contract.
    """
    cfg = ctx.plan["reframe"]
    layout = cfg.get("layout", "fill")
    spec = {"layout": layout}
    if layout == "split":
        spec["split"] = cfg["split"]
    else:
        spec["crop"] = cfg["crop"]
    spec_path = ctx.stage_path("reframe_spec.json")
    with open(spec_path, "w") as f:
        json.dump(spec, f)
    _run_stage_cli("motion/reframe_split.py", [mezz, spec_path, framed],
                   "reframe_split")
    return framed


def reframe_stage(ctx: RenderCtx, mezz: str) -> str:
    """Stage 2: 9:16 reframe (shorts). Longform/none passes through.

    ``reframe.layout == 'split'`` (or a fill-mode manual ``crop``) dispatches
    to the manual-geometry renderer; layout absent + no crop = the original
    strategy path, byte-for-byte unchanged.
    """
    mode = ctx.plan["target"]["mode"]
    cfg = ctx.plan.get("reframe") or {}
    if cfg.get("layout", "fill") == "split" or cfg.get("crop") is not None:
        framed = ctx.stage_path("framed.mp4")
        if ctx.skip(framed, "reframe"):
            return framed
        return _reframe_manual_stage(ctx, mezz, framed)
    strategy = cfg.get("strategy", MODES[mode]["reframe_default"])
    if strategy == "none":
        emit(status="stage_skipped", stage="reframe", reason="strategy none")
        return mezz
    framed = ctx.stage_path("framed.mp4")
    if ctx.skip(framed, "reframe"):
        return framed
    windows = ctx.stage_path("windows.json")
    if strategy == "face":
        # Coordinate contract: face_track measures crops ON THE MEZZANINE.
        _run_stage_cli("motion/face_track.py",
                       [mezz, os.path.join(ctx.out_dir, "timeline_map.json"),
                        windows], "face_track")
    else:
        with open(windows, "w") as f:      # center/blurpad ignore content
            json.dump([], f)
    _run_stage_cli("motion/reframe.py",
                   [mezz, windows, framed, "--strategy", strategy], "reframe")
    return framed


def overlays_stage(ctx: RenderCtx, framed: str) -> str:
    """Stage 3 (Phase 2): composite hook-card overlays on the reframed video.

    Reads ``ctx.plan['titleCards']``; an empty list passes through untouched
    (captions still burn later in master). Cards are pre-validated by plan_lint
    (<=2 lines / <=8 words / safe-box fit), so this only renders + overlays them.
    """
    cards = ctx.plan.get("titleCards") or []
    if not cards:
        emit(status="stage_skipped", stage="overlays", reason="no title cards")
        return framed
    overlaid = ctx.stage_path("overlaid.mp4")
    if ctx.skip(overlaid, "overlays"):
        return overlaid
    png_dir = ctx.stage_path("cards")
    os.makedirs(png_dir, exist_ok=True)
    built: list[dict] = []
    for i, tc in enumerate(cards):
        png = os.path.join(png_dir, f"card_{i:02d}.png")
        w, h = build_card_png(str(tc.get("text", "")), png)
        built.append({"png": png, "outStart": float(tc["outStart"]),
                      "outEnd": float(tc["outEnd"])})
    apply_cards(framed, built, overlaid)
    emit(status="stage_done", stage="overlays", cards=len(built))
    return overlaid


def graphics_track_stage(ctx: RenderCtx, video: str,
                         ass: str | None) -> tuple[str, str | None]:
    """Stage 3.5 (MG-2): motion graphics — render + composite graphicsTrack.

    Consumes the captions ASS so own-screen takeovers can suppress their
    caption events (returns the possibly-rewritten ASS path). Empty track =
    passthrough. Runs the CLI under the venv (hyperframes/node subprocess).
    """
    track = ctx.plan.get("graphicsTrack") or []
    if not track:
        return video, ass
    # THE EXIT LAW (G4): entries flagged exitOnCut die exactly ON the next
    # cutTrack seam — clamp deterministically before the composite (shared
    # math with plan_lint_motion via graphics.exit_on_cut).
    track, clamped = apply_exit_on_cut(ctx.plan)
    if clamped:
        emit(status="exit_on_cut_clamped", entries=clamped)
    out = ctx.stage_path("graphics.mp4")
    track_path = ctx.stage_path("graphics_track.json")
    with open(track_path, "w") as f:
        json.dump(track, f)
    args = [video, track_path, out,
            "--cache-dir", os.path.join(SCRIPT_DIR, "..", "..", "templates",
                                        "motion", "renders", "cache"),
            # Eye-trace placements sidecar → out_dir so Audit B finds it
            # (audit_motion.check_eye_trace — advisory WARN, LIAM move 4).
            "--placements-out", os.path.join(ctx.out_dir,
                                             "graphics_placements.json")]
    ass_out = ass
    if ass:
        ass_out = ctx.stage_path("captions-final.ass")
        args += ["--ass", ass, "--ass-out", ass_out]
    # The suppressed ASS is NOT covered by the video skip: captions may have
    # been regenerated (or captions-final.ass deleted) since the cached
    # graphics render — a stale/missing path here fails master's subtitles
    # filter with a bare "encode failed" (found the hard way, 2026-07-05).
    template_dir = os.path.join(SCRIPT_DIR, "..", "..", "templates",
                                "motion", "compositions")
    inputs = [video, os.path.join(SCRIPT_DIR, "graphics", "graphics_stage.py"),
              os.path.join(SCRIPT_DIR, "graphics", "delivery_geometry.py")]
    inputs += [os.path.join(template_dir, f"{row['kind']}.html")
               for row in track]
    if ass:
        inputs.append(ass)
    signature = stage_fingerprint(track, inputs)
    current = ctx.resume and stage_receipt_current(out, signature)
    if current:
        emit(status="stage_skipped", stage="graphics", out=out,
             reason="current stage fingerprint")
    if not current or (ass_out != ass and not os.path.exists(ass_out)):
        _run_stage_cli("graphics/graphics_stage.py", args, "graphics")
        write_stage_receipt(out, signature)
    return out, ass_out


def enhance_stage(ctx: RenderCtx, video: str) -> str:
    """Stage 4.4: voice-focus dialogue cleanup (plan.audioEnhance).

    Corrective before editorial: denoise/presence runs BEFORE the gain windows
    and the loudnorm master, so the cleaned signal is what gets leveled. Must
    run BEFORE transitions_stage (4.7): at 4.4 the program audio is still the
    pure dialogue bus (broll/graphics don't touch audio), so ``separate``
    (Demucs residual −60dB) and voice-rnn can't delete the authored transition
    whoosh SFX that transitions amixes in.
    """
    preset = (ctx.plan.get("audioEnhance") or {}).get("preset")
    if not preset:
        return video
    out = ctx.stage_path("enhanced.mp4")
    if not ctx.skip(out, "audio_enhance"):
        _run_stage_cli("audio/audio_enhance.py", [video, preset, out],
                       "audio_enhance")
    return out


def gain_stage(ctx: RenderCtx, video: str) -> str:
    """Stage 4.5 (MG-2): per-window dialogue gain (plan.audioGain).

    Runs BEFORE master's loudnorm — loudnorm re-measures, so the program
    stays at target while relative levels shift (PRODUCER_PLAN §4.5).
    """
    gains = ctx.plan.get("audioGain") or []
    if not gains:
        return video
    out = ctx.stage_path("gained.mp4")
    gains_path = ctx.stage_path("audio_gains.json")
    with open(gains_path, "w") as f:
        json.dump(gains, f)
    if not ctx.skip(out, "audio_gain"):
        _run_stage_cli("audio/audio_gain.py", [video, gains_path, out], "audio_gain")
    return out


def kept_words(ctx: RenderCtx, tmap: TimelineMap) -> list[dict]:
    """Gather every source's words, remapped to output time, sorted."""
    manifest_dir = os.path.dirname(os.path.abspath(
        ctx.manifest.get("_path", os.path.join(ctx.out_dir, "x"))))
    words: list[dict] = []
    for src in ctx.manifest.get("sources", []):
        rel = src.get("transcriptPath")
        if not rel:
            emit(status="captions_source_skipped", id=src["id"],
                 reason="no transcript")
            continue
        path = rel if os.path.isabs(rel) else os.path.join(manifest_dir, rel)
        with open(path) as f:
            entries = json.load(f).get("transcript", [])
        flat = [w for e in entries for w in e.get("words", [])]
        words.extend(remap_words(flat, src["id"], tmap))
    return sorted(words, key=lambda w: w["start"])


def corrected_caption_words(ctx: RenderCtx, tmap: TimelineMap) -> list[dict]:
    """Return kept words after the one grounded caption-correction contract."""
    words = kept_words(ctx, tmap)
    corrections = dict(CAPTION_AUTO_CORRECTIONS)
    corrections.update((ctx.plan.get("captions") or {}).get("corrections") or {})
    if not corrections:
        return words
    words, corr_log = apply_corrections(words, corrections)
    emit(status="captions_corrected", applied=len(corr_log),
         unmatched=unmatched_keys(corrections, corr_log))
    return words


def captions_stage(ctx: RenderCtx, tmap: TimelineMap) -> str | None:
    """Stage 3 (Phase 1 scope): burned captions from kept words."""
    mode = ctx.plan["target"]["mode"]
    cap_cfg = ctx.plan.get("captions") or {}
    if not cap_cfg.get("burn", MODES[mode]["captions_burn"]):
        emit(status="stage_skipped", stage="captions", reason="burn off")
        return None
    words = corrected_caption_words(ctx, tmap)
    if not words:
        # Burn is ON (checked above) but there is nothing real to burn.
        # Shipping a caption-less short as success would violate doctrine
        # (captions mandatory in shorts; never fabricate, never silently
        # degrade) — fail loudly; the operator can set captions.burn=false
        # explicitly to override.
        raise RuntimeError(
            "captions.burn is on but no transcribed words are available "
            "(missing transcripts?) — transcribe the sources or set "
            "captions.burn=false explicitly")
    # Minimal-style inputs (MG-3.5): emphasis words + face-relative band.
    cfg_extras = {}
    if cap_cfg.get("emphasisWords"):
        cfg_extras["emphasisWords"] = cap_cfg["emphasisWords"]
    if cap_cfg.get("faceBBoxNorm"):
        cfg_extras["faceBBoxNorm"] = cap_cfg["faceBBoxNorm"]
    ass_path = ctx.stage_path("captions.ass")
    style = cap_cfg.get("style", MODES[mode]["captions_style"])
    # Aspect-correct geometry: 16:9 longform captions land lower-CENTER third, not
    # the 9:16 mid-chest position CANVAS would otherwise force.
    cfg = caption_cfg_for_aspect(MODES[mode]["aspect"])
    cfg.update(cfg_extras)
    offset = int(cap_cfg.get("bandYOffsetPx", 0))
    if offset:
        # Edge C12: shift the caption band UP when the source has its own
        # burned-in lower-third in the default band (lint bounds the offset).
        top, bottom = cfg["y_band"]
        cfg["y_band"] = (top - offset, bottom - offset)
        cfg["baseline_max_y"] = cfg["baseline_max_y"] - offset
        emit(status="captions_band_shifted", offsetPx=offset,
             baseline=cfg["baseline_max_y"])
    with open(ass_path, "w") as f:
        f.write(build_ass(words, style, cfg))
    cards = [(float(c["outStart"]), float(c["outEnd"]))
             for c in ctx.plan.get("titleCards") or []]
    if cards:
        # LESSON-022: the hook zone shows the designed lockup INSTEAD of
        # captions — no frame may carry card text and caption cues together.
        dropped = suppress_captions(ass_path, ass_path, cards)
        emit(status="captions_suppressed_under_cards", dropped=dropped,
             cards=len(cards))
    emit(status="stage_done", stage="captions", words=len(words), style=style)
    return ass_path


def longform_sidecar_stage(ctx: RenderCtx, tmap: TimelineMap) -> str | None:
    """Longform SRT sidecar (+ chapters.txt if the plan has them) — the YouTube-CC
    caption deliverable. Longform defaults to NOT burning captions, so without this
    a longform shipped with no captions at all (and the Hook Contract's caption
    clause referenced a sidecar that was never written). Shorts skip it (they burn).
    """
    if ctx.plan["target"]["mode"] != "longform":
        return None
    if not lane_required(ctx.plan.get("target") or {}, "captions"):
        emit(status="stage_skipped", stage="longform_srt", reason="caption lane off")
        return None
    words = corrected_caption_words(ctx, tmap)
    if not words:
        emit(status="stage_skipped", stage="longform_srt", reason="no words")
        return None
    srt_path = os.path.join(ctx.out_dir, "captions.srt")
    cues = write_srt(words, srt_path)
    emit(status="stage_done", stage="longform_srt", cues=cues)
    chapters = ctx.plan.get("chapters")
    if chapters:
        with open(os.path.join(ctx.out_dir, "chapters.txt"), "w") as f:
            f.write(build_chapters(chapters))
        emit(status="stage_done", stage="chapters", count=len(chapters))
    return srt_path


def master_stage(ctx: RenderCtx, src: str, ass: str | None,
                 duration: float | None = None) -> dict:
    """Stage 5: loudnorm + final encode + cover frame (clamped to prediction)."""
    rate = probe_video(src)["r_frame_rate"]
    fps = int(round(float(Fraction(rate))))
    # Fractional NTSC rates must reach -r exactly (rounding 23.976 -> 24
    # duplicates frames and slides frame-indexed seams — v2 intro finding).
    fps_exact = None if float(Fraction(rate)) == fps else rate
    final = os.path.join(ctx.out_dir, "final.mp4")
    invalidate_assembled_sidecar(final)
    spec = MasterSpec(src=src, out=final, ass=ass, fps=fps,
                      fps_exact=fps_exact,
                      cover=os.path.join(ctx.out_dir, "cover.png"),
                      duration=duration)
    result = master(spec)
    if ctx.plan["target"]["mode"] == "longform":
        # Edge X18: the file-size cap is TikTok's in-app limit — shorts-only.
        # A 600MB+ long-form master is normal for YouTube.
        result["warnings"] = [w for w in result.get("warnings", [])
                              if "exceeds cap" not in w]
    if result.get("status") != "done":
        # master() reports failures as a dict — every other stage raises, so
        # convert here or a broken final encode would report render success.
        raise RuntimeError(f"master failed: {result.get('error') or result}")
    emit(status="stage_done", stage="master", **{
        k: result[k] for k in ("out", "lufs_measured", "lufs_within_tolerance")
        if k in result})
    return result


def _assert_reframe_frames(mezz: str, framed: str, n_segments: int) -> None:
    """Reframe must not change the timeline: frame counts must match.

    Symmetric with cut_speed's assertion — without it, per-segment rounding in
    the face path could silently shift captions/crops off the content
    (review finding, 2026-07-04). Tolerance mirrors stage 1: 1 + 0.5/segment.
    """
    n_in, n_out = probe_video_frames(mezz), probe_video_frames(framed)
    tolerance = 1.0 + 0.5 * n_segments
    if abs(n_out - n_in) > tolerance:
        raise RuntimeError(
            f"reframe changed the timeline: {n_in} -> {n_out} frames "
            f"(tolerance {tolerance:.1f})")
    emit(status="reframe_frames_ok", frames_in=n_in, frames_out=n_out)


def audit_stage(ctx: RenderCtx) -> Optional[dict]:
    """Audit B on the finished out_dir (auto QC — every render gets audited).

    Warn-level findings pass through in the report; a FAILED audit raises —
    a render that flunks its own deterministic QC must not report success.
    """
    env = {**os.environ, "PYTHONPATH": SCRIPT_DIR
           + os.pathsep + os.environ.get("PYTHONPATH", "")}
    cmd = [venv_python(), os.path.join(SCRIPT_DIR, "audit", "audit_render.py"),
           ctx.out_dir]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    summary: Optional[dict] = None
    for line in reversed(proc.stdout.strip().splitlines()):
        try:
            summary = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    if summary is None:
        raise RuntimeError("audit produced no parsable verdict: "
                           + (proc.stderr or proc.stdout)[-300:])
    emit(status="stage_done", stage="audit", **{
        k: summary[k] for k in ("overall", "passed", "warnings", "failed")
        if k in summary})
    if proc.returncode != 0 or summary.get("overall") == "fail":
        raise RuntimeError(f"render failed its own audit: {summary}")
    return summary


def _write_base_artifacts(ctx: RenderCtx, tmap: TimelineMap, report: dict) -> None:
    """BASE render bookkeeping: fingerprints + plan snapshot for assemble.py."""
    rec = fingerprint_record(ctx.plan)   # legacy + split video/audio prints
    report["baseFingerprint"] = rec["fingerprint"]
    with open(os.path.join(ctx.out_dir, "base.fingerprint.json"), "w") as f:
        # manifestPath = the rebuild context: assemble.py --auto-base re-runs
        # this base render when a cut/zoom/audio edit flips the fingerprint.
        json.dump({**rec, "outputDuration": tmap.output_duration,
                   "manifestPath": ctx.manifest.get("_path")}, f)
    with open(os.path.join(ctx.out_dir, "base_plan.json"), "w") as f:
        json.dump(ctx.plan, f, indent=1)   # the OLD timebase for plan_refit
    emit(status="base_ready", fingerprint=rec["fingerprint"])


def _checkpoint_full_render(ctx: RenderCtx) -> None:
    """Stamp provenance only after a non-base render fully succeeds."""
    if ctx.skip_graphics:
        return
    if (ctx.plan.get("music") or {}).get("enabled"):
        emit(status="final_provenance_skipped",
             warning="music is enabled but monolithic render does not apply "
                     "the assemble-time bed — run assemble.py before this "
                     "final can claim plan authority")
        return
    final = os.path.join(ctx.out_dir, "final.mp4")
    record = write_assembled_sidecar(final, ctx.plan)
    emit(status="final_provenance", planHash=record["planHash"],
         authorityHash=record["authorityHash"])


def render(ctx: RenderCtx, audit: bool = True) -> dict:
    """Run the full chain (+ automatic Audit B); returns the render report."""
    gate(ctx)
    tmap = compile_stage(ctx)
    mezz = cut_stage(ctx)
    mezz = channels_stage(ctx, mezz)
    based = baseline_stage(ctx, mezz)
    framed = reframe_stage(ctx, based)
    if framed != based:
        _assert_reframe_frames(based, framed, len(tmap.segments))
    recompose_stage(ctx, framed, tmap.output_duration)
    punched = punch_stage(ctx, framed)
    brolled = broll_stage(ctx, punched)
    overlaid = overlays_stage(ctx, brolled)
    ass = captions_stage(ctx, tmap)
    srt = longform_sidecar_stage(ctx, tmap)
    if ctx.skip_graphics:
        # BASE render (incremental-graphics loop): everything EXCEPT the graphics
        # composite, mastered graphics-free. assemble.py overlays the graphic
        # parts onto this base later — no base re-render on a graphics-only edit.
        emit(status="stage_skipped", stage="graphics",
             reason="base render (--skip-graphics); assemble composites later")
        video = overlaid
    else:
        video, ass = graphics_track_stage(ctx, overlaid, ass)
    # Enhance BEFORE transitions: the dialogue cleanup must never eat the
    # whoosh SFX that transitions amixes into the program (see enhance_stage).
    video = enhance_stage(ctx, video)
    video = transitions_stage(ctx, video, tmap.output_duration)
    video = gain_stage(ctx, video)
    result = master_stage(ctx, video, ass, tmap.output_duration)
    if (ctx.plan.get("music") or {}).get("enabled") and not ctx.skip_graphics:
        # Music is an ASSEMBLE-time stage (audio/music_stage.py) — say so
        # loudly instead of silently shipping a music-less monolithic master.
        emit(status="music_not_applied",
             warning="plan.music is applied by assemble.py (audio/music_stage.py"
                     " → audio_mix) — this monolithic render did NOT mix the "
                     "music bed; run assemble.py over this output to apply it")
    report = {
        "planVersion": ctx.plan.get("planVersion"),
        "mode": ctx.plan["target"]["mode"],
        "predictedDurationS": round(tmap.output_duration, 3),
        "captionsBurned": ass is not None,
        "captionsSidecar": srt,
        "master": result,
    }
    if ctx.skip_graphics:
        _write_base_artifacts(ctx, tmap, report)
    with open(os.path.join(ctx.out_dir, "render_report.json"), "w") as f:
        json.dump(report, f, indent=2)
    if audit and not ctx.skip_graphics:      # audit the assembled deliverable, not the base
        report["audit"] = audit_stage(ctx)
    _checkpoint_full_render(ctx)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="PRODUCER render orchestrator")
    ap.add_argument("plan_path")
    ap.add_argument("manifest_path")
    ap.add_argument("out_dir")
    ap.add_argument("--workdir", default=None,
                    help="keep intermediates here (default: temp, cleaned)")
    ap.add_argument("--resume", action="store_true",
                    help="skip stages whose --workdir outputs already exist")
    ap.add_argument("--no-audit", action="store_true",
                    help="skip the automatic post-render Audit B")
    ap.add_argument("--skip-graphics", action="store_true",
                    help="BASE render for the incremental-graphics loop: master "
                         "everything except the graphics composite + write "
                         "base.fingerprint.json (assemble.py overlays graphics after)")
    ap.add_argument("--approval-dir", default=None,
                    help="producer dir owning the template-history approval")
    args = ap.parse_args()

    temp_dir = None
    try:
        with open(args.plan_path) as f:
            plan = json.load(f)
        with open(args.manifest_path) as f:
            manifest = json.load(f)
        require_template_usage_approval(
            args.plan_path, args.manifest_path, args.approval_dir or args.out_dir,
            os.path.dirname(os.path.abspath(args.manifest_path)))
        manifest["_path"] = os.path.abspath(args.manifest_path)
        os.makedirs(args.out_dir, exist_ok=True)
        work = args.workdir
        if work:
            os.makedirs(work, exist_ok=True)
        else:
            temp_dir = tempfile.mkdtemp(prefix="producer-render-")
            work = temp_dir
        ctx = RenderCtx(plan=plan, manifest=manifest,
                        out_dir=args.out_dir, work_dir=work,
                        resume=args.resume and args.workdir is not None,
                        skip_graphics=args.skip_graphics)
        shutil.copy(args.plan_path, os.path.join(args.out_dir, "edit_plan.json"))
        report = render(ctx, audit=not args.no_audit)
        emit(status="done", **report)
    except (OSError, json.JSONDecodeError, KeyError,
            ValueError, RuntimeError) as exc:
        emit(error=str(exc))
        sys.exit(1)
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


if __name__ == "__main__":
    main()
