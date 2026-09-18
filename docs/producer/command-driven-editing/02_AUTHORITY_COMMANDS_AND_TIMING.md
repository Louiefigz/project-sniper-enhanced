# Authority, command, and timing contracts

> **Status:** Proposed target architecture.
>
> [Previous: product and workflows](01_PRODUCT_AND_WORKFLOWS.md) ·
> [Back to the plan index](../COMMAND_DRIVEN_EDITING_EXECUTION_PLAN.md) ·
> [Next: cuts, captions, and audio](03_CUTS_CAPTIONS_AND_AUDIO.md)

## Canonical artifacts

Keep `edit_plan.json` as the human/editorial compatibility authority during
migration. Add immutable, generation-scoped artifacts:

```text
producer/
├── edit_plan.json
├── ACTIVE_HEAD
├── edit_batches/<batchId>/
│   ├── intent.json
│   ├── resolved.json
│   └── receipt.json
├── picture_locks/<pictureLockHash>.json
├── picture_lock_supersessions/<receiptHash>.json
├── motion_scenes/<sceneId>/
│   ├── scene.json
│   ├── generations/<bundleHash>/...
│   └── CURRENT
├── caption_track.json
├── render_graph.json
├── artifacts/<sha256>/...
└── revisions/<revisionHash>/
    ├── revision.json
    └── compiled/<compilerHash>/
        ├── edit_plan.render.json
        ├── timeline_map.compiled.json
        └── projection_receipt.json
```

`ProjectRevisionV1` closes the complete immutable authority state:

- parent revision;
- canonical plan and caption track;
- selected scene/bundle generations;
- source and asset snapshot set;
- workflow state, picture-lock, and approval receipts;
- canvas and destination profiles;
- render graph root;
- every other authoritative sidecar.

`ACTIVE_HEAD` contains only the selected revision hash and advances by durable
expected-parent CAS.

## Renderer projection

`edit_plan.render.json` is not authority just because of its filename.
`ProjectionReceiptV1` binds:

- canonical plan hash;
- manifest and source-snapshot hash;
- compiler/toolchain hash;
- compiled timeline-map hash;
- projection hash and generation path.

The compiler owns projected timing. Every materialized window carries its
compiled `timelineMapHash`. The current render-produced `timeline_map.json`
sidecar remains a separate compatibility output and cannot become the next
candidate's input.

P1 produces the new projection in shadow mode. Rendering, gates, approvals, and
Palmier continue to bind the canonical plan until every reader verifies the
same projection receipt.

During P1 migration, `CompatibilityPictureLockV1` derives its hash from the
validated `.sniper-cut-approval.json` **and**
`.sniper-cut-review-approved.json`, the exact plan/timeline identity, and the
required two-clean-review policy. Neither current receipt is sufficient alone.
P2 replaces the adapter with a first-class workflow-selected picture-lock
receipt; it does not weaken the existing two-authority prerequisite.

```ts
interface PictureLockV1 {
  schemaVersion: 1;
  approvedCutRevisionHash: string;
  planContentHash: string;
  timelineMapHash: string;
  sourceSnapshotSetHash: string;
  transcriptTimingHash: string;
  cutApprovalReceiptHash: string;
  cutReviewApprovalReceiptHash: string;
  requiredCleanReviews: 2;
  workflowPolicy: "cut-first" | "autopilot";
  selectedApproval: {
    approver: "operator" | "system-policy";
    approvalPolicyHash: string;
    approvalReceiptHash: string;
  };
  compatibilityAncestorHash?: string;
  parentPictureLockHash?: string;
}
```

The content hash of the canonical serialized receipt is its
`pictureLockHash`. The lock binds the already-complete `CUT_REVIEW` revision;
after minting it, a separate `PICTURE_LOCKED` child revision references the
lock. The lock never contains the hash of the child that contains it.

Canonical JSON is a byte-level cross-runtime contract, not “whatever
`JSON.stringify`/`json.dumps` happens to emit.” The compact authority form and
the spaced plan-content form each have an explicit matching TypeScript/Python
serializer. They normalize negative zero, preserve finite numbers only inside
JavaScript’s exact safe-integer domain, use the form’s declared Unicode key
order, escape lone surrogates identically, and reject non-JSON values. The
cross-runtime regression currently compares 10,011 numeric values plus Unicode
keys, sparse-array behavior, cut-track hashes, and cut-decision hashes.

A P1 compatibility lock is not operator/system-policy approval and is never
reinterpreted as `PictureLockV1`. To cross the P2 migration boundary, the
selected policy approves the exact unchanged cut, then the controller mints a
first-class lock with `compatibilityAncestorHash`.
Deferred/compiled compatibility-bound clauses are superseded by first-class
successors; committed compatibility-bound treatment is explicitly revalidated.
Any cut/timeline/source/transcript drift requires normal cut review and approval
again.

## Request and clause lifecycle

Plain language is the interface, not the executable contract:

```text
operator prose
  → EditRequestV1 + clause ledger
  → cut stage batch
  → picture lock
  → deferred treatment stage batch
  → immutable candidate
  → render/QC/readback
  → receipt + request-ledger update
```

One generated `ClauseStateV1` is shared by request storage, receipts, QC, and
UI:

```text
pending
  → deferred | compiled | ambiguous | unsupported | conflict
deferred
  → compiled | ambiguous | unsupported | superseded
compiled
  → candidate-executed | not-promoted | superseded
candidate-executed
  → committed | not-promoted
```

Every terminal state has a reason, receipt, and blocking clause IDs where
needed. A new request may supersede a prior clause but cannot erase its history.

Intent may contain approximate timestamps, phrases, visible labels, and
creative wishes. It cannot mint source, word, scene, asset, Palmier, or exact
renderer IDs.

## Closed executable batches

```ts
interface FrameRange {
  startFrame: number;
  endFrameExclusive: number;
}

type ResolvedTargetV1 =
  | { kind: "timeline-range"; revisionHash: string; frameRange: FrameRange }
  | { kind: "word-range"; revisionHash: string;
      wordIds: [string, ...string[]]; occurrence: number;
      frameRange: FrameRange }
  | { kind: "cut-segment"; revisionHash: string;
      segmentId: string; elementVersion: number }
  | { kind: "stable-element"; revisionHash: string;
      elementKind: string; stableId: string; elementVersion: number };

interface EditBatchBaseRevisionV1 {
  projectRevisionHash: string;
  planContentHash: string;
  manifestHash: string;
  sourceSnapshotSetHash: string;
  timelineMapHash: string;
  canvasProfileHash: string;
  destinationProfileHashes: string[];
}

type EditBatchV1 =
  | {
      stage: "cut";
      base: EditBatchBaseRevisionV1 & { pictureLockHash?: string };
      operations: CutOperationV1[];
    }
  | {
      stage: "treatment";
      base: EditBatchBaseRevisionV1 & { pictureLockHash: string };
      operations: TreatmentOperationV1[];
    };
```

Common batch fields also bind schema version, batch ID, idempotency key,
`atomic: true`, ripple policy, and `preserveUnrelated: true`.

Cut batches accept only cut operations. Treatment batches require the exact
picture-lock hash and reject cut operations. A post-lock cut request opens a
new cut stage; dependent treatment is deferred/refit afterward.

When a non-ripple repair creates a child lock, emit:

```ts
interface PictureLockSupersessionReceiptV1 {
  parentPictureLockHash: string;
  childPictureLockHash: string;
  repairOperationHash: string;
  parentTimelineMapHash: string;
  childTimelineMapHash: string;
  authorizedDirtyWindows: FrameRange[];
  unchangedMappingProofHash: string;
  supersededClauseIds: string[];
  successorClauseIds: string[];
  revalidatedCommittedOperationIds: string[];
}
```

Every deferred or compiled treatment clause bound to the parent lock becomes
`superseded`. The controller creates a new successor clause version linked by
`supersedesClauseId`, then compiles and validates that successor against the
child lock—even when its resolved frame happens to stay the same. A prior
compiled operation is never silently replayed under a new lock.
Already-committed parent history stays immutable; the child records successor
revalidation for each carried-forward treatment operation and re-fingerprints
its dependent graphics, captions, music, audio, and Palmier bindings.

The operation schema is a discriminated union. Each action fixes its target,
payload, and preconditions. Generated schemas use
`additionalProperties: false`. Unknown actions, fields, target types, and
unreleased handlers fail; there is no `action: string`,
`Record<string, unknown>`, or broad model-writer fallback.

Target vocabulary:

- cut restore/trim/remove/pause;
- scene add/update/move/remove;
- caption enable/style/correct;
- b-roll add/replace/move/remove;
- motion, reframe, dialogue, and music changes;
- transition and SFX changes;
- grade ranges;
- chapter and thumbnail operations.

Title cards use scene operations. A listed action is not a release claim; the
capability matrix can still return `unsupported`.

## Candidate and Palmier commit saga

A filesystem and Palmier cannot share one database transaction. With Palmier
selected, commit is a durable saga:

1. Write/prove immutable local and isolated Palmier candidates.
2. Durably persist expected local/Palmier heads, candidate IDs, and hashes.
3. Acquire the project commit lease and CAS-activate the Palmier candidate.
4. Persist and `fsync` exact activation readback.
5. CAS `ACTIVE_HEAD` to the local child.
6. Verify the selected local/Palmier heads and durably mark `COMMITTED`.

Commit states:

```text
PREPARING
CANDIDATES_PROVED
PALMIER_ACTIVATING
PALMIER_ACTIVE
LOCAL_COMMITTING
COMMITTED
ABORTED
RECONCILIATION_REQUIRED
```

No new batch starts while an intent is nonterminal. Before Palmier activation,
a crash leaves both candidates private. After activation, Palmier may be ahead;
startup must finish the reserved local CAS or enter
`RECONCILIATION_REQUIRED`. It never claims rollback or blindly retries.

Palmier activation CAS and durable activation readback are also separate
effects. When Palmier is selected and proved CAS activation exists, startup
resolves the external head first:

| Observed Palmier head | Recovery action |
|---|---|
| Exact expected Palmier parent | Re-prove the reserved candidate/intent, acquire the lease, CAS once to the reserved candidate, persist full activation readback |
| Exact reserved Palmier candidate | Verify candidate hash and full readback, then persist `PALMIER_ACTIVE` idempotently |
| Anything else, unreadable, or partial | Persist `RECONCILIATION_REQUIRED`; do not advance local authority |

The local CAS and the `COMMITTED` intent transition are separate durable
writes. Only after Palmier is proved at the reserved candidate—or Palmier was
not selected—does startup observe local `ACTIVE_HEAD`:

| Observed local head | Recovery action |
|---|---|
| Exact expected parent | Re-prove the reserved child and external readback, CAS to the child, verify, then mark `COMMITTED` |
| Exact reserved child | Verify its revision/receipt hash and external readback, then mark `COMMITTED` idempotently |
| Anything else | Persist `RECONCILIATION_REQUIRED`; do not retry mutation or rewrite the head |

Persist and flush each saga state before its effect. Recovery follows the same
observed-state principle as current pending refit/audio receipts: prove what
already happened, then finish the unique valid transition.

If Palmier lacks a proved activation CAS, publication is explicitly
derived/non-atomic and the receipt may say
`local-committed/palmier-pending`.

Durable file publication is:

```text
temporary write
  → file fsync
  → same-filesystem atomic rename
  → parent-directory fsync
  → ACTIVE_HEAD last
```

The retained durability cohort proves injected sync/rename faults and named
local-process exits on the tested local filesystem. It does not simulate
physical power loss, storage-controller/cache reordering, filesystem
corruption, or hardware failure; those require a separate fault environment
before making a stronger durability claim.

## Receipt contract

`EditReceiptV1` contains:

- parent/child revision hashes;
- batch status (`rejected`, `needs-operator`, `candidate-proved`,
  `commit-in-progress`, `committed`, `not-promoted`,
  `local-committed/palmier-pending`, or `reconciliation-required`);
- commit-intent state;
- one operation record with clause ID/state, disposition, execution state,
  before/after hashes, dirty nodes/windows, and explanation;
- revision-invariant proof when executed.

An operation is never called “applied” because a private candidate ran.
`committed` means the stage batch passed and authority advanced.

## Stable identity and timing

Controller-mint stable IDs for:

- transcript words and correction revisions;
- cut segments and semantic beats;
- scenes, elements, render units, caption groups, and cues;
- b-roll, music/dialogue regions, operations, project revisions;
- Palmier media and clip bindings.

Models may use temporary aliases only inside one batch; the controller replaces
them.

```ts
type TimingAnchorV1 =
  | { type: "timeline-frame"; frame: number; timelineMapHash: string }
  | { type: "transcript-range"; startWordId: string; endWordId: string;
      offsetFrames?: number }
  | { type: "cut-segment"; segmentId: string; elementVersion: number;
      basis: "output-frame"; offsetFrames: number; timelineMapHash: string }
  | { type: "semantic-beat"; beatId: string; offsetFrames?: number }
  | { type: "source-time"; sourceId: string; sourceFrame: number;
      sourceSample?: number }
  | { type: "section"; sectionId: string; offsetFrames?: number }
  | { type: "music-beat"; cueId: string; beatIndex: number;
      offsetSamples?: number };
```

Use integer delivery frames, exact rational FPS, and integer audio samples.
Seconds are input/display values only.

A `cut-segment` anchor is explicitly output-relative and also binds the segment
version and compiled timeline-map hash. Content-relative intent must use a
`transcript-range` or `source-time` anchor; it cannot hide behind an ambiguous
segment offset. A speed change increments the segment version and changes the
timeline-map hash, so all affected content-relative anchors are re-resolved
within the segment and after it wherever the compiled map changes, even when
the segment ID survives. An intentionally output-locked frame anchor stays at
that delivery frame unless the operator changes it.

Anchor supersession is receipt-driven:

- display correction preserves word identity;
- word/segment/section split or merge records predecessor/successor mappings;
- removed beats/cues tombstone their anchors;
- re-resolution happens only with one valid successor;
- ambiguous/dangling anchors stop instead of snapping nearby.

A stale timestamp is interpreted against its recorded parent revision or
rejected; it is never silently reinterpreted on the current timeline.

## Normative refit contract

The target compiler wraps, rather than replaces, current
`scripts/producer/edit/plan_refit.py` behavior:

1. resolve the old output anchor against the old compiled cut track;
2. map it to the owning source frame/sample;
3. map that source point into the new compiled cut track;
4. if the point was removed, traverse nearest surviving content in **old output
   order** under the anchor's explicit before/after policy;
5. emit a unique successor mapping or stop as ambiguous/dangling.

Source-file order, new-output order, nearest floating-point seconds, and model
choice are not substitutes. Refit receipts bind old/new plan hashes,
old/new timeline-map hashes, source point, traversal decision, and final
integer frame/sample result.

## Speed and quantization contract

Project FPS is a reduced positive rational `p/q`. Segment speed is also stored
as `PositiveRationalV1 { numerator, denominator }`, using canonical positive
integer strings with no leading zeros and greatest common divisor one.
Compatibility numeric input is parsed once from its raw JSON token by an
arbitrary-precision decimal parser—including exponent notation—then reduced
and receipt-bound. Binary floating-point values never enter authority hashes.

For project sample rate `S`, define one authoritative absolute boundary:

```text
B(frame) = floor(frame × S × q / p)
```

The audio partition corresponding to picture interval `[f0,f1)` is exactly
`[B(f0),B(f1))`. Adjacent picture intervals therefore share one boundary and
cannot overlap or gap. A program of `F` delivery frames has exactly `B(F)`
compiled pre-AAC PCM samples before any explicitly authorized terminal
reconciliation. Never round a previously rounded value or accumulate
per-segment float error.

For a source with sample rate `Ss`, normalize absolute source boundaries with:

```text
P(sourceSample) = floor(sourceSample × S / Ss)
```

Source interval `[n0,n1)` becomes exactly `[P(n0),P(n1))` on the normalized
project clock. One shared boundary function prevents adjacent 44.1→48 kHz
intervals from duplicating or dropping a sample. Source rate, source boundary,
project rate, normalized boundary, resampler/toolchain, and decoded output
count are receipt-bound.

For a resolved segment with exact normalized source sample range `[N0,N1)` and
picture range `[F0,F1)`, let `Nout = B(F1)-B(F0)`. The canonical source-sample
point map is absolute:

```text
R(n) = B(F0) + floor((n - N0) × Nout / (N1 - N0))
```

The retimer consumes exactly `N1-N0` samples and produces exactly `Nout`
samples. Its receipt binds requested speed `u/v`, resolved frame range, source
and output sample ranges, and effective ratio; exceeding the frozen
speed-deviation tolerance fails rather than drifting. Audio-only L/J handles
are separate overlap layers on the same absolute project sample clock.

Normative policies:

- picture intervals are half-open integer frame ranges `[start, end)`;
- audio intervals are half-open integer sample ranges `[start, end)`;
- picture seams and picture duration-neutral repairs move by whole delivery
  frames only;
- source speech boundaries remain exact source samples;
- a padded **analysis/coverage envelope** may use `floor(start)` and
  `ceil(end)`, but it is never used to partition or concatenate program audio;
- an audio sample maps to its containing delivery frame with `floor`;
- a display-only point conversion uses nearest with ties-to-even and can never
  become authoritative;
- an audio-only L/J handle may be subframe and cannot change the picture map;
- a segment speed/version is an input to timeline, render-node, caption-cue,
  scene-placement, b-roll, transition, SFX, and Palmier-binding fingerprints.

If frame quantization leaves a residual, use only an explicit audio overlap,
crossfade, or proved room-tone interval, with exact samples recorded in the
receipt. Never steal adjacent speech or an onset. If complete-word preservation
cannot coexist with duration-neutral picture frames, return
`NON_RIPPLE_IMPOSSIBLE` and present the ripple impact.
