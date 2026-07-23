#!/usr/bin/env python3
"""plan_lint — the runnable gate between the brain and the renderer.

Validates an ``edit_plan.json`` against its ``asset_manifest.json``: the LLM
identifier contract (every sourceId/assetId/timestamp must resolve — the
brain never invents pipeline identifiers) plus the editorial bounds from
``producer_config``. Exit 0 = renderable (warnings allowed); exit 1 =
rejected, with machine-readable errors the brain retries against.

Usage:
    plan_lint.py <edit_plan.json> <asset_manifest.json>
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Optional

from plan_lint_audio import check_audio, check_music_source
from plan_lint_broll import check_focus_ops, check_slipcover
from plan_lint_face import check_face_pack
from plan_lint_motion import check_motion, check_word_lock
from plan_lint_overlays import check_broll, check_title_cards
from plan_lint_visual import check_form_shape
from graphics.intro_semantic_contract import check_intro_graphics
from graphics.style_profile_contract import check_style_profile
from plan_lint_reframe import check_reframe
from producer_config import (
    CAPTION_STYLES,
    LINT,
    MODES,
    PLATFORMS,
)


class Report:
    """Collects lint findings and renders the gate verdict."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        """Record a blocking error (the plan will be rejected)."""
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        """Record a non-blocking warning (the plan still renders)."""
        self.warnings.append(msg)

    def emit(self) -> int:
        """Print the JSON verdict and return the process exit code."""
        print(json.dumps({
            "ok": not self.errors,
            "errors": self.errors,
            "warnings": self.warnings,
        }, indent=2))
        return 0 if not self.errors else 1


def output_duration_s(cut_track: list[dict]) -> float:
    """Predicted output length: sum of range durations divided by speed."""
    total = 0.0
    for r in cut_track:
        speed = float(r.get("speed", 1.0)) or 1.0
        total += (float(r["end"]) - float(r["start"])) / speed
    return total


def _check_graphic_ids(plan: dict, rep: Report) -> None:
    """Graphic ids (editor-stamped) must be unique — the editor addresses each
    graphic by ``id``, so a collision lets two blocks masquerade as one. The
    field is OPTIONAL (brain-authored / legacy plans carry none; the editor
    stamps them at load), but a present id must be non-empty and unique.
    """
    seen: set[str] = set()
    for i, g in enumerate(plan.get("graphicsTrack") or []):
        gid = g.get("id")
        if gid is None:
            continue
        if not isinstance(gid, str) or not gid:
            rep.error(f"graphicsTrack[{i}]: id must be a non-empty string (got {gid!r})")
            continue
        if gid in seen:
            rep.error(f"graphicsTrack[{i}]: duplicate graphic id {gid!r}")
        seen.add(gid)


def _check_target(plan: dict, rep: Report) -> Optional[dict]:
    """Validate plan.target; return the mode preset or None on failure."""
    target = plan.get("target") or {}
    mode = target.get("mode")
    if mode not in MODES:
        rep.error(f"target.mode must be one of {sorted(MODES)} (got {mode!r})")
        return None
    for p in target.get("platforms") or []:
        if p not in PLATFORMS:
            rep.error(f"unknown platform {p!r} (allowed: {PLATFORMS})")
    if not isinstance(plan.get("planVersion"), int) or plan["planVersion"] < 1:
        rep.error("planVersion must be an integer >= 1")
    return MODES[mode]


def _check_pauses(rng: dict, bounds: tuple[float, float], tag: str, rep: Report) -> None:
    """Each protectedPause must sit within its own cut range [start, end]."""
    start, end = bounds
    for p_start, p_end in rng.get("protectedPauses") or []:
        if not (start <= float(p_start) < float(p_end) <= end):
            rep.error(f"{tag}: protectedPause [{p_start},{p_end}] outside its range")


def _check_audio_lead(i: int, cuts: list[dict], tag: str, rep: Report) -> None:
    """``audioLeadMs`` J-cut bounds (LIAM move 2; ``AUDIO['jcut']``).

    Hard bounds run through ``compile_timeline.parse_audio_lead`` — the
    renderer's own validator, so lint and cut_speed can never drift; plus a
    WARN outside the measured true-J-lead band (65-95 ms median).
    """
    rng = cuts[i]
    if rng.get("audioLeadMs") is None:
        return
    from compile_timeline import parse_audio_lead  # the executor's validator
    from producer_config import AUDIO
    prev = cuts[i - 1] if i > 0 else {}
    try:
        prev_len = ((float(prev.get("end", 0)) - float(prev.get("start", 0)))
                    / (float(prev.get("speed", 1.0)) or 1.0))
        lead_s = parse_audio_lead(
            i, rng, (float(rng.get("start", -1)),
                     float(rng.get("speed", 1.0)) or 1.0), prev_len)
    except (ValueError, TypeError) as exc:
        msg = str(exc)
        rep.error(msg if msg.startswith("cutTrack") else f"{tag}: {msg}")
        return
    lo, hi = AUDIO["jcut"]["lead_band_ms"]
    ms = lead_s * 1000.0
    if not (lo <= ms <= hi):
        rep.warn(f"{tag}: audioLeadMs {ms:g} outside the measured true-J-lead "
                 f"band [{lo},{hi}]ms (EC1/EC2 median 65-95ms) — legal but "
                 "off the measured grammar")


def _check_cut_track(plan: dict, manifest: dict, preset: dict, rep: Report) -> None:
    """Identifier contract + range sanity + speed bounds for every cut."""
    sources = {s["id"]: s for s in manifest.get("sources", [])}
    cuts = plan.get("cutTrack") or []
    if not cuts:
        rep.error("cutTrack is empty — nothing to render")
        return
    if len(cuts) > LINT["max_cut_ranges"]:
        rep.error(f"cutTrack has {len(cuts)} ranges (max {LINT['max_cut_ranges']})")
    for i, r in enumerate(cuts):
        tag = f"cutTrack[{i}]"
        src = sources.get(r.get("sourceId"))
        if src is None:
            rep.error(f"{tag}: sourceId {r.get('sourceId')!r} not in manifest")
            continue
        start, end = float(r.get("start", -1)), float(r.get("end", -1))
        if not (0 <= start < end <= float(src["duration"]) + 0.05):
            rep.error(
                f"{tag}: range [{start},{end}] outside source "
                f"'{src['id']}' duration {src['duration']}"
            )
        speed = float(r.get("speed", 1.0))
        cap = preset["speed_cap_filler"] if r.get("filler") else preset["speed_cap"]
        if not (LINT["speed_min"] <= speed <= LINT["speed_max"]):
            rep.error(f"{tag}: speed {speed} outside [{LINT['speed_min']},{LINT['speed_max']}]")
        elif speed > cap:
            rep.error(f"{tag}: speed {speed} exceeds mode cap {cap}")
        _check_pauses(r, (start, end), tag, rep)
        _check_audio_lead(i, cuts, tag, rep)
    _check_source_overlap(cuts, rep)


def _check_source_overlap(cuts: list[dict], rep: Report) -> None:
    """Reject overlapping cut ranges within one source (edge X14).

    ``remap_words`` maps each word to the EARLIEST containing segment, so a
    replayed range would render caption-less on the repeat. Forbidden in
    Phase 1; revisit if replays become a wanted editorial pattern.
    """
    by_source: dict[str, list[tuple[float, float, int]]] = {}
    for i, r in enumerate(cuts):
        key = str(r.get("sourceId"))
        by_source.setdefault(key, []).append(
            (float(r.get("start", -1)), float(r.get("end", -1)), i))
    for source_id, ranges in by_source.items():
        ranges.sort()
        for (_, e1, i1), (s2, _, i2) in zip(ranges, ranges[1:]):
            if s2 < e1:
                rep.error(
                    f"cutTrack[{i2}]: overlaps cutTrack[{i1}] in source "
                    f"'{source_id}' — replayed ranges drop captions (X14)")


def _check_duration(plan: dict, preset: dict, rep: Report) -> float:
    """Duration budget vs mode floor / target band / hard max.

    A plan flagged ``target.excerpt`` is a deliberate partial render (e.g. the
    first 2 minutes, for review), so the full-video duration FLOOR is a warning
    rather than a hard error. The hard-max ceiling still errors — an excerpt can
    be short, never over-long — so the flag can't be used to smuggle a bad plan."""
    out_dur = output_duration_s(plan.get("cutTrack") or [])
    lo, hi = preset["duration_target_s"]
    excerpt = bool((plan.get("target") or {}).get("excerpt"))
    if out_dur < preset["duration_floor_s"]:
        below = f"output {out_dur:.1f}s below mode floor {preset['duration_floor_s']}s"
        rep.warn(below + " (excerpt)") if excerpt else rep.error(below)
    if out_dur > preset["duration_hard_max_s"]:
        rep.error(f"output {out_dur:.1f}s exceeds hard max {preset['duration_hard_max_s']}s")
    elif out_dur > preset["duration_discovery_max_s"]:
        rep.warn(f"output {out_dur:.1f}s exceeds discovery sweet spot "
                 f"{preset['duration_discovery_max_s']}s")
    target = (plan.get("target") or {}).get("durationTargetS")
    band_hi = float(target) * 1.35 if target else hi
    if out_dur > band_hi:
        rep.warn(f"output {out_dur:.1f}s well above target ({target or lo}-{hi}s)")
    return out_dur


def _check_music_and_misc(plan: dict, manifest: dict, preset: dict, rep: Report) -> None:
    """Music variants/asset + reframe contract + caption style + chapter order."""
    music = plan.get("music") or {}
    if music.get("enabled"):
        variants = music.get("variants")
        if variants is not None and (not set(variants)
                                     or not set(variants) <= {"with", "without"}):
            rep.error("music.variants must be a non-empty subset of ['with','without']")
        check_music_source(music, manifest, rep)
    # Reframe (strategy + fill/split layout contract): plan_lint_reframe owns it.
    check_reframe(plan, preset, rep)
    style = (plan.get("captions") or {}).get("style", preset["captions_style"])
    if style not in CAPTION_STYLES:
        rep.error(f"captions.style {style!r} not in {CAPTION_STYLES}")
    offset = (plan.get("captions") or {}).get("bandYOffsetPx", 0)
    if not isinstance(offset, (int, float)) or not (0 <= offset <= 400):
        # Edge C12: shift is UP only, bounded so the band stays inside the
        # safe area and clear of the hook-card zone.
        rep.error("captions.bandYOffsetPx must be a number in [0, 400]")
    chapters = plan.get("chapters")
    mode = (plan.get("target") or {}).get("mode")
    if chapters and mode != "longform":
        rep.error("chapters are longform-only")
    if chapters:
        starts = [float(c.get("outStart", -1)) for c in chapters]
        if starts != sorted(starts) or (starts and starts[0] < 0):
            rep.error("chapters must have ascending non-negative outStart")


def lint(plan: dict[str, Any], manifest: dict[str, Any],
         words_out: Optional[list] = None) -> Report:
    """Run every check; returns the populated Report.

    ``words_out`` is optional for pure unit callers. Production CLIs/renderers
    always supply KEPT output-time words so transcript-derived form, intro
    semantic, and word-lock contracts cannot be bypassed.
    """
    rep = Report()
    preset = _check_target(plan, rep)
    if preset is None:
        return rep
    # Runs before the cut-track early-return: id uniqueness is independent of
    # cut validity, and a duplicate id is worth surfacing even on a broken plan.
    _check_graphic_ids(plan, rep)
    _check_cut_track(plan, manifest, preset, rep)
    if rep.errors:                      # duration/window math needs valid cuts
        return rep
    out_dur = _check_duration(plan, preset, rep)
    # Title-card + b-roll overlay windows: plan_lint_overlays owns them.
    check_title_cards(plan, preset, out_dur, rep)
    check_broll(plan, manifest, preset, rep)
    # Slip-cover windows (same-source b-roll) must pass the cover excludes —
    # retake spans + lip-flap (FAILURE_LEDGER LL-010); plan_lint_broll owns it.
    check_slipcover(plan, manifest, rep)
    # Image-focus ops on inserts (LIAM move 3): executor-validated shape +
    # treatment gate (EC2 vocabulary — produced graphics only).
    check_focus_ops(plan, rep)
    _check_music_and_misc(plan, manifest, preset, rep)
    check_audio(plan, out_dur, rep)
    check_motion(plan, out_dur, (plan.get("target") or {}).get("mode", ""), rep)
    # Face-aware placement pack (geometry contract v3 item #6): karaoke band,
    # hook cards, pip-hole faceCx, b-roll overlap, drag bbox — declared through
    # the gate-policy layer; plan_lint_face routes verdicts into this Report.
    check_face_pack(plan, rep)
    check_style_profile(plan, out_dur, rep, words_out)
    if words_out is not None:
        check_word_lock(plan, words_out, rep)
        # LL-015 (NATEHERK_CARDS §1.4): comparison-shaped info (≥2 numeric
        # spec tokens + a spoken comparative marker) on a non-comparison
        # card form WARNs — pick the form per MOTION["card_form_map"].
        check_form_shape(plan, words_out, rep)
        check_intro_graphics(plan, words_out, out_dur, rep)
    return rep


def main() -> None:
    if len(sys.argv) not in (3, 4):
        print(json.dumps({"ok": False,
                          "errors": ["Usage: plan_lint.py <edit_plan.json> "
                                     "<asset_manifest.json> [transcripts_dir]"],
                          "warnings": []}))
        sys.exit(1)
    try:
        with open(sys.argv[1]) as f:
            plan = json.load(f)
        with open(sys.argv[2]) as f:
            manifest = json.load(f)
        # render.py convention: relative manifest paths (transcriptPath)
        # resolve against the manifest file's own dir (plan_lint_broll).
        manifest.setdefault("_path", os.path.abspath(sys.argv[2]))
        # Transcript-aware gates are mandatory in production. The optional
        # argument only overrides the normal manifest-directory resolution.
        from graphics_planner import output_words  # local: heavy import
        transcripts_dir = sys.argv[3] if len(sys.argv) == 4 \
            else os.path.dirname(os.path.abspath(sys.argv[2]))
        words = output_words(plan, transcripts_dir, manifest)
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        print(json.dumps({"ok": False, "errors": [f"load failed: {exc}"], "warnings": []}))
        sys.exit(1)
    sys.exit(lint(plan, manifest, words).emit())


if __name__ == "__main__":
    main()
