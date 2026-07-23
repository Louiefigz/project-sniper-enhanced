# Plan-Time Geometry Contract — design (2026-07-23)

> Operator ask (after the short-20260723 live run): "Do all the planning up
> front — measure where I am, solve where every graphic goes so it can't block
> me, then execute once — instead of editing, rendering, discovering, and
> fixing on the backend. Target ≤20 min for a 30s short."
> Feasibility study: workflow `wf_bb615628-c4d` (11 agents, all key claims
> adversarially verified, real timings measured). Verdict: **buildable with
> existing machinery; kills the entire post-render placement-defect class at
> ~zero added render cost. Honest budget: ~30 min doctrine-compliant, ~23–26
> with a shadow-validated delta review round; ≤20 requires also compressing
> critic round 1.**

## Why the live run burned 15 minutes on placement

The placement solve structurally CANNOT fail before assemble today: its two
inputs (base pixels, rendered comp) first exist there
(`graphics_stage._render_all` → `resolve_offset_v2`). When no legal region
exists, `graphics_anchors.py:261` silently nudges toward frame center
(v1-deviation, ±220px cap) instead of failing — LL-034. Comp physical size is
unknown until pixels exist — LL-035. So defects are discovered by vision QC
after rendering, and every fix is a re-gate + re-assemble loop.

## The architecture (operator's proposal, mapped to code)

**Phase 1 — plan-time solve, fail-closed (the fix-loop killer):**
1. *Measure the person per window:* generalize `stamp_entry_face_bboxes`
   (recompose.py:290 — today longform-rails-only) to every face-anchored
   graphicsTrack entry, backed by `free_space_sample.sample_window` (median
   face box + hair top + busy cells from the ACTUAL frames of each window).
   No new tracker needed — three granularities already exist.
2. *Know each comp's true size before placement:* render the REAL production
   asset at plan time through the existing content-hash cache
   (`render_entry`: measured 3.4–9.5s/comp cold, 0s warm) and measure with
   the existing `_content_bbox` alpha probe (0.62s). Assemble later is a
   cache hit — total pipeline cost added ≈ 0. (Static layout math REJECTED —
   the template authors themselves could not predict chip-row's wrap; a
   probe-only artifact REJECTED — the real render IS the probe.)
3. *Solve rectangles into the plan:* run `build_free_map` + `_choose_region`
   + `place_content` during planning; write the result into
   `entry.placement {x, y}` + a `solveMeta` sidecar field.
   `entry.placement` already WINS OUTRIGHT at composite and never falls back
   (`graphics_stage.py:225`, `_explicit_offset` raises on failure).
4. *Fail closed, at lint:* `graphics_anchors.py:261` raises typed
   `NoLegalRegion` (face-width-frac, region dims, content dims) instead of
   nudging; `graphics_stage.py:232` stops catching geometry failures into a
   v1 guess (environment failures stay separate). A plan whose comp fits
   nowhere fails PLANNING → the brain swaps anatomy there (LESSON-047
   becomes machine-enforced). Chip overflow (LL-035) is caught the same way:
   measured bbox vs canvas at lint.
5. *Keep the net:* `verify_placement` (free_space.py:363, today opt-in env
   var) becomes default-on for solver-authored placements with
   `verify_min_gap_px > 0`; exemption keys on operator pins (no solveMeta),
   never solver pins.

**Phase 2 — legal concurrency (no doctrine change):**
- Base render starts at round-2 launch, keyed to `base_plan_digest` with a
  non-base diff allowlist on round-2 revisions (fingerprints.py already
  splits base vs non-base keys) — with the allowlist it is not even
  speculative.
- Audit B ∥ vision critics after decoupling the critics' evidence packet
  from Audit B's output (today built FROM it — small mechanical split).

**Phase 3 — the review wall (shadow-gated; this is where ≤20 lives):**
- Delta round 2 (3–5 min focused re-verification of changed fields) is
  legitimate only for revised-plan convergence; validate with the
  seeded-defect + blinded-quality noninferiority pack (QUALITY_MINING_REPORT
  Tier-4 item) before adopting — the no-quality-trade guardrail (#12) holds.
- Round-1 scope shrinks naturally once geometry/fit/contrast are
  deterministic (the critic stops re-deriving placement by eye).

## Honest time budget (30s produced short)

| Stage | Today (clean) | Phase 1 | +Phase 2 | +Phase 3 |
|---|---|---|---|---|
| Ingest+transcribe | 1 | 1 | 1 | 1 |
| Edit-brain + plan + measure pass | 4 | 5 | 5 | 5 |
| Critic rounds (2× Opus) | 18–24 | 18–24 | 18–24 | ~10–11 |
| Render + assemble | 4 | 4 | ∥ (0–2) | ∥ |
| Audit B + C | 6 | 6 | ~4 ∥ | ~4 ∥ |
| Placement fix-loop | **0–15** | **0** | 0 | 0 |
| **Total** | **~33–50** | **~30–32** | **~26–28** | **~20–23** |

The floor is the review wall: even at best, one full critic round + one
delta round ≈ 10–11 min of the ~20. Everything else is now measurement,
cache hits, and parallelism.

## Build order

1. Phase 1 (≈ the fix-loop killer, all existing machinery): S/M — highest
   value per line of code in the pipeline right now.
2. Phase 2 concurrency: S — two mechanical decouplings.
3. Phase 3 delta round: M + shadow validation before adoption.

Related: LL-034 (OPEN — closed by Phase 1 §4), LL-035 (comp fix shipped;
Phase 1 §2 prevents the class), LESSON-047, QUALITY_MINING_REPORT gate-policy
layer (the fail-closed edits should declare semantics through it).
