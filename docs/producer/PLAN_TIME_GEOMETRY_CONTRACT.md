# Plan-Time Geometry Contract — v3, final (2026-07-23)

> v1 of this doc proposed solving exact rectangles into `entry.placement` at
> plan time. A 5-attacker + judge panel (workflow `wf_740b3bb6-001`, all
> load-bearing claims spot-checked in code) returned **two confirmed KILLs**
> against v1 and a forced HYBRID verdict. This v2 IS that verdict. v1's
> authored-placement idea is REJECTED — do not resurrect it.

## Why v1 died (keep these; they are load-bearing)

1. **KILL — the measurement artifact doesn't exist at plan time (shorts).**
   Every sampler v1 cited (`build_free_map`, `sample_window`,
   `stamp_entry_face_bboxes`) measures the DELIVERY-CANVAS video — which for
   shorts is a render product (reframe crops are computed by `face_track`
   inside `reframe_stage`, render.py:325-357; shorts have no persistent
   base). Sampling the raw 16:9 source produces confidently-wrong rectangles
   that would win outright at composite.
2. **KILL — punch zoom was unmodeled.** `punch_stage` runs BEFORE graphics
   (render.py:706-708); the motivating defect happened UNDER a 1.12 punch.
   v1 never mentioned zoom once.
3. **WOUNDs (all confirmed):** no staleness contract binding a solved rect to
   the geometry it was solved against (`plan_refit` remaps windows but never
   placement); solver-authored pixels round-tripping through the LLM every
   revision round violates the code-owns-numbers doctrine; `_clip_record`
   has no solveMeta carrier; the Palmier lane discards `entry.placement`
   wholesale (parity.py:146-147); the caption band (9:16 y 1150-1340) was
   excluded from the solve; the budget table's critic-compression row was
   unevidenced; Phase-2 early-base saves ~0 on revision paths
   (`_NON_BASE_KEYS` is only 5 keys — nearly everything is base-side).
4. **Scope truth (angle 5):** tight faces are this operator's NORM (44.7% and
   61.9% face-width on the two real shorts, falsifying the tail-case
   hypothesis) — but the defect needs a conjunction (planner-seeded unfit
   anatomy + tight face): the other real short placed 10/10 graphics legally.
   Expected incidence ~2-4 of 10 runs.

## The judged architecture — build exactly this, in this order

1. **Fail-closed core (S, first):** typed `NoLegalRegion` replaces the v1
   seed nudge (`graphics_anchors.py:261-264`); `graphics_stage._placement`
   stops catching geometry failures into the v1 guess (environment failures
   stay separate); `verify_placement` default-on (operator pins get
   WARN-with-evidence, never exemption). Declared through the gate-policy
   layer (minimal shim if unbuilt). NO assemble-time anatomy retry — a
   post-gate plan mutation breaks the hash-bound authority contract; typed
   errors route to the brain for re-plan. (Closes LL-034.)
2. **Comp-size measurement at plan time (S):** render the REAL comp early
   through the existing content-hash cache + `_content_bbox` probe —
   comp pixels are video-independent, so this piece has no
   measurement-artifact problem. Order it AFTER `word_lock` snap and
   `exitOnCut` clamp so durations are bit-identical to assemble's (cache-hit
   guarantee). Measured bbox vs canvas = lint FAIL. (Kills the LL-035 class.)
3. **Geometry feasibility LINT — not authored placement (M):** for shorts'
   face-anchored, non-recompose entries, COMPOSE delivery geometry from
   plan-authored transforms: timeline-mapped source-frame face sampling ×
   planned reframe crop × punch scale mirrors (`ramp_scale_at`/
   `push_scale_at` are pure) + caption-band exclusion, then run
   `build_free_map`/`_choose_region` as a fail-closed CHECK with a clearance
   margin. `NoLegalRegion` surfaces PRE-review with anatomy evidence so the
   brain swaps forms at zero loop cost. **Write NO `entry.placement`, NO
   solveMeta** — render-time `resolve_offset_v2` (now fail-closed) remains
   the placement authority on ground-truth pixels. No persisted solved state
   → the staleness/authorship/refit/Palmier wounds dissolve by construction.
4. **Concurrency, only the safe half (S):** decouple the vision critics'
   evidence packet from Audit B so B ∥ C. Early-base only if round-2
   revisions become allowlist-constrained; otherwise skip. Re-baseline the
   budget from durable per-stage timestamps before quoting numbers again.
5. **Delta round 2 stays an EXPERIMENT:** shadow-gated with the
   seeded-defect noninferiority pack. Honest operator promise: **~26-30 min
   now, ~23-26 after step 4; ≤20 is the experiment's success criterion,
   never a commitment.**

## Judge's value math (next ten 30s shorts)

~2-4 runs hit a fit conflict. Today: +10-15 min each (post-render discovery +
re-review). Fail-closed alone: still +10-14 (bounce lands AFTER the review
wall). Hybrid: conflicts die at lint round 0, cost ~+1 min/run measure pass →
~25-50 min saved across ten, plus ~2 avoided Opus critic rounds per avoided
loop. Risk added ≈ 0 persistent state (feasibility recomputed each lint).

## The single most load-bearing fact

The solver's two inputs split cleanly on 9:16 shorts: **comp size is
video-independent** (plan-time measurable through the render cache), but
**delivery-canvas face geometry first exists at render** — so plan-time
placement can only ever be a derived feasibility check, never authored
truth. That one fact kills v1 §3 and rescues everything else.

Related: LL-034 (closed by step 1), LL-035 (class killed by step 2),
LESSON-047, QUALITY_MINING_REPORT gate-policy layer (steps 1+3 declare
through it). Panel: `wf_740b3bb6-001`.


---

# v3 addendum — final pass (workflow `wf_d051ccd7-2df`, 5 attackers + synthesizer)

The v2 hybrid survived with its doctrine core intact (no authored placement,
render-time authority, comp-size measurable, fail-closed replaces the nudge)
— but the final pass KILLED v2 step 3's analytic math and forced three
amendments plus new scope. **This addendum supersedes the conflicting parts
of v2 above.**

## Forced amendments

- **A1 — no analytic composition; measure a real proxy.** The lint cannot
  predict `face_track`'s crop: it is a knife-edge branch (face-vs-center on
  `min_face_samples`/spread) measured on the MEZZANINE (render.py:348) with a
  different detector (YuNet) than the free-map sampler (Haar). Instead the
  lint renders the REAL cut_speed mezzanine (stage 1, deterministic, ~30-60s
  proxy for a short) and runs the REAL `face_track`/`build_free_map`/
  `_choose_region` on it — same detectors, same artifact, same branches, so
  the lint's predicate IS the render's predicate by construction. The caption
  band moves into ONE shared occupancy function consumed by both lint and
  render. Stage order truth the composition missed: baselineLook recrops
  BEFORE reframe; brollTrack REPLACES frames; hair-top is a pixel-motion
  measurement (350px search window, 40% fallback) that no face box composes.
- **A2 — steps 1+3 ship ATOMICALLY + a typed render-time route.** Fail-closed
  alone is a REGRESSION: worker.ts has exactly one failure route
  (`failAutoEditJob`) — a render-time `NoLegalRegion` after the review wall =
  wedged job, worse than today's silent misplace. The worker needs a typed
  error → re-plan route before anything raises at render.
  `verify_placement` default-on demotes to LAST (it has deterministic
  false-FAIL classes on legal compositions: hook cards, PIP takeovers,
  no-face b-roll windows) behind an allow-vocabulary + calibrated margin.
- **A3 — the margin is an empirical residual, never a chosen constant.** The
  render authority runs at `verify_min_gap_px = 0`; any invented lint margin
  is stricter than the authority with no dataset behind it (n=2 real shorts).
  Journal lint-predicted vs render-measured geometry per run; margin = a
  quantile of that residual, with a named owner. Until the ledger exists the
  lint is WARN-with-evidence, not FAIL.
- The "gate-policy minimal shim" was fiction — zero code exists. Its verdict
  schema (FAIL / WARN / SKIP-with-evidence + severity routing) is an explicit
  prerequisite task, not a shim.

## New scope the sweeps found (same disease, other organs)

- **Karaoke captions are face-blind** — the DEFAULT shorts caption style uses
  the fixed y 1150-1340 band with zero face input (face-relative logic is
  wired only to minimal/whisper). On this operator's normal framing (45-62%
  face width) captions can sit on the chin. Cheap arithmetic lint.
- Hook cards: fixed-band, clamp-only, no face check. pip_hole `faceCx`
  defaults to 0.5 — nothing measures it. graphicsTrack↔brollTrack overlap is
  unlinted. GUI drag WARN net is point-degenerate for GUI-created entries.
- **Critic parallelism is ALREADY SHIPPED in the GUI controller**
  (`planning-review-batch.ts` Promise.allSettled) — the skill lane never
  adopted it. Free wall compression.
- **56% DARK TIME:** the real run was ~102 min wall clock; 57 min produced
  zero artifacts and is unattributed because NO stage-timing journal exists.
  Every latency number ever quoted (including v2's table) is modeled, not
  measured. The journal is build slot 0.
- **Draft mode:** doctrine already permits unapproved rendered candidates; a
  DRAFT-watermarked watchable candidate after deterministic gates (pre-wall)
  is buildable and changes the experienced answer more than any wall
  optimization. Nothing watchable existed until minute 62 of the real run.

## FINAL build list (supersedes v2's)

| # | Item | Size |
|---|---|---|
| 0 | Stage-timing journal at every controller boundary + planVersion bumps | S |
| 1 | Gate-policy verdict schema (prerequisite, real task) | S-M |
| 2 | Comp-size plan-time measurement (unchanged from v2 step 2) | S |
| 3 | Feasibility lint + fail-closed core, ATOMIC (A1 proxy-mezzanine + A2 typed worker route) | M |
| 4 | Margin calibration loop (A3) | S |
| 5 | verify_placement default-on (last, allow-vocabulary) | S |
| 6 | Face-aware placement lint pack (karaoke band, hook cards, faceCx, broll overlap, drag bbox) | S |
| 7 | Skill-lane wall adoption: 2 concurrent round-1 critics + plan-review packet + cache counters | S-M |
| 8 | Draft mode (DRAFT-watermarked pre-wall candidate) | S-M |
| 9 | B ∥ C decoupling (after #0 provides real numbers) | S |
| 10 | Delta-round-2 shadow experiment (seeded-defect pack first) | exp |

## The honest 20-minute answer (final)

The real run was ~102 min experienced (not the ~50 modeled); 57 min of that
is dark time nobody measured. After this list: **draft in ~10-15 min,
approved final in ~22-30 min; ≤20 approved remains the delta-round
experiment's success criterion — never a commitment.** Quote no number again
until the timing journal has produced one.
