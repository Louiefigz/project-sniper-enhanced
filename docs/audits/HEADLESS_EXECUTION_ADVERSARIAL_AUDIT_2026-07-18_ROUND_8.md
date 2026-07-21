# Headless execution adversarial audit — 2026-07-18, round 8

> **STATUS: FROZEN AUDIT SNAPSHOT.** This records the eighth adversarial wave and cross-examination. Corrections belong in the living [headless optimization dossier](../producer/HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md) and executable [95% evidence plan](../producer/HEADLESS_MP4_95_CONFIDENCE_EXECUTION_PLAN.md), not by rewriting this record.

## Scope and method

Reviewed only Claude Code/Codex planning and repair into deterministic MP4, approved-plan rendering to MP4, and the protocol boundary that could later permit Palmier. GUI implementation remained excluded.

Three independent attacks tried to disprove round seven from different directions:

1. an implementation-slice attack traced request identity, route/worker imports, job persistence, project identity, generation paths, source capture, receipt paths, publication, repair resume, and reader migration;
2. an experiment-feasibility attack tried to execute the proposed telemetry, offline renderer, R0, cut, audio, cache-isolation, proxy, corpus, and disk plan from current artifacts;
3. a release-contract attack tried to make the 95/95 population, estimator, quality multiplicity, provider identity, enrollment, human adjudication, correlation, and evidence files executable.

The primary agent cross-examined these results against the exact routes, worker, model launchers, renderer, template approval, project schema, status/approval readers, CLI help, artifacts, and local filesystem. A final focused attack tested whether a new headless-only endpoint with no GUI projections really reduced scope.

Read-only probes confirmed:

- `claude --help` exposes `--safe-mode`, `--strict-mcp-config`, `--mcp-config`, `--no-chrome`, and session/control flags needed for a stricter MP4 launch policy;
- `codex exec --help` confirms the existing ignore-user-config/rules, ephemeral, strict-config, sandbox, and feature controls;
- every one of the 46 motion composition HTML files references remote GSAP, while the vendored GSAP directory lacks the core `gsap.min.js`;
- the repository is about 18 GiB, the graphics render cache about 8.4 GiB, and the filesystem currently has roughly 47 GiB free at 98% utilization;
- the retained artifact set contains only two distinct original source families, despite multiple C0679 copies.

No production code changed and no live provider/Palmier call or full render was made. This round changed documentation only.

## Round-eight verdict

The bounded deterministic-MP4 direction survives, but two prior implementation assumptions do not:

1. **The existing Auto Edit/AI Edit route, job, worker, status, and pipeline cannot be safely redirected into a generation directory.** Their call graph is root-oriented, transitively Palmier-coupled, and semantically overloaded through `ctx.dir`.
2. **The “minimal generation authority seam” is not one small slice.** It is an ordered group of contracts: explicit target/request identity, dedicated async attempts, stable lineage/fence, frozen inputs, neutral planning/QC cores, generation-relative receipts, sealed toolchain, private execution, verification, publisher, initialization, repair recovery, and fault evidence.

The strongest narrowed recommendation is a genuinely parallel `HeadlessMp4V1` lane:

- a versioned headless initialize/quality-pass/status API or CLI;
- its own durable attempt store, detached worker, trace, and pinned terminal result;
- no static or transitive Palmier dependency;
- no reuse of the root V1 job journal, producer-run registry, or root approval/promotion path;
- no legacy GUI projections or transparent migration initially;
- generation-native output selected only by `CURRENT`.

The existing GUI-era routes remain an isolated disposable comparator. A later transparent replacement would be a separate project requiring drained migration, route/direct-CLI writer fences, all-reader cutover, and projections. It is unnecessary for the requested scope.

The experiment plan is also not runnable today. Before R0, add a zero-provider **Discriminator 0** that proves one `section-marker` overlay can render offline from a pinned HyperFrames/GSAP/browser closure with isolated scratch/cache and a pixel oracle. This is cheaper and more diagnostic than discovering mutable-network/runtime failure inside a full video arm.

Confidence remains below the requested threshold. The plan is more falsifiable, but there are still zero qualifying natural product units and the current moving provider alias plus correlated Aaron-only enrollment may make a frozen field 95/95 claim infeasible.

## Findings that change the plan

### Use a new asynchronous headless composition root

[`auto-edit/route.ts`](../../src/app/api/producer/auto-edit/route.ts) statically imports Palmier classifiers/guards and always calls the launch guard before starting the worker. [`ai-edit/route.ts`](../../src/app/api/producer/ai-edit/route.ts) attempts Palmier-native editing before deterministic request preparation and reclassifies under its root mutation lease.

The current detached worker imports the mixed [`pipeline.ts`](../../src/app/api/producer/auto-edit/pipeline.ts), completes a root V1 job/run, and exposes Palmier-specific progress. Its job schema in [`auto-edit-job-types.ts`](../../src/lib/server/auto-edit-job-types.ts) has no realization, parent commit, generation, fence, publish state, or repair identity. The persistence/store path activates root quality policy, caps evidence, and archives/reuses root journals.

A thin branch around that stack would inherit the defects the new authority is meant to remove. Create a dedicated attempt protocol:

```text
POST initialize|quality-pass -> 202 {attemptId}
GET attempt -> running | failed | committed pinned result
terminal result -> {authorityId,generationId,commitDigest,mp4Path,sha256,mediaFacts}
```

The status response pins the terminal tuple recorded by that attempt. It never reads `CURRENT` again and accidentally returns a later generation. Synchronous MP4 delivery is unsafe because current authoring can run 45 minutes and critics have 20–25-minute ceilings.

### Execution target is not editorial intent

The current [`ProjectIntent`](../../src/lib/producer/intent-presets.ts) and `AutoEditIntent` describe mode, scope, lanes, style, reference, audio, and other editorial choices. `realizationKind` belongs in a separate closed `ExecutionPolicyV1` and explicit request identity.

Current Auto Edit canonicalizes `dir` and returns early for `reviewSavedPlan` in [`request.ts`](../../src/app/api/producer/auto-edit/request.ts). Current AI Edit calls Palmier before deterministic preparation. Any retrofit would therefore need to parse target before saved-plan/resume/dead-journal logic or any classifier. The new headless route avoids this ambiguity altogether, but still persists `realizationKind:"deterministic-mp4"` and rejects unknown fields.

[`autoEditRequestKey`](../../src/lib/server/auto-edit-hash.ts) removes several named runtime fields and hashes everything left by object spread. Target inclusion would be accidental and future runtime fields could silently change identity. Freeze an explicit `HeadlessRequestIdentityV1` projection plus cross-language golden fixtures. Old V1 semantics stay frozen as legacy.

### An `if` does not prove zero Palmier

The shared pipeline statically imports Palmier primary/checkpoint/mirror modules. Planning, authoring, quality, template history, and current job persistence contain additional direct or transitive Palmier dependencies. Python deterministic rendering also reaches `palmier.quality_hash` through [`template_usage_approval.py`](../../scripts/producer/template_usage_approval.py).

Create separate composition roots and enforce their transitive closures:

- TypeScript build-metafile denylist for Palmier, live-build, mixed worker/job/status, candidate-QC, and project-Palmier modules;
- Python AST import-closure denylist for `palmier.*`, after moving canonical hashing to a neutral Producer module;
- runtime filesystem/port/MCP/tool tripwires;
- a pinned MP4 controller snapshot that physically omits or denies Palmier modules.

For Claude MP4 work, the current prompt already names the pinned Producer skill file as a required read. Invoking ambient `Skill(producer)` is redundant. Reading that file directly permits safe mode plus strict empty MCP, disables plugin/hook/prefetch surprises, and removes one ambient discovery path. Codex already has useful ignore/config/feature controls, but its attempt root and tool set must remain closed.

### Stable local lineage and cancellation fence are missing

[`ProjectJson`](../../src/app/api/_lib/workspace.ts) has no UUID; project roots are mutable slug/date paths and the registry keys absolute directories. Define a project-local `.sniper/lineage.json`, then derive `authorityId` from a domain-separated `{lineageId, realizationKind}`. Project-local storage makes a filesystem copy an isolated branch, but copies of one lineage cannot count as independent reliability units.

Expected-parent CAS prevents two siblings from both publishing. It does not stop a canceled old worker from publishing when no successor has advanced the parent. The authority therefore also needs a durable mutable `FENCE` rotated under the publication lock on admission/cancel/stop.

Current TypeScript lease/job locks are exclusive-create/age/PID schemes, not a kernel-held publication lock; one job lock can be stolen solely because it is old. The repository already proves `fcntl.flock` availability in [`assemble_lock.py`](../../scripts/producer/assemble_lock.py) and Palmier ownership code. Use a small never-unlinking flock publisher helper that validates fence/parent/bytes, replaces and flushes `CURRENT`, and spawns no descendants.

### `GenerationPaths` alone cannot isolate execution

`ctx.dir` currently means project discovery, job/log identity, model CWD/write root, plan/base/final root, QC/review root, learning history, and Palmier workspace. There are more than one hundred uses. Replacing it with a generation path would also break persisted checkpoint round-trips, which restore canonical context.

Split:

```text
ProjectIdentityContext
GenerationExecutionContext
  GenerationPathsV1
  GenerationInputsV1
```

[`chain.ts`](../../src/app/api/producer/auto-edit/chain.ts) hardcodes base/plan/fingerprint root paths and omits `--cache-dir`. [`assemble.py`](../../scripts/producer/assemble.py) derives base-plan, refit, lock, proxy, proof, and output siblings. [`render.py`](../../scripts/producer/render.py) and assemble treat the output/approval directory as template authority. Template verification discovers live `project.json`, root approval, and a history path constrained under root `.sniper-learning/runs`.

Therefore the frozen inputs include operator intent, template-history approval/evidence, source/manifest/transcripts, cut approval, asset closure, implementation/toolchain root, and expected parent—not only render filenames. Make render/assemble accept explicit generation-scoped frozen authority instead of fabricating a fake project layout or pointing them back at root.

### Absolute evidence paths defeat directory rename sealing

Current approval, audit, plan packet, and review records embed and re-open absolute producer/candidate paths. Renaming a verified generation invalidates those receipts.

Allocate the final random generation directory before execution, keep every V3 artifact reference relative to that root, and use `CURRENT`—not a directory rename—as the visibility boundary. A non-self-referential digest graph is:

```text
generationId = random UUID known before build
FinalApprovalV3 includes generationId, never future commitDigest
commit.json lists every authoritative relative file except itself
commitDigest = SHA256(exact commit.json bytes)
CURRENT stores {authority,epoch,generationId,commitDigest}
```

Write `commit.json` last, close writable descriptors, flush, make the generation read-only, then publish. Publication/recovery revalidate exact bytes while the authority flock is held.

### Headless-only outputs remove migration work, with an explicit compatibility break

Current [`project-status/route.ts`](../../src/app/api/producer/project-status/route.ts) and [`auto-edit-quality-artifacts.ts`](../../src/lib/server/auto-edit-quality-artifacts.ts) recognize only root final/plan/base/approval layouts. Migrating all those readers and every writer is unnecessary when GUI is excluded.

The new headless authority initializes generation zero by cold rebuild/full re-QC of one frozen legacy snapshot. It does not transform/copy the current V2 approval, whose absolute refs would fail anyway. Thereafter headless reads only its selected generations and never falls back to root. Existing GUI/status continues to see the independent legacy branch.

This removes initial legacy approval genesis conversion, migration markers, root compatibility copies, projection recovery, and legacy writer fencing. It does **not** remove source freezing, neutral template authority, relative receipts, initialization, immutable generations, fence/CAS publication, recovery, or fault tests.

The timing claim must not hide initialization. Exclude it only for projects initialized before organic feedback was known; otherwise charge it to the unit or execute the declared fallback.

### The renderer experiment is blocked before R0

[`templates/motion/package.json`](../../templates/motion/package.json) runs `npx --yes hyperframes@0.7.33` and has no local package lock. [`graphics_render.py`](../../scripts/producer/graphics/graphics_render.py) invokes the same mutable `npx` command, writes `_gs-<key>.html` into shared composition source, and defaults to the shared source-tree cache. [`section-marker.html`](../../templates/motion/compositions/section-marker.html), like all 46 compositions, loads GSAP from a CDN. [`hyperframes.json`](../../templates/motion/hyperframes.json) contains remote schema/registry URLs.

The detached worker does point Python source at its captured pipeline snapshot through `SNIPER_PIPELINE_ROOT`; that partial pin is useful. The worker/controller still executes live TypeScript through live `tsx`, live `node_modules`, the live venv, ambient Node/npm/Python/ffmpeg/browser/font/runtime caches, and model read roots. A source snapshot is not a complete toolchain closure.

Before R0, seal one-overlay execution:

- exact HyperFrames integrity lock and absolute local binary;
- vendored GSAP core and local template URL;
- pinned browser path/hash, telemetry/download denial, external egress denial;
- attempt-local pipeline/runtime/temp/cache/output roots;
- full decode and direct pixel/color/alpha/window proof.

This becomes G2/Discriminator 0. Failure stops larger renderer work.

### R0, proxy, cover, audio, cut, and corpus are not ready

The retained social plan supplies real stable `section-marker.spec.accent` IDs, but no coherent approved base/final/proof parent. `render.py` also copies its input plan to the output, so a fixture must not make input plan and output plan the same path. R0 needs a newly frozen source/transcript/intent/template approval and four arms: old, revised reuse, revised fresh A, revised fresh B.

`assemble.py` always encodes a proxy and exposes no `--no-proxy` option. Keep proxy symmetric until a switch is implemented. It also does not regenerate cover after composite; the outer candidate receipt must regenerate/bind the candidate-derived cover rather than accept a stale existing file.

The retained audio seed has mismatched base/fingerprint/base-plan/plan/final proof state and cannot establish route latency. Cut work must mutate `cutTrack + cutDecisions`, run cut-only previsual, merge/refit privately, inspect every drop, and only then run approval/downstream gates.

Finally, the artifacts contain only two distinct source families. Multiple C0679 manifests/repairs are nested technical repeats. Phase 2's six distinct organic project/feedback units do not exist yet. With about 47 GiB free and an 8.4 GiB graphics cache, sequential tiny work is plausible; broad parallel repository clones are not.

### The current evidence system cannot run the confidence program

Current job events cap at 256/16 KB, producer runs cap at 24 and delete successful state, and worker logs retain a 1 MB tail. Provider adapters keep messages/stderr/elapsed time while discarding or not forwarding the needed usage/cache/build events. Renderer stages lack a complete span/overlap trace.

Build and crash-test an append-only checksummed trace before experiments. Run one tiny tools-disabled provider call and assert requested/resolved model, token/cache, output, and cost fields from command stdout. Missing counters kill the corresponding claim.

Claude defaults to moving alias `opus`; the current adapter records the requested alias, not an immutable resolved build. A frozen-build claim is blocked without resolved identity/rotation detection. An alias-policy claim must freeze and expire with a calendar interval rather than pooling indefinitely.

### The 95/95 contract needed statistical corrections

Round seven's 59/59 example is mathematically correct only under its independent/common-marginal Bernoulli model. Unique authority roots do not remove same-provider, same-day, cache, machine, load, and creator correlation. Fifty-nine rapid replays are not 59 field units. The release must either defend consecutive iid sampling, count at most one unit per preregistered independent block, or use a clustered/hierarchical/anytime-valid design.

The initial population is now explicitly Aaron's **first organic quality-pass request** on a qualifying project. It does not cover later passes unless every pass is enrolled and clustered within project. Freeze duration/aspect/language/scope/source/request/cache/load/calendar details.

The exact primary time value is:

```text
Y[a,i] = elapsed to terminal trace + system-ready committed hash,
         if QualifiedJobSuccessV1 and elapsed <= H;
         H otherwise
theta = mean_or_frozen_weighted_mean(Y[treatment]) / mean_or_frozen_weighted_mean(Y[baseline])
```

Freeze weights and the paired/clustered confidence algorithm. Prefer a consecutive unweighted portfolio rather than selecting an effect class and estimating its prevalence from the same optimistic census. “Concurrent baseline” is corrected to contemporaneous AB/BA in isolated resources unless independent physical/provider capacity proves simultaneous noninterference.

If every quality component must pass, the global noninferiority procedure is an **intersection-union test**, not the dossier's ambiguous union/intersection wording. Minimum informative cases per critical lane and an absolute single-output human acceptance rubric are required. Missing ratings and enriched/seeded jobs cannot be quietly counted.

Finally, a latency-only threshold is not an economics gate. Freeze provider-cost, operator-time/intervention, and storage ceilings or rename it.

## Corrected cheapest sequence

1. Freeze the headless endpoint/request/result schemas, first-organic-pass population, comparator, `Y`, `H`, economic ceilings, quality IUT, provider identity policy, and independent-unit design.
2. Run tiny provider capability probes. Stop cache/build claims whose counters are not emitted.
3. Build and kill-test the durable attempt/enrollment trace and frozen analysis fixtures.
4. Seal the deterministic runtime and pass one offline `section-marker` overlay with a pixel oracle.
5. Build/qualify the coherent R0 parent, then run old/reuse/fresh-A/fresh-B.
6. Build coherent audio and dependency-closed cut fixtures.
7. Collect six distinct organic projects; do not multiply retained source copies.
8. Extract a neutral private candidate controller and measure the integrated disposable quality pass in fresh isolated clones.
9. Run the six-project complete product pilot. Stop if the fallback-inclusive time/cost/quality gate fails.
10. Only then build dedicated headless attempts, stable lineage/fence, frozen inputs, neutral kernels, relative receipts, private generations, flock publisher, cold initialization, recovery, and faults.
11. Freeze the release and enroll untouched natural units under the executable evidence protocol.
12. Treat Palmier and transparent legacy/GUI migration as separate later claims.

## New mandatory fault cases

In addition to round seven's matrix, add:

| Injection | Required result |
|---|---|
| Missing/unknown execution policy | Fail before saved-plan, provider, classifier, or Palmier module load |
| Static TS or Python import closure reaches Palmier | Build fails |
| User/global MCP, plugin, hook, Chrome, or skill discovery present | MP4 launch remains strict-empty/disabled; any access fails |
| Stop rotates fence but parent stays unchanged | Old worker cannot publish |
| Publisher helper killed while holding flock | Lock releases; pointer remains exact old or exact new |
| Final generation has an open writable descriptor at seal | Verification fails |
| Absolute artifact ref enters V3 | Schema/commit verification fails |
| Headless terminal result observed after later `CURRENT` advance | Response remains pinned to its original committed tuple |
| Initialization occurs after feedback selection | Initialization is charged to the unit or unit is ineligible under frozen rule |
| Root GUI/CLI mutates plan/final after headless initialization | Headless generation/current remains unchanged and never falls back |
| Raw filesystem project copy | Isolated branch; never counted as an independent field unit without declared fork sampling |
| Remote GSAP/registry/browser/package download attempted | Offline overlay test fails closed |
| Two arms share `_gs-<key>.html`, cache, browser, temp, or source inode writes | Contamination test fails |
| Provider event schema omits required usage/build field | Corresponding optimization/release claim is `INSUFFICIENT_EVIDENCE` |
| Clock moves backward or worker restarts | persisted deadline/unit clock does not reset; trace records anomaly |
| Quality lane has too few informative projects | Global release is `INSUFFICIENT_EVIDENCE` |

## Go/no-go after round eight

**Go now:** provider capability probes, durable trace/fault writer, sealed offline one-overlay renderer, prospective request census, and distinct-project collection.

**Conditional go:** coherent R0, audio, cut, and integrated disposable experiments only after their preceding stop gates pass.

**Go only after the complete six-project pilot:** production `HeadlessMp4V1` attempt/authority/publisher work.

**No-go:** branching the current Auto Edit/AI Edit worker into production MP4 generations; reusing root job/status/promotion authority; passing root as generation template approval; compatibility projections; live Palmier mutation; or any claim that current artifacts/rapid replays establish 95/95.

**Confidence status:** below threshold. Round eight materially reduced migration scope and made the build/evidence order executable, but the provider/toolchain/corpus/publisher/natural-enrollment blockers are still open.
