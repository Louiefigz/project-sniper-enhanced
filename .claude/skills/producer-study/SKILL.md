---
name: producer-study
description: "STUDY reference videos (shorts or long-form) and extract their graphics/cards/zooms/edit decisions into PRODUCER templates and doctrine. Use when the operator provides example videos to learn from: study this video, extract these graphics, build templates from this reference, why does this edit work, analyze this before/after pair. Outputs: style rules, template specs, built+verified comps."
---

# PRODUCER STUDY — references in, templates + doctrine out

The proven loop (ran end-to-end 2026-07-05/06 on the operator's IG shorts +
"Replaced 5 Content Tools" pair; produced R1–R13, 21 templates, the zoom
engine, and the retake brain). Follow it verbatim; every step's tool exists.

## Inputs the operator may give
- One or more finished reference videos (any aspect) — STYLE study
- A raw + edited PAIR of the same content — EDIT-DECISION study (the gold)
- Screenshots — save to a folder/Desktop FIRST (temp paths purge; filenames
  carry NNBSP — copy with globs, never typed spaces)

## Phase 1 — Deterministic fingerprints (cheap, always first)
```bash
.venv/bin/python3 scripts/producer/study/study_video.py <ref> <outdir>   # cuts/min, states, audio, music
# ZOOM MAP is 3 steps: extract frames at a known fps, face series, then the map:
ffmpeg -i <ref> -vf fps=5 <frames>/f_%06d.jpg
.venv/bin/python3 scripts/producer/study/study_zoom_faces.py <frames> <faces.json> --fps 5
.venv/bin/python3 scripts/producer/study/study_zoom.py <ref> <frames> <faces.json> <outdir>  # punch-in cuts + animated ramps, magnitudes
# PAIR only (transcribe BOTH in one session — same keyword set, else tokenization noise):
.venv/bin/python3 scripts/producer/edit/study_edit_diff.py raw.json edited.json --out report.json
```
For the full per-frame event layer (cuts/zooms/pans/panels/pops + easing + OCR),
`scripts/producer/study/study_deep.py <ref> <outdir>` runs P1 automatically —
schema in `scripts/producer/study/DEEP_SCHEMA.md`.

## Phase 2 — Graphics extraction (the operator's "extract the cards")
1. Unique states already land in `<outdir>/states/` (pHash dedup, settled
   frames). Build chronological contact sheets, 12-up 4×3 grids (ffmpeg
   hstack/vstack — see scratchpad precedent `review-ref*-batch*.png`).
2. VISION-REVIEW EVERY SHEET (operator mandate: sampled ≠ studied — the
   full-state pass found progressive-disclosure, value hand-offs, and
   placement laws the 6-frame sample missed). Catalog per graphic: type,
   anchor position, entrance style, hold, exit, typography, colors.
3. ANIMATION GRAMMAR: for each distinct graphic, extract a frame BURST
   around its entrance (5–8 frames at ~80ms) — mid-wipe/mid-fade frames
   reveal build order and entrance timing (reference standard: 100–170ms,
   staged builds, never pop-from-nothing — R9).

## Phase 3 — Write the rules
Append findings to `docs/studies/REFERENCE_STYLE_STUDY.md` (numbered R-rules with
evidence: timestamps, quoted words, measured values). Contradictions with
existing doctrine get an operator-visible callout, never silently resolved.

## Phase 4 — Template specs → build
For each NEW graphic type: write a spec (canvas, variables incl. atN land
times, build order, tokens — swap reference brand for the Project Sniper accent
#054BC9, keep STRUCTURE) and dispatch a builder agent pointed at:
- the reference frames (exact sheet paths)
- `templates/motion/compositions/` conventions (data-duration attr,
  seek-safe paused timeline, tokens.css)
- verification bar: lint/validate clean; realistic-data render; alpha via
  RGBA-PNG-first (G18 — never ProRes over lavfi color); settled frame
  reviewed NEXT TO the reference frame; sample into renders/samples/;
  backward-compat proof if upgrading an existing comp.

## Phase 5 — Bake numbers into code
Measured constants (cadence, magnitudes, density, thresholds) go to
`producer_config.py` with study citations; legality rules go to
`plan_lint_motion.py` + selftests; workflow rules go to the producer SKILL.
MG-4 (`graphics_planner*.py`) picks new templates up via its trigger→kind
mapping — extend the mapping when a new type earns a trigger.

## Known limits (state honestly in every study)
- pHash barely collapses continuously-moving talking heads (states ≠ cuts)
- scdet misses matched-background punch cuts (zoom_detect catches them)
- Compression floors: sub-4% ramps unreliable below ~1 Mbps sources
- N=1 studies are priors, not laws — recalibrate on each new pair
