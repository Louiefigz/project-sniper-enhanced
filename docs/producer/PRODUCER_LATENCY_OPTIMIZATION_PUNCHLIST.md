# PRODUCER auto-edit — latency/reliability optimization punch list

> **STATUS: HISTORICAL TACTICAL PUNCH LIST.** The living [headless execution optimization dossier](HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md) now controls optimization order and experiment policy. Keep the current Opus/xhigh settings as the production default, but item 12 does not prohibit isolated frozen-packet model/effort noninferiority tests with seeded-defect and blinded-quality gates.

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

## Applied 2026-07-21 (verified: tsc 0, lint 0, npm test all green, Python selftest 2638 OK)

- **#4 — Overlap the render→Palmier courtesy checkpoint with the QC round.**
  `pipeline.ts` `qualityRoundWithRenderCheckpoint` starts the courtesy publish, runs the
  QC round concurrently, and injects a `renderCheckpointSettled` barrier that
  `quality-loop.ts` awaits after its read-only phase and **before** any mutation
  (promote/revise) — so no plan rewrite or candidate rename can race the checkpoint
  subprocess reading `edit_plan.json`/candidate media (an adversarial review caught the
  unbarriered version). Rejection precedence and non-fatal courtesy outcomes match the
  old serial await exactly; ordering pinned by tests. ~24s/round when Palmier is open.
  Known non-fatal degradation: a revision-stage courtesy publish that collides with a
  still-running render checkpoint defers (SyncLock, `queue_if_busy=False`) and that
  round's revision snapshot is skipped — a later round republishes newer state.
- **#7 — Bound total gate-fix work.** `planning-loop.ts` — `MAX_GATE_FIX_TOTAL = 3`
  per planning-loop invocation + no-progress guard (a consecutive fixer spawn is funded
  only if the gate-error count strictly shrank; counts not identities, because
  `GATE_<GATE>_<n>` codes are positional and renumber). Denial falls through to the same
  revision-writer routing as #1. Caveat: the cap is per `runPlanningReviewLoop`
  invocation — a resumed job gets a fresh budget of 3.
- **#8 — Separate the Palmier working-checkpoint timeout from the 10-min export mirror.**
  `palmier-checkpoints.ts` — `WORKING_CHECKPOINT_TIMEOUT_MS = 6 min` for
  cut/plan/revision/render courtesy checkpoints; `EXPORT_MIRROR_TIMEOUT_MS = 10 min`
  for the approved mirror (unchanged, fail-loud). A hung working checkpoint now warns at
  6 min instead of stalling 10. Caveat: a first publish importing two media assets each
  near the 300s per-import `wait_media` ceiling could exceed 6 min of legitimate work
  and be cut to a warned outcome (courtesy skipped, run continues).
- **#6 — Restore audio-only QC composite-reuse.** `auto-edit-quality-artifacts.ts`
  `seedQcRoundFromPriorCandidate` — rounds ≥ 2 seed the fresh QC round dir with the
  prior round's `final.mp4` + `.assembled.json`, but only after the copied bytes
  SHA-256-match the sidecar's recorded `authorityHash` (staged to `.seed.tmp`, renamed
  after verification; any failure removes all seed files and silently falls back to the
  full composite). `graphics_placements.json` rides along when the prior plan has a
  non-empty graphicsTrack — without it Audit B's fail-closed eye-trace gate would doom
  exactly the seeded rounds (an adversarial review caught this as a blocker). With the
  seed, an eligible audio-only repair takes the ~12s mux path instead of the ~70–86s
  composite; any fingerprint mismatch recomposites exactly as before. A dedicated
  stale-artifact attack on the seed path was run and refuted — no stale frame can reach
  an approved final without byte-exact hash agreement at every stage.

All four verified end-to-end by two independent adversarial reviewers (concurrency +
hash-binding lenses); 1 serious + 1 blocker finding fixed before landing, remaining
minors recorded above as caveats.

## Deferred — medium risk / cross-module (review before doing)

- **#5 — Gate salvaged/resumed partial plans on plan-health.** `authoring-stage.ts:113,268`
  — run the gate bundle on a deadline-salvaged draft; if structurally broken, invalidate
  back to authoring **preserving the approved cut receipt** and re-author only the visual
  lane. Systemic fix for the partial-plan-resume trap (large; cross-module).
- **#9 — Overlap first-clean-review checkpoint with the subsequent assemble render.**
  `planning-clean-progress.ts:67`.

## Measure a real baseline first (a too-tight cap inverts the win)

- **#10 — Split the shared 45-min authoring timeout into independent cut + visual bounds.**
  `claude-authoring-process.ts` — cut authoring doesn't need 45 min (observed 22–26 min);
  bounding it separately unblocks future visual raises. (Live run 2026-07-14 saw cut
  authoring reach ~26 min — decouple before tightening.)
- **#11 — Recalibrate the gate-fix timeout to the Sonnet/low fixer** now that it's off Opus.
  `brain-review-runner.ts:51`. Small, redundant with #1; measure first.

## PRODUCTION GUARDRAIL — do not downgrade without noninferiority evidence

- **#12** — Do not downgrade **authoring** (`authoring.ts:93`) or **rendered/frame vision
  critics** (`scripts/producer/palmier/candidate-qc/reviewer.ts`) off Opus during any
  latency pass. Those are the craft-judgment spawns; downgrading them trades quality,
  which is the stated non-goal. (The gate-fixer → Sonnet move earlier is fine — it's
  mechanical.)
