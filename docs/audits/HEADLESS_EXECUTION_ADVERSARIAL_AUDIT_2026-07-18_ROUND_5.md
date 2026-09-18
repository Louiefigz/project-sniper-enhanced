# Headless execution adversarial audit — 2026-07-18, round 5

> **STATUS: FROZEN AUDIT SNAPSHOT.** This records the fifth adversarial wave and its cross-examination. Corrections belong in the living [headless optimization dossier](../producer/HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md), not by rewriting this record.

## Scope and method

Reviewed only headless Claude Code/Codex plan repair into deterministic MP4, approved-plan rendering to MP4, and the protocol boundary that would later permit Palmier. GUI work remained excluded.

Three independent attacks tried to disprove the round-four plan:

1. A dependency and quality attack on the proposed MP4 scoped-repair boundary.
2. A minimum-sequence attack asking whether the plan was building new infrastructure before using working code.
3. A protocol-feasibility attack on lock handoff, descendant quiescence, `CURRENT`, durability, frozen inputs, and remote Palmier fencing.

The agents were then cross-examined from the opposite position: assume a small repair experiment must ship, find its narrowest defensible class, and identify what can safely wait. No production code or tests changed. This round inspected code, ran small fingerprint diagnostics, and changed documentation only.

## Round-five verdict

The direction survives only after changing the thing being optimized. **The near-term hypothesis is no longer “build dependency-scoped rendering.” It is “prove a bounded end-to-end quality-pass lane using the existing governed surgical editor and incremental assembler.”**

The renderer already has graphics and audio fast paths. On the retained 108-second specimen, graphics-only assembly was 19.9 seconds and audio-only was 11.7 seconds versus roughly 190 and 158 seconds respectively. Even eliminating a 190-second render from a 60-minute pass saves only 2.83 minutes, or 4.7%. The hour is dominated by revision authoring, whole-plan review, and rendered critics—not MP4 compositing.

The existing fast paths are also not yet a safe dependency graph. They contain both under-invalidation and over-invalidation, do not bind the complete source/runtime/output authority, can retain a stale cover image, and have known graphics/caption/recompose cross-lane dependencies. They are suitable as a research mechanism inside a frozen disposable clone, not as production reuse authority.

The fastest trustworthy next move is therefore:

1. Measure frozen model/reasoning alternatives offline because LLM stages dominate wall time.
2. Separate renderer reuse, review topology, and model/effort into three controlled experiments so one cannot manufacture another's speedup.
3. Use the existing governed [`ai-edit`](../../src/app/api/producer/ai-edit/route.ts) → [`assemble`](../../src/app/api/producer/assemble/route.ts) path for the later disposable user-path experiment.
4. Add only the experiment seams needed to force deterministic MP4, compute a controller-owned canonical diff, bind the reused base/runtime/output, regenerate derived artifacts, and report an audit-complete terminal receipt.
5. Run the proposed selective review policy in shadow against the current full planning/rendered-review wall. Do not promote selective review until it proves noninferior defect recall.
6. Build production authority, migration, and atomic generations only after the speed hypothesis survives.

Live Palmier mutation remains temporary no-go. Nothing in this round improves its evidence or remote recovery contract.

## Decisions overturned or narrowed

### Renderer scoping is already implemented and is not the primary hour-long lever

[`fingerprints.py`](../../scripts/producer/fingerprints.py) splits base, video, audio, and graphics fingerprints. [`assemble.py`](../../scripts/producer/assemble.py) dispatches current-base reuse, an audio-only rebuild, or a full graphics-free base rebuild. Individual graphics are content cached. These are working mechanisms, not an unimplemented architecture hypothesis.

The current quality loop explains the repeated hour. After a QC writer changes the plan, [`quality-loop.ts`](../../src/app/api/producer/auto-edit/quality-loop.ts) invalidates the job back to `plan_authored` and explicitly reruns every planning review and gate. The planning packet binds the entire plan, manifest, authority, gate verdict, timeline, and transcript evidence in [`plan-review-packet.ts`](../../src/app/api/producer/auto-edit/plan-review-packet.ts). A new candidate then receives fresh Audit B and both full rendered lenses.

The primary product hypothesis must cover three costs:

- bounded plan revision;
- proof that untouched editorial/render lanes remain untouched;
- affected-evidence review plus every global safety gate that can still fail.

Calling only the last rendering step “scoped repair” hides most of the actual pass.

There is nevertheless a smaller path worth reusing. The `ai-edit` finalizer normalizes a private candidate, rejects top-level fields outside the controller-inferred lane, runs the deterministic governance wall and one fresh surgical critic, and promotes only on pass. The assemble route checks the surgical marker, lints, runs incremental assembly, and then Audit B. It does **not** equal Auto Edit's two full planning critics plus two rendered critics, and its `outputs` event precedes Audit B. It is a research harness, not an approval shortcut.

### Same-input critic receipts are tail-reliability work, not ordinary revision speed

Planning critics run concurrently with `Promise.allSettled`; rendered lenses run concurrently with `Promise.all`. Retaining one successful critic while retrying its failed sibling prevents wasted tokens and protects against transient batch failure. It does not reduce normal wall time when the plan or candidate changes, and it may save zero wall seconds when the retried critic remains the batch critical path.

Every normal revision changes the whole planning packet root. Every candidate-byte change changes rendered evidence, including the candidate hash, assembly proof, Audit B report, and frames in [`review-evidence.ts`](../../src/app/api/producer/auto-edit/review-evidence.ts). Per-critic receipts remain worthwhile for restart and transient-failure recovery, but they are removed from the claimed 35% normal-pass mechanism.

### The current fingerprints are neither approval authority nor a semantic dependency DAG

The same hash family is being asked to answer incompatible questions:

- Did editorial approval evidence change?
- Did delivered pixels/audio change?
- Which renderer stages need to run?

Small diagnostics disproved that equivalence:

- Changing only `punchIns[].rationale` changes the base and plan-content hashes even though the punch renderer strips rationale. This needlessly rebuilds.
- Changing graphics addressing/decision metadata can leave the render-content hash unchanged while whole-plan review authority changes.
- `base_fingerprint` excludes all `graphicsTrack`, although long-form rail graphics can cause [`recompose_stage`](../../scripts/producer/render.py) to modify punch/recompose windows.

The correction is to keep separate editorial-approval roots and compile explicit stage input projections. A generic plan hash does not infer dependency closure. The reusable lesson and diagnostic are preserved in [EDITORIAL_HASHES_ARE_NOT_RENDER_DAGS.md](../../scripts/producer/docs/findings/EDITORIAL_HASHES_ARE_NOT_RENDER_DAGS.md).

## Concrete scoped-repair counterexamples

### Incremental graphics can retain a stale thumbnail

The graphics-free base creates `cover.png` during master. Incremental [`assemble.py`](../../scripts/producer/assemble.py) copies that base cover forward but never regenerates it from the new final candidate. [`copyAuditInputs`](../../src/lib/server/auto-edit-quality-artifacts.ts) then copies the stale cover into QC. Audit B checks only dimensions and mean luma in [`audit_checks.py`](../../scripts/producer/audit/audit_checks.py); it does not prove that the cover equals the candidate's selected frame.

A hook-card repair can therefore produce the intended MP4 while publishing and approving a thumbnail from before the repair. Any incremental candidate must regenerate all derived artifacts from the exact final bytes or bind a deliberate unchanged-artifact proof.

### Graphics affect captions and base composition

The monolithic graphics stage consumes caption ASS and suppresses captions beneath an own-screen takeover. The graphics-free base path skips that stage and burns captions into the base. The later assembler creates a `GraphicsJob` without caption input/output, so the two paths are not generally equivalent.

A concrete long-form hole-comp makes the mismatch visible: a transparent presenter hole can expose captions already burned into the base, while the monolithic path would have suppressed them. Toggling `spec.presenterFrame` on a registered hole kind changed its render format from opaque MP4 to alpha MOV while both base and video fingerprints remained unchanged. Hole comps are currently prohibited for shorts, which narrows the immediate short-form exposure but does not repair the invalid generic dependency claim.

Long-form rails provide a second cross-lane case: `recompose_stage` reads `graphicsTrack` and mutates presenter framing, while the base fingerprint excludes `graphicsTrack`.

The initial experiment must be explicitly 9:16-short-only and fail closed on any graphic property that changes opacity, takeover behavior, format, placement, window, anchor, collision, caption interaction, or footage recomposition. It must not advertise generic graphics-only reuse.

### Graphics cache identity omits runtime dependencies

The graphics content key hashes the composition HTML, shared tokens, selected resolved assets, spec, and duration. Templates can also load local vendor scripts and CDN runtime behavior not included in that key. A cache hit can therefore be returned under different renderer bytes.

At minimum, an experimental reuse receipt binds the selected template and every loaded local runtime file, pinned package/browser/renderer identity, resolved remote assets or a prohibition on remote runtime dependencies, input hashes, output hash, size, and decoded media facts. Production shared-cache publication additionally needs per-key exclusion and atomic verified publish.

### Existing `--resume` is existence-based for most stages

Most render stages skip when `--resume` is present and an output path exists. Only punch and graphics use stage fingerprints, and their receipts store the expected fingerprint without binding the output hash/media facts. Missing input paths are silently omitted from `stage_fingerprint`. `assemble.py` does not pass `--resume` for a stale base rebuild anyway.

The plan must not elevate current resume files into trusted stage receipts. The first safe class uses the existing base only inside a frozen, single-process research clone with a new experiment-specific base receipt. A production compiler may later emit explicit per-stage input projections and complete output receipts.

## Revision locality is not controller-enforced today

The cut-stage writer has a protected-field check. General QC revision does not. It asks the model for the “smallest coherent revision,” then verifies only that render content changed before promotion. Prompt language is not a mutation boundary.

Selective review requires a controller-owned diff computed after normalization:

- canonical JSON-pointer changes, not only top-level fields;
- a stable row identity and exact before/after element binding;
- issue-code-to-lane and lane-to-allowed-pointer tables owned by code;
- exact unchanged hashes for every protected lane;
- fail-closed handling of normalization-induced changes;
- a render-effect class proving whether a field can alter format, geometry, captions, base footage, audio, or timing.

Anything outside a proved allowlist falls back to the current full replay. The model never declares its own scope.

## Measurement seams the current path lacks

Surgical Codex does not set a reasoning override and can inherit the global setting; the surgical Claude writer and critic do not explicitly set effort. Current process wrappers reduce several results to message, stderr, and elapsed time, dropping provider usage/cache data. The producer run registry is a bounded operational projection, not an append-only benchmark record, and successful state can disappear. The experiment therefore needs explicit stage settings and a separate monotonic trace; missing provider usage must be reported as missing rather than inferred from elapsed time.

## Smallest useful experiments

Do not bundle renderer reuse, review invalidation, and model effort into one six-project comparison. First isolate each causal lever; only survivors enter an end-to-end user-path trial.

### Study A — renderer mechanism discriminator, no LLM

This asks whether incremental execution itself is worth further work. It does not claim production approval parity.

1. Select disposable Palmier-free clones of six representative 45–60-second 9:16 projects. Reserve disk and run projects sequentially.
2. Freeze the exact source, manifest, transcripts, approved MP4 plan, canonical revised-plan bytes, toolchain, and cache condition.
3. Predeclare an eligible repair stratum and separate structural fallback strata. Do not impose one eligible and one fallback edit per project and then infer a 50% field eligibility rate.
4. Compare a forced full base rebuild with existing `assemble.py --auto-base` for the same graphics change, an audio-only change, and structural cut/caption/motion fallbacks.
5. Compute the normalized canonical diff. Permit the fast path only for the initial allowlist below; otherwise run the defined fallback.
6. Assemble into a unique candidate, regenerate candidate-derived evidence including cover, fully decode it, run Audit B, and emit a terminal receipt containing final hash, audit artifact hashes, route, timings, and eligibility decision. The existing `outputs` event is not the endpoint because it is emitted before Audit B.
7. Compare full-replay and reuse candidates with exact decoded hashes wherever identity is promised and a preregistered, calibrated lossless-equivalence policy where an encode boundary makes byte identity impossible. Any unexplained spatial, temporal, audio, or artifact difference fails.

Initial eligible class `R0` is deliberately microscopic:

- short-form 9:16 only;
- one existing `graphicsTrack` row selected by stable ID and fixed as `kind: "text-element"`, `anchor: "free-band"`, with explicit unchanged placement;
- only `/graphicsTrack/<stable-id>/spec/color` may change, from one gate-approved `#RRGGBB` brand token to another;
- exact unchanged text, font, weight, alignment, row count/order, ID, `outStart`, `outEnd`, anchor, placement, focus/takeover/exit behavior, format/alpha class, asset set, and every non-graphics lane;
- no caption, cut, title-card, B-roll, punch, transition, reframe, music, audio, target, canvas, source, manifest, runtime, or policy change;
- no hole, presenter-frame, rail/recompose, or unknown kind/spec field.

Always regenerate `cover.png` from the exact candidate. The strongest counterargument is that this class may be so narrow that it has little field value. That is intentional: first prove one safe dependency boundary, then measure actual feedback eligibility before widening it.

### Study B — review-topology discriminator

Start both arms from the same exact approved MP4 plan and inject the same canonical revised-plan bytes. The control reruns the current complete planning-review wall. The treatment runs deterministic scoped governance plus the proposed affected planning review. Both arms then use the same renderer policy, Audit B, complete decode, and both current rendered visual critics.

This isolates review invalidation from writer quality and renderer speed. Run treatment decisions as a shadow policy: the current complete wall remains the oracle and decides approval. Measure what the shadow policy would have missed on clean controls, seeded defects, cross-lane collisions, and natural repairs. A material defect missed by the shadow policy kills promotion. Only after blinded noninferiority and defect-recall gates pass may it replace full planning review for its exact repair class.

### Study C — model/effort discriminator

Replay frozen writer and critic packets across stage-specific Claude/Codex model and effort settings. Hold the packet, prompt, review topology, renderer, seeded defects, provider-comparison rules, and quality rubric fixed. Randomize or counterbalance order. This tests model settings without attributing their effect to renderer or review changes.

Only after Studies A–C survive should the existing governed `ai-edit` → `assemble` path run the complete vertical user-path comparison from identical initial plans and feedback. This separates a fast renderer from a fast, safe quality pass. A quick Audit B candidate is useful research evidence but is not Auto Edit-equivalent final approval.

### Endpoints and stop rules

Use three timers, reported separately:

1. feedback submission → governed revised plan;
2. approved revised plan → Audit-B-complete exact candidate;
3. feedback submission → current Auto Edit-equivalent final approval.

The primary product endpoint remains the third. The first two diagnose where time moved. “Full replay” must be named precisely: base rebuild, full plan/QC replay, or full re-author are not interchangeable controls.

With six projects, report all paired values, the median, and the maximum. Do not claim p95 or greater-than-95% reliability. Kill the candidate policy on any material quality miss, unexplained out-of-window change, stale derived artifact, invalid receipt/cache hit, or failure to beat the preregistered complete-pass target. The retained target remains a paired median at most 35% of the matching full quality replay, but it is a falsification threshold—not a forecast.

### Model/effort study comes before new renderer engineering

Revision and critic calls can each consume far more wall time than rendering. After basic telemetry, run Study C and treat provider/model and execution route as separate experimental factors. Surgical Codex currently inherits the global reasoning setting, and the surgical Claude writer/critic do not explicitly set effort; the experiment must record and pin those values rather than assume they are already capped.

No lower setting reaches production merely because it is faster. Promotion requires blinded noninferiority and seeded-defect recall. The earlier blanket “never test a downgrade” guardrail is retained as a production default, not as a prohibition on isolated measurement.

## Protocol corrections

### The offline experiment does not need JobV2

A single-process disposable clone with frozen copies, isolated cache/work directories, unique candidate paths, disk reservation, exact timings, full audit, and no promotion is sufficient to test the mechanism. V1/V2 migration, `CURRENT`, remote intent, power-loss durability, and a production cross-process arbiter may wait.

This creates translation risk: a fast research candidate might become slower after production controls. Report mechanism latency now, then rerun the complete product endpoint after production hardening. Do not count the research result as production reliability.

### Full-lifetime V1 lock handoff is not yet designed

The current route launches a detached worker and releases its project lease. The worker inherits only its logs, and nested Claude/Codex processes can create their own detached process groups tracked only in memory. A parent-held kernel lock cannot simply be “handed” to the detached worker without a gap or deadlock, and killing the outer worker group cannot prove those nested groups died after a crash.

Legacy root-writing V1 containment needs one of:

- a non-detached supervisor/wrapper that owns the lock and every descendant for the lifetime; or
- an explicit `STARTING` reservation and fenced parent-to-worker handoff protocol with no writable gap.

Do not add a new `STOPPING` value to V1 before readers understand it. Keep legacy job/run status nonterminal while a separate arbiter record says stopping, rotate the fence, and write `interrupted` only after quiescence. Deploy a tolerant reader, drain/restart all old HTTP and worker processes, then enable any new status/version writer.

### Private generation compute does not need a full project lock

For production V2 MP4, frozen attempts may compute concurrently in unique private generation directories. They need resource admission, isolated work paths, per-cache-key locks, and immutable input authority. Only the short publish step needs the project writer arbiter and expected-parent/fence comparison. A stale attempt may finish computing but cannot advance `CURRENT` or materialize shared compatibility output.

This is simpler and faster than holding a project lock until every descendant dies. The full-lifetime lock remains containment for legacy code that mutates shared root files.

### Narrow the durability claim

The first release should claim process-crash/SIGKILL and server-restart atomicity on a declared filesystem, not universal hardware power-loss durability. Ordinary Node `fsync` is not by itself a portable proof of storage-controller ordering on this host. A stronger claim requires a supported-filesystem contract, full-flush primitive/native publisher where required, and destructive power-failure testing. Every nested modified directory must be flushed according to that contract.

### Source authority needs two moments

The planner cannot freeze the exact selected asset closure before it has selected assets, while copying the entire multi-gigabyte motion library per run is wasteful. Split authority into:

1. a pre-plan input source root containing source media, manifest/catalog identity, transcripts, intent, and reference;
2. a post-plan selected asset closure root containing every exact local/remote asset and runtime dependency used by the approved realization.

An immutable content-addressed catalog can satisfy the second root without per-run library copies. Current authority hashes manifest descriptions rather than every referenced source-media byte, so it cannot authorize production reuse yet.

### A local Palmier fence cannot prevent an already-sent remote effect

The current Palmier mutators do not send a durable operation/idempotency key or remote expected parent. The JSON-RPC ID is only a session-local counter. A stale local process can therefore finish an already-sent create/import/mutation even after its fence is revoked. The defensible guarantee is narrower: it cannot locally approve, activate through the broker, or promote the ambiguous result.

Palmier is also a singleton protected today by a user-global lock, so production ordering is project admission followed by the global Palmier broker. An ambiguous remote operation quarantines the unique Palmier candidate and blocks that Palmier target; it must not freeze unrelated local MP4 work forever. No automated retry, queue drain, canonical activation, or cleanup is allowed without exact reconciliation or a server-supported operation identity/CAS.

## Revised implementation order

1. **Baseline and capacity:** instrument full wall time/tokens/cost/cache/retries/disposition; reserve disk; freeze a small corpus.
2. **Offline model/effort replay:** attack the dominant author/reviewer latency before new renderer work.
3. **Three isolated discriminators:** renderer microbenchmark without LLM, review-topology shadow test with identical revised plans, and frozen-packet model/effort replay.
4. **Disposable existing-path experiment:** explicit MP4 `ai-edit` → canonical diff → `assemble` → terminal Audit B/full-decode/two-rendered-critic receipt; no promotion.
5. **Dependency and review proof:** compile the `R0` effect allowlist, complete base/runtime/output receipts, derived-artifact regeneration, full-replay equivalence checks, and shadow selective-review defect corpus.
6. **Decision gate:** stop if complete-pass latency or quality fails. Expand one repair class at a time only if field eligibility justifies it.
7. **Production containment:** tolerant-reader/drain boundary, V1 supervisor or proven handoff, stop/quiescence fencing, sanitized model evidence roots, and disk admission.
8. **Production MP4 authority:** pre-plan source plus post-plan asset closure, explicit stage projections, complete receipts, private immutable generations, short locked publish, `CURRENT`-first readers, and process-crash fault injection.
9. **Palmier:** offline compiler/protocol work only; one live canary remains conditional on MP4 failure and all prior Palmier gates.

## Round-five go/no-go

| Path | Decision after this round |
|---|---|
| Full baseline telemetry and disk reservation | Go first |
| Frozen offline model/effort replay | Go after basic telemetry; production stays on current quality settings until noninferiority |
| Disposable Palmier-free `ai-edit` → `assemble` experiment | Go after the small explicit-MP4/diff/receipt/terminal-event seams; never promote |
| Current generic graphics-only fingerprint as production reuse authority | No-go |
| `R0` short-form `text-element` color-only repair | Research go with fail-closed allowlist and full-replay oracle |
| Selective planning/rendered review | Shadow-only until defect-recall and blinded noninferiority pass |
| Per-critic same-input receipts | Go for retry cost/tail reliability; removed from normal-pass speed claim |
| New JobV2 or new renderer DAG before the kill test | No-go |
| Production deterministic MP4 | Conditional go after containment, authority, receipt, atomic publish, and fault-injection gates |
| Another live Palmier mutation | Temporary no-go |
| Greater-than-95% product-direction claim | Not supported |

## Confidence effect

This round increases confidence in the **next experiment** because it reuses the actual governed edit and assemble paths and removes unnecessary architecture from the learning loop. It decreases confidence in the previous **dependency-scoped repair design** because the existing fingerprints and outputs have concrete false-reuse cases.

Latency/economic confidence remains Red until complete-pass measurements exist. Authority/correctness remains Red until stage projections, source/asset closure, runtime identity, exact output receipts, and derived-artifact binding are implemented. The product direction remains below the user's greater-than-95% threshold.
