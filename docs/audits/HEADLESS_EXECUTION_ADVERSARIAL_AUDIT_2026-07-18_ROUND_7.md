# Headless execution adversarial audit — 2026-07-18, round 7

> **STATUS: FROZEN AUDIT SNAPSHOT.** This records the seventh adversarial wave and its cross-examination. Corrections belong in the living [headless optimization dossier](../producer/HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md), not by rewriting this record.

## Scope and method

Reviewed only Claude Code/Codex planning and repair into deterministic MP4, approved-plan rendering to MP4, and the boundary that could later permit Palmier. GUI work remained excluded.

Three independent attacks tried to disprove round six:

1. A minimal-path attack counted the actual model barriers/calls, traced cut dependency closure, checked whether renderer fast paths are reachable from a fresh quality candidate, and searched for the smallest credible orchestration change.
2. An authority/recovery attack injected conceptual crashes at staging, base/refit, cache, review, repair, media/proof promotion, and pointer boundaries and traced resume behavior through the current code.
3. A confidence-program attack tried to derive the requested 95% claim from the proposed weighted table, six-project pilot, current quality wall, and retained evidence.

The primary agent cross-checked their conclusions against the route, worker, renderer, audit, model adapters, artifact corpus, logs, and selected tests. No production code changed. This round changed documentation only.

The following selected regression scripts all passed:

```text
ai-edit-authority-invalidation.test.ts
surgical-edit.test.ts
auto-edit-quality-artifacts.test.ts
auto-edit-quality-loop.test.ts
auto-edit-pipeline-resume.test.ts
ask-edit-preview-invalidation.test.ts
auto-edit-review-concurrency.test.ts
audit-gate-contract.test.ts
```

That green result became adversarial evidence rather than a release pass. [`ask-edit-preview-invalidation.test.ts`](../../src/lib/producer/__tests__/ask-edit-preview-invalidation.test.ts) requires authority invalidation before model-facing plan mutation; the concurrency test expects same-code defects to merge; and the Audit B contract accepts an empty/unbound machine report. All match V1 behavior and conflict with the proposed claim-level invariants.

## Round-seven verdict

The bounded deterministic-MP4 direction survives. The current implementation and evidence do not.

The plan now has two distinct tracks:

- **Disposable evidence track:** instrument, add typed-patch property tests, run one planner-reachable render fixture, measure context/effort only with adequate provider telemetry, and exercise an integrated V1 quality-pass mode only inside a frozen throwaway clone with no production promotion.
- **User-facing production track:** first add the minimum immutable-generation authority seam—explicit MP4-only routing, private base/refit/media/sidecars, complete verification, `commit.json`, durable publish intent, locked expected-parent `CURRENT`, recovery, and cache isolation or hardening.

A rollback-based V1 pilot and an immutable-generation production path were proposed by different attackers. The stricter conclusion wins: backup/restore can be useful inside a disposable clone, but current assembly mutates too many canonical files and current promotion is too destructive to make restore a crash-safe production contract.

The requested confidence target is also narrowed. There is no honest global “95% sure” score for an architecture. There can be a 95%-controlled release decision for one frozen deterministic-MP4 population, route, effect class, fallback, build, endpoint, and statistical plan. Unless a broader creator sample is preregistered, the initial claim is Aaron-only. The repository currently supplies zero qualifying independent product units for that claim.

## Findings that change the plan

### The existing second-pass path repeats nearly the whole model wall

The present two-route produced/full non-cut path has a clean best-case minimum of four serial model barriers and six calls:

1. surgical writer in [`ai-edit/route.ts`](../../src/app/api/producer/ai-edit/route.ts);
2. serial surgical critic in [`ai-edit/finalize.ts`](../../src/app/api/producer/ai-edit/finalize.ts);
3. two concurrent planning critics selected by [`round-policy.ts`](../../src/app/api/producer/auto-edit/round-policy.ts) and launched by [`planning-review-batch.ts`](../../src/app/api/producer/auto-edit/planning-review-batch.ts);
4. two concurrent rendered critics in [`quality-loop.ts`](../../src/app/api/producer/auto-edit/quality-loop.ts).

A light non-cut path has the same four barriers but five calls because it uses one planning critic. Changed-cut produced/full can reach six barriers/nine calls; light can reach six/eight because cut critics are added and [`authoring-stage.ts`](../../src/app/api/producer/auto-edit/authoring-stage.ts) unconditionally launches the full visual author before planning/rendered review. Gate fixes and revision loops add more.

This is a direct code-level explanation for the report that a quality pass can cost nearly the original hour. Renderer reuse alone cannot remove those serial model barriers.

The cheapest first orchestration treatment is one integrated quality-pass request that retains every verdict but runs surgical and planning critics concurrently after deterministic governance; eligible cut work also tests cut critics in that batch. Resource-admitted speculative private rendering may overlap the critics and is discarded on revise/block. Removing the surgical critic is a later shadow treatment. Complete saved cut edits run dependency-closed cut review and skip the unconditional initial visual author. None becomes production policy until hidden-ground-truth noninferiority passes.

### Cut edits are not dependency closed

Current surgical cuts scope permits only `cutTrack` mutation in [`surgical-edit.ts`](../../src/lib/producer/surgical-edit.ts) and the writer prompt. The transcript contract in [`transcript_cut_contract.py`](../../scripts/producer/transcript_cut_contract.py) requires schema-valid `cutDecisions.removals` matching actual inter-cut gaps.

A fast cut pass must therefore treat `cutTrack + cutDecisions` as one controller-owned dependency. It then deterministically refits the complete saved plan, runs cut gates/reviews, and goes directly to planning review. A cut mutation that leaves stale decisions is ineligible, not a reason to keep retrying the writer.

### The current “private candidate” still mutates selected authority

The Auto Edit pipeline calls the canonical base guard and assembler for its candidate. The guard in [`auto_base_guard.py`](../../scripts/producer/edit/auto_base_guard.py) can rename canonical `base_final.mp4`. [`assemble.py`](../../scripts/producer/assemble.py) can write/refit/promote plan, base, fingerprint, proof sidecars, and base-plan state sequentially before the candidate has passed quality approval.

A process death or `ENOSPC` during those steps can damage the previous approved generation even if the candidate never promotes. A directory named “candidate” is not private authority if its subprocesses still write through canonical paths.

The production invariant becomes:

> Every plan, base/refit product, MP4, proof, cover, diagnostic, review, and approval for a candidate is written only inside one private generation. Until `CURRENT` advances, no selected-parent byte changes.

### Current promotion is neither one generation nor a compare-and-swap

[`auto-edit-quality-artifacts.ts`](../../src/lib/server/auto-edit-quality-artifacts.ts) removes/moves candidate media, assembly proof, and proxy, copies diagnostics/frames, then writes approval through a separate per-file rename. A crash can leave a mixed projection and can destroy the prior good media/proof before the new approval exists; the individual approval rename does not make the whole generation atomic.

Several plan transactions compare current state and later rename, including [`revision-staging.ts`](../../src/app/api/producer/auto-edit/revision-staging.ts), [`plan-refit-transaction.ts`](../../src/app/api/_lib/plan-refit-transaction.ts), [`save-plan/transaction.ts`](../../src/app/api/producer/save-plan/transaction.ts), and [`ai-edit/finalize.ts`](../../src/app/api/producer/ai-edit/finalize.ts). That is check-then-write under cooperating route locks, not a conditional filesystem commit against noncooperating headless writers.

The minimum production state machine is:

```text
PREPARED -> VERIFIED -> PUBLISH_INTENT -> COMMITTED
    |           |             |
    v           v             v
 ABORTED     ABORTED        STALE
```

- `PREPARED` binds attempt/fence, exact expected parent, target/effect or request contract, frozen input manifest, and implementation root.
- `VERIFIED` binds the immutable generation manifest and every complete decode/effect/audit/critic receipt. `commit.json` is written last.
- `PUBLISH_INTENT` records `{expectedParent, newCommit, fence}` durably.
- `CURRENT` lives under a permanent project × realization `authorityId`, not under a per-run namespace. Sealed generations and mutable attempt/publish state are separate siblings.
- Publication holds the stable authority kernel lock, revalidates the complete generation manifest/bytes from pinned descriptors, re-reads the full parent tuple, and replaces only `CURRENT`.
- Recovery revalidates the generation, completes when `CURRENT` already equals the new commit, retries publication when it still equals the expected parent, and marks `STALE` otherwise.
- Compatibility `final.mp4` and legacy JSON files are projections created after publication. Readers use `CURRENT` first.

Every reader pins one validated commit tuple for its entire operation. Existing V1 authority enters through a drained expected-null genesis transaction with a migration marker; invalid legacy evidence cold-rebuilds/requalifies, and no legacy fallback remains after migration.

Never restore truth by rewriting backup files after a crash.

### Repair recovery can repay the same expensive quality pass

[`quality-loop.ts`](../../src/app/api/producer/auto-edit/quality-loop.ts) checkpoints `repairing` before the writer has committed, then writes the repair receipt and invalidates the old candidate/reviews later. Generic checkpoint ordering can regard quality review as already reached while the unchanged rejected plan/candidate remains reusable.

A stop between those boundaries can resume Audit B and both rendered critics on the same rejected candidate and then attempt the same repair again—the exact “same amount again” failure mode.

Rejected candidate, repair intent, repair staging, repaired plan commit, and revised candidate need distinct durable identities. Resume before repair promotion must resume/restart repair from the immutable parent; resume after promotion must see the new plan digest and never double-apply.

### Review and system failures can manufacture full extra loops

Rendered reviews use `Promise.all` in [`quality-loop.ts`](../../src/app/api/producer/auto-edit/quality-loop.ts). One infrastructure rejection can escape while its sibling remains alive for up to the 25-minute cap. The parent must not fail/unlock until every launched child has terminated and been reaped.

Audit findings are aggregated into the same review shape in [`quality-review-aggregate.ts`](../../src/app/api/producer/auto-edit/quality-review-aggregate.ts), then can flow to a 20-minute revision writer. Decoder failure, missing evidence, malformed critic output, timeout, and corrupt artifacts are system outcomes, not editorial instructions. Add at least:

- `PLAN_DEFECT_REPAIR`;
- `TRANSIENT_SYSTEM_RETRY_SAME_CANDIDATE`;
- `DETERMINISTIC_SYSTEM_BLOCK`;
- `AUTHORITY_STALE`.

Only the first may summon a plan writer.

### The end-to-end R0 should use a planner-reachable template

Round six selected a synthetic `text-element.spec.color` fixture, but no retained plan used that kind and Audit B lacked a direct request-effect oracle for it.

The retained short plan [`social-polished-20260717/edit_plan.json`](../../artifacts/social-polished-20260717/edit_plan.json) contains stable-ID `section-marker` rows with `spec.accent`. `section-marker` is emitted for topic boundaries by [`graphics_planner_rules.py`](../../scripts/producer/planner/graphics_planner_rules.py), and its catalog contract exposes `accent` in [`comps-catalog.ts`](../../src/lib/producer/comps-catalog.ts).

The retained artifact has no approved final/base/proof, so the microscopic test has two steps. R0a derives a five-to-ten-second window around a retained marker, fully renders/QCs it, and freezes the seed parent. R0b performs an expected-parent/expected-old stable-ID replacement of one preregistered `section-marker.spec.accent` token pair that already passes worst-frame contrast, followed by old/reuse/direct-fresh-base comparison, complete decode, exact pre-encode token proof, calibrated decoded color, full-window contrast, protected-region checks, and regenerated derived artifacts. A synthetic `text-element` may remain a unit smoke. Neither proves organic field incidence.

### The audio-only and proxy opportunities need route-level eligibility proof

The retained 11.7-second audio-only assembly is not presently reachable for a fresh quality candidate. The quality loop recreates the candidate directory, while [`assemble.py`](../../scripts/producer/assemble.py) requires an existing candidate MP4 plus matching `.assembled.json` proof for audio-only mux.

Final media/proof alone is insufficient; the generation also needs exact base, fingerprint, and base-plan authority. First enhancement/gain on a pristine base may use the existing path. Music-only change needs unchanged processed dialogue plus exact final-video/base-audio projections and a remix proof. Modifying/removing baked processing needs a retained pristine-audio projection or full rebuild. SFX/order changes fall back unless an exact projection proves equivalence. Every eligible case requires an `audio_only_mux` receipt; do not report the standalone number as complete second-pass latency.

Headless assembly should also test `--no-proxy`. [`preview_proxy.py`](../../scripts/producer/preview_proxy.py) performs another full encode, while the no-GUI product endpoint needs the approved final MP4, not a preview proxy. Disable it symmetrically in reuse/fresh renderer arms and report proxy omission separately so two optimizations are not conflated.

### MP4-only execution is not explicit authority today

Auto Edit request/context/request-key types do not bind a realization target, and [`pipeline.ts`](../../src/app/api/producer/auto-edit/pipeline.ts) invokes Palmier primary selection, checkpoints, or mirrors based on ambient state. [`ai-edit/route.ts`](../../src/app/api/producer/ai-edit/route.ts) tries Palmier-native editing before deterministic preparation. The repository also advertises a local Palmier endpoint in [`.mcp.json`](../../.mcp.json).

Add a required, request-keyed and journaled `realizationKind`. Both Auto Edit and AI Edit HTTP routes parse/validate it before Palmier classification, guarded launch, or native-edit probing; the worker also branches before any `palmier.sync` read, MCP load/discovery, checkpoint, mirror, or port access. Tests exercise both routes with a Palmier state file, valid/invalid listener on 19789, and filesystem/network tripwires; any attributable access fails.

### Current traces and model adapters cannot support the evidence plan

The Auto Edit journal retains the newest 256 events and compacts payloads in [`auto-edit-job-store.ts`](../../src/lib/server/auto-edit-job-store.ts). The worker log truncates to a 1 MB tail in [`auto-edit-log.ts`](../../src/lib/server/auto-edit-log.ts). The producer registry is also bounded and deletes successful state. None is a complete request-to-approved-output benchmark record.

Codex exposes an `onEvent` hook in [`codex-cli.ts`](../../src/app/api/_lib/codex-cli.ts), but review callers retain only provider, elapsed milliseconds, and parsed verdict. Claude result parsing in [`brain-review-process.ts`](../../src/app/api/producer/auto-edit/brain-review-process.ts) retains the final result and elapsed time, not token/cache/build telemetry.

Phase 0 therefore flushes a durable attempt-index admission record before paid work, then creates a separate secret-free, schema-versioned checksummed append-only trace. Recovery truncates only a torn tail, appends the observed crash disposition, and leaves every unsealed attempt in the denominator before terminal sealing. It also instruments adapters. The critic-prefix cache hypothesis runs only if the provider reports cache-create/read and noncached input counters. Latency alone cannot establish a cache hit.

### The current full-quality wall is a control, not ground truth

The retained Palmier rendered critics both returned pass with zero material issues in [`rendered-reviews.json`](../../artifacts/palmier-live-acceptance-20260715/producer/rendered-reviews.json), while the [round-three audit](HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_3.md) documents an observed music-QC false pass and incomplete caption/continuous-media proof. Two treatments can agree because they share a blind spot.

Use the full current wall as a concurrent diagnostic control. Confirmatory quality comes from hidden seeded defects, clean negatives, natural defects, continuous video/audio inspection, and blinded human adjudication. Hidden labels never enter prompt, doctrine, rubric, or threshold tuning.

### Passing tests can preserve the wrong authority invariant

All eight selected tests passed, yet three assertions conflict with the proposed contract: early authority invalidation; merging distinct defects that share a model display code; and accepting an empty/unbound machine report as a passing audit summary. This is not a paradox: behavior-lock tests prove conformance to an old design.

Replace implementation-order assertions with claim-level tests:

- pending old output is never labeled as the requested new approval;
- candidate failure leaves prior `CURRENT` readable;
- a crash yields exact old or exact new generation, never a mixture;
- stale parent cannot publish or silently rebase;
- every child is terminal before failure/retry;
- compatibility projections never become authority.
- same-code defects at different evidence windows remain distinct;
- an audit pass binds exact report/media/plan/effect/base/toolchain bytes.

The durable lesson is recorded in [PASSING_TESTS_CAN_ENFORCE_OBSOLETE_AUTHORITY.md](../../scripts/producer/docs/findings/PASSING_TESTS_CAN_ENFORCE_OBSOLETE_AUTHORITY.md).

## What 95% can and cannot mean

The round-six 25/20/25/20/10 register had no probability model, averaged correlated domains, and could hide a red deterministic gate. It is removed.

The frozen claim is conjunctive:

> For the declared deterministic-MP4 release, population, repair class, fallback, build, and endpoint, the fallback-inclusive portfolio is materially faster, quality-noninferior, and full-job qualified-success probability exceeds 95%.

Freeze `QualifiedJobSuccessV1` before outcomes: correct immutable expected-parent publication; exact request/effect fulfillment; Audit B and checked full decode; all required critic/evidence receipts; no unplanned intervention; system-ready result within absolute horizon `H`; and the same blinded human acceptance policy used by the quality cohort. Timeout, missing/malformed evidence, out-of-policy fallback/recovery, or exclusion is failure. Treatment-only reliability jobs require identical adjudication.

For jobs satisfying `QualifiedJobSuccessV1`, the primary latency value is first valid submission to the system-ready final hash. Any job that later fails any success condition, including human rejection, is assigned `H`. The release estimand is the prevalence-weighted restricted mean of that value divided by the concurrent baseline's restricted mean. Retries, fallback, and recovery stay in the clock. Paired median/maximum, active operator time, and user-accepted elapsed time are separate diagnostics. The baseline uses the same starting approval and organic feedback under the same common release/runtime with isolated equivalent cache state; historical timings are not controls.

Evidence has different units:

| Claim | Unit | Current qualifying count | Gate |
|---|---|---:|---|
| Authority/crash correctness | State/write/interleaving/effect boundary | 0 | Complete declared finite state/fault matrix; any counterexample fails |
| Field eligibility | Consecutive organic first request on unique project | 0 | Prospective census and joint portfolio uncertainty |
| Latency | Unique project-feedback cluster paired with concurrent baseline | 0 | One-sided upper bound on prevalence-weighted restricted-mean time ratio through `H` ≤ `0.35` |
| Quality | Aaron-only original-project × first-organic-feedback pair; defects/frames/raters nested | 0 | Hidden-ground-truth multiplicity-controlled simultaneous noninferiority |
| Operational reliability | Complete frozen-release `QualifiedJobSuccessV1` on unique authority root | 0 | Preregistered fixed/sequential one-sided 95% lower success bound >95% |
| Editable Palmier | Accepted frozen server/tool-schema job | 0 | Blocked by remote ambiguity and QC gaps |

Exact one-sided 95% Clopper–Pearson examples for complete qualified jobs:

- 6/6 success: lower bound about 60.7%;
- 30/30: about 90.5%;
- fixed `N=59`, pass only on 59/59: about 95.05%, the smallest simple zero-failure design clearing 95%;
- a separately preregistered design allowing one failure first qualifies at 92/93;
- a separately preregistered design allowing two failures first qualifies at 122/124.

These are fixed-design thresholds. Do not observe a failure and switch designs or continue until 59 successes. Interim looks require preregistered alpha spending or an anytime-valid confidence sequence. Any behavior-affecting code, prompt, doctrine, model, schema, runtime, or audit change starts a new cohort; reuse evidence only for a preregistered change mechanically proved observational/non-behavioral. A moving model alias scopes the cohort to the alias plus a bounded calendar window, with provider rotations detected and never pooled.

Six paired development projects can kill a direction and estimate variance. The `1/64` sign calculation for 6/6 favorable independent preregistered representative signs is illustrative only: the planned balanced development corpus is nonrepresentative and tuned, so it has no confirmatory product-population p-value. Six cannot prove p95, 95% reliability, rare-failure probability, field prevalence, creator generalization, every quality lane, or Palmier correctness.

Use one fixed-sequence confirmatory cohort: latency/economics first, hidden-ground-truth quality second, operational reliability third. Every stage is a preregistered valid level-0.05 test under its fixed/sequential sampling rule; later hypotheses run only after formal rejection of every earlier null, and a failed gate is never bypassed. Inside quality, preregister union-intersection/closed-testing, Holm, or max-T control with simultaneous bounds for recall, each critical lane, the defined false-positive denominator, and human score. Seeded detector validation stays separate from natural generative-quality noninferiority. This avoids treating several unadjusted 95% intervals as one 95% decision.

## Corrected cheapest sequence

1. **Freeze the claim and comparator.** Hash Aaron-only or creator-sampled population, route, effect/fallback, `QualifiedJobSuccessV1`, horizon `H`, restricted-mean latency estimand, quality denominators/margins/multiplicity, concurrent baseline, tool/model/build identities, exclusions, and fixed/sequential look/stop rules.
2. **Add evidence infrastructure.** Sealed per-attempt trace, provider/cache/token/build telemetry, active operator time, stage barriers, child drain, failures, cost, storage, and final disposition.
3. **Run a prospective request census.** Consecutive first quality-pass requests establish field eligibility; selected easy repairs do not.
4. **Close deterministic cheap failures and run an Amdahl kill.** Typed-patch properties, route-level MP4 tripwire, cut dependency closure, no initial visual author after eligible complete cut review, system-failure routing, batch drain, and audio eligibility. Compute optimistic concurrent critical paths for typed, semantic, and cut lanes; kill any lane whose upper bound already exceeds `0.35 × control`.
5. **Run one planner-reachable R0 pair.** Derive/qualify R0a seed, then apply `section-marker.spec.accent` R0b with full/full nondeterminism, old/reuse/direct-fresh-base, exact effect and complete decode. Stop on mismatch.
6. **Measure integrated orchestration in fresh disposable V1 clones.** Retain every verdict but overlap surgical/planning and eligible cut critics; optionally overlap resource-admitted private render. No production publication. Test critic removal only later and separately.
7. **Run plan-only successive halving.** Exact prefix if counters exist, effort within provider, then model, compact doctrine, then affected review. No combined-factor attribution.
8. **Run six paired development projects in fresh clones.** Distinct sources/feedback clusters, AB/BA, isolated caches, all failures retained; select/freeze the route and size the untouched holdout. Do not pay for production publication if the route dies here.
9. **Build the minimal authority seam for the surviving route.** `GenerationPaths`, immutable private generation, stable authority-level `CURRENT`, separate attempt/publish state, genesis migration, revalidation, pinned readers, recovery, cache hardening/isolation, repair identity, and durable singleflight. This is `Mp4GenerationV1` under the existing job envelope; JobV2 remains later and optional.
10. **Freeze the release candidate and run the fixed-sequence holdout.** Predeclare the reliability design before outcomes—simplest is fixed `N=59`, pass only on 59/59. If the paired quality cohort is smaller, predeclare the exact number of equally adjudicated fresh treatment-only jobs needed to reach `N=59`; never adapt by continuing until 59 successes.
11. **Only then consider production Palmier.** It remains a separate claim after the bounded MP4 kill test and remote/QC protocol work.

## Mandatory fault matrix before user-facing release

| Injection | Required result |
|---|---|
| Kill before/after each generation state write | Prior `CURRENT` readable; deterministic recovery |
| Partial patch/model write | Private attempt aborts; selected generation unchanged |
| Parent changes after verification | Publish becomes `STALE`; never rebase |
| Kill after publish intent, before pointer replace | Recovery retries or marks stale |
| Kill after pointer replace, before terminal journal state | Recovery recognizes committed `CURRENT` |
| Modify sealed generation after verification, before publish/recovery | Byte/manifest revalidation fails; pointer never accepts it |
| `ENOSPC` at any generation file or `commit.json` | No visible partial generation |
| Kill in current base/refit/plan/sidecar boundaries | Cannot damage selected parent |
| Stop before/after repair promotion | No repeat review of rejected candidate; no double repair |
| One critic infrastructure-fails while sibling runs | Both terminal/reaped before return; no partial credit |
| First Claude revision partially edits then session fails | Fallback starts from original immutable staging |
| Two identical cache writers; kill one | One verified immutable cache object; no partial hit |
| Preexisting truncated cache entry | Quarantine and exactly one rebuild |
| FFmpeg returns nonzero or empty diagnostic output | System fault, never pass or plan repair |
| Corrupt final GOP/audio tail | Complete decode fails |
| Valid MP4 renders wrong requested color/effect | Effect-bound proof fails |
| Stale audit report from prior attempt | Hash/authority binding rejects it |
| Duplicate identical typed requests | One durable owner; same terminal commit returned |
| Duplicate semantic requests | Declared admission or render-only singleflight semantics hold |
| MP4 request with Palmier files/listener/MCP present | Zero Palmier reads, probes, calls, checkpoints, or mirrors |
| Client disconnect during render | Private generation recoverable; current unchanged |
| Kill during compatibility-copy projection | Readers still resolve through `CURRENT` |
| `CURRENT` advances halfway through a reader operation | Reader stays on one pinned validated commit |
| Concurrent expected-null genesis or truncated/missing pointer target | One valid genesis or fail closed; no post-migration legacy fallback |
| Two V1 snapshots of one version in one second | UUID/digest `wx` snapshots remain distinct |
| PID reuse/stale lease simulation | Start identity/fence prevents false ownership |
| Source/manifest A→B swap or in-place truncate/append/rewrite during capture | Frozen snapshot remains exact or admission fails |

## Go/no-go after round seven

**Go now:** documentation-backed telemetry implementation, prospective request census, pure typed-patch/property harness, explicit MP4 tripwire, cut dependency fix, system-failure routing, batch-drain tests, planner-reachable R0, and disposable cloned orchestration experiments.

**Go only after adapter capability check:** exact critic-prefix caching.

**Go only after the minimal generation seam:** any user-facing bounded deterministic-MP4 fast path or authority-preserving promotion.

**Temporary no-go:** live Palmier mutation, production V1 backup/restore fast path, affected-scope promotion, compact-doctrine promotion, and lower-effort/model promotion.

**Confidence status:** below threshold. Round 7 made the route to a legitimate 95/95 deterministic-MP4 claim explicit; it did not create the missing evidence.
