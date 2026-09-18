# Stop-gated implementation roadmap

> A failed exit gate blocks dependent work. Passing a phase does not imply a
> later capability is released.
>
> [Previous: edge cases](06_EDGE_CASES.md) ·
> [Back to the plan index](../COMMAND_DRIVEN_EDITING_EXECUTION_PLAN.md) ·
> [Next: performance and testing](08_PERFORMANCE_AND_TESTING.md)

## Dependency order

The phase labels below group stop gates; they do not authorize a big-bang
rewrite. Execute in this order:

```text
current authority/reader inventory + baseline telemetry
  → shipped correctness and durability fixes
  → minimum typed identity/CAS/receipt + minimum render graph/oracle
  → refit, speed, and quantization contracts
  → word-safe repair
  → first-class caption track/shards
  → custom scenes/assets (parallel where dependencies permit)
  → optimized dirty rendering + hybrid Palmier
  → full typed command/handler breadth
  → reference and performance cohorts
```

Typed authority is not deferred: P1 establishes the minimum closed mutation
path. Product-wide command breadth comes later, after each lane can prove its
own handler and invalidation semantics.

## P0 — Make current contracts truthful and safe

Deliver:

- machine-readable inventory of every current authority, reader, writer,
  promotion point, fingerprint, durability seam, and reuse/adapter/replacement
  decision;
- cold/warm current full-path baseline trace on named short/long fixtures;
- one truthful vocabulary for workflow, story form, canvas, destinations,
  finish, timing, realization, and delivery;
- fix current enum contradictions (`short`, not `shortform`;
  `trim|light|produced|full`, not `clean|produced`);
- fix/remove contradictory platform fields;
- lane-correct starter plans: trim does not inject title/captions;
- truthful `produced` versus `full`, chapters, and thumbnail capability;
- no ghost `captionsTrack` claim;
- transactional reference-study generations;
- vendored runtime for all production comps;
- immutable content-addressed input snapshots;
- non-root networkless bounded probe/decode for every external media byte;
- cancellation fencing and immutable candidate/final publication;
- hardened current recompose/caption-suppression dependencies;
- explicit current FPS support matrix;
- one executable capability matrix across code, UI, skills, and docs;
- normative refit, speed, and frame/sample quantization specifications,
  preserving current old-output-order refit behavior;
- legacy regression traceability for geometry, footage contrast, measured comp
  capability, audio channel ordering, duration/AAC padding, exact rational FPS,
  captions, prompt vocabulary, and headless authority.

Exit:

- current cross-language enums/contracts agree;
- mutation tests cover every current render-affecting field;
- graphics cannot cause stale base reuse through recompose/suppression;
- all production comps render/decode offline at every measured/released FPS;
- source mutation during snapshot/decode cannot promote;
- malformed codec, huge dimensions/frame count, truncated stream, archive bomb,
  and decoder hang fail in sandbox;
- MP4-only runs make zero Palmier calls;
- short/long docs match executable behavior;
- every current authority reader/writer has a migration disposition;
- baseline telemetry reports stage/resource/cache behavior without turning the
  provisional 90-minute allocation into a measured estimate;
- `captionsTrack` cannot satisfy coverage before it renders end to end;
- cut-authoring prompt vocabulary is generated/checked against canonical enums;
- missing/stale/unmeasured/error comp capability fails closed;
- channel normalization precedes every mix path, and multi-segment AAC/duration
  authority fixtures pass;
- all applicable gates in
  [Legacy regression gates](10_LEGACY_REGRESSION_GATES.md) have owners.

The exact current verdict and evidence for each bullet are retained in
[P0 exit audit](11_P0_EXIT_AUDIT.md). That audit is authoritative for the
phase-level pass/block count.

Current checkpoint: the current-system inventory sub-gate has passed. The
measured short/LF-14 baselines are retained, and the current inventory contains
62 artifact/family rows, 50 bounded hidden literals, 839 persistence sites,
and 166 direct or selected-wrapper process boundaries. Both AST audits report
zero blocking and zero unknown sites. `completeness=complete` and
`phaseExit=passed` describe this inventory contract; the exact P0 phase
evidence remains in the P0 exit audit.

Short/long documentation parity is also closed independently: the complete
`short-long-route-matrix-v1.json` inventories every production Producer route
plus the user-facing workflows, binds each claim to executable evidence, and
generates
[the short/long executable matrix](12_SHORT_LONG_EXECUTABLE_MATRIX.md).
Unsupported and unqualified rows remain visibly blocked rather than being
counted as missing documentation.

The production Auto Edit controller now also carries a closed
`palmier-hybrid|mp4-only` delivery policy in request identity and durable
resume. MP4-only bypasses Palmier launch discovery, native-primary selection,
all working checkpoints, QC-repair publication, and the approved mirror; a
successful run retains a content-addressed zero-call receipt. Hybrid remains
the default.

## P1 — Minimum typed authority and render-graph foundation

Deliver:

- closed schemas for project revision, clause state, commit intent, request,
  discriminated operations, stage batch, projection, and receipt;
- `CompatibilityPictureLockV1` derived from both validated current cut
  authorities and exact plan/timeline identity;
- stable controller-owned IDs, including transcript word/correction identity;
- durable request coverage across cut/deferred treatment stages;
- expected-parent CAS, idempotency, conflicts, atomic stage promotion;
- durable local/Palmier commit saga and startup reconciliation;
- Ask Editor one-operation adapter and the minimum deterministic handler set
  needed to prove the path;
- minimum render nodes, invalidation receipts, revalidation, immutable inputs,
  and forced-full oracle harness;
- generation-scoped projection in shadow mode;
- adapters for every inventoried reader touched by the minimum slice;
- shadow comparison with current surgical edits.

Exit:

- generated schemas agree across languages and reject unknown/mismatched input;
- short and 14-minute plan-only fixtures retain 20+ supported clauses using the
  released minimum handler set; this is coverage/durability proof, not 20
  distinct product actions;
- every clause has exactly one state/disposition;
- mixed cut+treatment request defers and re-resolves correctly;
- timestamps land within one frame;
- every P1-released anchor survives or explicitly fails
  ripple/split/merge/removal;
- a removed dependency edge fails promotion;
- power loss at each durable boundary yields old head, exact child, or explicit
  reconciliation—never torn/false commit;
- fault at each Palmier saga state yields old, exact dual commit, or blocking
  reconciliation;
- startup tests Palmier and local observed heads at expected parent, exact
  reserved child, and foreign/partial state before it can report commit;
- restart loses/duplicates no operation;
- no unrelated plan diff;
- no render-performance claim is inferred from plan-only tests.

The exact implementation-level verdict and limits for these bullets are
retained in [the P1 exit audit](15_P1_EXIT_AUDIT.md). The P1 compatibility
scope passes all 13 exits; connected live Palmier qualification remains a
separate release gate and the revision store remains a migration shadow.

Full action vocabulary and UX breadth remain closed/unreleased. Each later
phase registers only handlers whose authority, invalidation, receipt, and
recovery fixtures pass; broad catalog completion follows P5.

## P2 — Picture lock and non-ripple speech repair

Deliver:

- enforced cut-only state and first-class workflow-selected picture-lock
  receipt, replacing the P1 compatibility adapter after parity;
- `PictureLockSupersessionReceiptV1` with parent→child lineage, unchanged
  mapping proof, and explicit clause supersession/recompile records;
- occurrence-aware phrase/word resolver;
- exact frame/sample/source anchors;
- deterministic candidate enumerator and governed alternate-take selection;
- explicit ripple impact;
- segmented cut video/dialogue nodes and handles;
- general L/J schema, lint, compiler, renderer, source proof, Palmier projection,
  and parity;
- segment speed/version and exact rational frame/sample semantics wired through
  compiler, anchors, fingerprints, refit, and proofs;
- pinned alignment runtime/model/cache/provenance;
- semantic-closure invalidation for transcript/content changes;
- dirty-window preview and seam QC.

Exit:

- early/middle/late repair, caption refit, L/J, and Palmier projection pass at
  every released rational FPS, normalized VFR, and multi-source fixtures;
- non-ripple duration/mapping outside the window is identical;
- adjacent frame-derived audio partitions have zero gap/overlap at every
  released rational FPS, and terminal pre-AAC PCM count matches `B(F)`;
- adjacent 44.1→48 kHz source ranges share `P(sourceSample)` boundaries with
  zero dropped/duplicated samples;
- canonical speed rational and resolved retime ranges match across TypeScript,
  Python, renderer, receipt, and Palmier projection;
- a P1 compatibility lock becomes first-class only after selected-policy
  approval and explicit clause migration/revalidation;
- child-lock treatment is recompiled/revalidated rather than silently reused;
- repeated-phrase ambiguity is caught;
- impossible local repairs return `NON_RIPPLE_IMPOSSIBLE`;
- alternate/L/J fixtures introduce no duplicate, click, or uncovered lip-sync
  drift;
- alignment is labeled bounded evidence, not sole audibility proof;
- ripple reopens picture lock and enumerates dependents.

Phase demo: early/middle/late repair plus one honest impossible case.

### P2 implementation audit — 2026-07-30

The complete implementation-level verdict and evidence are retained in
[the P2 exit audit](16_P2_EXIT_AUDIT.md). The exact stop-gate result is
**12 PASS / 0 BLOCKED for the released bounded P2 contract**.

The governed path now executes distinct
analyze → prepare → review → approve → execute phases. It binds exact V2
revision, plan, timeline-map, render-graph, candidate-media, automated-QC,
operator-selection, retime, caption, and child-lock authority. The selected
promotion preserves prior graphics, music, karaoke captions, and disjoint
repairs. Exact impossible cases use a separate durable `reopen` action that
moves `PICTURE_LOCKED → CUT_DRAFT`, clears picture lock, preserves the current
plan/graph/projection, and enumerates dependents without silently applying a
ripple.

The former two P2 blockers are now closed at their declared bounded scope.
The retained row-1 cohort passes 24/24 real-media cells: all eight exact
released rates × early/middle/late, with normalized VFR, multi-source
authority, caption refit, general L/J, exact outside picture/PCM, terminal
sample authority, and honest fail-closed Palmier disposition. Governed
alternate-take orchestration reruns its pinned detector and derives the unique
later take; the caller may provide only a normalized `visualSpeechRegion`, not
a candidate or retake identity. Selection now binds controlled visual-seam
evidence through promotion.

The visual acceptance is selected-source A/V temporal mapping inside the
caller-supplied ROI, not face/mouth detection, phoneme inference, lip-reading,
audibility, or creator footage qualification. Picture-changing execution is
also deliberately restricted to the 30 fps/48 kHz/single-source/speed-1/
zero-residual terminal-silence-reclaim subset. Any caption, graphics, b-roll,
title-card, transition, baseline/reframe/punch-in, music, gain/enhancement, or
unknown lane fails closed rather than being erased. Native sample-exact or
connected Palmier remains unsupported; the picture result is
reference-media-only. General layered dirty-window repair and hybrid delivery
remain P5 work.

## P3 — First-class captions — released

Deliver:

- `CaptionTrackV1`;
- word-boundary splitting and bounded alpha shards;
- one SRT/burned/Palmier compiler;
- migration of current renderer/master/assemble, short gates, fingerprints,
  authority hashes, Audit B, and legacy `captions`;
- separate caption-content digests and timing/placement cue fingerprints plus
  global correction authority;
- scene suppression, destination safe zones, and Palmier bindings;
- chapter compilation from the same semantic/timing authority.

Exit:

- arbitrary range karaoke/style;
- caption-only edit rebuilds only caption/preview nodes;
- repeated-name correction hits the right occurrence;
- SRT/burned output matches;
- chapters bind the same timeline and survive non-ripple repair;
- no missing/duplicate/ghost words after cut/speed changes;
- speed/timeline-map changes rebuild every cue/placement node whose resolved
  range or relevant map slice changes, including shifted downstream cues, even
  when text content is unchanged.

Phase demo: karaoke one phrase, correct one repeated name, prove all other
caption/base nodes unchanged. The combined real-media proof is
`test_p3_caption_phase_demo`; its retained result is the `phaseDemo` row in
`scripts/producer/tests/fixtures/p3-caption-shard-traces.json`.

Release evidence is retained in
`scripts/producer/tests/fixtures/p3-caption-shard-traces.json`. Real ffmpeg
renders over synthetic lavfi short `30000/1001` and long-form `24000/1001`
media fixtures each reuse the unchanged shard, render only the corrected
shard, match a forced-full decoded-frame oracle, preserve the caption-free
base, and stream-copy identical mastered audio. This is reproducible
incremental-media evidence, not creator-footage or full-project evidence.
The reproducible focused rerun on 2026-07-30 passed **27 Python cases** across
`test_p3_caption_phase_demo`, `test_caption_shards`, `test_caption_compile`,
and `test_caption_repair_revalidation`, plus the four TypeScript contract
scripts for chapters, operations, schema parity, and stable word identity.
The word-index contract now also proves that a quoted replacement is not
misclassified as source transcript text and that an explicit timestamp more
than two seconds from every matching occurrence fails closed. Those cases
include real alpha media, first/last-frame and one-frame cues, RTL/CJK
font-closure, safe-bound authority, exact shard invalidation, and non-ripple
chapter revalidation. The older aggregate “146 tests” was not backed by a
retained command manifest and is therefore not used as release evidence.

## P4 — Governed custom motion and assets — released

Deliver:

- catalog scenes wrapped as `SceneSpecV1`;
- closed parametric grammar;
- project-scoped bundles and immutable resolver;
- sealed coding-agent staging and local runtime closure;
- target-FPS graphics/proof/cache support;
- measured/proved capability authority with missing/stale/unmeasured/error
  fail-closed behavior;
- render-unit/shared-mask contract and full-scene oracle;
- animation map/filmstrip proof;
- bounded parallel render-unit cache and Palmier bindings;
- `AssetRecordV1`, sandboxed acquisition/generation, rights/consent/
  attribution/expiry gates;
- real thumbnail, cover, and loop-frame deliverables;
- typed scene/title, transition, SFX, and grade handlers;
- separately gated continuous-reframe/animated-PIP workstream;
- creative/delight proposer.

Exit:

- at least 12 briefs cover overlay, takeover, presenter hole, masks/blends,
  particles, real-copy overflow, released aspects, and released FPS;
- fire/sparkles two-card case passes;
- exact delivery-pixel own-screen geometry and real-footage text
  contrast/backing fixtures pass;
- clean-process and randomized-seek renders match every decoded frame;
- right-copy repair renders one unit;
- ordered units match full-scene oracle;
- timing move reuses scene media;
- governed OCI renders prove OS-level network denial; direct local renders
  disclose that denial as unproved;
- package reference passes TS/Python schema, lint, renderer, CLI, provenance,
  QC, and Palmier consumers;
- malicious media, expired rights, missing attribution, and untrusted metadata
  fail closed;
- thumbnail/cover/loop are hash-bound deliverables;
- transition/SFX/grade changes have correct local closures;
- tracking/PIP remains unsupported unless every no/multi/occluded-face,
  screen-share, boundary, motion, canvas/FPS, and override fixture passes.

Phase demo: author two-card fire/sparkles, change only right copy, replace one
unit.

### P4 release boundary and evidence — 2026-07-30

The released operator surface is the production
`scripts/producer/graphics/scene_package_cli.py` workflow invoked directly by
Codex or Claude Code. It stages a closed authoring packet, resolves an exact
catalog source or project bundle by ID and SHA-256 (never `CURRENT`), validates
and durably packages `ScenePackageV1`, renders bounded scene units, reobserves
the actual media bytes, and includes proved baked-regenerable Palmier
projection/readback in the canonical render receipt. This is not an Ask Editor
UI release and it does not claim native After Effects/Palmier keyframe-layer
parity. Local CLI execution removes ambient secrets and rejects remote
resources and network-capable bundle source, but it does not prove OS-level
network denial. That stronger claim applies only when
`SNIPER_RENDER_IMAGE_ID` selects the governed networkless OCI render path.

The opt-in production CLI acceptance
`scripts/producer/tests/live_scene_package_cli_acceptance.py` passed a real
two-card fire/sparkles package in the fresh 2026-07-30 closure: both
independently cacheable
alpha units rendered and fully decoded, the exact bundle admission survived
render, the create-once receipt matched the returned canonical bytes, and both
Palmier unit bindings read back against the actual media. The separate live
scene oracle acceptance passed clean-process and randomized-seek frame
comparison plus ordered-unit/full-scene color and alpha SSIM thresholds. The
retained machine evidence is the exact **368-row** composition/rate matrix
(46 registered compositions × eight released exact rates), the **12-brief**
scene matrix covering both aspects and all eight rates, and a fresh 141-file
P4 exit closure. Its geometry, copy/timing-repair, and typed-treatment cohorts
completed in `8.171`, `204.270`, and `5.278` seconds respectively. Focused
contract, asset, authoring, render,
readability, deliverable, treatment, creative-proposer, and Palmier tests are
also green; the older aggregate “100 tests” was not backed by a retained
command manifest and is therefore not used as release evidence. All eight
closed treatment operations have local invalidation fixtures.

The authoring stage owns a mode-`0700` attempt directory and enforces an
application path contract, but its receipt deliberately records
`osSandboxProved: false` and `modelWriteIsolationProved: false`. External
timed media, still images, static SVG, and single SFNT fonts still cross the
separate non-root, networkless media admission boundary before publication.

This release excludes continuous subject reframe and animated PIP; those remain
unsupported behind their separate fixture gates. It also does not qualify the
90-minute `LF-14-A` hypothesis, the monolithic short-form graphics repair path,
or the broader P0/P1 authority and render-graph exits.

## P5 — Optimized render graph and hybrid Palmier delivery

Deliver:

- optimize P1 graph/receipts;
- reusable base/stem/scene/caption nodes;
- one-encode-per-dirty-window compositor;
- memory-aware concurrency and invariant-diff QC;
- migrate every reader to projection receipt before changing authority;
- Palmier scene/caption/base/b-roll/audio revision lanes;
- baked-regenerable fallback where native translation is not proved;
- complete versioned readback, unknown-field fail-closed comparison, audio
  authority, paging, reconciliation, crash/resume, explicit-timeline export.

Exit:

- one-scene change in 14-minute/50-scene project renders one scene and zero full
  base encodes during review;
- 24 overlays do not cause three full-duration passes;
- dirty output matches forced-full oracle;
- timing move dirties old/new windows only;
- cancellation, disk failure, stale parent, and bad cache cannot promote mixed
  generations;
- representative short/long projects have 100% ledger/readback disposition and
  zero unexplained mutations;
- export fully decodes from the bound timeline with exactly one encoded audio
  stream, a separate current `audioRouteAuthority` receipt proving exactly one
  audible timeline route, and a hidden exact-master reference;
- editable-build frames/timing/audio match frozen tolerances or carry explicit
  approved approximations;
- one-scene repair replaces only its clip;
- apply-before-disconnect and manual-edit preservation pass;
- channel-normalization dependency mutation, exact rational FPS,
  frame/sample-duration authority, and multi-segment AAC padding fixtures pass.

The exact implementation-level verdict is retained in
[the P5 exit audit](17_P5_EXIT_AUDIT.md): **6 of 11 exits pass**. The exact
14-minute/50-scene one-unit private repair, 24-overlay one-pass compositor, and
complete 36-cell mixed-generation fault cohort now pass. The five connected
Palmier exits remain blocked.

Passing the remaining P5 exits would release hybrid delivery, not native
parity. Hybrid delivery is not released by the current 6-of-11 result, and
native cut/ripple remains off until its separate live short/long fidelity,
timeout, readback, and export gate.

Post-P5 demo: cut repair, range caption, two-card scene, one-unit repair,
invariants, hybrid Palmier update, and one final export on one project.

### P5B — Typed command and UX breadth

Expand the closed operation union and UI only across lanes whose capability,
invalidation, receipt, recovery, and Palmier-disposition gates have passed.
Contract tests require every advertised action to reach a deterministic handler
or return a truthful `unsupported`; there is still no general model writer.

## P6 — Verified reference-style execution

Deliver:

- inspired and verified-mimic modes;
- transactional style-pack lifecycle across planning, authoring, dependencies,
  and QC;
- grammar/event bindings;
- V1 compatibility and V2 migration;
- rights/provenance;
- frozen objective tolerances and independent review;
- distinct UI/provenance labels.

Exit:

- three materially different packs have zero unclassified/waived critical
  items; every noncritical waiver is explicit;
- reviewer disagreements are adjudicated;
- every realized mechanic has a proved scene;
- unsupported mechanics disclosed before execution;
- no identity asset copied without rights;
- unseen raw footage meets frozen objective tolerances and three-reviewer
  no-regression threshold;
- onboarding time is separate from approved-pack editing time.

The exact implementation-level verdict is retained in
[the P6 exit audit](18_P6_EXIT_AUDIT.md): **0 of 7 exits pass**. Current
reference study/profile machinery is released only as reference-inspired
guidance. The offline schema-V1 pack compiler is preparation work, not a
production-consumed verified-mimic authority.

## P7 — Directional pilot

Run six frozen projects:

| Project | Form/canvas | Duration | Challenge |
|---|---:|---:|---|
| S1 | 9:16 light | 45–60s | cuts, karaoke, title |
| S2 | 9:16 produced | 60–90s | multi-scene one-brief |
| S3 | 9:16 full | 45–90s | verified mimic |
| L1 | 16:9 produced | 12m | talking head, pacing, cards |
| L2 | 16:9 full | 13m | screen share, b-roll, captions |
| L3 | 16:9 full | 14m | reference-heavy custom scenes |

L1–L3 are independent complete `LF-14-A` jobs, including one bounded `C2-A`
scene each.

Each project performs initial build, copy/color repair, timing move, caption
correction, scene add/remove, broad structural fallback, and optional Palmier
editable repair/export/exact-master comparison.

Use separate comparator arms:

1. capability acceptance for new features;
2. same approved plan for renderer speed;
3. same parent/edit for incremental versus forced-full.

Prospectively classify organic requests before rendering as local, broad,
unsupported, or operator-intervention. Report eligibility, fallback-inclusive
latency, fallback cost, and intervention.

Go/no-go:

- zero lost clauses, mixed/stale promotions, data loss, or unexplained Palmier
  mutation;
- dirty/full equivalence on every eligible repair;
- all destinations export/decode correctly;
- style jobs meet pre-registered objective/blind-review thresholds;
- all three long autopilot jobs meet the bounded 90-minute hypothesis.

Six projects are falsification/variance evidence, not release qualification or
p95.

## P8 — Untouched confirmation

Freeze the release candidate and pre-register an untouched, claim-sized
cohort. The first 90-minute claim applies only to `LF-14-A`; every run must pass
preservation, QC, and export gates, and failures stay in the denominator.

Code, prompt, model, runtime, hardware, or workload changes invalidate the
cohort.

Do not convert a small cohort into a p95/95%-reliability claim. A separately
powered reliability study is required; roughly 59 independent
zero-critical-failure runs are needed merely to bound a 5% failure rate at
one-sided 95% confidence, before a proper latency-quantile design.

The exact retained-evidence verdict is in
[the P7/P8 qualification audit](19_P7_P8_QUALIFICATION_AUDIT.md). P7 has
**0/6 required projects, 0/4 shared protocol requirements, and 0/5 go/no-go
gates**. P8 has **0/3 executable confirmation requirements**; its no-p95
non-claim is truthful, but no untouched cohort exists.
