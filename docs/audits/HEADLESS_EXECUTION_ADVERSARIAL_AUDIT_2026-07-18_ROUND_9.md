# Headless execution adversarial audit — 2026-07-18, round 9

> **FROZEN AUDIT SNAPSHOT.** This records attacks and corrections from the ninth adversarial pass. The living decision record is [`HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md`](../producer/HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md); the ordered contract is [`HEADLESS_MP4_95_CONFIDENCE_EXECUTION_PLAN.md`](../producer/HEADLESS_MP4_95_CONFIDENCE_EXECUTION_PLAN.md).
>
> **Scope:** Claude Code/Codex to deterministic MP4. GUI implementation and editable Palmier release are excluded.

## Verdict

Round nine again disproved “ready for implementation” and found several ways the Round 8 plan could have produced false authority or false 95% evidence.

The corrected direction remains a **conditional go** for a separate headless MP4 API and a **no-go** for adapting the mixed Auto Edit/AI Edit worker into the production fast path. External release remains blocked. No production code changed during this round.

The largest new discoveries were:

1. the approved input plan is not necessarily the plan current render/assemble code executes;
2. sealing by `chmod` cannot revoke an escaped writable file descriptor;
3. attempt traces, publication, cancellation, and initialization lacked one coherent crash protocol;
4. the original latency definition structurally penalized the legacy comparator;
5. the simple 59/59 program still depended on independence and common-marginal assumptions the workload does not currently justify.

## Attack deployment

Three independent adversarial roles attacked the Round 8 execution contract:

- **code disproof:** traced render/assemble transforms, model launchers, conditional runtimes, attempt/publish ordering, and trace concurrency;
- **contract consistency:** attacked API location/idempotency/cancel semantics, lineage/fence/current state, sealed paths, initialization, slices, and cross-document contradictions;
- **statistics disproof:** attacked comparator symmetry, population selection, clocks, estimators, provider identity/carryover, costs, quality raters, and reliability sampling.

The parent agent then reconciled every accepted correction into the living dossier and execution plan and reran contradiction/link checks.

## New code-level counterexamples

### The renderer approves one plan and can execute another

[`render.py`](../../scripts/producer/render.py) calls its gate before `recompose_stage`, but recompose mutates the plan. [`recompose.py`](../../scripts/producer/motion/recompose.py) replaces `punchIns` and stamps measured face geometry into graphics entries. The renderer also copies the original input plan to `edit_plan.json` before running those transforms, while base/provenance bookkeeping uses the later in-memory plan.

[`assemble.py`](../../scripts/producer/assemble.py) verifies template usage before `ensure_base()`, but base recovery can refit and replace the plan afterward. Its later `base_plan.json` write can use the stale parent-process object.

**Correction:** add `ResolvedPlanV1`. Complete deterministic refit, recompose, face measurement, ID reconciliation, and canonicalization before lint/template approval/critics. Render/assemble must prove identical before/after plan digests; a later transform creates a new unapproved candidate. The reusable lesson is frozen in [`APPROVE_THE_RESOLVED_PLAN_NOT_THE_INPUT_PLAN.md`](../../scripts/producer/docs/findings/APPROVE_THE_RESOLVED_PLAN_NOT_THE_INPUT_PLAN.md).

### Current `render_report.json` is not terminal audit authority

The renderer flushes `render_report.json` before Audit B, then adds `audit` only to the returned in-memory object. A successful-looking on-disk report cannot prove terminal audit completion.

**Correction:** commit a separate terminal-audit receipt produced after checked full decode and Audit B, or move/reflush the report after both stages. The current report remains diagnostic.

### Final-directory `chmod` cannot seal escaped writers

An already-open writable descriptor survives permission changes. Current process-group termination helpers also do not prove that every descendant has lost every descriptor before returning.

**Correction:** models/renderers write only attempt staging. Reap all writer-capable descendants, then a trusted sealer copies or verified-reflink-clones authoritative bytes into fresh final-generation inodes never exposed to those writers. Sandboxed read-only verifiers inspect final bytes and write outside final; the trusted controller writes receipts and `commit.json` last, flushes, then makes the generation read-only.

### Current model wrappers do not prove closed candidate ownership

Current Claude authoring can resume sessions and exposes file-writing tools from repository-root context. Current Codex authoring uses workspace-write/default tooling; the wrapper does not express the required closed structured-output tool surface.

**Correction:** model processes receive a sealed read-only evidence root and emit schema-validated patch/plan bytes on stdout. The controller alone writes candidate files. Claude requires explicit tools, no slash commands/session resume, strict empty MCP, safe mode, and pinned skill bytes. Codex requires read-only/no-tools structured output or an OS sandbox. CLI flags alone are not a filesystem isolation proof.

### The minimal overlay does not close conditional runtime dependencies

A section-marker overlay exercises HyperFrames/GSAP/browser, but a real plan can activate Demucs, a separate Python environment, YuNet/ambient detector selection, model caches, and other conditional paths.

**Correction:** after `ResolvedPlanV1` freezes and before render, derive `RuntimeCapabilityManifestV1`. Bind every executable/library/model/backend/cache digest and run offline smokes with downloads, telemetry, and ambient fallback denied. Unsupported capabilities fail before rendering.

## Authority and API corrections

### Initialization needed explicit states

Expected-null initialization contradicted the former rule that missing `CURRENT` always fails. Deleting `CURRENT` after a prior publication could also have been mistaken for a new project.

The corrected authority states are:

```text
UNINITIALIZED -> INITIALIZING -> READY
                       \-------> BROKEN
```

Only proved `UNINITIALIZED` permits expected-null initialization. Prior publication evidence plus missing/corrupt pointer is `BROKEN`, never re-genesis. Initialization consumes a presealed content-addressed snapshot; it does not read a mutable root file set as one atomic source.

### Parent sequencing and cancellation fencing were conflated

Cancellation can occur without publishing a new parent, so one `epoch` cannot represent both facts.

The corrected records are:

```text
CURRENT = {authorityId, publicationSeq, generationId, commitDigest}
FENCE   = {authorityId, fenceRevision, fenceToken, activeAttemptId}
```

Only one publisher-capable attempt is admitted per authority. Cancel checks `CURRENT` under the lock: when it already equals the publish-intent tuple, publication wins and success recovery completes; otherwise cancel rotates/flushes the independent fence before termination. Publication compares the complete parent plus exact attempt fence.

### The API was not locatable or idempotent

Project-local attempts cannot be resolved safely from a bare UUID. The original list also omitted cancel/current, initialize schema, existing-current behavior, and atomic idempotency admission.

The corrected local API requires canonical workspace-contained `projectRoot` for status/current/cancel resolution and caller-pre-enrolled `unitId` on both POST envelopes. Under the authority lock it persists `{idempotencyKey, requestDigest, attemptId, unitId, firstSubmittedAt}` before returning `202`. Same key/unit/bytes returns the original clock/result; changed bytes or unit is `409`. Nonterminal project moves are rejected.

### Publication needed a post-pointer crash bridge

`CURRENT` can advance before the trace/result is sealed. Without durable intent and admission blocking, a later publication could obscure recovery of the prior attempt.

The corrected attempt model separates phase and disposition. Every success/failure/block/stale/cancel outcome reaches `TERMINAL_SEALED` before clearing `FENCE.activeAttemptId`. `publish-intent.json` binds attempt/request, parent, fence, generation, commit, and result before pointer replacement. No later admission occurs until recovery seals that exact transition.

### `O_APPEND` did not serialize a hash-linked trace

Multiple processes can read the same tail and append two valid-looking children even when writes do not byte-interleave.

**Correction:** `trace.jsonl` uses one supervisor or a never-unlinked trace flock around tail-read, sequence/digest calculation, one bounded canonical JSON frame, and `fdatasync`. Each line contains payload length, CRC, sequence, prior digest, and event digest. Recovery may truncate only a torn last line.

### Generation and attempt lifecycles were mixed

The trace must record post-publication facts and therefore cannot live inside the pre-publication immutable generation. Cache/work/temp are also mutable scratch.

**Correction:** split `GenerationPathsV1` from `AttemptPathsV1`, and split admission-time inputs from post-planning realization inputs. Commit the full closed input/root records, output/proof/approval records, and relative hashes; exclude attempt state, trace/log, locks, cache, work, and temp.

### External CAS objects needed reachability authority

A commit that references large source/assets by digest is not self-sufficient when those objects can disappear.

**Correction:** every reachable generation pins external source/asset/tool objects. Missing or substituted bytes make authority `BROKEN`; never refetch mutable remote content. Generation and external-CAS GC are both disabled until joint reachability/refcount/pin recovery is proved.

## Statistical counterexamples and corrections

### The first latency definition made the comparator fail automatically

The former `QualifiedJobSuccessV1` required headless expected-parent publication, while the baseline was a legacy root-writing route. Every baseline could therefore have been charged `H`, mechanically improving the treatment ratio.

**Correction:** current legacy routes are disposable pilot comparators only. The confirmatory baseline is the full current quality policy inside the same new trace/generation/publisher wrapper with optimizations disabled. `QualifiedComparisonJobV1` applies identically to both arms. An A/A bridge determines whether a “faster than today's route” claim is allowed; otherwise the claim is narrowed to wrapped-control plus absolute SLA before enrollment.

### Enrollment, clocks, and initialization could select success

“Qualifying” projects, a provider-availability window, and first-valid-submission clocks allowed post-selection or clock reset. Successful-initialization-only projects also cannot prove initialization reliability.

**Correction:** the primary claim is exactly **system-ready automation latency and reliability for Aaron's first organic quality pass, conditional on initialization before feedback**. It does not cover initial-short creation or human-decision workflow time. An external ledger records `pairId`, each `armUnitId`, and `t0[arm]` before the API call; `400/409/429/500`, retries, outages, and fallback remain in the unit. Enrollment uses only pre-feedback immutable criteria. Initialization and initial creation need separate cohorts.

### The latency estimator was underspecified

The corrected arm value and effect test are:

```text
Y[a,i] = max(t_system_ready_committed_hash, t_required_trace_seal) - t0[a,i]
         when QualifiedComparisonJobV1 and elapsed <= H; H otherwise

D[i] = Y[treatment,i] - 0.35 * Y[baseline,i]
```

Use the unweighted unit-level mean. The planned inference is a paired wild-cluster bootstrap-t over whole operational blocks, at least 9,999 deterministic resamples, and `N_blocks = max(30, pilot-powered requirement)`. Before enrollment, coverage/power fixtures must include few clusters, zero variance, unequal informative cluster sizes, heavy tails, mass at `H`, and temporal correlation. Failure is `INSUFFICIENT_EVIDENCE`.

### Provider crossover can contaminate AB/BA

Local clone/cache isolation cannot isolate provider prefix caches, account throttles, rate limits, or backend load.

**Correction:** freeze account/session/cache policy, retain cache/throttle counters on every call, preregister order-by-arm carryover and first-period sensitivity, and use independent provider capacity when possible. Material unresolved carryover is insufficient evidence.

### Economics conditioned away expensive failures

Provider cost “per qualified job” discards the units most likely to be expensive.

**Correction:** charge provider, allocated local compute, retained storage, and operator cost across every attempt/fallback through quiescence for every pre-enrolled unit. Freeze rate-card/allocation and numeric ceilings. Cost/operator/intervention bounds form an intersection-union gate; peak storage is a hard cap. A failed-high-cost golden fixture must worsen the decision.

### 59/59 did not follow from unique projects

Clopper–Pearson 59/59 requires independent jobs with one common marginal success probability. Unique roots, consecutive enrollment, and one project per same-day provider regime do not create those assumptions. Heterogeneous blocks do not have a common marginal merely because one job is selected from each.

**Correction:** exact 59/59 is permitted only under an independently justified sampling frame drawing each unit from the same frozen target mixture. Multiple arrivals in a dependence block remain nested; heterogeneous strata require a stratified, Poisson-binomial, hierarchical, clustered, or anytime-valid method. Claude and Codex are separate releases unless routing weights/strata and surface-specific margins are frozen.

### Quality and human acceptance needed executable rules

Each critical lane must freeze its project-level denominator, endpoint, null, margin, minimum informative projects, missingness, and sample size. Three blinded calibrated raters use an absolute single-output rubric; majority decides binary acceptance, any critical report follows a frozen blinded adjudication, missing ratings cannot be replaced, and failed calibration/inter-rater/blinding checks stop the gate.

## Current go/no-go after round 9

**Go now, in parallel:** G0 provider capability/identity probe, G1 locked framed trace fault test, G2 sealed offline overlay, and distinct-project collection.

**Go only after dependencies pass:** R0 old/reuse/fresh-A/fresh-B; coherent audio and cut fixtures; six-project disposable pilot; then the production authority slices under an internal feature flag.

**No-go:** external headless release, production `CURRENT` publication before G8/G9, current mixed-worker branching, root projections/migration, live Palmier mutation, initial-build speed claims, current-route speedup wording without the A/A bridge, and any field 95/95 statement from current artifacts or rapid replays.

## Confidence status

Still below 95%. Round nine removed additional logical paths to false success, but it did not create qualifying evidence. The repository still has no implemented headless authority, no completed G0/G1/G2, only two distinct retained source families, unresolved provider-build identity, no frozen numeric cost/quality protocol, and zero natural confirmatory units.

The design is now more falsifiable and more buildable. Confidence must rise from executed gates and natural evidence, not the number of review rounds.
