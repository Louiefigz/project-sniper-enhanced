# AUTO-EDIT lane — bounded authoring, review, render, and QC

`POST /api/producer/auto-edit` with `{dir, scope, ...storedIntent, resume?}`
returns an SSE stream backed by a detached worker. A transcribed Producer project
goes through an initial brain-authored `edit_plan.json`, controller-owned review
rounds and deterministic gates, isolated render candidates, deterministic and
visual QC, and only then an approved `final.mp4`.

The initial author is not the approval authority. A green self-reported gate or
an MP4 existing on disk cannot skip the controller's quality policy.

## Request and authority

- `dir` — canonical `<workspace project>/producer` directory.
- `scope` — `trim | light | produced | full` from the stored intent.
- the remaining intent fields — Short/Long mode, lane ownership, pace/style,
  reference, music, audio enhancement, and optional brief. The API validates
  them against `project.json`; a missing, invalid, or drifted launch is rejected.
- `resume` — optional boolean. `true` is accepted only when the saved job belongs
  to the same resolved request and stored intent.

Manifest resolution fails loudly:

1. `<dir>/base.fingerprint.json` → its recorded `manifestPath`; a recorded path
   whose file is gone is an error, not a fallback.
2. Otherwise exactly one `<dir>/../source/*manifest*.json`; multiple matches are
   ambiguous and return 409.

An exclusive per-directory launch lease, durable worker PID, stale-token
fencing, and `assemble.py`'s `.assemble.lock` prevent competing owners. A fresh
authoring attempt snapshots an existing plan into `<dir>/plan-history/`.

## Quality policy

Every new or resumed Auto Edit job is `qualityPolicyVersion: 1`. Its durable
checkpoints are:

```
queued → authoring → plan_authored → planning_review → plan_reviewed
       → validating → validated → rendering → rendered → quality_check
       → repairing → complete
```

The policy has two bounded loops.

### Planning loop

- Trim/light: at least one independent plan audit round.
- Produced/full: at least two independent plan audit rounds.
- Every scope: at most four rounds; the final round must be clean.

Each round runs the complete transcript-aware deterministic bundle:

1. `operator_intent_contract.py`
2. `plan_lint.py`
3. `hook_contract.py`
4. `claims_contract.py`
5. `reference_profile_lint.py` when a reference is selected

The stored-intent gate receives authority from the controller, not from the
plan. It requires `target.mode`, `target.scope`, resolved lane ownership,
reference identity, music/audio finish, and unconditional concrete lane coverage
to match the validated `project.json` intent. A plan cannot silently turn Full
into Light or omit an automatically assigned graphics/b-roll/etc. lane.
Credibility remains content-gated by `hook_contract.py`.

The controller also starts a fresh read-only critic process each round. It reads
the current plan, manifest, transcripts, doctrine, failure ledger, stored
operator intent, and reference evidence. It returns a strict structured verdict:
`pass`, `revise`, or `block`, with stable material-issue identifiers.

Material issues go to a separate writer process. Before revision, the current
plan is snapshotted. The writer must account for every issue and produce a
different plan; deferred issues, no-op receipts, a block verdict, or the round cap
stop rendering. A changed plan invalidates downstream authority and starts a
fresh gate/critic round.

### Candidate/QC loop

- At most three isolated render candidates.
- Every plan repair must return through the complete planning loop before another
  render.
- Missing evidence and system-level blocks fail closed instead of approving or
  blindly retrying.

Each candidate must pass deterministic Audit B and two separate fresh visual
critics:

- **composition** — hierarchy, safe geometry, placement, readability, overlap,
  full-screen/own-screen intent, and motion-graphic finish;
- **editorial** — narrative timing, pacing, repetition, cut/graphic alignment,
  restraint, and whether the rendered treatment earns its slot.

Audit B must produce a readable machine report and review frames. Graphics plans
also require measurable placement evidence; absent/unreadable evidence is a hard
failure, not a warning. Plan-repairable material findings invoke a separate
writer, invalidate the reviewed plan, and start the next planning/render round.

## Detached worker and resume contract

The API route validates and leases the request, then launches
`auto-edit/worker.ts` with repo-local Node/tsx in a detached process group. The
worker PID, token, checkpoints, hashes, round counts, candidate path, unresolved
finding ids, and bounded event journal are atomically stored in
`<producer>/.sniper-auto-edit-job.json`. stdout/stderr use the bounded mode-0600
`<producer>/.sniper-auto-edit.log`.

A browser disconnect or Next restart does not own or kill the worker. A dead
owner becomes `interrupted`; the project card offers **Resume Edit** from the
last safe hash-proven checkpoint.

Resume is authority-aware:

- `plan_reviewed` is reusable only when the current plan, manifest, and optional
  reference-profile hashes match the reviewed checkpoint;
- a rendered checkpoint is an isolated candidate, reusable only when its plan
  and manifest hashes, bytes, and assembled-authority proof match;
- an approved final is reusable only when `.sniper-qc-approved.json` matches the
  current plan hash, manifest hash, final hash, assembled proof, and completed
  job;
- any changed input invalidates every downstream checkpoint.

The reusable checkpoint authority is a versioned digest over the raw and
render-affecting plan, manifest, stored/requested intent, manifest transcripts,
reference profile/deep-study/representative frames/decision/provenance,
renderer/config/templates, and QC implementation. Review receipts, candidates,
audit reports, sampled frames, and schema-v2 approval evidence are hash-bound to
that digest. Missing or corrupt job state cannot turn a managed project into a
legacy one; the durable `.sniper-quality-policy.json` marker is authoritative.

Jobs are project-scoped and detached. The user may navigate away or start a
different project without interrupting the first. **Stop & keep checkpoint**
marks only the selected token as interrupted and terminates only that detached
process group; late worker writes are fenced. **Resume Edit** continues from the
last safe checkpoint. There is no fake pause state.

Detached means independent of Next, not immortal. OS shutdown, an explicit
signal, machine failure, or a killed worker group can still interrupt a run.

## Phase 1 — Initial author

The configured subscription brain runs headless with a 45-minute default
timeout per authoring spawn (`SNIPER_AUTHORING_TIMEOUT_MIN` in `.env.local`,
integer minutes 10..240, overrides it — `claude-authoring-process.ts`). Local
mode uses the Codex bridge; the preserved live provider uses Claude Code. It
reads the Producer skill, manifest/transcripts, failure ledger, stored intent,
and optional deep reference study, then writes only `edit_plan.json` plus bounded
scratch artifacts. It may run proposer tools and its prompt-level lint/hook/
reference convergence loop, but it must not render.

The required terminal summary remains:

```
AUTHORED ok segments=<cutTrack length> graphics=<graphicsTrack length>
```

That line only proves the initial author finished. The controller subsequently
re-runs the full stored-intent/plan/hook/claims/reference bundle and independent
critic rounds.

## Phase 2 — Plan review and render-authority lock

After the bounded planning loop passes, the worker checkpoints the exact reviewed
plan hash, manifest hash, and optional reference-profile hash. Validation refuses
to render if current disk authority differs from those reviewed bytes.

`edit/auto_base_guard.py` quarantines a stale or unproven `base_final.mp4` before
assemble. This prevents an auto-authored plan—whose windows are already in its
own output timebase—from being incorrectly refit against an older base. A proven
current base can still take the fast path.

## Phase 3 — Isolated render and promotion

`assemble.py` renders to:

```
<producer>/.sniper-qc/<job-token>/round-<N>/final.mp4
```

The candidate directory also receives its assembled proof plus the plan,
timeline map, cover, render report, and captions when present. The public
`<producer>/final.mp4` is left untouched while the candidate is under review.

After all QC passes, promotion moves the candidate final, proof, proxy, and
diagnostics into the Producer directory and atomically writes
`.sniper-qc-approved.json` last. Only then does the worker emit approved
`outputs` and complete the job.

Every GUI re-render uses the same controller through `reviewSavedPlan: true`.
It loads persisted intent server-side, skips only the initial author, and still
runs fresh planning gates/reviews, isolated candidate render, Audit B, two
rendered critics, bounded repair, and approval-only promotion. After a plan edit
or Save, the old player, filmstrip, waveform, Reveal action, and Palmier toggle
remain stale/disabled until current approved outputs arrive.

For a project without a managed Palmier workspace, this plan-first lane creates
the first approved candidate and may publish a verified one-clip visual-master
bootstrap. Baked/approximate/known-unsupported concepts are capability labels,
not sync blockers; malformed/unknown state is a blocker.

Once Palmier has a managed working timeline, this lane is no longer allowed to
replay `edit_plan.json` over it. Governed AI work must reconcile the complete
current Palmier readback, fork that head, apply a scoped native delta, and keep
the parent preserved. Opening changes nothing; manual edits become the next
working head. There is no product-level take-control/reclaim switch.

## Durable progress events

The worker appends bounded structured events to the job journal, including:

- initial authoring stream and `authoring_done`;
- `planning_review_started`, `planning_gate_bundle`,
  `planning_review_completed`, and `revision_completed`;
- candidate render phase, assemble passthrough, and `candidate_ready`;
- Audit B and per-lens `rendered_review_started/completed`; the aggregate QC
  summary is persisted beside the candidate;
- `repair_started/completed`, `quality_blocked`, or
  `max_rounds_exhausted`;
- `candidate_approved`, approved `outputs`, `candidate_promoted`, and `complete`;
- explicit `error` or `interrupted` terminal evidence.

The request tails this journal to the browser. Reconnect/resume can replay the
current attempt's bounded evidence; a spinner is never the status authority.

## Historical evidence

### Restart survival — 2026-07-12, before the bounded review/QC policy

An older C0679 job resumed from a saved plan and entered ffmpeg rendering. Next's
process group was terminated; the supervisor became ready again in 813 ms while
the detached worker survived, continued advancing its journal, and the browser
reconnected. This proves the detached worker is independent of the request,
browser, and Next process.

That run later exercised the older QC-only resume and finished at 27 pass / 1
warning / 0 fail after missing promotion artifacts were repaired. It does **not**
constitute live-render or E2E evidence for the current multi-round planning,
isolated-candidate, two-critic, repair, or promotion policy.

### Edit-quality exercise — 2026-07-09, pre-detached path

One historical 335-second longform take produced a trim plan in 403.7 seconds,
then rebuilt a 275.65-second final. The author used 19 turns, removed the cold
open/pauses/retakes, authored eight cuts and no engaging lanes (correct for
trim), and passed the then-required plan/hook checks. Restoring the prior plan
and base returned the previous 108.358-second final with matching plan/base
artifacts. This proves the older author/gate/render behavior only.

No new live media or Palmier mutation was run merely to document the current
bounded controller. Record such evidence only after an explicit safe exercise.

## Code map

- `src/app/api/producer/auto-edit/route.ts` — stored-intent validation,
  launch/resume lease, detached-worker start, journal-backed SSE.
- `worker.ts` — detached job owner and durable progress bridge.
- `pipeline.ts` — resumable controller and candidate render loop.
- `planning-loop.ts` / `planning-gates.ts` — bounded independent plan review,
  complete deterministic gate bundle, revision receipts.
- `quality-loop.ts` — Audit B, composition/editorial critics, repair, approval,
  and promotion.
- `brain-review-runner.ts` + review/revision prompts/schema — fresh read-only
  critics and separate plan writers.
- `authoring.ts` / `authoring-prompt.ts` — initial configured brain process.
- `chain.ts` — manifest resolution, base guard, assemble, and Audit B boundary.
- `src/lib/server/auto-edit-job-*` — atomic job journal, locks, hashes,
  checkpoint invalidation, recovery, and stale-token fencing.
- `src/lib/server/auto-edit-quality-artifacts.ts` — isolated candidate paths,
  review artifacts, approval record, and promotion.
- `src/lib/server/producer-run-registry.ts` — durable UI run state.
- `scripts/producer/operator_intent_contract.py` — deterministic stored-intent
  identity and lane-coverage gate.
- `scripts/infra/next_supervisor.mjs` — supervised Next dev/start commands.
