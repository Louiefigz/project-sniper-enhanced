# P1 exit audit — minimum typed authority and render graph

> **Verdict: COMPLETE only for the released P1 compatibility scope — all 13
> implementation-level exits pass under the declared test model.**
>
> **Evidence date:** 2026-07-30
>
> This is a protocol and implementation result. A connected live Palmier
> service qualification has not been run, so this is not a claim that the
> complete hybrid product, full action vocabulary, or long-form SLA is
> production-qualified.

This ledger audits the exact P1 exits in
[the implementation roadmap](07_IMPLEMENTATION_ROADMAP.md#p1--minimum-typed-authority-and-render-graph-foundation).
P1 deliberately releases one typed compatibility operation and a minimum
render graph. Later phases own broad editing vocabulary, native scene
authoring, universal incremental rendering, and creator-project performance.
The roadmap's “power loss” shorthand is intentionally narrowed below to the
fault model actually exercised: injected interruption at named local durable
boundaries. Physical power-loss and storage-reordering qualification remains
open.

## Verdict rules

- **PASS** requires executable enforcement plus a passing test for the
  released P1 surface.
- A synthetic or adapter test can establish contract, durability, or
  invalidation behavior. It cannot establish live-service behavior, visual
  quality, or render speed.
- An unreleased action is not counted as a P1 failure. Closed parsers and
  handlers must continue rejecting it until its owning phase passes.

## Exact exit table

| # | P1 exit | Verdict | Executable evidence | Scope limit |
|---:|---|---|---|---|
| 1 | Generated schemas agree across languages and reject unknown/mismatched input | **PASS** | `producer-schema-parity.test.ts` sends valid and unknown-field variants of every released P1 shared schema through the Python validator; `producer-schema-enum-parity.test.ts` compares the TypeScript constants with JSON Schema enums. The Palmier production bridge additionally rejects unknown fields and independently recomputes its reservation hash in `producer-palmier-native-commit.test.ts`. | This covers the released P1 contract set, not future action schemas. |
| 2 | Short and 14-minute plan-only fixtures retain 20+ supported clauses | **PASS** | `producer-shadow-fixtures.test.ts` commits and reopens exactly 20 `SetGraphicTextV1` clauses for `p1-baseline-short.json` and `p1-baseline-lf14.json`; `producer-revision-coverage.test.ts` independently retains 20 unique clause and operation IDs across restart. | These are synthetic plan-only durability fixtures. They prove 20 instances of the minimum handler, not 20 product actions or render performance. |
| 3 | Every clause has exactly one state/disposition | **PASS** | Closed request parsing rejects malformed state, and `producer-revision-coverage.test.ts` reopens all 20 clauses with one committed state and one committed receipt disposition. `deferred-request-v1.test.ts` retains one committed cut clause and one compiled treatment clause after re-resolution. | Only P1-released states and dispositions are accepted. |
| 4 | Mixed cut+treatment request defers and re-resolves correctly | **PASS** | `deferred-request-v1.test.ts` commits the cut clause, keeps the treatment clause deferred, requires one exact anchor for every deferred clause, then persists and reopens the compiled resolution receipt. Ambiguous and dangling anchors remain blocked. | This is request-lifecycle proof; broad cut and treatment handlers arrive in later phases. |
| 5 | Timestamps land within one frame | **PASS** | `deferred-request-v1.test.ts` resolves the 45-second treatment position to frame 1,350 at 30 fps. `timing-anchor-migration-matrix.test.ts` preserves that exact output frame across a map migration, and `producer-revision-shadow.test.ts` proves the released text edit has zero start- or end-frame drift. | P1 does not qualify every legacy seconds-to-frame conversion outside this typed path. |
| 6 | Every P1-released anchor survives or explicitly fails ripple, split, merge, and removal | **PASS** | `timing-anchor-migration-matrix.test.ts` covers all seven released anchor types. Stable/unique successors resolve, split successors are `ambiguous`, removed identities are `dangling`, merge successors resolve uniquely, and a timeline-frame bound to the wrong map fails. Source-time identity is no longer silently retained after source split/removal. | No nearest-neighbor fallback is permitted. |
| 7 | A removed dependency edge fails promotion | **PASS** | `current-render-graph-authority.test.ts` removes the required `scene → composite` edge, rehashes the otherwise self-consistent staged generation, and proves reopen rejects it. `current-render-graph-semantics.ts` enforces the complete minimum semantic edge set after structural parsing. | This is the minimum P1 graph topology; later nodes must register their own required edges. |
| 8 | Injected interruption at every released local durable boundary yields old head, exact child, or reconciliation | **PASS** | `producer-revision-store.test.ts` faults six local commit boundaries plus post-commit and recovers one exact child or replay. `producer-palmier-native-commit.test.ts` adds the production-code windows after private local-child reservation and after saga initialization; replay performs no early external effect and converges to the exact child. | This is crash consistency under the named local-filesystem and injected process-exit/synchronous-fault model. It is not hardware power-loss, storage-reordering, or distributed-database atomicity proof. |
| 9 | Fault at every Palmier saga state yields old, exact dual commit, or blocking reconciliation | **PASS** | `producer-palmier-saga.test.ts` faults all seven saga boundaries, caps Palmier activation and local publication at one, checks exact candidate/timeline readback, and blocks foreign, mismatched, unreadable, or post-local Palmier drift as reconciliation. | Palmier exposes no transactional compare-and-swap token; the adapter uses fresh proof, serialized activation, exact readback, and fail-closed reconciliation. |
| 10 | Startup checks Palmier and local parent, exact child, foreign, and partial states before commit | **PASS** | `producer-palmier-saga-startup.test.ts` exhausts the 4 × 4 matrix of Palmier parent/child/foreign/partial against local parent/child/foreign/unreadable. Only exact parent/child combinations converge; every other combination persists `RECONCILIATION_REQUIRED`. Candidate proof is repeated on restart before effects. | This is exhaustive state-machine coverage with an adapter, not a connected-service run. |
| 11 | Restart loses or duplicates no operation | **PASS** | `producer-revision-store.test.ts` and `producer-revision-coverage.test.ts` recover/replay one content-addressed child and receipt under the same idempotency key, including concurrent exact requests. `producer-palmier-native-commit.test.ts` replays a committed candidate with one saga file and one Palmier activation. | A different request under the same key fails closed. |
| 12 | No unrelated plan diff | **PASS** | `set-graphic-text-v1.test.ts`, `typed-compatibility-edit.test.ts`, `producer-revision-shadow.test.ts`, and both 20-clause shadow fixtures change only the selected graphic text. Target, cut track, timing, neighboring graphics, and unrelated fields remain byte/structure-equivalent. | P1 releases text replacement only; it does not infer timing, animation, or neighboring edits. |
| 13 | Plan-only tests do not imply render performance | **PASS** | Both fixture manifests label themselves `synthetic-harness-validation`; this audit and the performance chapter explicitly exclude them from latency evidence. No P1 test result is used to support the 90-minute hypothesis. | The retained real LF-14 cohort and future P5/P8 qualification own performance claims. |

## Production code-path Palmier bridge

The saga is no longer an unused mechanism:

- the production candidate-QC `promoteCandidate` path constructs a bridge from
  the candidate's pinned `native_qc_cli.py` and calls
  `commitApprovedPalmierCandidateSync`;
- `saga_bridge.py` fresh-reads the approved parent and candidate, validates the
  approval, restores the visible parent during proof, and observes the active
  head without switching it;
- the local side reserves a private content-addressed revision child, persists
  the saga, activates Palmier, publishes the expected-parent local advance,
  then re-reads both sides before reporting `COMMITTED`;
- Auto Edit resume re-enters promotion for an already promoted native
  candidate, so a crash after the Palmier effect cannot bypass local recovery;
- project-card state exposes `commit-recovery` and
  `reconciliation-required` instead of presenting an incomplete saga as
  approved.

`test_palmier_saga_bridge.py` proves the Python bridge contract with the native
client fixture. `producer-palmier-native-commit.test.ts` proves production
reservation, replay, ambiguous-effect recovery, foreign-head quarantine,
restart re-proof, exact dual readback, and closed bridge parsing.
`palmier-primary-auto-edit-contract.test.ts` proves resumed Auto Edit calls this
recovery path before it can emit outputs.

## Reproducible focused gate

Run from the repository root:

```bash
for f in \
  src/lib/producer/__tests__/producer-contracts-v1.test.ts \
  src/lib/producer/__tests__/producer-schema-parity.test.ts \
  src/lib/producer/__tests__/producer-schema-enum-parity.test.ts \
  src/lib/producer/__tests__/compatibility-timeline-projection.test.ts \
  src/lib/producer/__tests__/compatibility-picture-lock.test.ts \
  src/lib/producer/__tests__/compatibility-picture-lock-integration.test.ts \
  src/lib/producer/__tests__/deferred-request-v1.test.ts \
  src/lib/producer/__tests__/timing-anchor-migration-matrix.test.ts \
  src/lib/producer/__tests__/set-graphic-text-v1.test.ts \
  src/lib/producer/__tests__/typed-compatibility-edit.test.ts \
  src/lib/producer/__tests__/typed-compatibility-finalize.test.ts \
  src/lib/producer/__tests__/render-graph-v1.test.ts \
  src/lib/producer/__tests__/render-graph-executor-v1.test.ts \
  src/lib/producer/__tests__/palmier-primary-auto-edit-contract.test.ts \
  src/lib/server/__tests__/producer-revision-store.test.ts \
  src/lib/server/__tests__/producer-revision-coverage.test.ts \
  src/lib/server/__tests__/producer-revision-shadow.test.ts \
  src/lib/server/__tests__/producer-shadow-fixtures.test.ts \
  src/lib/server/__tests__/producer-palmier-saga.test.ts \
  src/lib/server/__tests__/producer-palmier-saga-startup.test.ts \
  src/lib/server/__tests__/producer-palmier-native-commit.test.ts \
  src/lib/server/__tests__/current-render-graph-authority.test.ts \
  src/lib/server/__tests__/current-render-graph-command.test.ts
do
  node --import tsx "$f" || exit 1
done

cd scripts/producer
PYTHONPATH=.:tests ../../.venv/bin/python -m unittest \
  tests.test_compatibility_projection \
  tests.test_current_render_graph \
  tests.test_current_render_graph_store \
  tests.test_current_render_graph_candidate \
  tests.test_current_render_graph_artifact_dir \
  tests.test_ingest_execution_authority \
  tests.test_palmier_saga_bridge \
  tests.test_palmier_native_qc \
  tests.test_palmier_native_qc_contract \
  tests.test_palmier_native_qc_repair
```

The 2026-07-30 focused rerun passed all 23 TypeScript scripts, TypeScript
type-checking, and 65 Python cases. The complete `npm test` suite also passed
sequentially. The complete Python discovery suite passed its 3,480-case run
with one recorded skip.

## Open qualification and non-claims

The implementation-level P1 exit does **not** prove:

- a connected Palmier desktop/service short and LF-14 replay. That live
  qualification must exercise expected-parent, already-active exact child,
  foreign active head, partial/unreadable response, crash-after-activation,
  and restart, retaining the saga plus both readbacks;
- atomic Palmier/local distributed transactions. The proved guarantee is
  deterministic recovery or blocking reconciliation;
- hardware power-loss or storage-reordering durability. Boundary coverage uses
  the named local-filesystem and injected interruption model;
- canonical all-reader revision authority. The revision store remains a
  compatibility shadow while current readers migrate;
- arbitrary keyframes, paths, easing, general motion authoring, or the full
  edit action vocabulary;
- universal dirty-window rendering, complete native Palmier editability,
  verified reference-style mimicry, or the 90-minute long-form target.

These are explicit later-phase or release-qualification gates. They do not
weaken the narrower 13-of-13 P1 protocol result, and they must not be presented
as already solved.
