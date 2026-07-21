# Headless execution adversarial audit — 2026-07-18, round 3

> **STATUS: FROZEN AUDIT SNAPSHOT.** This records the third adversarial wave and its cross-examination. Corrections belong in the living [headless optimization dossier](../producer/HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md), not by rewriting this record.

## Scope and method

Reviewed only headless Claude Code/Codex planning/execution into Palmier and approved-plan realization into MP4. GUI work remained excluded.

Three independent attacks covered:

1. Competing/simpler architectures versus integrated JobV2 and MP4-first.
2. QC false passes, quality evidence, reliability math, and the greater-than-95% confidence method.
3. Exact V1/V2 migration, persistence, runtime authority, cache, and promotion seams.

The agents then cross-examined the disagreements about early Palmier repair and separate executors. No production code or tests were changed in this round. The earlier full baseline remained the most recent test evidence: complete TypeScript tests and 1,559 Python tests passed before documentation-only changes.

## Decisions overturned

### Integrated JobV2 is not the correct first implementation

The previous dossier selected one integrated detached JobV2 worker with a uniform sink ledger. This round found that choice workable but unnecessarily broad and incorrectly ordered.

Current V1 already provides single-job exclusion, worker tokens, stale-worker fencing, atomic rename persistence, and candidate/final recovery checks in [auto-edit-job-store.ts](../../src/lib/server/auto-edit-job-store.ts), [auto-edit-job-persistence.ts](../../src/lib/server/auto-edit-job-persistence.ts), and [pipeline.ts](../../src/app/api/producer/auto-edit/pipeline.ts). These can support a near-term deterministic MP4 hardening slice.

Separately, a uniform local hash-chain does not solve the Palmier crash gap after remote mutation but before a local receipt. Palmier needs pre-mutation intent, remote operation identity/idempotency, exact readback/reconciliation, and quarantine when an effect is ambiguous.

Revised architecture:

```text
immutable source/cut approval
  -> one target-specific realization approval
  -> one detached realization executor
  -> immutable generation + exact QC
  -> zero or more deliveries of the same approved bytes
```

A broad JobV2 can later project and coordinate this state. It is not the foundational authority boundary.

### Realization and delivery were conflated

The prior `deliveryTarget = mp4 | palmier-flat | palmier-editable` mixed two concepts:

- `deterministic-mp4` and `palmier-editable` describe how content is realized.
- `local-file` and `palmier-flat` describe where the same approved bytes are delivered.

The current pipeline already treats a Palmier mirror failure as independent after MP4 success in [pipeline.ts](../../src/app/api/producer/auto-edit/pipeline.ts). Therefore one realization may have multiple delivery receipts only when they distribute the exact same approved bytes. MP4 and editable Palmier remain separate realization generations and require separate QC.

For the first V2 release, allow one realization per job. Never revive ambiguous `both` semantics.

### The previous authority graph invalidated its own reuse claim

The dossier placed target and intent inside `InputSnapshotRoot`, then claimed editorial approval could be shared across targets. That makes a target switch change the root and invalidates the shared approval.

Corrected roots:

1. `SourceSnapshotRoot`: immutable source/media/transcript/assets and normalized manifest; no target.
2. `EditorialIntentRoot`: requested outcome; no realization or delivery mechanism.
3. `CutApprovalRoot`: target-neutral approved cuts.
4. `RealizationApprovalRoot`: realization kind, capability profile, and compiled instructions.

The existing [edit-plan.ts](../../src/lib/producer/edit-plan.ts) schema includes renderer kinds, pixel placement, punch-ins, transitions, audio presets, music paths, crop/reframe behavior, and other MP4-oriented semantics. Only cut approval is currently demonstrated as portable. The current plan must be treated as a legacy MP4 realization approval until another target establishes a genuinely shared schema.

## Positive Palmier evidence and its limit

The retained `palmier-card-repair-acceptance-20260716-r2` artifact materially improves the performance picture.

### What it demonstrates

- Cut turn: 82.832 seconds.
- Visual turn: 462.752 seconds.
- Combined model turns for initial cut plus visual execution: roughly 9m06s.
- One cached card repair: plan/cache preparation 0.492 seconds; Claude mutation 40.413 seconds.
- One presenter-card replacement: 43.941 seconds.
- Each repair retained timeline/window/track stability, removed one old clip, added one new clip, and reported no full render.

Evidence: [.live-first60-runtime.json](../../artifacts/palmier-card-repair-acceptance-20260716-r2/producer/.live-first60-runtime.json), [card-repair-live-evidence.json](../../artifacts/palmier-card-repair-acceptance-20260716-r2/producer/card-repair-live-evidence.json), and [presenter-hole-repair-live-evidence.json](../../artifacts/palmier-card-repair-acceptance-20260716-r2/producer/presenter-hole-repair-live-evidence.json).

This is the strongest direct evidence that compiled element-level repair can attack the “second quality pass costs another hour” problem.

### What it does not demonstrate

The retained [candidate record](../../artifacts/palmier-card-repair-acceptance-20260716-r2/producer/palmier.timeline-candidate.json) remains edited with QC pending. The desktop authority remains at an active repair stage. There is no retained exact candidate export, deterministic audit, rendered critic approval, completion event, promotion receipt, or publication proof.

The recorded requested replacement copy is self-attested rather than OCR/readback proof. The presenter-visibility assertion does not bind retained reviewed frames. Setup and final QC are excluded from the 40–44-second numbers. The evidence comes from two changes on one project.

Conclusion: scoped-mutation feasibility is proved for this specimen. Publish-ready quality, crash recovery, field reliability, and end-to-end repair latency are not.

## Newly verified QC false-pass mechanisms

### Q1 — music-aware audio QC is silently disabled

[native_qc_audit.py](../../scripts/producer/palmier/native_qc_audit.py) calls `check_audio_quality(export, {})`, discarding the effective plan. [audio_quality.py](../../scripts/producer/audit/audio_quality.py) treats missing `music.enabled` as “music disabled/not declared” and skips the ending music-mask check.

The retained plan requests music, ducking, and an 18 dB gap, while the staged execution explicitly reports that native ducking was unavailable. A native audit can still record an ending-mix pass because the plan was not supplied. This is an observed contract contradiction, not merely a hypothetical edge case.

### Q2 — canvas checks prove only self-consistency

Native structural QC requires positive graph dimensions, then checks export dimensions against that graph. It does not bind the graph/export to the requested delivery canvas.

Consequence: a 16:9 Palmier timeline can pass graph/export consistency for a requested 9:16 short. The later live evidence is itself a 3840×2160 longform-mode project, not evidence for the core vertical-short path.

### Q3 — most mutation families lack operation-specific evidence

[native_qc_frames.py](../../scripts/producer/palmier/native_qc_frames.py) plans targeted evidence for `add_texts`, `apply_layout`, `set_keyframes`, `split_clips`, and `ripple_delete_ranges`. The native planner supports additional caption, text-update, color, effects, audio, silence/word removal, and clip-property operations.

Those additional mutations can receive only generic frame samples rather than evidence bound to the affected operation/window. Imports and overlay replacement also lack an operation-ID-to-frame proof.

### Q4 — caption groups are outside structural proof

[native_qc_audit.py](../../scripts/producer/palmier/native_qc_audit.py) traverses ordinary track clips for structural IDs and bounds but not caption-group IDs, ranges, text, or animation. The live artifact contained 30 caption clips while the structural ID check reported only 16 IDs.

### Q5 — stills do not prove continuous motion or audio

[audit_frames.py](../../scripts/producer/audit/audit_frames.py) extracts three generic caption beats plus event-phase stills. Reviewers receive an MP4 path and stills but are not proven to watch continuous video or listen to the audio. A bad word reveal, one-frame occlusion, transient crop, click, or unducked music interval can fall between samples.

### Q6 — audit-plan copies are not explicitly bound to render proof

MP4 candidate rendering copies `edit_plan.json` into the candidate directory before Audit B. [audit_render.py](../../scripts/producer/audit/audit_render.py) later reads that mutable copy to select windows and allow declared dark/freeze behavior. The copied plan hash is not explicitly asserted against the assembly proof's rendered plan hash at audit time.

### Q7 — warnings and critic independence remain weak

[quality-review-aggregate.ts](../../src/app/api/producer/auto-edit/quality-review-aggregate.ts) promotes only `motion_pacing` warnings into material failures. Other warnings rely on the visual critics. Both Palmier critics run the same reviewer/provider/model over the same evidence in [attempt.ts](../../src/app/api/producer/palmier/candidate-qc/attempt.ts); separate lens prose does not make their misses independent.

Current evidence omits resolved model build, CLI version, prompt hash, token usage, and complete toolchain identity. Moving model aliases undermine longitudinal comparisons.

## Smallest safe Palmier repair canary

The cross-examination revised “ship the fast repair beta early” to “build and benchmark an internal quarantined canary early.”

Required envelope:

- Disposable/forked candidate only; never mutate or promote the canonical timeline.
- One existing cached graphical overlay replacement.
- Same element ID, track, start/end frames, transform, canvas, duration, cuts, captions, audio, color, reframe, effects, and source media.
- One durable common project/Palmier lease for the complete attempt.
- Exact parent/candidate fingerprint, old/new plan digests, asset hash, compiled two-operation manifest, and pre-mutation intents.
- Complete pre/post readbacks and canonical path diff; the only permitted edit is one bound old/new clip plus expected ledger fields.
- Exact unchanged hashes for all unrelated clips, caption groups, and audio tracks.
- Entry/middle/exit or short-clip evidence for the dirty window, with OCR or human confirmation of visible requested copy.
- Any interruption, ambiguity, or unexpected mutation quarantines the candidate.
- Terminal record says `experimental-draft`, `publishable:false`, and `qcStatus:not-run`.
- No approval, output-ready event, automatic promotion, or publication.

An exact full candidate export followed by corrected complete QC is the proper future publication boundary. The current QC defects above must be fixed before automated publication. A human watching and listening to the complete export may approve an individual experiment but does not validate the automated QC system.

## Migration attacks

### V1 can destroy or ignore V2 state

[auto-edit-job-persistence.ts](../../src/lib/server/auto-edit-job-persistence.ts) accepts only version 1. [auto-edit-job-store.ts](../../src/lib/server/auto-edit-job-store.ts) archives a prior non-running journal during a fresh launch. A V2 journal at the existing path can therefore appear invalid and be mishandled. A side-by-side V2 path also fails mutual exclusion because existing V1 launch/status logic would not see it.

Required migration: deploy a common raw envelope reader first. All launch, archive, resume, registry, stream, stop, and worker paths must recognize and fence V1/V2 in the same execution namespace while dispatching to dedicated payload readers. Drain pre-fence workers and prohibit rollback before V2 writers are enabled.

### Dead-journal bootstrap is unsafe now

[launch.ts](../../src/app/api/producer/auto-edit/launch.ts) accepts any parseable `edit_plan.json` from a failed/interrupted journal for fresh retry without proving an exact request-key or immutable approval match. Fix this before V2 work.

### Legacy base-cache semantics cannot authorize V2

[fingerprints.py](../../scripts/producer/fingerprints.py) can recompute recorded fingerprints using current hash semantics. [assemble.py](../../scripts/producer/assemble.py) also deliberately accepts some unverifiable legacy bases.

The first V2 MP4 run must cold-build a generation-local base and must not inherit root `base_final.mp4`, legacy fingerprint authority, or `auto_base_guard.py` reuse. Legacy generations produced during transition must be labeled diagnostic/`legacy-v1`, never FinalApprovalV3.

### Immutable manifest capture must precede planning

Render, cuts, B-roll, music, and approval paths consume manifest/plan paths. Snapshotting only at render time would make planning approval refer to different path authority. Rewrite source, transcript, B-roll, music, and required assets into a normalized immutable manifest before authoring.

### Runtime capture remains incomplete

The current pipeline snapshot omits or does not execute all tsconfig/schema, Node dependency, Python environment, font, SFX, browser, ffmpeg, and model/runtime inputs. V2 resume requires a pinned release bundle or explicit complete runtime attestations, not merely copied source files.

### Common locking is missing for early repair

The detached Auto Edit worker and desktop Palmier commands do not currently share one durable cross-family execution lease for their full lifetimes. A repair can overlap ordinary V1 work. Internal canary work requires a common arbiter before mutation.

## Corrected release sequence

1. Fix cross-request dead-journal bootstrap and freeze V1 request-key behavior.
2. Add reader-first V1/V2 envelope fencing and a common execution arbiter while V1 remains the only writer.
3. Add shadow immutable `CutApprovalV1` and legacy plan approval artifacts; extract sink modules but keep one synchronous realization in the V1 worker.
4. Capture complete content-addressed source authority and normalized manifest in shadow mode; add cross-language golden fixtures and new receipts without changing legacy fingerprint meaning.
5. Build and benchmark the bounded Palmier repair canary under the quarantine envelope. It remains internal and non-publishable.
6. Land immutable MP4 generations behind V1, with full fault injection and `CURRENT`-first readers; materialize root files only after commit.
7. Drain pre-fence workers and launch MP4-only JobV2 using a cold generation-local base and pinned runtime.
8. Cut over MP4 only after repeated quality/performance parity and crash recovery.
9. Add independently resumable Palmier execution only after remote intent/idempotency reconciliation and corrected full QC.

## Statistical corrections

The prior fixed counts were planning heuristics, not sufficient confidence proof.

- Seeded defects inside one project are clustered, not independent observations.
- Size a confirmatory study from pilot paired discordance and the preregistered noninferiority margin.
- Use a development corpus plus untouched holdout; repeated tuning on the holdout invalidates ordinary confidence intervals.
- Use project-level paired endpoints, cluster bootstrap/mixed models, and at least three blinded calibrated raters per pair.
- Seeded defects validate detector sensitivity, not natural defect incidence or generative quality.
- Full-job correct completion after bounded recovery is the primary reliability endpoint.
- A 99.5% per-operation success rate across 45 operations yields only about 79.8% all-operation success without recovery.
- Zero failures in 30 runs leaves a one-sided 95% failure upper bound near 9.5%; 300 approaches 1% and 3,000 approaches 0.1% only under frozen iid conditions.
- Requalify after any model, Palmier, prompt, doctrine, plan-schema, or audit change.

## Round-three go/no-go

| Path | Decision after this round |
|---|---|
| V1 containment and immutable approval seams | Go |
| Atomic MP4 generation behind V1 | Go after authority/fault-injection gates |
| MP4-only JobV2 | Conditional go after reader-first fencing and cold-base parity |
| Quarantined one-card Palmier repair canary | Go internally after common locking and exact pre/post diff |
| External Palmier repair beta | No-go pending plan-aware QC and complete affected-window evidence |
| Palmier-native publishing | No-go |
| Rich direct-MCP production | No-go |
| Greater-than-95% product-direction claim | Not supported yet |

The corrected direction is lower risk and more reversible: establish immutable approvals and atomic MP4 authority, exploit the proven card-local repair only behind quarantine, and postpone independently resumable Palmier publication until its remote and QC contracts are demonstrably complete.

