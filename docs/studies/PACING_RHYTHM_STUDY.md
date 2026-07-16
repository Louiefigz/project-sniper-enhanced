# PACING / RHYTHM / TRANSITION STUDY — upstream planner knowledge base

**Purpose.** The PRODUCER planning agent must decide pacing, rhythm, and transition
speed at PLAN time (looking at the transcript + dead space), not leave it to render-QC.
This doc is the measured, grounded knowledge it plans against — derived from the
operator's raw + pro-edited footage. Like `MOTION_GRAMMAR_STUDY.md`: extract
PRINCIPLES, never copy a specific edit.

**Sample (2026-07-06). Validated across 17 pro edits (12 long-form + 5 shorts) +
2 raw.** Cross-reference `LONGFORM_VISUAL_STUDY.md` (the existing deep zoom-grammar
study — 5 punch rules, front-load 2.5×, "cuts keep the *rhythm*, zooms carry the
*meaning*") and `MOTION_GRAMMAR_STUDY.md`. This doc adds what those don't: the
transition-SPEED distribution, shot-length shape, raw dead-space, and SHORTS pacing.
- Frame-inspected in depth: `Replaced 5 Content Tools…` (975s), `angle generator`
  (654s) — these two sit at the SLOW/produced end of the range.
- Validation batch: 12 long-form + 5 shorts from the operator's library.
- RAW: `C0679` (834s), `C0666` (1104s).
- Method: ffmpeg scene-detect (thr 0.3, downscaled 640w for the batch) → cluster
  consecutive detections (a run = one animated transition, its span = speed; a lone
  detection = hard cut) → de-clustered shot lengths + momentum. Raw: `silencedetect`.
  A scene "cut" = a VISUAL change (hard audio cut OR b-roll/graphic/reframe cutaway
  over continuous speech), so cuts/min is the visual-change RATE, not audio chopping.

---

## 1. Measured numbers

### Pacing / rhythm — VALIDATED group medians
| metric | LONG-FORM (n=12) | SHORTS (n=5) |
|---|---|---|
| **visual-change rate** | **7.0 /min** (range 5–15) | **17.3 /min** (13–20) |
| median shot | **4.6s** | **2.7s** |
| hard cuts (vs animated) | **84%** | **94%** |
| animated-transition span | ~2f (83ms) | ~3f (100ms) |
| hook front-load (vs body) | **×1.7** | **×2.0** |

Shorts run **~2.5× faster** than long-form and are almost pure hard cuts. Long-form
has real STYLE SPREAD (5–15 /min): the two frame-inspected videos (4.5/min) are the
slow/produced end; the median is faster (7/min, ~4.6s shots). Shot-length is
**bimodal** — short 2–6s beats (b-roll/graphics/emphasis) + longer 10–20s talking
stretches — not metronomic.

### Transitions (pro edited, frame-verified)
| | Replaced-5 | angle-gen |
|---|---|---|
| hard cuts | 53% | 65% |
| animated transitions | 47% | 35% |
| animated span — median | 83ms (~2f) | 167ms (~4f) |
| animated span — p90/max | 250ms (~6f) | 167ms (~4f) |

Frame strips confirm the animated ones are **white-flash bridges** (1–2 pure-white
frames) and **graphic/logo pop-ins on a colored (white) card** (~4 frames to settle),
NOT slow dissolves. Nothing measured over 6 frames (250ms).

### Raw dead-space (what the planner tightens)
| | C0679 | C0666 |
|---|---|---|
| silence ≥0.35s | 32% of runtime | 35% |
| pauses | 351 | 518 |
| pause median / max | 0.57 / 9.3s | 0.62 / 11.6s |
| speech density | ~68% | ~65% |

**~1/3 of raw is dead space.** Median pause ~0.6s (trim), plus long 9–11s pauses
(clear removals).

---

## 2. Derived principles for the PLANNING AGENT (upstream)

**Dead-space (cut first):**
- **D1** Expect ~30–35% dead space in raw. Tighten inter-sentence pauses toward
  ~0.2–0.4s; remove pauses >~1s unless a deliberate beat. (`pause_scan` does this —
  calibrate its targets to land speech density ~90%+ post-cut, up from raw's ~65–68%.)

**Pacing / rhythm** (a "cut" = any VISUAL change — audio cut OR b-roll/graphic/reframe
over continuous speech):
- **P1** Visual-change RATE: **long-form ~7/min** (a change every ~8–9s; style range
  5–15), **shorts ~17/min** (every ~3s). No talking-head shot past **~20s** without a
  change (already partly held by the aliveness creep, but a CUT/cutaway ≠ a creep).
- **P2** **Front-load the hook**: first ~60s at **×1.7–2.0** the body rate (confirmed;
  `LONGFORM_VISUAL_STUDY` measured ×2.5 on zoom events).
- **P3** Target shot lengths **bimodally**: short **2–6s** beats (b-roll/graphics/
  emphasis) + longer **10–20s** talking stretches. Median **~4.6s long-form / ~2.7s
  shorts**.
- **P4** **Momentum triggers** — raise rate + add graphics/b-roll where the transcript
  hits: a numbered list ("3 steps"), a reveal/payoff, a tension/high-energy claim.
  Pacing follows CONTENT energy, not a clock.

**Transitions (speed):**
- **T1** **HARD CUT dominates** — **~84% long-form, ~94% shorts**. Instant,
  dialogue→dialogue. This is the default; animated is the exception.
- **T2** Animated transitions are **FAST: ~2–3 frames typical (80–100ms), ≤6f**.
  White-flash bridges (`transitions.py` already renders these + light-leak + whoosh
  SFX). A slow wash (~15f/500ms) appears rarely — reserve it, don't default to it.
- **T3** Reserve flash/animated transitions for entering **graphics / b-roll / a
  high-energy beat**; keep talking-to-talking cuts hard.

**Graphics / image presentation:**
- **G1** Show a still image/logo **on a colored (white) card** with a fast **pop-in
  (~4 frames)**, not necessarily full-bleed. (Answers the b-roll "colored background"
  question — it's a real pattern here.)
- **G2** Graphics carry **internal motion** (e.g. animated background gradient) so the
  frame is never static even during a held graphic.

---

## 3. Gap vs current system (what to build/calibrate)

| Principle | Planner today | Action |
|---|---|---|
| D1 dead-space | `pause_scan` cuts pauses | calibrate thresholds to the ~0.2–0.4s target |
| P1 rate / P3 bimodal / P4 momentum | **not represented** — no visual-change-RATE target coordinating cuts+b-roll+graphics+reframe; each proposer sets its own density ad hoc | **build**: an upstream rhythm target + momentum triggers in the planner |
| P1 max-shot >20s | partly held by aliveness creep (motion, not a cut) | **add** a cut/cutaway when no visual change in ~20s |
| P2 hook front-load | measured (`LONGFORM_VISUAL_STUDY` ×2.5) | confirm it's applied to the cut/graphic rate, not only zooms |
| T1/T2/T3 transition speed | **EXISTS** — `transitions.py` white-flash + light-leak + whoosh SFX | calibrate: hard-cut default (84–94%), flash 2–3f, reserve the 500ms wash |
| shorts pacing | proposers longform-gated | **build** shorts rate (~17/min), 2.7s shots, 94% hard |
| G1 image-on-card | `broll_insert` rejects images | **build** image path + colored-card pop-in (b-roll gaps) |
| G2 graphic internal motion | kinetic-quote holds static (known drift) | **fix** animated bg |

**Backstop (QC, downstream only):** animation smoothness + presence + pacing checks
in Audit B — catch what slips past the planner, never the primary mechanism.

> Caveat: 17 pro edits + 2 raw, downscaled scene-detect (batch) — directional, robust
> on rate/shot-length/hard-cut-share. NOT yet measured: transcript-aligned momentum
> triggers (P4 — which content beats the rate actually tracks), and per-video
> transition-TYPE classification beyond the two frame-inspected. Reconciles with
> `LONGFORM_VISUAL_STUDY.md` (zoom grammar) — this doc owns pacing/rhythm/transition
> speed; that one owns zoom/emphasis.
