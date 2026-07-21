# Headless deterministic-MP4 execution and 95% evidence plan

> **STATUS: PROPOSED EXECUTION CONTRACT — EMPIRICAL GATES ACTIVE, NOT READY FOR A PRODUCT TRIAL, AND NOT AT 95% CONFIDENCE.**
>
> **Scope:** Claude Code/Codex planning or repair into an approved deterministic MP4. GUI changes and editable Palmier publication are excluded.
>
> **Authority:** the living [headless optimization dossier](HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md) explains why these choices were made. This document turns that rationale into ordered, falsifiable build slices.

## Outcome first

The fastest credible route is not to modify the GUI-owned Auto Edit and AI Edit endpoints into a second architecture. Add one versioned, headless-only MP4 controller with a CLI entry point for Claude Code/Codex Desktop, reuse extracted planning/QC cores, and keep the existing routes only as a read-only disposable comparator until a later migration is justified.

Recommended first surface, not yet implemented:

```text
sniper-headless mp4 initialize --request <request.json>
sniper-headless mp4 quality-pass --request <request.json>
sniper-headless mp4 cancel --attempt <attemptId> --project <canonical-root>
sniper-headless mp4 status --attempt <attemptId> --project <canonical-root>
sniper-headless mp4 current --authority <authorityId> --project <canonical-root>
```

Work-creating CLI commands return one structured `accepted` envelope only after durable admission, including `attemptId`; Claude Code/Codex polls `status` because authoring and critic deadlines can exceed one command lifetime. The terminal attempt result contains the pinned `{authorityId, publicationSeq, generationId, commitDigest, mp4RelativePath, sha256, mediaFacts}` captured at commit, plus optional informational `projectRootAtCommit`. It never makes an absolute path authoritative and never lazily re-resolves a later `CURRENT`. The current reader validates and pins the same tuple for one operation. An HTTP transport may be added later over this controller, but no Next.js route is part of the first implementation or this confidence claim.

`initialize` cold-builds and fully requalifies generation zero from one explicit **presealed, content-addressed** legacy snapshot. The controller never treats a live set of root files as an atomic snapshot and never imports the current absolute-path V2 approval. The snapshot must have been captured from an immutable clone/CAS or under a declared short quiescent-capture contract and must bind every input byte plus its manifest digest. A quality-pass clock may exclude initialization only when every enrolled project was initialized before its feedback was known; otherwise initialization/fallback remains in the product clock.

The first headless release does **not** materialize `edit_plan.json`, `final.mp4`, approval, or proof files back into the legacy GUI root. That projection is unnecessary for this scope and recreates the mixed-file crash class the generation design removes.

The executed gate results are recorded in
[HEADLESS_EMPIRICAL_GATE_LEDGER.md](HEADLESS_EMPIRICAL_GATE_LEDGER.md). The
present state is still earlier than an integrated product experiment:

- a durability composition root integrates admission/idempotency,
  authority-bound trace, boot identity, exact terminal intent, and terminal
  manifest recovery. A separate render-specific pre-admission artifact and
  admission facade now bind request, build, and overlay-source bytes. Neither
  path is yet the production worker/publisher controller;
- provider probes exposed the Claude counters but falsified the full Codex
  cache-create/cost/build contract;
- one renderer composition passed an independent exact-adapter qualification in
  an immutable `--network none` container; this is a clean-success mechanism
  result, not cancellation/crash safety or integrated-product qualification;
- the retained R0 specimen has no coherent approved parent generation;
- only two distinct retained source projects exist, not the six required for the direction-killing pilot;
- the fail-closed `CURRENT` reader, versioned R0/R1/V2 profiles, byte-bound
  artifact store, approved-parent loader, private prebound compositor, full
  selected-genesis payload reobservation, and recursive selected-history walk
  now exist as pre-release primitives. The history proof covers only the chain
  selected by one pinned `CURRENT`; it is not global fork uniqueness, a live
  execution lease, or publication authority;
- prospective unit enrollment, durable V3 operation admission, and a shared
  outer cross-ledger order transaction now retain and reobserve exact
  enrollment, PREPARED, admission, and COMMITTED bytes. Replay durability
  barriers repair only deterministic safe residue, retain the exact flushed
  inodes through the final named reload, and return the pinned observation.
  Pending cleanup validates semantic bytes on the held file immediately before
  unlink. This closes denominator/order structure, not worker launch, child
  success, or publication;
- static runtime/build receipts, exact executable endpoint reobservation,
  graphic-receipt payload binding, an attempt-owned exact R0 graphic receipt
  set, and fresh-inode generation sealing now exist as non-authorizing
  evidence. The graphic controller is limited to the current one-graphic R0
  profile, and the sealer neither proves writer quiescence nor touches
  `CURRENT`;
- a standalone append-only active-fence primitive implements bootstrap,
  reservation, and cancel under the never-unlinked publisher mutex. It has no
  release transition, starts no work, is not composed with V3 admission or the
  worker, and does not inspect or advance `CURRENT`. Journal mutation re-scans
  the held descriptor instead of trusting caller summaries and rejects capacity
  exhaustion before writing;
- zero natural product units qualify for a 95/95 claim.

Do not start production publisher work until the cheap mechanism and six-project pilot gates below survive.

## Product boundary

### Version and identity vocabulary

| Term | Exact meaning |
|---|---|
| Headless controller `v1` | CLI/controller contract namespace; unrelated to the legacy Auto Edit job envelope version |
| `HeadlessMp4AttemptV1` | Mutable, recoverable execution/admission record for one submitted operation |
| `Mp4GenerationV1` | Immutable committed realization schema selected by `CURRENT` |
| legacy `FinalApprovalV2` | Current root-oriented absolute-path approval; never imported as headless authority |
| `FinalApprovalV3` | New generation-relative approval bound to `Mp4GenerationV1` |
| `unitId` | Statistical enrollment identity; survives retries/fallback and may contain multiple attempts |
| `attemptId` | Durable system execution identity nested inside one unit |
| `pairId` / `armUnitId` | Paired experiment identity and the independently clocked baseline/treatment submissions |
| `publicationSeq` | Monotonic parent sequence stored only in `CURRENT` and `ParentRefV1` |
| `fenceRevision` / `fenceToken` | Independent mutable cancellation/admission record; rotating it does not advance `CURRENT` |

### One explicit request envelope

`realizationKind` is execution policy, not editorial intent. It must not be added to `AutoEditIntent` or inferred from `project.json`, Palmier files, a listener, the active desktop project, or the selected delivery.

The proposed controller accepts a closed schema resembling:

```text
HeadlessMp4QualityPassRequestV1
  schemaVersion: 1
  projectRoot: canonical absolute workspace project root
  operation: "quality-pass"
  unitId: caller-issued, durably pre-enrolled UUID
  expectedParent: { publicationSeq, generationId, commitDigest }
  idempotencyKey: caller-generated UUID
  request: raw operator feedback
  scope: controller-validated lane scope
  repairIntent: optional non-authoritative RepairIntentV1 hint

HeadlessMp4InitializeRequestV1
  schemaVersion: 1
  projectRoot: canonical absolute workspace project root
  operation: "initialize"
  unitId: caller-issued UUID from the initialization/enrollment ledger
  expectedCurrent: null
  initializationSnapshot: { manifestPath, manifestDigest }
  idempotencyKey: caller-generated UUID
```

The controller creates and persists:

```text
ExecutionPolicyV1
  schemaVersion: 1
  operation: "initialize" | "quality-pass"
  realizationKind: "deterministic-mp4"
  qualityPolicy: frozen policy identifier
  fallbackPolicy: frozen policy identifier
  controllerOperation: exact operation-matching versioned CLI/controller command
```

`fallbackPolicy` may select only another fully traced path inside the same frozen headless MP4 implementation closure, such as complete semantic replanning. It never invokes a legacy worker, reads root authority, touches Palmier, or changes realization kind. If no declared headless fallback succeeds inside the original unit and horizon, the unit fails.

Caller `repairIntent` can narrow a request but never authorizes mutation. The controller derives the normalized effect/target from frozen feedback and parent bytes; a hint mismatch is typed `EFFECT_MISMATCH`, not a reason to trust the hint or broaden scope. Initialization uses its own operation-matching policy with no repair/fallback path.

The explicit request-identity projection includes the execution policy, canonical project identity, normalized request/effect, expected parent, scope, fallback, and quality policy. It excludes only a closed, versioned list of runtime fields. Do not keep the current “hash every remaining context property” spread contract: unknown fields must fail schema validation, not silently enter or escape request identity.

`unitId` is part of request identity and can never be rebound by the server. Idempotency is closed and durable: the same key, unit, and request digest returns the original attempt/result; the same key with different bytes or another unit is `409 IDEMPOTENCY_CONFLICT`. Initialization requires absent `CURRENT`; a valid existing pointer returns `409 ALREADY_INITIALIZED` plus its pinned tuple unless this is a replay of the original initialization key. One publisher-capable attempt may be admitted per authority; a second request returns `409 ACTIVE_ATTEMPT` and does not rotate the first attempt's fence.

Attempt IDs are UUIDs but attempt records are project-local, so a bare ID is not a locator. Status requires the canonical workspace-contained `projectRoot`; cancel requires the same field in its closed JSON body. Project move is rejected while an attempt is nonterminal. A later opaque/global locator is optional and cannot weaken project containment.

Cancel is idempotent and publication has a precise linearization point. Under the publisher lock, first compare `CURRENT` with the attempt's publish-intent tuple. If they match, publication wins: cancel does not rotate the fence or record `CANCELED`; it triggers/awaits terminal-success recovery. Otherwise cancel rotates and flushes the independent fence token, records cancellation, then signals TERM/grace/KILL/reap. It returns a structured nonterminal `accepted` envelope while termination/reconciliation is pending. Cancel after terminal commit returns the existing terminal result and never rolls `CURRENT` back.

### Existing jobs and routes remain a separate legacy branch

The current `/api/producer/auto-edit` and `/api/producer/ai-edit` routes omit execution policy, branch on ambient Palmier state, write root files, and are coupled to GUI/SSE behavior. Their worker/job/status path also owns root quality markers and imports the mixed Palmier pipeline. They remain only the contemporaneous **disposable-pilot comparator** in fresh clones. The confirmatory baseline is the full current quality policy re-expressed inside the same headless trace/generation/publisher wrapper with every optimization disabled; a behavior-equivalence gate must show that this wrapper has not weakened the control. Treatment and confirmatory baseline then differ only by the frozen optimization policy, not by publication semantics.

Create a dedicated `HeadlessMp4AttemptV1` store, detached worker, trace, status reader, and generation result. Do not reuse `.sniper-auto-edit-job.json`, the producer-run registry, root quality-policy markers, or current project-status as primary state. This is a narrow attempt protocol for one MP4 realization, not a general JobV2.

The legacy root and the headless authority may coexist as intentionally separate branches. After initialization, the headless lane reads only its pinned generation/input authority and never falls back to root plan/final/approval files. Existing GUI/status routes remain blind to headless generations. Legacy writer fencing, transparent replacement, genesis migration, and compatibility projections are later optional integration work, not initial release prerequisites.

### Target-specific dependency graphs

The MP4 worker's static module graph must contain no Palmier/live-build modules. Current code statically imports Palmier classification in both HTTP routes and Palmier primary/checkpoint/mirror functions in the shared pipeline. A boolean branch after those imports is not the strongest zero-Palmier proof.

Split the implementation closure:

```text
headless/v1/mp4 controller composition root
  -> detached envelope/trace
  -> mp4-quality-pass pipeline
  -> deterministic planning/render/QC/generation publisher

headless/v1/palmier controller composition root (later, separately qualified)
  -> Palmier-specific broker/protocol/QC
```

Enforce this with a bundled TypeScript import-metafile denylist and a Python AST import-closure test, not source grep or dependency mocks. Today even deterministic render transitively imports `palmier.quality_hash` through `template_usage_approval.py`; move canonical hashing into a neutral Producer module. Template-history TypeScript also imports Palmier project state and must be replaced by a generation-scoped neutral contract.

Model processes never own or edit candidate files. They receive a sealed read-only evidence root and emit a schema-validated `RepairPatchV1` or plan payload on stdout; the controller alone writes candidate bytes. For Claude Code, use `--safe-mode`, `--strict-mcp-config`, explicit empty MCP, `--no-chrome`, an explicit closed `--tools` availability list, no slash commands, and no persistent/cross-attempt session resume; read the pinned Producer `SKILL.md` as ordinary immutable evidence instead of invoking ambient `Skill(producer)`. For Codex, use read-only/no-tools structured output or an OS sandbox exposing only the frozen attempt root, plus ignored user config/rules and disabled apps/hooks/multi-agent behavior. The current provider wrappers do not meet this contract and must not be reused unchanged. Any Palmier file, port, MCP, tool, checkpoint, mirror, import, or queue access fails the attempt.

## Stable project and generation authority

### Project identity

The current `ProjectJson` has provenance and intent but no durable local UUID. A path basename is not a stable authority identity. Avoid making the parallel headless lane depend on a rewrite of the legacy project schema: create `<projectRoot>/.sniper/lineage.json` exclusively under a dedicated never-unlinked lineage/authority-create kernel lock, not a legacy root-writer lease, then derive the deterministic-MP4 authority from a domain-separated hash of its random lineage ID and realization kind. Never reuse Palmier's project ID.

Required copy/move semantics:

- moving one project preserves the lineage ID;
- a copied project root is a physically isolated branch of the same lineage, is permitted, can never count as an independent reliability unit, and can never merge authority state back automatically;
- an explicit logical fork may mint a new lineage ID and record `forkOf`;
- disposable experiment clones use an experiment namespace and are incapable of production publication;
- malformed, symlinked, permission-unsafe, or conflicting lineage/authority claims **within one canonical project root** fail closed. Duplicate lineage IDs in explicitly separate copied roots are not “multiply claimed”; the caller must choose one canonical root and the system never scans/merges them.

Recommended project-local authority root:

```text
<projectRoot>/.sniper/authorities/<authorityId>/
  authority.json
  FENCE
  CURRENT
  .publish.mutex
  generations/<generationId>/
  attempts/<attemptId>/
```

`FENCE` is a separately mutable record containing `{schemaVersion, authorityId, fenceRevision, fenceToken, activeAttemptId}`. Admission under the lock verifies the expected parent, rejects another active attempt, and mints a random `fenceToken` captured in the attempt. Cancel/stop rotates that token without changing `CURRENT`. Expected-parent CAS alone cannot stop a canceled old worker when no newer generation has published. `CURRENT` is a small validated JSON pointer containing `{schemaVersion, authorityId, publicationSeq, generationId, commitDigest}`; `publicationSeq` advances only on publication. It is not a bare path or symlink.

The repository now has a narrower standalone fence journal and materialized
`FENCE` projection with `BOOTSTRAP`, `RESERVE`, and `CANCEL`. It deliberately
has no `RELEASE`, worker launch, admission integration, final fence recheck, or
`CURRENT` operation. It is therefore a crash-tested state primitive, not the
active-attempt protocol described by this section.

Authority resolution has four explicit states:

- `UNINITIALIZED`: valid lineage/authority metadata, no `CURRENT`, no published generation, and no unresolved initialization intent; only `initialize` is allowed;
- `INITIALIZING`: one valid active expected-null initialization attempt; reads and quality passes return the attempt locator/non-ready status;
- `READY`: `CURRENT` and its generation validate completely;
- `BROKEN`: partial, corrupt, mismatched, or ambiguous state; all normal work fails closed and recovery/repair is explicit.

Missing `CURRENT` is therefore valid only in the proved `UNINITIALIZED` or recoverable `INITIALIZING` states; it is never interpreted as a legacy-root fallback.

### One kernel-held publisher

Current TypeScript lockfiles use exclusive creation and lease metadata; they are not a kernel-held publication lock. Put compare, generation revalidation, pointer replacement, and directory flush inside one small publisher helper that holds `fcntl.flock` on a never-unlinked `.publish.mutex`, following the existing Python flock pattern.

The helper must:

1. open the authority and pointer through safe descriptors;
2. validate same-filesystem staging and every no-symlink/containment invariant;
3. revalidate `commit.json` and exact generation bytes while the lock is held;
4. compare the complete expected parent tuple and the attempt's exact durable fence token;
5. write and flush a unique pointer temporary;
6. atomically replace and flush `CURRENT`;
7. return the observed old/new tuple and never spawn descendants.

Killing the helper releases the kernel lock. A stale TypeScript worker may continue private computation, but its rotated fence cannot publish.

### Paths are not enough; freeze execution inputs too

Introduce both contracts:

```text
GenerationPathsV1
  root, requestIdentity, executionPolicy, admissionInputs, realizationInputs,
  generationInputs, sourceSnapshotManifest, intent, cutApproval, assetClosure,
  runtimeCapabilityManifest, repairState, realization, plan, base, basePlan,
  fingerprint, final, assembledProof, proxy, refit, audit, reviews, cover,
  finalApproval, verification, commit

AttemptPathsV1
  root, state, publishIntent, trace, traceManifest, log, cache, work, tmp

AdmissionInputsV1
  projectIdentity, parent generation, normalized feedback/request identity,
  operator intent, source/manifest/transcript snapshot, template-history policy,
  implementation/toolchain root, execution/fallback policy, expected parent

RealizationInputsV1  (frozen after planning, before render)
  ResolvedPlanV1, controller-derived effect and routing decision,
  repair/fallback disposition, RepairStateV1, cut approval, asset closure,
  exact template-usage approval/history evidence

GenerationInputsV1
  exact digests of AdmissionInputsV1 + RealizationInputsV1
```

This staged distinction is mandatory: cut approval, chosen assets, effect classification, and repair/fallback disposition are planning outputs, not admission-time facts, but they must become immutable before render. Immutable generation artifacts and mutable attempt state cannot share a manifest or lifecycle: trace/recovery may continue after `CURRENT` advances, while cache/work/tmp are never committed. `chain.ts` currently hardcodes root basenames, while `assemble.py` derives `base_plan.json`, refit state, proxy, lock, and proof paths from the supplied base/output/fingerprint. Template approval also looks for `project.json`, `.sniper-template-usage-approved.json`, and history relative to the output directory. Merely replacing three TypeScript path strings cannot create an isolated generation.

The first implementation may keep the renderer's proven co-located basename layout inside one private generation, but every implicit input must be passed or staged from `GenerationInputsV1`. Generation mode passes an explicit isolated `--cache-dir`; it never accepts the renderer's shared source-tree default.

All semantic normalization, recompose, and refit occurs on the private execution-plan copy **before** lint, template approval, plan critics, and the realization digest freeze. The exact post-transform plan bytes are the approved renderer input. Render/assemble then run in a no-semantic-mutation contract and prove the before/after plan digest is identical. If a legacy helper proposes a different refitted/recomposed plan, that output becomes a new unapproved candidate and returns through governance; it cannot render or inherit the prior approval. This closes the current behavior where render/assemble may mutate a plan after lint/template approval.

Allocate the final random/UUID generation path before the first write and keep every receipt path generation-relative. Current approval, audit, and review records embed absolute paths and would become invalid if a verified directory were renamed. In V3:

- `generationId` is known before execution;
- `FinalApprovalV3` may include `generationId` but never its future commit digest;
- `commit.json` lists every authoritative relative generation file and digest except itself, including request/execution policy, admission/realization/generation inputs, source snapshot manifest, intent, cut/asset/runtime/repair/realization records, plan/base/refit/final/proxy-if-required/proofs/cover/audit/reviews/verification/final approval; large immutable source/CAS objects may remain external only by validated content digest and a durable reachability pin; it excludes attempt state, trace/log, caches, work, temp, locks, and pointer files;
- `commitDigest = SHA256("sniper-mp4-generation-commit-v1\0" || exact commit.json bytes)`;
- `CURRENT` stores that digest.

Allocate `generationId` and its final path before work, but never expose that final inode namespace to models, renderers, or writer-capable descendants. They write only beneath attempt staging. Reap every writer-capable process group, then a trusted sealer copies or verified-reflink-clones authoritative bytes into fresh final-generation inodes and rejects symlinks/devices/FIFOs/sockets and external/multiply-linked files. Sandboxed read-only ffmpeg/audit/critic verifiers may read final bytes but write only attempt-owned stdout/staging; reap them before the trusted controller writes relative receipts/approvals and hashes the final closure. This avoids the fiction that `chmod` revokes an escaped descriptor while still auditing exact final bytes. The controller writes `commit.json` last, flushes the directory chain, and makes the generation read-only before publication. `CURRENT` is the visibility boundary.

The fresh-inode generation sealer now implements the staging-to-installed-
generation portion in isolation, including bounded exact manifests,
no-replace installation, conservative pending recovery, and exact replay. Its
result contains only generation and commit identity. The caller still must
prove every writer-capable descendant is dead, supply semantically complete
receipts, reserve disk, and pass the future fenced publisher; installation is
not publication.

The commit verifier accepts only canonical JSON with no duplicate keys and exact serialization, normalized unique relative paths, no `.`/`..`/absolute/unicode-alias collisions, and a closed manifest binding authority ID, generation ID, attempt ID, request/unit identity, expected parent, execution/quality/fallback policy IDs, per-file size and SHA-256, and every mandatory artifact class. Fence token and proposed publication sequence are intentionally **not** generation content; publish intent plus the publisher bind them, and `CURRENT` records the resulting sequence. Files not copied into the fresh final namespace are scratch and cannot be referenced. `commit.json` excludes itself by construction.

Every reachable generation pins each referenced external source/asset/tool CAS object for at least the generation retention period. `CURRENT` resolution and re-verification fail `BROKEN` when a pinned object is missing, substituted, or digest-mismatched; they never refetch mutable remote bytes. Automatic generation and external-CAS GC are both absent initially. Later GC must compute joint generation/object reachability with reader pins and crash-safe refcounts.

Attempt recovery separates phase from disposition:

```text
phase:       ADMITTED -> RUNNING -> VERIFIED -> PUBLISH_INTENT -> POINTER_COMMITTED
                 \-----------------------------------------------> TERMINAL_SEALED
disposition: PENDING | SUCCEEDED | FAILED | BLOCKED | STALE | CANCELED
```

Every outcome, including pre-worker failure, stale parent, block, and cancel, reaches `TERMINAL_SEALED{disposition}` before `FENCE.activeAttemptId` clears. `publish-intent.json` pins the attempt/request identity, exact proposed parent, fence token, generation ID, commit digest, and terminal result tuple before the pointer write. The authority's active attempt is not cleared and no later admission/publication is allowed until terminal recovery seals this transition. If `CURRENT` advances and trace/result sealing then crashes, recovery revalidates that intent and generation, confirms `CURRENT` equals the proposed tuple, and seals `SUCCEEDED`; it never publishes or reports a different generation. A committed pointer is not downgraded because trace sealing was interrupted, but the status query remains nonterminal until recovery. An `ADMITTED` crash before worker launch either relaunches the exact pinned worker under the frozen retry budget or seals `FAILED`; torn failure/cancel traces recover by the same framed-tail rule.

The attempt-status command always returns `{phase, disposition, terminal, attemptId, unitId, authorityId, requestDigest, result?, error?}`. Closed typed outcomes distinguish malformed schema, unknown attempt/wrong authority, stale parent/active attempt/idempotency conflict/`BROKEN`, pre-admission capacity, durable acceptance, known state/result, and unexpected controller fault after evidence capture. CLI exit codes and JSON error codes are frozen with the schema. A future transport may map them to HTTP without changing state semantics. Errors never trigger legacy/Palmier fallback.

## Stop-gate ladder

Each gate is a hard stop. G0, G1, G2, and G7 corpus collection may run in parallel; G3 requires G1+G2, G4 requires G3, G5/G6 require G4, G8 requires G0/G1/G4/G5/G6/G7, production slices/G9 require G8, G10 requires G9 plus the wrapped-control bridge, and confirmatory enrollment precedes G11. No dependent work begins because an earlier result is “close.”

| Gate | Minimal proof | Current status |
|---|---|---|
| G0 — provider capability | One tiny tool-less call per provider exposes secret-free raw terminal events with requested/resolved model, input, cache-create, cache-read, output, and cost counters | Claude capability PASS; full Codex contract BLOCKED by missing cache-create/cost/resolved-build fields |
| G1 — durable trace | Admission record and append trace survive forced kill/torn-tail recovery; unsealed attempt remains in denominator | INTEGRATED TRACE PRIMITIVE PASS; later isolated suites also exercise enrollment/order replay, fresh-inode sealing, and a standalone active fence. Full gate BLOCKED because these paths are not one worker lifecycle and trusted liveness/startup resource replay, final fence integration, publisher, and pointer recovery are absent |
| G2 — offline overlay | One pinned `section-marker` overlay renders with external egress denied, exact HyperFrames/Node/browser/GSAP closure, isolated scratch/cache, full decode, and pixel oracle | HISTORICAL PASS for independent attempt 008's frozen source closure; current source changed and needs a fresh independent run |
| G2b — explicit renderer root | The headless launcher owns policy, cache, process group, expected proof, and daemon-resource identity without GUI/Palmier imports | Local contract passes; retained specimen remains `qualifying:false`, eleven frozen files changed, and no current-source OCI qualification exists |
| G3 — R0 parent closure | An approximately eight-second planner-reachable source/plan/intent/template approval becomes one coherent fully approved seed | Missing |
| G4 — R0 equivalence | Old, revised-reuse, revised-fresh-A, and revised-fresh-B pass exact receipts, decode, derived artifacts, and color/ROI/time-window proof | Not run |
| G5 — audio mechanism | One coherent pristine/base/final/proof seed passes the declared audio eligibility matrix | Current retained seed is incoherent |
| G6 — cut mechanism | A dependency-closed `cutTrack + cutDecisions` private fixture passes previsual, cut critic, refit/drop inspection, approval, and downstream gates | Not run |
| G7 — development corpus | Six distinct original source/project/first-feedback clusters exist | Two retained source families; zero of six have prospective first-feedback admission evidence |
| G8 — complete disposable pilot | Six paired AB/BA projects pass the complete latency, quality, failure, cost, and contamination kill rules | Not run |
| G9 — authority seam | Lineage, headless-only resolver, immutable generation, fence, flock publisher, initialization, recovery, and fault matrix pass | BLOCKED: full selected-genesis payload reobservation, recursive selected-history authentication, prospective unit enrollment, ordered V3 admission, exact R0 graphic receipts, fresh-inode sealing, and a standalone active fence now exist as disjoint non-authorizing primitives. Production lineage/state orchestration, trusted worker execution and quiescence, final fence composition, publisher/`CURRENT`, terminal recovery, capacity admission, and the fault campaign are absent |
| G10 — confirmatory readiness | Legacy→wrapped control bridge disposition, exact comparator claim, release lock, analysis/power/coverage harness, population/drift rule, rater protocol, provider identity policy, cost limits, and independent enrollment plan are sealed | Not ready |
| G11 — release decision | Frozen confirmatory cohort passes every fixed-sequence gate and `release-decision.json == PASS` | Zero qualifying units; external/general enablement forbidden |

### G0 — capability probe before optimization claims

Add a raw-event capture hook without changing model behavior. Run one minimum-token, tools-disabled structured call per configured provider. Assert the exact fields the later analysis needs.

If cache-create/read and noncached-input counters are absent from command stdout, stop the prefix-cache branch. If neither immutable resolved model/build identity nor a reliable rotation signal exists, a prospective frozen-build 95/95 claim is blocked. An unobservable moving alias permits only a retrospective calendar-bounded statement, not continuing release qualification. Every later call reasserts the capability/schema/build fields; one G0 probe is not ongoing identity proof.

### G1 — evidence before experiments

Create attempt-owned, secret-free `trace.jsonl` where each physical line is one bounded canonical JSON frame:

- one designated supervisor writer or a never-unlinked trace `flock` around tail-read → sequence/digest → one-line append → `fdatasync`; `O_APPEND` alone is insufficient across admission/worker/publisher/cancel/recovery processes;
- frame fields include payload-byte length, payload CRC32, sequence, prior digest, canonical payload, and event digest; newline plus CRC distinguishes a torn tail from an interior fork;
- no-follow/safe-open semantics, monotonic sequence, prior-record digest, and event digest;
- wall timestamp plus boot-bound monotonic nanoseconds;
- `unitId`, `attemptId`, release/build/policy IDs, expected parent, and normalized request digest;
- stage start/end and overlap IDs, queue/admission time, provider raw-event digest, process identity/exit, resource/cache lineage, failures, and terminal disposition;
- flush at admission, provider start/end, child terminal, generation verification, publish intent, pointer result, and terminal seal.

Recovery validates the chain, truncates only an authorized torn final record,
and durably retains the exact canonical terminal-result bytes before appending
their domain-separated digest to the terminal frame. It seals a manifest last.
Startup processes durable terminal intent before generic torn-tail
classification, then revalidates sequence, trace digest, disposition, result
digest, exact result bytes, and immutable attempt identity. A digest without
retained bytes proves integrity but cannot make the result available after a
crash. The bounded V1 journal and 1 MB log remain diagnostics only.

Under the authority admission lock, persist `{authorityId, idempotencyKey, requestIdentityDigest, attemptId, unitId, firstSubmittedAt}` and flush it before returning the structured accepted envelope. Same key/same unit/same digest returns this record and original clock; changed unit or digest returns a typed conflict; terminal replay returns the pinned result. Retain an idempotency tombstone for at least the result/evidence retention period.

### G2 — Discriminator 0: one offline overlay

Before deriving R0 or paying for a corpus:

1. check in an exact HyperFrames package lock/integrity closure and invoke exact
   absolute Node and CLI-module paths, never `npx --yes` or a shebang-selected Node;
2. vendor the exact GSAP core and rewrite one `section-marker` template to local bytes;
3. pin and hash the browser binary and set telemetry/download denial explicitly;
4. execute in one attempt-exclusive network/process namespace backed by a
   prebuilt immutable OCI image digest, with frozen pipeline/runtime inputs and
   attempt-owned `TMPDIR`, cache, work, and output mounts;
5. have the trusted controller run the image directly with `--pull=never`,
   `--network none`, read-only root, nonroot user, dropped capabilities, no new
   privileges, bounded tmpfs, and no host/Docker/SSH/temp sockets; do not use
   HyperFrames' mutable `render --docker` helper;
6. render one overlay, fully decode it, and prove requested color/alpha/dimensions/window pixels.

Stock HyperFrames 0.7.33 selects random file-server and TCP CDP ports. A host
policy that allows all localhost is not a sealed closure, and brittle runtime
monkeypatching is not the preferred product fix. The qualified `--network none`
adapter keeps an isolated container loopback for those two random sockets while
making host loopback and external networks unreachable. Independent attempt 008
passed the exact clean-success adapter, frozen-source, decode, pixel, network,
runtime, removal, and warm-cache proofs. This proves only that toolchain
mechanism, not product quality, field incidence, asynchronous cleanup, or the
Palmier machine-interface lane.

Before G3 or integrated use, the headless composition root must inject the
renderer strategy and attempt-owned cache explicitly. Ambient
`SNIPER_RENDER_IMAGE_ID` selection in the shared graphics module is a G2
prototype boundary only; it must not choose execution policy for Palmier or
legacy callers. The integrated supervisor must also prove late/ambiguous Docker
creation cleanup, cancellation, controller `SIGKILL`/reboot recovery, terminal
daemon re-attestation, and job-scoped daemon-identity caching. None of those
requirements is retroactively counted as part of the G2 clean-success pass.

The corrected `sealed-oci-v2` wrapper now provides the explicit renderer mode,
literal secret-free child environment, attempt-owned cache/temporary roots,
owner receipt, strict result/runtime/asset binding, output inode/hash binding,
local process-group ownership, and a parent-allocated Docker name durably
registered before spawn. Its retained parent preflight
reproduced the exact G2 MOV/tar with 13.181-second cold, 0.666-second warm, and
11.902-second second-attempt cold runs. It remains `qualifying:false`: the first
version was falsified by symlink-result and restrictive-umask cases; later
versions were additionally falsified by impossible occupancy, live-asset reread,
same-inode overwrite, descendant, and descriptor-leak cases. The current source
has no independent pass, production controller call site, trusted
request/build/capability constructor, startup resource-replay integration, or
trusted sealer handoff.

This minimal overlay does not qualify conditional runtime paths. After each candidate `ResolvedPlanV1` freezes—and before any render/execution, including generation-zero initialization—derive `RuntimeCapabilityManifestV1` and bind exact executables, libraries, model weights, detector backend, auxiliary Python environments, and cache hashes. Demucs, YuNet/face detection, and every other enabled lane pass an offline smoke with downloads/telemetry/ambient fallback denied; unsupported capabilities fail before render work.

### G3/G4 — planner-reachable R0

The retained `social-polished-20260717` plan has stable `section-marker.spec.accent` IDs and a real source, but no approved base/final/proof. Rebase its source/transcript into the immutable input closure, mint a new local intent/template-history approval, and seal its complete runtime capability manifest.

Build the seed with a plan path outside the render output directory, because `render.py` copies the plan into the output and can otherwise hit a same-file error. Render graphics-free fresh, rename its output to the private base, then assemble with an explicit cache/fingerprint/manifest. Do not use `auto_base_guard.py` in the oracle; it renames stale bases and changes treatment semantics.

The revised arms all start from identical old-cache snapshots:

- reuse: clone the approved seed, patch only one stable accent, then assemble and require `base_current`;
- fresh A and fresh B: two clean identical clones, direct fresh base render then assemble;
- old: retained parent truth.

Require full audio/video decode, ffprobe coverage, nondeterminism characterization, exact plan/spec/asset/runtime receipts, regenerated candidate-frame-zero cover, proxy disposition, requested pre-encode color, calibrated decoded color, full-window contrast, protected-region/collision checks, and no cross-arm cache donation. Current `render_report.json` is written before Audit B and is diagnostic only; bind a separate flushed terminal-audit receipt produced after Audit B and full decode, or change the renderer to rewrite/flush its report after those stages.

`assemble.py` currently always writes a proxy and has no `--no-proxy`. Keep proxy behavior identical in every arm until an explicit symmetric switch exists. Do not claim a proxy-off treatment before then.

### G5/G6 — audio and cut after R0

Do not use the retained audio specimen until one generation's base, fingerprint, base plan, final, assembly proof, plan, and requested audio state agree. Test each audio eligibility cell separately.

For cut work, the writer/controller mutation scope must include the dependency pair `cutTrack + cutDecisions`. Run cut-only previsual before merging into the private full-plan copy. Refit privately, inspect every moved/dropped row, then run approval and downstream gates. `plan_refit.py --write` is not the production transaction; the experiment contains it inside a disposable private copy and verifies the postdiff.

### G7/G8 — complete disposable product pilot

Do not manufacture six units from retained variants of C0679. Collect six distinct original source/project/first-organic-feedback clusters. Give every arm a new fail-closed CoW clone, distinct inode checks, isolated caches, and AB/BA order inside a narrow time block. “Contemporaneous comparator” does not mean resource-contending simultaneous execution.

Freeze the disposable legacy comparator as `LegacyFullQualityMp4ComparatorV1`: exact route sequence, source commit, prompt/model/effort/policy bytes, cache policy, deadlines, and MP4-only outcome. Any Palmier access is a contamination failure. Before confirmation, run an arm-neutral A/A bridge between this legacy comparator and `HeadlessFullQualityControlV1` (the same policy inside the new wrapper with optimizations disabled). Bridge equivalence is mandatory for any “65% faster than today's/current route” claim. If it fails, amend and freeze the release claim **before enrollment** to “versus wrapped control” plus the absolute SLA, characterize the bridge difference, and forbid current-route speedup wording. Treatment fallback never invokes either legacy route/worker.

The treatment needs an extracted candidate controller, not the current `finalizeSurgicalEdit` monolith. Normalize and govern one immutable candidate; then launch the surgical and planning critics against the same bytes. The planning path consumes the same deterministic gate receipt rather than rerunning it. Resource-admitted render may speculate against those bytes and is killed/reaped/discarded on revise or block. Cut critics join only for dependency-closed cut work.

Only a surviving complete pilot earns G9 publisher implementation.

## Production implementation slices after G8

Each slice is deployable/testable with later behavior disabled.

1. **Closed schemas and tripwires.** Add `ExecutionPolicyV1`, explicit request identity, lineage/current/fence/attempt/commit/final-approval/repair schemas, target-specific module boundary, generation-relative artifact refs, empty-MCP model launch, and transitive dependency tests. No new output writer.
2. **Lineage and headless resolver.** Add project-local lineage under a dedicated lineage/authority-create lock, authority parser/state machine, and `PinnedGenerationView`. With no writer enabled, missing/corrupt authority fails closed and no legacy root fallback exists.
3. **Attempt store and CLI reader, still disabled for work.** Add idempotency admission records, attempt-owned framed trace, state/recovery schema, durable status/error envelopes, cancel/fence protocol, and terminal pinned-result envelope. Do not launch workers or reuse V1 jobs/root run state/root quality markers.
4. **Frozen inputs and private execution adapter.** Add `ProjectIdentityContext` separately from `GenerationExecutionContext`, `AdmissionInputsV1 + RealizationInputsV1 + GenerationInputsV1`, `GenerationPathsV1 + AttemptPathsV1`, descriptor/reflink/CAS capture, rebased manifest, explicit template/operator authority, target-specific implementation closure, required attempt-owned cache/work roots, and a generation-local renderer strategy injected by the headless composition root. Ambient environment variables and shared cache defaults cannot select the adapter. It produces unselected private candidates only.
5. **Neutral planning/QC kernels.** Extract current planning/authoring/QC logic from mixed modules so the MP4 composition root has no Palmier defaults, root promotion, or root checkpoint path. Add durable `RepairStateV1` with rejected/staged/repaired candidate identities.
6. **Toolchain closure.** Execute an immutable controller bundle with pinned Node/tsx/Python/ffmpeg/HyperFrames/browser/fonts/local GSAP, plan-derived runtime capability manifest/model weights/backends, and attempt-owned caches. The current detached worker's pinned Python source snapshot is useful but does not pin its live TS worker, `tsx`, venv, model read roots, or renderer runtime.
7. **Trusted sealing and verification.** Reap all writer-capable descendants, clone/copy into fresh final inodes, run sandboxed read-only decode/effect/terminal-audit/critic verification with outputs outside final, reap verifiers, let the trusted controller write receipts/derived artifacts, verify the closed manifest, write/flush `commit.json` last, then make the generation read-only. Still no `CURRENT` write.
8. **Publisher and initialization.** Add the flock helper, durable fence, expected-null cold-built generation-zero initialization, byte revalidation, pointer publication, and deterministic recovery. Never import the legacy absolute-path approval and never materialize a root projection.
9. **Internal controller canary only.** Under an experiment-only feature flag, send one frozen typed effect class through the CLI/controller publisher. Return the pinned commit/final path only after pointer publication and terminal trace seal. No external/general enablement.
10. **Fault campaign.** Inject at least: durable accepted response before worker launch; same-key same/different-body replay; concurrent initialize; missing `CURRENT` after prior publish; cancel before/after pointer; pointer committed before result/trace seal; failure/cancel torn trace; corrupt or unflushed fence rotation; stale parent; dual publisher; `ENOSPC`; source/cache race; missing/replaced external CAS object; authoritative symlink/device/external hardlink; escaped child writer; plan mutation after approval; conditional-runtime download/backend fallback; status after project move/copy; and baseline/treatment Palmier access. A single mixed generation, stale publish, lost attempt, hidden failure, Palmier access, or unclassified fault disables the controller.
11. **Wrapped-control bridge and confirmatory freeze.** Run the frozen legacy→wrapped bridge. Either prove equivalence for a current-route claim or narrow the preregistered claim to wrapped-control plus absolute SLA; then hash build/runtime/provider/prompt/policy/analysis/rater/cost/drift artifacts and enroll untouched natural units under the internal flag.
12. **Release enablement.** External/general use remains disabled unless every fixed-sequence gate passes and the frozen `release-decision.json` is exactly `PASS`. Any later behavior change resets qualification.

Slices 3–7 now have disjoint pre-release building blocks: prospective unit
enrollment and ordered V3 admission, exact admitted-composition inspection,
tagged R0/R1/V2 disk selection, full selected-genesis payload reobservation,
recursive selected-history authentication, a render-specific pre-admission
artifact, strict render validation, one-graphic admitted receipt persistence,
process-group ownership, a Docker resource ledger, standalone active-fence
transitions, and fresh-inode generation sealing. These remain non-authorizing
and are not one lifecycle. The slices are not satisfied because the production
CLI/status/cancel surface, trusted runtime and writer-quiescence supervisor,
resource-vector capacity reservation, final fence integration, semantic child
verification, publisher/`CURRENT` recovery, and end-to-end fault campaign are
still absent.

## Reader and writer boundary

The headless release does not convert any GUI endpoint into a generation editor.

| Surface | Initial managed-project behavior |
|---|---|
| Headless initialize | Requires proved `UNINITIALIZED`, consumes one presealed snapshot, and publishes expected-null; it does not resolve legacy `CURRENT` |
| Headless quality-pass/status/current readers | Resolve and pin one validated headless `CURRENT` tuple for the full operation |
| Template-usage history used by headless planning | Use a generation-scoped neutral contract; scan committed headless generations and an explicitly frozen initialization history, never Palmier mirror state or live root approval |
| Existing root-writing Auto Edit, AI Edit, assemble, render, save-plan, speech-cleanup routes | Continue to operate only on the separate legacy branch; they cannot update headless `CURRENT` |
| Existing project-status backend | Remains legacy-only and intentionally blind to headless generations |
| Palmier mirror/push/delivery | Disabled for the first MP4 release; later reads the pinned commit and owns a separate delivery receipt |
| Legacy GUI plan/final readers | Outside release scope; no authority projection or transparent replacement is promised |

For every ready headless operation, corrupt `CURRENT`, a missing generation, or an identity mismatch is an error. Absent `CURRENT` is accepted only by the explicit `UNINITIALIZED/INITIALIZING` initialization state machine above. There is no fallback to root files. Transparent migration, legacy writer fences (including direct Python CLIs), all-reader cutover, and projections are later optional work if GUI integration is ever authorized.

## Executable release evidence contract

### Population

The primary release claim is labeled exactly **system-ready automation latency and reliability for Aaron's first organic quality pass, conditional on initialization before feedback**. It does not establish initial-short planning/build speed or request-to-Aaron-decision workflow time. Initial creation needs a separate controller operation, cohort, estimand, and release decision; initialization success/failure is reported separately and cannot be hidden by enrolling only successful initializations. Report request-to-first-human-accept/reject and active operator seconds as separate diagnostics; a ten-minute automation followed by forty-five planned review minutes cannot be called a ten-minute completed workflow.

Both quality-pass arms start from byte-identical copies of the same committed, pre-feedback headless parent generation. The full-quality control runs in the same trace/generation/publisher wrapper with optimization disabled. Freeze only pre-feedback immutable inclusion criteria: duration range, aspect, language, source condition, and declared population calendar/load policy. Automatically enroll all consecutive first organic requests meeting those criteria before routing. Effect eligibility and fallback are outcomes, not inclusion criteria; provider outages and rate limits are outcomes, not post hoc “availability-window” exclusions. Later passes are outside the claim; an all-pass claim must enroll them and cluster within original project.

The confirmatory interpretation is prospective only for the frozen release/build under a preregistered stationary operational distribution and expiry window. Freeze exchangeability assumptions and numeric drift limits for request mix, latency/load/cache state, provider schema/build, failure rate, and human acceptance. A learning trend, provider degradation, build rotation, or exceeded drift limit expires the decision and requires a new cohort. If stationarity cannot be defended, report only the exact finite calendar interval observed and make no future-population claim.

Do not select the highest-incidence effect class from one census and use the same unadjusted census to claim its prevalence. Fix the class before the census, split development from an independent release census, or use simultaneous familywise-valid prevalence bounds across every candidate and carry that uncertainty into the release analysis. A deterministic winner-selection rule alone does not remove winner's curse.

### Latency and economics

Define `QualifiedComparisonJobV1` identically for both confirmatory arms: correct request/effect, the arm's predeclared full-quality policy, complete decode/audit/critic/evidence receipts, no unplanned intervention, identical absolute blinded human acceptance, correct committed expected-parent publication, and a sealed required trace. `QualifiedHeadlessJobSuccessV1` is the treatment reliability endpoint and adds any treatment-specific routing/fallback obligations; it cannot weaken the shared comparison definition.

Assign `pairId` before arm order. Each arm receives a distinct `armUnitId[a,i]` and `t0[a,i]` at that arm's first scheduled controller-submission attempt after only predeclared user-input checks; artificial AB/BA washout/order waiting is outside both clocks, but a failure to submit at the scheduled slot is `H`. Typed validation/conflict/capacity faults, retries, restarts, internal attempts, and resubmissions cannot reset that arm's `t0`. The same idempotency key/request identity returns the original attempt; internal retries remain that attempt; every attempt/fallback stays nested in the arm unit. The natural treatment `armUnitId` may overlap the reliability cohort only under the frozen overlap rule.

For paired unit `i` and arm `a`, freeze:

```text
Y[a,i] = max(t_system_ready_committed_hash, t_required_trace_seal) - t0[a,i],
         when QualifiedComparisonJobV1 and elapsed <= H;
         H otherwise.

D[i] = Y[treatment,i] - 0.35 * Y[baseline,i]
```

The primary estimator is the **unweighted unit-level** mean across automatically enrolled representative units; balanced/enriched development projects do not enter it. Release requires the preregistered cluster-aware one-sided 95% upper confidence bound for `E[D]` to be at most zero. Use a paired wild-cluster bootstrap-t over whole preregistered operational blocks with equal unit weights, at least 9,999 deterministic resamples, and `N_blocks = max(30, the pilot-powered requirement)`. Lock the power/sample-size simulation, cluster definition, unequal-cluster-size handling, missing/block-loss rule, and type-I coverage fixtures before G10. Zero estimated between-block variance, too few blocks, or failed heavy-tail/correlation coverage is `INSUFFICIENT_EVIDENCE` unless the declared finite population was exhaustively enumerated. Freeze the business SLA horizon `H` before outcomes; the later reliability gate must separately show the declared probability of complete success within `H` exceeds 95%, so a treatment cannot pass merely because its baseline was extremely slow. Human ratings may arrive later, but rejection changes that arm's already measured value to `H`; human waiting time is not added asymmetrically.

For every pre-enrolled unit, define total cost as all provider charges, allocated local compute, retained storage, and operator time across every attempt/fallback through child-process quiescence. Freeze the rate card/allocation rules and numeric absolute plus baseline-relative bounds before outcomes. The economic stage is an intersection-union gate: one-sided alpha-.05 upper bounds for mean total cost, mean active operator seconds, and intervention probability must each clear their ceiling, while peak retained storage is a hard per-unit cap. A failed expensive unit remains in every denominator; the golden analysis suite includes a failed high-cost fixture that must worsen the gate. Until these bounds are chosen, call this a latency study rather than an economics result.

AB/BA ordering does not by itself isolate provider-side prefix caches, account throttles, or rate limits. Freeze provider account/session/cache policy, record cache-create/read and throttling counters on every call, preregister an order × arm/carryover gate and first-period-only sensitivity analysis, and use independent provider capacity when available. Detectable carryover that can change the decision yields `INSUFFICIENT_EVIDENCE`, not an adjusted success.

### Quality

If every critical component must pass, use a preregistered **intersection-union test**: each component is tested one-sided at alpha .05 and release passes only if all reject inferiority. Use closed testing/Holm/max-T only when simultaneous lane-level claims/intervals are also required. Do not mix the procedure names.

Freeze minimum independent informative project-level opportunities for captions, temporal motion, audio, canvas, graphics/effect correctness, cross-lane contamination, clean negatives, and false positives. An unsupported lane is `INSUFFICIENT_EVIDENCE`, not pass.

Before G10, materialize one `QualityLaneProtocolV1` per lane with: project-level unit/opportunity denominator; outcome measure; direction; exact null; smallest-meaningful justified noninferiority margin; minimum independent informative projects; aggregation; missingness; and sample size powered from a conservative upper confidence bound on pilot discordance. Zero discordance in six development projects cannot imply a tiny confirmatory sample.

Use an absolute blinded rubric that can judge one output; paired preference is secondary. Each artifact receives three independently randomized calibrated raters. Binary acceptance is fixed majority vote; any reported critical defect triggers a blinded senior adjudication whose rule and deadline are frozen. A missing rating at deadline is failure for reliability and `INSUFFICIENT_EVIDENCE` for the affected NI component; never replace a unit after outcome. Freeze calibration sensitivity/specificity and inter-rater thresholds before confirmation; falling below either stops the gate. Record an arm-guess after each rating and fail blinding qualification when arm identification exceeds its preregistered chance bound. Model project and rater effects; three ratings are not three projects. Seed labels remain inaccessible until dataset seal.

### Reliability

`59/59` gives the simple one-sided exact lower bound above 95% only under a defended independent/common-marginal Bernoulli model. Unique directories and consecutive enrollment do not create independence. Choose and defend one design before enrollment:

- automatic consecutive sampling plus an externally justified iid model;
- an exact-binomial sampling frame whose blocks/units are independent draws from the same frozen target mixture and therefore share one marginal success probability; or
- a preregistered clustered/hierarchical/anytime-valid method with its own sample size.

Fifty-nine same-day replays are not 59 field units. Every pre-enrolled unit remains. Multiple arrivals inside a dependence block stay nested and force the clustered design; heterogeneous block-specific probabilities require a preregistered stratified/Poisson-binomial/hierarchical method rather than Clopper–Pearson 59/59. A same-regime failure can never be discarded. Development, synthetic, seeded, enriched, tuned, and fault-injection jobs never count. Natural treatment arms from the fixed-sequence latency/quality cohort may count only if this overlap rule is sealed before outcomes and they receive the identical absolute adjudication.

A provider alias such as current Claude `opus` is not an immutable build. Every confirmatory call must record and assert the resolved model/build and provider event-schema identity; G0's one probe proves capability only. Claude and Codex are separate releases unless routing weights/strata and surface-specific success margins are frozen and jointly analyzed. A prospective frozen-build claim requires a resolved immutable ID or observable rotation signal. If rotation is unobservable, an alias interval can support only a retrospective time-bounded statement, not continued deployment or automatic pooling; operational 95/95 for the current build is blocked.

## Required preregistration and evidence files

```text
release/<releaseId>/
  release-claim.json
  release-lock.json
  sampling-randomization.json
  analysis-plan.json
  quality-protocol.json
  enrollment-ledger.jsonl
  pair-ledger.jsonl
  ratings-and-adjudication.jsonl
  drift-and-deviation-ledger.jsonl
  units/<unitId>/
    evidence-manifest.json
    attempts/<attemptId>/trace.jsonl
    attempts/<attemptId>/trace-manifest.json
  release-analysis.json
  release-decision.json
```

For a paired study, each `armUnitId[a,i]` is a `unitId`; `pair-ledger.jsonl` links `{pairId, baselineUnitId, treatmentUnitId, order, block}`. The confirmatory enrollment controller durably appends each unit and `t0[a,i]` **before** controller submission, so typed validation/conflict/capacity/controller faults, queue wait, retry, restart, fallback, clone replacement, or cancel remains in the same unit and clock even when no attempt was created. Every code/prompt/policy/model/router/QC behavior change creates a new release ID. An “observation-only” change may bridge evidence only when the timed execution binary/path is byte-identical, or when a preregistered equivalence test proves its added I/O/CPU/storage cannot change latency, failure, or scheduling within the frozen margin; schema intent alone is not proof.

Dry-run the frozen analysis against golden simulated pass, failure, fallback, cancellation, missing-rating, missing-telemetry, correlation/block, and drift fixtures before enrolling one confirmatory unit. The final decision is exactly `PASS`, `FAIL`, or `INSUFFICIENT_EVIDENCE`.

## Current go/no-go

**Go now:** preserve historical G2 and the explicitly nonqualifying G2b parent
preflight. Compose the existing render artifact, ordered admission, receipt,
history, sealer, and fence primitives behind a feature-disabled headless
controller; add the trusted runtime/writer-quiescence and capacity layer; and
falsify the combined crash protocol without a publisher. Freshly requalify
current OCI source before R0. Continue the prospective request census and
collection of distinct organic projects. Do not repeat unsupported Codex
telemetry branches without a changed provider surface.

**Go after full G1:** coherent R0 seed and old/reuse/fresh-A/fresh-B mechanism study.

**Go after G4:** coherent audio and cut fixtures, then integrated disposable orchestration.

**Go after G8 only:** production-enable stable lineage, the dedicated
attempt/status protocol, generation resolver/paths/inputs, neutral kernels,
integrated trusted sealing and fence checks, the flock publisher, cold
initialization, pointer/terminal recovery, the fault campaign, and an internal
controller canary.

**External/general release only after G11:** `release-decision.json == PASS`; no pilot, fault campaign, or architecture review substitutes for confirmatory evidence.

**No-go now:** production fast-path publication, compatibility projections, live Palmier mutation, broad semantic 95/95 claims, and any inference that the current two-source retained corpus or 59 rapid replays establishes field reliability.
