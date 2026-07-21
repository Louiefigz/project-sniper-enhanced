# Headless MP4 empirical gate ledger

**Status:** active evidence record

**Scope:** Claude Code/Codex to deterministic MP4; no GUI and no Palmier-native execution

**Started:** 2026-07-18

This ledger records executed evidence for the stop-gate ladder in
[`HEADLESS_MP4_95_CONFIDENCE_EXECUTION_PLAN.md`](HEADLESS_MP4_95_CONFIDENCE_EXECUTION_PLAN.md).
The plan defines what would count; this file records what actually happened. A
design review, retained output, or passing legacy test does not advance a gate.

## Current gate state

| Gate | State | Executed evidence | Next admissible action |
|---|---|---|---|
| G0 — provider capability | CLAUDE PASS / CODEX BLOCKED | Tools-disabled live calls completed. Claude exposed requested/startup/resolved model signals, all four token counters, per-model attribution, and provider-reported estimated cost. Codex exposed input/cached-input/output/reasoning-output only; no cache-create, cost, or success-event resolved build. | Continue only the Claude cache branch. Stop Codex cache-create, cost, and prospective frozen-build claims unless its surface changes and a new probe passes. |
| G1 — durable evidence | INTEGRATED TRACE PRIMITIVE PASS / GATE BLOCKED | A non-GUI composition root integrates admission/idempotency, authority record, framed trace, OS boot identity, exact terminal intent, and terminal-manifest startup recovery. Later isolated suites cover prospective enrollment/order replay, fresh-inode generation sealing, and a standalone active fence, but those primitives are not one worker lifecycle. | Compose exact request/admission, trusted runtime and writer quiescence, resource startup replay, final fence checks, sealing, pointer publication, and terminal recovery; then pass startup, cancel, pointer, process-death, daemon-restart, and reboot recovery before G3. |
| G2 — offline overlay | HISTORICAL FROZEN PASS / CURRENT SOURCE UNQUALIFIED | Independent attempt 008 qualified its exact frozen successful-render source closure. Current renderer/policy/proof sources have changed, so the pass is preserved as historical mechanism evidence only. | Rerun the current frozen closure independently. Do not generalize the historical pass to cancellation, conditional lanes, Palmier, or integrated release. |
| G2b — explicit headless renderer root | LOCAL CONTRACT PASS / RETAINED RESULT NONQUALIFYING | The current wrapper adds a render-specific pre-admission request/build/source artifact, admission-derived launch, strict parent proof validation, sealed asset bindings, local process-group ownership, and a parent-owned durable Docker resource name. The retained specimen still says `qualifying:false`, its frozen closure is stale, and the newer receipt/sealer/fence paths were not part of that run. | Integrate trusted creator/startup replay, runtime quiescence, receipt and sealer handoff; then run a fresh independent current-source qualification. |
| G3–G6 | BLOCKED | Their declared prerequisites have not passed. | Do not start until the ladder permits it. |
| G7 — development corpus | BLOCKED | Repository inventory proves five retained artifact trees collapse to two source families; there is no repository-verifiable first-organic-feedback admission record for either family. | Prospectively collect six distinct original source/project/first-feedback clusters. |
| G8 — complete disposable pilot | BLOCKED | No qualifying complete paired pilot exists. | Do not enroll a pilot until the mechanism and authority prerequisites pass. |
| G9 — authority seam | IMPLEMENTATION PRIMITIVES / GATE BLOCKED | Full selected-genesis payload reobservation, recursive selected-history authentication, prospective unit enrollment, PREPARED-before-admission cross-ledger ordering, V3 admission, exact one-graphic R0 receipt persistence, fresh-inode sealing, and standalone fence bootstrap/reserve/cancel now exist. They are disjoint, non-authorizing paths. | Continue only non-authorizing composition: trusted runtime/writer quiescence, capacity reservation, final fence recheck, semantic child verification, and terminal recovery. Do not add a publisher/`CURRENT` path before its prerequisite gate. |
| G10–G11 | BLOCKED | No qualifying complete pilot or confirmatory cohort exists. | Do not implement external enablement or make a 95/95 claim. |

Gate states in this ledger are `NOT_RUN`, `RUNNING`, `PASS`, `FAIL`, or
`BLOCKED`; provider-specific gates name each provider's state. `PASS` requires
the exact proof defined by the execution plan. A partial success remains
`RUNNING` or `BLOCKED`; it is never rounded up.

## G0 live provider capability result

Both probes ran in `/private/tmp` with tools, MCP, hooks/rules/apps, browser
integration, and session persistence disabled. The fixed prompt contained no
project or user data. Raw events were normalized in memory; the ledger retains
no prompt, response text, session ID, UUID, credential, environment, or stderr.

### Claude Code 2.1.211 — PASS for telemetry capability

- Requested alias: `opus`; startup model: `claude-opus-4-8`.
- `modelUsage` attributed work to both `claude-opus-4-8` and auxiliary
  `claude-haiku-4-5-20251001`. A requested alias is therefore not a one-model
  cost/latency unit.
- Opus counters: 2 noncached input, 2,084 cache-create, 0 cache-read, and 52
  output tokens.
- Auxiliary Haiku counters: 527 noncached input, 0 cache-create, 0 cache-read,
  and 12 output tokens.
- Provider-reported estimated total cost: `$0.022737` (`$0.022150` Opus plus
  `$0.000587` Haiku). This is not a billing attestation.
- The result also exposed per-model context/output limits and the CLI startup
  version. It did not separately attest an immutable provider build.

Claude passes only the **capability** probe. Every measured call must still
reassert its resolved-model set and event shape.

### Codex CLI 0.144.1 — BLOCKED for the full G0 contract

- Requested alias: `gpt-5.6-sol`.
- The configured `ultra` reasoning value failed before inference with HTTP 400;
  the error identified `gpt-5.6-sol-1p-codexswic-ev3` and allowed only
  `none|low|medium|high|xhigh`. The Sniper default is now `xhigh` and has a local
  regression check.
- A tools-disabled `none` probe completed with 8,164 input, 0 cached-input, 9
  output, and 0 reasoning-output tokens. The corrected production `xhigh` tuple
  then independently completed with 7,956 input, 0 cached-input, 9 output, and
  0 reasoning-output tokens.
- The successful terminal event had only `type` and `usage`; it exposed no
  cache-creation counter, reported cost, resolved model, or remote build.

This is a useful falsification result. Codex can support the narrower direct
claim “this call reported cached input” when that counter is positive. It cannot
support the universal cache-create branch, cost ceiling, or prospective
frozen-build qualification on this CLI event surface.

## G1 durable-evidence primitive result

The standard-library-only proof lives in `scripts/producer/headless/`. It now
contains five connected pre-production layers:

1. an immutable admission/idempotency denominator registry under one
   never-unlinked flock;
2. an attempt-owned `trace.jsonl` with a never-unlinked `.trace.lock`;
3. Linux/Darwin OS boot-identity derivation; and
4. an exact canonical terminal intent retained before the terminal trace frame;
   and
5. an immutable terminal manifest plus composition root that recovers those
   boundaries without guessing worker liveness.

Each bounded canonical trace frame carries sequence, predecessor digest, event
digest, payload byte length, CRC32, repeated attempt identity, wall time, boot
ID, and monotonic nanoseconds. Appends use locked tail-read/validate/write,
`fdatasync` (or `fsync` fallback), and directory `fsync`. The closed lifecycle
requires first `ADMITTED`, orders `WORKER_START → VERIFIED → PUBLISH_INTENT →
POINTER_COMMITTED`, and permits `SUCCEEDED` only after the pointer event.

Executed results:

- 57/57 focused G1 composition-root tests pass.
- The combined focused headless/render suite passes 178 tests with one
  environment-only host-loopback positive-control skip and `ResourceWarning`
  promoted to an error.
- Eight concurrent admission processes produced exactly one immutable record
  and replayed its original attempt. Changed request/unit identity and attempt-ID
  reuse fail; an admission-record-before-attempt-directory crash is healed on
  replay without removing the denominator.
- Restrictive umask, symlink, hardlink, nonregular, unsafe-owner/mode, malformed
  record, duplicate-tail, and common credential-like content cases fail closed.
- A child killed after its durable `ADMITTED` append left one valid unsealed
  frame. A child killed after a partial physical append left only a typed,
  recoverable final fragment. Sixteen simultaneous writers form one chain.
- Cross-boot work requires `RECOVERY_RESUMED` or `TERMINAL_SEALED`; same-boot
  monotonic rollback and boot-ID recurrence fail. Terminal disposition is one of
  `BLOCKED/CANCELED/FAILED/STALE/SUCCEEDED` and is absorbing.
- Reproduced crash windows showed both that disposition-only terminal events did
  not bind result content and that a digest could not recover bytes never stored.
  Exact canonical result bytes are now flushed before their terminal digest;
  changed bytes/trace fail, and durable intent repairs its own torn terminal frame
  before generic torn-tail classification.
- A local 100-append benchmark remains about 20.3 ms per fully synced event.

This proves an integrated durability primitive, not full G1. The new composition
root supplies boot identity, admission, trace, and terminal recovery, but no
production CLI or worker supervisor calls it. The renderer separately owns a
local process group and durable Docker resource ledger, yet controller startup
does not call that ledger after parent `SIGKILL`, daemon restart, or reboot.
A render-specific exact request/build/source artifact and admission facade now
exist, as do a standalone active-fence journal and a fresh-inode generation
sealer. They use different composition roots and do not create a production
worker lifecycle. There is still no trusted worker quiescence proof, integrated
final fence recheck, `CURRENT` publisher, pointer-before-terminal recovery, or
resource-vector capacity admission. A same-UID process can also ignore advisory
lock conventions. Full G1 remains blocked.

## G2 exact-adapter result

Independent qualifying attempt 008 passed the exact clean-success container
adapter with no production-source change during the run. Its sealed evidence is
[`attempt-008-independent-qualifying/evidence-manifest.json`](../../artifacts/headless-gates/g2-offline-overlay-20260718/attempt-008-independent-qualifying/evidence-manifest.json),
SHA-256
`20c01b8a5e34ec51f27b8ed32de98cc1665ffbf344b6abeba2a9c385b729e13e`.

- Exact image:
  `sha256:bc56d3860d2ec1c843f7184bcecd21137aa79fe9fe19c90a67136d3052222ba8`.
- Cold render: 11.639 seconds; warm cache reproof: 0.528 seconds; stable key
  `a777523c0555a5edb6171bc7c5329e4bf88f9f23`.
- MOV SHA-256
  `dfb5da3f91a31504b9af14f258a18a4a140660f2a9cd74c697b87550db8aa12e`,
  18,780,757 bytes. The sole stream is 1080x1920 ProRes 4444
  `yuva444p12le`, 2.5 seconds, 75 frames at 30 fps.
- Retained sealed-input tar SHA-256
  `2d6e7ea6bfaa531ff0b798cc9356e586245e382bea87bd3984d4561f73a12459`,
  1,269,760 bytes with the exact eight-member allowlist.
- Fail-on-error full decode, frame occupancy, requested `#054BC9` pixel/color
  proof, copy binding, and terminal frame-74 alpha zero all passed.
- The same container proved its own loopback positive control and host decoy
  positive control while host loopback, external IPv4/IPv6, and DNS were denied.
- Pre/post runtime inspection bound Docker 29.2.1, containerd 2.2.1, runc 1.3.4,
  the LinuxKit kernel, and the approved image/config/rootfs closure. Exact
  container ID/name absence plus an empty identifying-label set passed after
  removal.
- Fourteen local evidence files, two retained harness dependencies, and every
  frozen production source hash were revalidated after the run.

Attempt 007 remains retained and nonqualifying because its independent harness
incorrectly hard-coded an obsolete preflight cache key. Its positive production
observations were not recycled into the pass; attempt 008 used a new empty
attempt and required only a stable valid cold/warm key bound to frozen sources.

This is deliberately a **historical G2 successful-mechanism pass for its frozen
source closure only**. It does not prove
late or ambiguous Docker creation cleanup, cancellation, controller
`SIGKILL`/reboot recovery, hostile same-UID Docker mutation, conditional runtime
capabilities, or any Palmier machine-interface behavior. The current ambient
`SNIPER_RENDER_IMAGE_ID` selection and shared-cache fallback must be replaced by
an explicitly injected headless renderer strategy and attempt-owned cache before
integrated release. Process-global daemon identity memoization also requires a
job scope/reset and terminal re-attestation before it can support a long-lived
worker. Current source differs from the static manifest and must qualify again.

## G2b explicit-renderer-root preflight

This is an implementation-isolation subgate, not a promotion of G3. The first
parent preflight remains retained and nonqualifying because two counterexamples
falsified it: a symlink result inside the cache was accepted after `realpath`,
and a restrictive umask could create an unreadable first-use owner receipt.

The retained preflight's corrected-at-that-time frozen sources were:

- `render_lane.py`
  `cd0cc18ccddb016aaabf2c1ab39c0c7fc34de7ef9546214b90197826a3b6a683`;
- `render_lane_cache.py`
  `64be94bc3938f2ead8a86f810099e58e23066e092dcfc65aade76f5bd99fb75e`;
- `render_worker.py`
  `33ef98f62e929ac72e071af283849b22ada1e85fdd419e3069e76db8c6eae43c`.

The corrected parent evidence is
[`attempt-002-parent-preflight/preflight-result.json`](../../artifacts/headless-gates/g2b-render-lane-20260718/attempt-002-parent-preflight/preflight-result.json)
and is explicitly `qualifying:false`.

- Attempt A cold miss: 13.181 seconds; warm hit: 0.666 seconds.
- Independent attempt directory B cold miss: 11.902 seconds.
- All three results matched MOV SHA-256
  `dfb5da3f91a31504b9af14f258a18a4a140660f2a9cd74c697b87550db8aa12e`
  and input-tar SHA-256
  `2d6e7ea6bfaa531ff0b798cc9356e586245e382bea87bd3984d4561f73a12459`.
- Exact mode, stable cache key, attempt-specific owner receipts, output
  device/inode/hash/size, parent ambient-variable poisoning, and pre/post
  container absence all passed.

No independent reviewer result completed, so the parent preflight was not
rounded up. It also has no non-test call site. Current code now owns the local
process group, strict result proof, sealed asset bindings, and a durable
parent-allocated Docker name. It also has a render-specific pre-admission
request/build/source artifact, admission-derived locator, and an attempt-owned
one-graphic receipt store. Those newer bytes and the standalone generation
sealer/fence were not in the retained manifest. Controller startup resource
replay, creator impossibility, writer quiescence, integrated sealer handoff,
conditional-capability matrix, and a new independent run remain mandatory. G2b
remains blocked.

## G7 retained-corpus inventory

Inventory timestamp: 2026-07-18 in the repository worktree. The source SHA-256
values below were computed from the referenced original media, not from rendered
variants. Transcript hashes independently confirm that the four C0679 trees are
copies of one source family.

| Potential cluster | Retained trees | Source duration | Source SHA-256 | Transcript SHA-256 | Gate disposition |
|---|---:|---:|---|---|---|
| C0679 intro | 4 | 60.061 s | `45f2e8020f19d05c9ce5074bbcabdc127fd8c8adedc565ae19be9e89eee714de` | `d6232c2d94ab5bd8b7b9b808744d733f2ef2878e1068a6296d514c698fb5625c` in all four trees | At most one source/project cluster; no repo-verifiable prospective first-feedback record. |
| Social vertical | 1 | 99.867 s | `f55ba9e6d7528d861db14368027de7d5ca15b08a3d762be7fe15a21a696248f0` | `965bb82644682e2baf2a08818b33c3009af0ae2e509ec9ce6c5c64edcf22b5aa` | A second source family, but not by itself a qualifying 45–60-second cluster and no repo-verifiable prospective first-feedback record. |

The honest G7 result is therefore **two retained source families, zero of six
fully evidenced prospective clusters**. Variants, retries, model samples,
Palmier copies, and repeated feedback on C0679 remain nested technical evidence.

Every future census row must be recorded before outcome inspection and contain
only secret-free metadata: `unitId`, admission time, source SHA-256, immutable
project lineage ID, target duration/scope, first-feedback digest and fixed class,
inclusion disposition, and exclusion reason if any. The raw feedback text does
not belong in this ledger.

## Evidence chronology

### 2026-07-18 — empirical phase opened

- Froze paper review at round nine and started G0, G1, G2, and G7 in parallel.
- Confirmed the project still invokes mutable `npx --yes hyperframes@0.7.33`
  and `section-marker.html` still loads GSAP core from jsDelivr; those are facts
  to close, not an assumed G2 failure result.
- Confirmed the current TypeScript auto-edit log uses append-only writes and is
  not a G1 trace.
- Recomputed the G7 source and transcript hashes above. No retained variant was
  promoted to an independent project.

### 2026-07-18 — first renderer closure was falsified

- Vendored GSAP 3.14.2 for `section-marker`, pinned HyperFrames 0.7.33 with an
  integrity lock, and moved the production wrapper from `npx`/PATH discovery to
  explicit Node, CLI-module, browser, ffmpeg, and ffprobe paths.
- A 2.5-second direct render produced 75 fully decodable 1080x1920 ProRes 4444
  frames with retained alpha and the requested color. The first oracle exposed
  a surviving full-frame scrim; the second exposed timeline end-point sampling.
  Fading the whole stage through `(N - 1) / fps` reduced final-frame alpha to 0.
- The retained attempt-004 overall evidence remains `FAIL`: its static cache
  regression check was brittle, and the direct command was not the exact
  production adapter. Passing selected pixel checks was not rounded up.
- Source inspection and a narrow Seatbelt experiment proved the remaining G2
  blocker: HyperFrames 0.7.33 hard-codes a random file-server port and Puppeteer
  uses a second random CDP port. Allowing all localhost reaches ambient services;
  allowing exact ports cannot launch the stock adapter. G2 therefore stopped.

### 2026-07-18 — exact container adapter independently qualified

- Replaced the host-Seatbelt assumption with an immutable OCI adapter using
  `--network none`, read-only root, nonroot execution, dropped capabilities,
  bounded tmpfs, sealed read-only inputs, and attempt-owned writable roots.
- Nonqualifying attempt 007 exposed a stale expected-cache-key oracle in the
  independent harness and remained rejected. No production result was promoted
  from that attempt.
- Fresh attempt 008 independently passed the exact frozen clean-success adapter,
  cold/warm cache proof, media and visual oracles, active network-denial controls,
  runtime identity, container removal, evidence sealing, and post-run source
  verification. G2 moved to `PASS` with the limitations recorded above.

### 2026-07-18 — G1 admission and terminal primitives extended

- Added immutable idempotency/denominator admissions, crash-window healing,
  trusted Linux/Darwin boot identity, and terminal manifests.
- Closed terminal vocabulary and lifecycle so success requires a prior
  pointer-committed event.
- Falsified disposition-only terminal sealing, then bound the exact result digest
  before the terminal append and made replay revalidate the trace.
- Focused G1 reached 39/39 passing tests. Full G1 stayed blocked because none of
  the primitives has a controller call site or integrated recovery campaign.

### 2026-07-18 — explicit headless renderer root preflighted

- Added the isolated `sealed-oci-v2` launcher with a literal child environment
  and attempt-owned cache; legacy/Palmier callers were not changed.
- Rejected the first parent preflight after symlink-output and restrictive-umask
  counterexamples.
- The corrected parent rerun reproduced exact G2 media cold/warm/cold across two
  attempts and retained `qualifying:false` pending independent qualification and
  supervisor/sealer integration.
- Cancellation analysis kept R0 blocked: delayed Docker create, process-group
  ownership, verifier deadlines, `SIGKILL`, daemon restart, and reboot remain
  unproved.

### 2026-07-18 — durability composition and strict proof adversarial rounds

- Integrated admission, authority, trace, boot identity, exact terminal intent,
  and terminal-manifest recovery through one non-GUI composition root. Focused
  G1 reached 57 passing tests.
- Rejected terminal-recovery misordering, impossible occupancy, worker-selected
  keys, unapproved/empty runtime evidence, live-asset rereads after sealing, and
  same-inode overwrite after media hashing.
- Added local process-group ownership and fixed a host-socket cleanup leak. The
  retained proof remained validator-compatible but did not become qualifying.

### 2026-07-18 — lifecycle and Docker resource adversarial round

- Reproduced and fixed a zero-exit command leaving a descendant and a promotion
  source descriptor leaking when destination-directory open failed.
- The parent now durably registers the exact Docker name before spawn, passes it
  in the closed environment, requires the runtime proof label, proves absence
  before removal state, and exposes startup reconciliation.
- The focused headless/render suite reached 178 passing tests. Current-source OCI
  qualification, controller startup wiring, request sealing, generation sealing,
  publisher/fence, and field cohorts remain absent.

### 2026-07-19 — pre-release generation-authority implementation

- Added an exact 42-row R0 generation profile, fail-closed `CURRENT` reader,
  byte-bound private materialization store, approved-parent authority card, and
  acyclic generation-verification record. This is implementation evidence, not
  a coherent G3 seed.
- The disk-backed parent loader now enforces exact policy documents, base/media
  and prebound-clip bindings, cover/QC/two-critic/final-approval semantics, plus
  full-decode/effect/Audit-B receipt schemas and cross-record bindings. Its
  quality-evidence result is explicitly
  `SEALED_CLAIMS_BOUND_NOT_RUNTIME_REOBSERVED`; it cannot authorize execution.
- Added a selected-`CURRENT` ancestry resolver that holds the publisher flock,
  walks strictly to genesis, fully hashes every traversed R0 closure, and
  materializes only an exact requested ancestor. Fourteen focused adversarial
  tests pass. Its proof scope is deliberately
  `selected-current-ancestry-only`; V1 has no append-only ledger proving global
  fork uniqueness.
- Added disjoint canonical `initialize` and `quality-pass` operation contracts.
  The current execution policy binds quality passes but explicitly blocks
  initialization because it lacks an operation discriminator, initial-base
  build disposition, and presealed-snapshot authority.
- Structural quality-pass assembly validation now rejects genesis and reports
  `STRUCTURAL_CURRENT_CARD_BOUND_NOT_RUNTIME_VERIFIED`. Historical continuity,
  executable/runtime authority, media/audio/alpha re-observation, retained YDIF,
  and graphic build semantics remain required.
- Adversarial review exposed a schema-level stop: the fixed R0 profile has no
  initialization-origin receipt or initialization snapshot/operation artifact,
  while still requiring a quality-pass assembly receipt. Initialization needs a
  versioned profile and authority card; it will not be smuggled through R0.
- Focused loader/schema/policy/evidence tests reached 116 passing tests with 209
  subtests; historical resolution passed 14 tests; real compositor and related
  generation/loader checks passed 28 tests with 23 subtests. These results do
  not advance G3, G8, G9, or the 95/95 release claim.

### 2026-07-19 — versioned authority and admitted-composition checkpoint

- Added a disjoint genesis R1 profile, initialization policy/origin/card
  authority, AssemblyReceiptV2 parent discriminant, and first-child bridge. The
  bridge authenticates `initialization-origin-receipt-v1` separately from prior
  assembly V1/V2 and proves only the immediate base edge; recursive ancestry,
  runtime, execution, and publication remain false.
- Added a pre-walk tagged disk reader/loader for genesis R1, quality-pass V2/R1,
  and non-null-parent frozen R0. Null-parent R0, wrong publication edges,
  class/version mismatch, stale/symlinked bytes, hostile tag construction, and
  post-materialization mutation fail closed. Loader results expose no absolute
  path, store, or lease and never authorize execution.
- Added durable V3 operation admission with exact canonical admission and
  operation bytes, idempotency/attempt/intended-child set invariants, atomic
  directory publication, shared V2/V3 authority initialization locking, orphan
  refusal, and strict UTF-8/NFC filesystem-path bounds. Six concurrent exact
  submissions produce one record and five replays.
- Added admitted quality-pass composition inspection. It closes exactly
  `OPERATION_DURABLE_ADMISSION_AND_CHILD_BINDING`; unit enrollment, recursive
  genesis/assembly ancestry, operation runtime and child seal, active fence,
  terminal seal, and publication remain explicit blockers. Downstream
  inspection failure does not erase the already durable admission.
- Added static runtime/build binding, exact ffmpeg/ffprobe endpoint inode/byte
  reobservation, and canonical render-build receipt semantics frozen from live
  writer evolution. Compositor-receipt semantics, graphic-render receipt
  binding, source/tool byte reobservation, dynamic closure, and execution
  attestation remain blocked.
- Adversarial rounds fixed retained-set replay duplication, filesystem pending
  poison, cross-protocol authority races, hostile equality, unsafe whitelisted
  lock inodes, historical build-schema drift, and an R0-only store-validation
  bypass. The consolidated structural suite passed 347 tests and 535 subtests;
  focused render/build regression passed 54 tests and 64 subtests. This is
  implementation evidence only and does not advance G3, G8, G9, or the 95/95
  release claim.

### 2026-07-19 — round 15 durability and non-authorizing authority seams

- Added complete selected-genesis R1 payload reobservation, recursive
  R0/R1/V2 selected-history authentication, and a fresh-inode generation
  sealer. The sealer copies an exact bounded staging manifest into new inodes,
  writes `commit.json` last, installs without replacement, and recovers only
  identified safe pending state. It neither proves writer quiescence nor reads
  or writes `CURRENT`.
- Added prospective unit enrollment plus a shared outer cross-ledger
  transaction. Durable PREPARED intent precedes V3 admission; exact enrollment,
  admission, and COMMITTED receipt are reobserved before success. Unsafe,
  conflicting, oversized, non-prefix, or identity-ambiguous pending state fails
  closed.
- Hardened operation, enrollment, and cross-ledger replay after injected sync
  failures. A rename or journal append that became visible before a reported
  `fsync` failure is not assumed durable; replay pins the named inode,
  re-flushes the request-relevant record and directories, then reparses exact
  bytes. A second adversarial pass now retains those file/record/store pins
  through the final named reload and returns the pinned observation, rejecting
  same-byte replacement. Targeted cross-ledger barriers avoid re-syncing every
  unrelated row.
- Bound the real admitted render lane to controller-derived R0 graphic receipt
  expectations and an attempt-owned atomic receipt-set manifest. Replay and
  explicit load reobserve retained receipt bytes and cache media; cross-attempt
  copying, post-render media mutation, same-byte inode replacement, and unsafe
  pending residue reject. The current profile permits exactly one graphic.
- Added a standalone active-fence journal and materialized `FENCE` projection
  under the never-unlinked publisher mutex. `BOOTSTRAP`, `RESERVE`, and
  `CANCEL` survive final-tail recovery and exact replay. There is intentionally
  no `RELEASE`, worker launch, V3-admission integration, publication check, or
  `CURRENT` mutation.
- Hardened fence mutation against forged scan summaries, hostile nested
  equality, and over-cap appends. Hardened pending cleanup by validating exact
  semantic bytes on the held inode, rechecking the named identity immediately
  before unlink, and proving the held inode became unlinked. Portable POSIX
  still does not provide hostile same-user atomic compare-and-unlink; this
  remains a cooperative-lock/private-filesystem contract.
- Removed descendant-sensitive directory link count from runtime executable
  path identity after reproducing false tamper failures under unrelated APFS
  temporary-directory churn. Directory pins still bind device, inode, mode,
  owner, and group; executable leaves retain link-count, size, timestamp,
  inode, and digest checks. Ten repeated focused stress runs passed.
- Final independent reruns were separated by concern and overlap, so their
  counts must not be summed: ordered admission/enrollment/cross-ledger/
  composition passed 161 tests plus 104 subtests; render/lane/graphic-receipt/
  build-closure passed 114 plus 100; generation/sealer/history passed 97 plus
  56; active-fence plus the headless import boundary passed 36 plus 12. Focused
  handoffs separately reported cross-ledger recovery at 51 plus 17 and graphic
  controller/store at 20 plus 6; those are subsets, not additional evidence
  units.
- No gate advanced. No run above exercised one operation from prospective
  enrollment through trusted worker execution, child sealing, final fence
  recheck, `CURRENT` publication, terminal recovery, and MP4 qualification.

## Release boundary

No entry in this ledger authorizes external/general enablement. That boundary
remains exactly `release-decision.json == PASS` at G11.
