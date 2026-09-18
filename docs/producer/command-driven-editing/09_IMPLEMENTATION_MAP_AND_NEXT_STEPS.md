# Implementation map and immediate next steps

> **Status:** Proposed ownership boundaries plus the bounded released exits for
> P0 (15/15), P1 (13/13), P2 (12/12), P3 (8/8), and P4 (13/13). P5 remains
> blocked at 6/11; P6 remains blocked at 0/7; P7/P8 remain blocked. These
> bounded subsystem exits are not connected-Palmier, arbitrary-mimic,
> complete-project, or performance qualification. The exact current verdicts
> live in the phase exit audits; the implementation inventory below is a
> checkpoint narrative rather than a release ledger.
>
> [Previous: performance and testing](08_PERFORMANCE_AND_TESTING.md) ·
> [Back to the plan index](../COMMAND_DRIVEN_EDITING_EXECUTION_PLAN.md) ·
> [Next: legacy regression gates](10_LEGACY_REGRESSION_GATES.md)

## Implemented checkpoint — 2026-07-30

The first compatibility slice now exists in the current pipeline:

- trim-only starter behavior, canonical prompt vocabulary, and fail-closed
  ghost-caption coverage;
- shared half-up frame quantization and compiled-frame/pre-AAC audio-duration
  authority regressions;
- pinned offline GSAP for every registered comp plus a complete measured
  46-comp capability artifact whose missing, stale, unmeasured, or error rows
  fail closed;
- two distinct clean-review rounds remain mandatory downstream;
- an immutable compatibility timeline projection and
  `CompatibilityPictureLockV1` derived from both current cut authorities, with
  clean-cut approval bound to the current mode, scope, operator intent, and
  reference intent;
- canonical local-workspace admission before Ask Editor reads, model work, or
  Palmier dispatch, plus no-follow checks for the plan authority;
- expected-parent validation and exact-child Ask Editor promotion under the
  shared project mutation lease, with post-promotion reobservation,
  conditional rollback, and a blocking reconciliation marker for detected
  foreign state;
- cancellation fencing that keeps the mutation lease until rollback/release
  settles, and transactional restoration of cut approval, template approval,
  and plan-refit receipts when finalization fails;
- Palmier writer routes serialized by the same mutation lease, with Palmier
  authority rechecked before promotion and again around sidecar publication;
- exact-inode stale-lease recovery: a new-format hard-linked owner is reaped
  automatically only after its durable process identity is dead and the lock,
  recovery claim, and nonce-named owner are proved to be the same inode;
  legacy directories, malformed records, missing/unsupported OS start
  identity, mismatched owner inodes, and an already-present interrupted
  recovery claim remain fail-closed for explicit operator quarantine;
- a content-addressed compatibility projection whose compiler identity covers
  the Python entry wrapper as well as its dependent source closure;
- one strict typed compatibility operation, `SetGraphicTextV1`, wired through
  live Ask Editor finalization for an isolated statement-card text change;
- closed revision/request/clause/batch/receipt/projection/render-graph/timing
  schemas consumed by strict TypeScript parsers and the shared Python schema
  validator, including cross-runtime valid/invalid corpus and enum parity;
- content-addressed revision objects, immutable one-winner parent advances,
  durable idempotency/intents, restart recovery, and committed receipt binding;
- live post-promotion revision shadow publication for qualified
  `SetGraphicTextV1` requests, plus persisted short/LF-14 synthetic 20-clause
  restart/no-unrelated-diff fixtures;
- a minimum topological render-graph executor plus a file-backed bridge around
  the actual `/producer/render` and `/producer/assemble` ffmpeg/browser stages.
  The bridge revalidates source-set admission, plan, timeline, base, scene
  cache, caption shards, composite, final media, and exact executable/source
  closure; rejects missing edges; rehashes retained artifacts; persists a
  crash-safe base-to-assemble handoff; and stores a strict graph/receipt
  generation only after the real child succeeds;
- QC-coupled graph publication in the auto-edit compatibility path. The
  assemble command stages the private candidate generation without advancing
  `ACTIVE`; approval reopens the immutable generation and exact candidate
  bytes, promotes those bytes into `final.mp4`, activates the graph, and only
  then writes the QC approval. Approved-output resume also requires `ACTIVE`
  to bind the current source set, plan, toolchain, and final hash;
- a retained actual-assemble dirty-card/QC control: changing only the statement
  card from `BEFORE` to `AFTER` left the prior graph active through candidate
  staging and classified exactly `scene -> composite -> final` dirty while
  source, timeline, and base were reused. After exact candidate verification,
  the promoted output was byte-identical to an isolated empty-cache
  forced-full render across all 72 decoded frames and normalized PCM. The
  retained final hash is
  `dc3ef09b691cb17dec1f0ad51c080a57cc97605fbf51358ed8327e99827caea8`;
  oracle receipt
  `91d72c45c2722f60fff2f0326de804d642ccd2d3c001e32012d90c6e2c4d6c7c`
  passed, and the activated graph/receipt hashes are
  `b9b877b8377c53803bb236e8bd3b8c4e3a5b893d0798c8cdb36dddffa18fe101`
  and
  `18daf90aa6a204a2d648ff6d984fb7c470ee5f10a32b2f48e52c2259099c141a`.
  This three-second harness proves the compatibility publication and
  invalidation path, not the frozen short or LF-14 full-path/performance gate;
- a three-pair/six-output canonical `libx264` codec-floor cohort. Repeated
  byte-identical 45-second pre-master input produced non-identical decoded
  pixels: worst mean SSIM `0.997517339`, worst frame `0.992094`, with exact
  1,350-frame timing and normalized PCM. The calibrator snapshots its input
  into a dedicated SHA-256-addressed retained-source store and renders every
  pair from that object, so later baseline work-file rewrites cannot stale the
  cohort. The oracle therefore reports exact `framemd5` or pinned `0.995` mean
  / `0.985` minimum SSIM equivalence and explicitly does not claim pixel
  identity;
- strict timing anchors and persisted mixed cut+treatment re-resolution:
  unique successors resolve, while split/removed identities become explicit
  `ambiguous`/`dangling` states rather than snapping nearby;
- an authority-scoped durable local/Palmier saga with a seven-boundary crash
  matrix and exact candidate/timeline readback checks. Governed native
  candidate promotion now calls that saga through the candidate's pinned
  native-QC CLI, reserves a private local revision child, recovers interrupted
  Auto Edit promotion before emitting output, and exposes recovery or
  reconciliation truthfully in project state;
- an explicit P2
  `analyze → prepare → review → approve → execute` path. Preparation stores
  exact and semantic plan identities, graph, execution receipt, candidate
  pointer/media, context, analysis, and projection content-addressed without
  mutating the selected head. Review stages only that candidate, approval
  seals operator selection plus automated QC, and promotion-only execution
  activates only the sealed package. A separate exact-impossible `reopen`
  action moves `PICTURE_LOCKED → CUT_DRAFT`, preserves the plan/graph/
  projection, and enumerates affected dependents without applying a ripple;
- a candidate-bound automated-QC controller that reopens only that verified
  preparation/descriptor, extracts at most 30 seconds around dirty frames with
  pinned FFmpeg, runs CPU-only pinned Whisper re-transcription, program-waveform
  continuity/seam checks, and a separately pinned source-waveform adapter whose
  receipt is explicitly bounded evidence rather than sole audibility proof.
  Passing audio-only runs publish four gate-shaped lane items and one immutable
  content-addressed bundle keyed from the preparation hash. Governed
  alternate-take orchestration now reruns its pinned detector and derives a
  unique later-take candidate from controller-owned source/sample/frame/output
  identity; the caller may supply only the normalized `visualSpeechRegion`.
  Selection, controlled visual-seam evidence, and promotion bind together.
  The visual gate proves selected-source A/V temporal mapping inside that ROI,
  not automatic face/mouth detection, lip-reading, phoneme proof, semantic
  audibility, or operator approval;
- a narrow production picture-repair terminal. It stages a graph against the
  exact ACTIVE parent and, before copying media, reopens and rehashes the
  parent graph, receipt, root media, plan, source, and current toolchain.
  Post-copy activation rechecks the expected parent inside the caller-held
  project mutation lease; it is not an atomic filesystem CAS against writers
  that bypass that lease. Admission is limited to 30 fps, 48 kHz, one source,
  speed 1, zero residual, a target-edge source extension, and exact
  terminal-silence reclaim. Plans with captions, graphics, b-roll, title
  cards, transitions, baseline/reframe/punch-ins, music, gain/enhancement, or
  unknown lanes fail closed so burned layers cannot be erased;
- a truthful two-run baseline harness plus retained real short and LF-14
  current-full-path traces. The 45-second short completed in `45,407 ms` cold
  and `30,175 ms` warm. The 20,139-frame LF-14 completed in `566,941 ms` cold
  and `443,057 ms` warm, with exact `839.964125` timeline length, identical
  decoded audio, 24 QC passes/two warnings/zero failures, and independently
  reproduced codec-floor picture equivalence. Both prove current-path
  comparators while showing that composite, master, and audit remain
  monolithic warm passes; the synthetic fixtures still validate only
  workload/telemetry shape;
- a retained 46-composition × 8-exact-rate HyperFrames browser/decode matrix,
  bound to the current motion-source closure, measured capability digest, and
  exact Node/browser/ffmpeg/ffprobe binaries. Its 368 rows prove released
  catalog render compatibility, not full-path duration or performance;
- immutable full-byte external-media snapshots plus a live-proved non-root,
  networkless, read-only, resource-bounded ffprobe/full-decode sandbox;
- mandatory canonical Producer-ingest admission for raw sources, input-project
  b-roll, and input-project music. New manifests execute the immutable
  snapshots and bind exact per-file receipts through a content-addressed
  `.sniper-source-sets/<sha256>.json`. The late b-roll pool now requires that
  manifest, rejects post-ingest additions, and probes/extracts only admitted
  snapshots. Reference intake uses its own retained admission authority;
  Palmier live-build imports remain outside the canonical gate.

The compatibility projection, picture lock, and typed operation are intentionally
small. They prove migration seams without replacing the current plan authority.
The Ask Editor promotion guard serializes participating Project Sniper and
Palmier routes; it is not a universal filesystem compare-and-swap against
arbitrary out-of-band writes. Detected post-promotion foreign state is retained
and quarantined. New mutation leases use a hard-link exact-inode owner protocol
with durable PID/start identity. Legacy, malformed, or unverifiable lock files
remain fail-closed and require explicit recovery.

The revision, request, and render-graph implementations remain a
**compatibility shadow**, not the canonical authority. They do **not** yet
provide general typed editing, canonical all-reader revision authority,
project-scoped scene authoring through Ask Editor, or general plan-wide hybrid
Palmier delivery. The Palmier saga now owns production promotion for the
governed native-candidate path, but connected live-service qualification has
not been retained.
Direct governed P4 scene authoring remains a separate CLI surface. The
auto-edit candidate loop now has QC-coupled graph staging and activation for
the current compatibility path, but the route bridge still wraps the current
monolithic renderer stages. It does not yet make each legacy ffmpeg/browser
substage or dirty window independently graph-scheduled.

The following implementation-checkpoint blockers remain relevant, but this
list is not the authoritative P5/P6/P7/P8 exit count. Use
[`17_P5_EXIT_AUDIT.md`](17_P5_EXIT_AUDIT.md),
[`18_P6_EXIT_AUDIT.md`](18_P6_EXIT_AUDIT.md), and
[`19_P7_P8_QUALIFICATION_AUDIT.md`](19_P7_P8_QUALIFICATION_AUDIT.md) for the
current release verdicts:

1. run the now-wired production Palmier saga against connected short and LF-14
   sessions, retaining expected-parent, exact reserved-child, foreign,
   partial/unreadable, ambiguous-effect, and restart readback evidence;
2. finish admission for Palmier live-build imports and retain
   descriptor-to-subprocess authority across path-based host consumers;
3. migrate every touched current reader/writer under retained-media shadow
   parity before making the revision store canonical;
4. implement general layered dirty-window recomposition so a picture repair
   can preserve rendered captions, graphics, b-roll, title cards, transitions,
   reframes/punch-ins, and audio treatments instead of failing closed;
5. run the connected Palmier short/long readback, one-clip repair, export,
   disconnect, audio-authority, exact-master, editable-parity, and manual-edit
   preservation gates. The local 14-minute/50-scene workload already passes.

The render-effect field-registry blocker is closed. A 31-row registry and 42
generated mutations own the current plan/manifest surface and compiler stage
roots. Actual-media short and LF-14 controls dirtied only
scene/composite/final for an ordinary graphic, reused source/timeline/base, and
matched isolated forced-full output exactly. The final-tree replay binds both
graphs to toolchain `1c1898a4…` and registry `8f8bea83…`, passes
1,394/20,139-frame exact FrameMD5 and PCM oracles in 530.289 seconds, and is
retained under `artifacts/p0-render-effect-parity-canonical-closure-v1`.
The short and LF-14 final hashes are `ad7592ea…` and `b7580bae…`.
Finer ffmpeg/browser substage scheduling remains later optimization work
behind those oracles.

The current inventory passes with 62 artifact/family rows, 50 hidden literals,
839 persistence sites, and 166 process boundaries, with zero blocking or
unknown dispositions. This proves disposition completeness, not canonical
revision-store migration.

## Retained checkpoint verification

The retained compatibility checkpoint passed:

- `npm run lint`;
- `npm run type-check`;
- the complete `npm test` suite: all 200 TypeScript test files plus both Node
  harnesses;
- `PYTHONPATH=.:tests ../../.venv/bin/python3 -m unittest discover -s tests -p
  'test_*.py'` from `scripts/producer`: **3,480 tests passed, 1 skipped**;
- the real offline capability probe for all **46 of 46** registered comps:
  **9** clean fades, **18** hold-to-cut, and **19** partial fades, captured by
  capability digest `a2a72bf8f5790521093c0b7c2d7f16c13ab31c41`.

These results verify the compatibility checkpoint only. They are not
performance evidence for the 90-minute long-form hypothesis and do not satisfy
the later phase gates named above.

## Schemas

Implemented shared schemas:

```text
schemas/producer/
  asset-record-v1.schema.json
  caption-chapters-v1.schema.json
  caption-correction-ledger-v1.schema.json
  caption-repair-revalidation-v1.schema.json
  caption-track-v1.schema.json
  clause-state-v1.schema.json
  commit-intent-v1.schema.json
  compatibility-timeline-projection-v1.schema.json
  compatibility-picture-lock-v1.schema.json
  cut-repair-fragment-receipt-v1.schema.json
  cut-repair-composite-receipt-v1.schema.json
  cut-repair-review-action-v1.schema.json
  cut-repair-promotion-action-v1.schema.json
  cut-repair-transition-receipt-v1.schema.json
  cut-repair-execution-package-v1.schema.json
  cut-repair-preparation-package-v1.schema.json
  cut-restore-speech-v1.schema.json
  edit-batch-v1.schema.json
  edit-receipt-v1.schema.json
  edit-request-v1.schema.json
  fps-support-matrix-v1.schema.json
  hyperframes-rate-matrix-v1.schema.json
  palmier-commit-saga-v1.schema.json
  picture-lock-supersession-v1.schema.json
  picture-lock-v1.schema.json
  positive-rational-v1.schema.json
  product-capability-matrix-v1.schema.json
  project-revision-v1.schema.json
  projection-receipt-v1.schema.json
  render-graph-v1.schema.json
  scene-bundle-v1.schema.json
  scene-spec-v1.schema.json
  set-graphic-text-v1.schema.json
  timing-anchor-v1.schema.json
```

`edit-intent-v1`, a broad operation envelope, destination profiles, and a
general revision-proof vocabulary remain intentionally unreleased until a real
handler/invalidation/recovery path needs them. The model must not advertise
schema-only actions.

## TypeScript/controller boundaries

```text
src/lib/producer/contracts/
  cut-repair-preparation.ts
  cut-repair-review-transition.ts
  cut-repair-promotion-transition.ts
  cut-repair-transition-receipt.ts
  edit-batch.ts
  targets.ts
  timing-anchor.ts
  scene-spec.ts
  caption-track.ts
  destination-profile.ts
  render-graph.ts
  workflow-policy.ts

src/app/api/producer/edit-batch/
  route.ts
  compile.ts
  resolve.ts
  conflict-check.ts
  apply.ts
  commit-saga.ts
  reconcile.ts
  review.ts

src/lib/server/
  cut-repair-preparation-store.ts
  cut-repair-review-store.ts
  cut-repair-promotion-store.ts
  cut-repair-transition-store.ts
  cut-repair-transition-reconciliation.ts

src/app/api/producer/ai-edit/
  cut-repair-preparation-plan.ts
  cut-repair-prepare-runner.ts
  cut-repair-route-policy.ts
  cut-repair-route-runner.ts
  cut-repair-execute-runner.ts
```

## Deterministic Python boundaries

```text
scripts/producer/edit/
  target_resolver.py
  batch_apply.py
  cut_repair.py
  cut_repair_selection.py
  cut_repair_route.py
  cut_repair_route_target.py
  cut_repair_route_cli.py
  cut_repair_context_sources.py
  cut_repair_context_timeline.py
  cut_repair_context_materialize.py
  cut_repair_prepare_media.py
  cut_repair_execution.py
  cut_repair_promotion_gate.py
  non_ripple.py
  repair_fragment.py
  repair_composite.py
  revision_invariants.py

scripts/producer/graphics/
  scene_contract.py
  scene_bundle.py
  scene_lint.py
  scene_render.py
  animation_map.py
  asset_governance.py

scripts/producer/captions/
  caption_contract.py
  caption_operations.py
  caption_compile.py
  caption_plan_pipeline.py
  caption_render.py
  caption_shards.py
  caption_shard_media.py
  caption_shard_contract.py
  caption_shard_composite.py
  caption_authority.py
  caption_repair_revalidation.py

scripts/producer/render_graph/
  model.py
  build.py
  dirty.py
  execute.py
  receipts.py
```

Local-ASR provenance capture is implemented in `scripts/local_whisper.py`: new
results bind the exact executable, model, settings, and raw Whisper result
hashes and reject in-call runtime/model drift. This is an evidence input, not a
replacement for the P2 aligner, VAD, seam-analysis, or operator-audition
producers.

These are responsibility boundaries, not permission to clone the system or
create oversized parallel implementations. Reuse:

- `compile_timeline.py`;
- `cut_speed.py`;
- `edit/plan_refit.py` and `edit/refit_authority.py`;
- `fingerprints.py`, `edit_scope.py`, `gate_policy.py`, and
  `graphics/frame_oracles.py`;
- existing plan gates and content hashing;
- asset proof and sealed authority primitives;
- Palmier revision/CAS/readback modules;
- current QC/Audit B.

The proposed `scripts/producer/render_graph/` package is an adapter/execution
boundary over existing fingerprints, artifacts, proofs, gates, and selectively
reused headless durability primitives. It is not a second project authority.
The current headless tree supplies valuable mechanisms but is not yet a
complete general worker/publisher or cross-lane DAG; its own blocked gates
remain binding.

## Migration decisions

| Existing subsystem | Near-term move |
|---|---|
| Two current cut receipts | P1 derives compatibility picture lock from both; released bounded P2 adds first-class lock lineage and explicit supersession/revalidation |
| Speed-aware timeline compiler and refit | Freeze behavior in specs/fixtures, then extend |
| Coarse base/video/audio/graphics fingerprints | Wrap as compatibility nodes, split only with dirty/full oracle proof |
| Measured comp catalog and asset proof | Make authoritative for physical capability and freshness |
| Headless admission/fence/seal/receipt primitives | Reuse through narrow adapters after their own tests; do not adopt experimental authority wholesale |
| Ghost/global caption behavior | Explicit `CaptionTrackV1` is released; preserve the legacy adapter only for plans without an explicit track |
| Palmier exact mirror | Preserve; add hybrid editable lanes only behind separate fidelity/readback gates |

## What to do now

Treat the phase exit audits—not this checkpoint inventory—as the current
release queue. The items below are architecture-maintenance work that remains
valid while those exact blocked exits are closed.

Keep the compatibility checkpoint fail-closed while closing its remaining
integration gates:

1. Keep the now-complete 62-family inventory green. New direct persistence or
   process boundaries must bind to a typed artifact/tool family or enter an
   exact reviewed exclusion; family-bound legacy members should be split into
   first-class artifacts as their lanes migrate.
2. Keep the retained short/LF-14 dirty-versus-forced-full controls fresh after
   every renderer/invalidation change, then use them to qualify each finer
   legacy substage or dirty-window scheduling change.
3. Connect the durable Palmier saga to real activation/readback and startup
   reconciliation, and replace manual stale-lease recovery.
4. Keep the passing external-ingress/source-set gate intact; if Palmier
   live-build imports are re-enabled, admit them before execution and close
   the remaining descriptor-to-subprocess host intervals.
5. Expand reader/writer shadow parity and flip authority only after every
   touched reader proves the same output.
6. Expand the command catalog only behind each later lane's own authority,
   invalidation, recovery, QC, and Palmier gates.

For P2 specifically, the governed
`analyze → prepare → review → approve → execute` lifecycle is implemented.
Preserve its now-qualified 12-of-12 bounded boundary:

1. keep the 24-cell all-rate/early-middle-late real-media cohort and its
   63-file source closure fresh;
2. keep candidate identity controller-derived and keep the caller limited to
   the normalized visual ROI;
3. retain the negative visual controls for three-frame delay, occlusion,
   static/unmeasurable ROI, and periodic ambiguity;
4. keep surgical picture admission fail-closed when a plan contains any
   rendered lane the raw fragment cannot reproduce.

Do not expand that P2 result into automatic lip-reading, creator-speech
quality, native or connected Palmier, universal picture repair, or P5
dirty-render claims.

## Demo sequence

Avoid one-off glossy demos that bypass architecture.

- **P1:** plan-only 20-clause request, restart/idempotency, no unrelated diff.
- **P2:** early/middle/late local word repair plus one honest impossible case.
- **P3:** range karaoke and repeated-name correction with all other shards/base
  nodes unchanged.
- **P4:** author two-card fire/sparkles and change only right copy.
- **Post-P5 integration:** one project combines cut repair, range caption,
  custom scene, unit-only repair, invariant proof, hybrid Palmier update, and
  one final export.

The post-P5 demo proves the highest-value workflow and the hardest preservation
boundaries together; it is not a substitute for phase gates.
