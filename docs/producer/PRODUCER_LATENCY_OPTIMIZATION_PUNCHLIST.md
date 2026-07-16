# PRODUCER auto-edit — latency/reliability optimization punch list

Source: adversarial multi-agent audit (2026-07-14), 30 agents, 18 verified findings
→ 12 actionable items. Every finding was verified against the real code and checked
for quality/correctness/invariant safety. **No item trades output quality** — Opus
xhigh stays on all authoring and rendered/frame critics (item 12 is a guardrail
enforcing exactly that).

The headline: happy-path latency wins are modest (~1–3 min). The real value is
**eliminating doomed work and tail-risk catastrophic aborts** — a single critic
timeout or a broken salvaged plan today discards 15–40 min of work or wedges the job.

## Applied 2026-07-14 (verified: producer TS 95/97, tsc 0, lint clean)

- **#1 — Gate-fix routing by violation count.** `planning-loop.ts` — new
  `MAX_GATE_FIX_ISSUES = 8`; a gate-only failure with more than 8 gate errors skips
  the mechanical fixer and routes straight to the revision writer. Kills the observed
  false-economy (25–30-violation salvaged plan → 2 doomed gate-fixes ~10 min → revision
  anyway).
- **#2 — Critic/revision deadline 12 → 20 min.** `brain-review-runner.ts`
  `REVIEW_STAGE_DEADLINE_MS`. These run on Opus xhigh (not medium — the old comment was
  stale); the 12-min cap could kill one mid-reasoning and **abort the whole job**.
- **#3 — Rendered/QC lens critic cap 20 → 25 min.** `brain-review-runner.ts`
  `REVIEW_TIMEOUT_MS`. Cap now sits above the ~20-min measured max, not at it.

All three are pure constant/routing changes — no model, no effort, no invariant, no
effect on an already-running worker (they harden the next run / any retry).

## Recommended next (low-risk, small — not yet applied)

- **#4 — Overlap the render→Palmier courtesy checkpoint with the QC round.**
  `pipeline.ts:302` — `Promise.all([checkpoint, quality])` instead of serial await
  (QC reads nothing from the checkpoint). ~24s/round when Palmier is open. Deferred only
  because it's a hot-path concurrency change worth a careful review.
- **#7 — Bound total gate-fix work.** `planning-loop.ts` — run-scoped global cap (~3)
  + no-progress guard (2nd attempt only if the error set shrank). Mostly subsumed by #1.
- **#8 — Separate the Palmier working-checkpoint timeout from the 10-min export mirror.**
  `palmier-checkpoints.ts:14` — give the sub-minute working checkpoint its own ~5–6 min
  bound (above the 300s media-import ceiling) so a hung build can't stall 10 min.

## Deferred — medium risk / cross-module (review before doing)

- **#5 — Gate salvaged/resumed partial plans on plan-health.** `authoring-stage.ts:113,268`
  — run the gate bundle on a deadline-salvaged draft; if structurally broken, invalidate
  back to authoring **preserving the approved cut receipt** and re-author only the visual
  lane. Systemic fix for the partial-plan-resume trap (large; cross-module).
- **#6 — Restore audio-only QC composite-reuse.** `auto-edit-quality-artifacts.ts:47` —
  seed each QC round dir with the prior round's `final.mp4` + matching sidecar so an
  audio-only repair muxes (~12s) instead of a full composite (~70–86s).
- **#9 — Overlap first-clean-review checkpoint with the subsequent assemble render.**
  `planning-clean-progress.ts:67`.

## Measure a real baseline first (a too-tight cap inverts the win)

- **#10 — Split the shared 45-min authoring timeout into independent cut + visual bounds.**
  `claude-authoring-process.ts` — cut authoring doesn't need 45 min (observed 22–26 min);
  bounding it separately unblocks future visual raises. (Live run 2026-07-14 saw cut
  authoring reach ~26 min — decouple before tightening.)
- **#11 — Recalibrate the gate-fix timeout to the Sonnet/low fixer** now that it's off Opus.
  `brain-review-runner.ts:51`. Small, redundant with #1; measure first.

## GUARDRAIL — do NOT do

- **#12** — Do not downgrade **authoring** (`authoring.ts:93`) or **rendered/frame vision
  critics** (`scripts/producer/palmier/candidate-qc/reviewer.ts`) off Opus during any
  latency pass. Those are the craft-judgment spawns; downgrading them trades quality,
  which is the stated non-goal. (The gate-fixer → Sonnet move earlier is fine — it's
  mechanical.)
