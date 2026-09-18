# Claude Code Desktop → Palmier output audit

> **Historical audit.** Its prescribed first-60 exercise was later run and
> exposed additional failures rather than qualifying the product: 56m48s,
> candidate QC still pending, seven lost karaoke timings, and an accepted
> 3840×2160 canvas. Current local contracts and remaining connected blockers are
> tracked in
> `docs/producer/command-driven-editing/17_P5_EXIT_AUDIT.md`.

## Verdict

The poor output was not primarily a model-intelligence problem. The repository
made quality knowledge advisory while giving Desktop either no Palmier mutation
authority or unlimited mutation authority. It also serialized full visual-plan
convergence ahead of the first visible edit.

The resulting failure chain was:

`full-plan-first skill → multiple serial reviews → global mutation denial →
operator bypass marker → direct ad-hoc MCP placement → no per-operation CAS →
QC sees the export late (or not at all)`

## Why speaker/container placement failed

`motion/recompose.py` already measures the face and computes the center of the
remaining clear region for registered rails. The deterministic renderer and
checkpoint preparation use it. Freehand Desktop MCP calls did not. A model saw
`set_keyframes` and `apply_layout`, but it did not receive an enforced geometry
receipt tying the graphic window to the measured face box and synchronized
recompose window.

The new visual-stage manifest runs the same checkpoint preparation first. A
rail that cannot produce measured recompose fails before its files unlock.

## Why graphics repeated or looked generic

The template catalog, graphics proposal, authoring prompt, plan critic, skill,
and Palmier tool vocabulary were separate information surfaces. The agent could
know that many templates existed without receiving a deterministic assignment
for the current transcript beat. The reference uses repeated design tokens but
changes information anatomy; the old output often repeated one familiar anatomy.

The Desktop branch now requires reading the source-derived template catalog and
the graphics proposal before visual-stage unlock. `checkpoint_plan.py` renders
the chosen catalog form into a proved alpha asset; the bound worklist authorizes
only those imports.

## Why “more transitions” did not fix smoothness

The reference has only 7 hard cuts in 323 seconds. Its continuity comes from
face persistence, progressive builds, word-locked entrances, and a persistent
PIP/screen-share chapter. Palmier has no proven general transition primitive.
The supported white-flash and light-leak visuals can be rendered as explicitly
labeled alpha overlays; zoom-pull remains unsupported because it needs
blur-masked cross-cut keyframe composition.

The previous checkpoint code rejected even the supported overlays when the
transition lane was automatic. That veto is removed. Supported transitions are
now visible and labeled `baked`/`approximate`; unsupported kinds remain explicit
omissions rather than being faked.

## Why it stalled

The canonical skill said “understand everything before deciding anything” and
required repeated whole-plan audits before a frame was rendered. The GUI audit
also measured at least eight model spawns across six serial stages, with a best
case around 24–30 minutes and common 55–100 minute runs. QC defects restarted a
large tail of that sequence.

The reference-study path exposed the same shape during this audit. The 2fps
fingerprint completed and produced 647 sampled frames, 82 unique states, and 7
hard cuts. The deeper OCR pass then entered serial Tesseract work over 200 text
events and had produced no final artifact after roughly 34 minutes, so it was
stopped. Existing hash-bound Nate Herk studies already contained the fine-step
card analysis. Production must reuse those studies; download/OCR is offline
style ingestion, never a repeated job-stage gate.

The Desktop workflow now splits the authority boundary:

1. transcript-bound cut-only plan → gate → candidate fork → visible cut;
2. visual plan/gates and asset rendering continue while that cut remains safe;
3. exact worklist applies in resumable batches;
4. QC repairs preserve verified candidate ancestry.

The visual-stage deterministic gates run concurrently because their inputs are
immutable and independent. The cut gate remains a single cheap previsual check.

## QC that now blocks completion

`desktop_cli.py qc` exports the exact candidate timeline and verifies graph
structure, canvas, fps, duration, native audio, loudness, audio quality,
black/freeze/flash glitches, smoothness, and plan-aware frame extraction.

`desktop_cli.py approve` then requires two exact-export review rows:

- composition: framing, occlusion, typography, contrast, color, transitions,
  blank frames;
- editorial: spelling, word lock, graphic variety, graphic relevance, pacing,
  audio.

Every check must be `pass` and the review must bind the candidate fingerprint,
export hash, and deterministic audit digest.

## Residual risks

- Palmier native captions re-transcribe; they do not preserve Sniper word cues.
- Named color-grade mappings remain unmeasured. Exact knob settings or a real
  LUT are allowed; guessed presets are not.
- Advanced b-roll focus operations may need an own-screen rendered asset even
  though ordinary b-roll placement is native.
- A passing representative connected short/long cohort remains required before
  calling the Desktop path production-proven; the historical first-60 run was
  a falsifier, not that proof.
