# Current-system inventory and extension map

> **Status:** Audited starting point for the proposed architecture. File counts
> and wiring observations are repository facts as of 2026-07-30; they are not
> release claims.
>
> [Back to the plan index](../COMMAND_DRIVEN_EDITING_EXECUTION_PLAN.md) ·
> [Next: product contract and workflows](01_PRODUCT_AND_WORKFLOWS.md)

## Why this chapter comes first

Implementation begins by tracing the current authorities, readers, writers,
receipts, fingerprints, and timings. The target architecture must extend those
seams or replace them behind a proved compatibility boundary. It must not create
a second cut authority, refit engine, cache, durability subsystem, or graphics
capability truth.

Before substantial implementation:

1. inventory every canonical artifact and every reader/writer/call site;
2. capture a current full-path cold and warm trace on named hardware;
3. record stage wall time, CPU, memory, disk, browser/ffmpeg concurrency, cache
   decisions, retries, and outputs;
4. freeze representative short and long fixtures;
5. classify each proposed module below as reuse, extend, adapter, or replacement.

The first trace is a baseline, not evidence that the target is fast enough.

## Existing authority and cut-review contract

The shipped cut gate already has two distinct hash-bound receipts:

| Existing artifact | Current responsibility | Target treatment |
|---|---|---|
| `.sniper-cut-approval.json` | Deterministic previsual/cut-wall receipt through `CutApprovalReceipt` in `src/app/api/producer/auto-edit/cut-approval.ts` | Reuse as one input to the compatibility picture-lock adapter |
| `.sniper-cut-review-approved.json` | Independent clean-review authority through `CutReviewApprovalReceipt` in `cut-review-approval.ts` | Reuse as the second input; it requires exactly two clean reviews |
| `edit_plan.json` | Current human/editorial plan authority | Keep authoritative during shadow migration |
| `authoring-stage.ts` | Requires both cut authorities before downstream authoring | Preserve this prerequisite; never weaken it to one receipt |

The temporary P1 `pictureLockHash` is derived from both existing cut authorities,
the exact approved plan/timeline identity, and their validation result. P2 adds
the first-class selected workflow-state picture-lock receipt and child-lock
lineage. The adapter is not permission to treat one current receipt as complete
picture lock.

## Existing timing and cut machinery

| Primitive | What already exists | Required action |
|---|---|---|
| `scripts/producer/compile_timeline.py` | Speed-aware source/output compilation; cut-track order is output order | Reuse as the compiler kernel and specify exact rational/frame/sample projections around it |
| `scripts/producer/cut_speed.py` | Exact speed/audio-tail replacement behavior | Reuse; add segment-version and invalidation bindings |
| `scripts/producer/edit/plan_refit.py` | Old output → source → new output refit; removed spans resolve in old-output order | Reuse; freeze this behavior in the refit contract and fixtures |
| `scripts/producer/edit/refit_authority.py` | Pending receipt, exact-byte promotion, and startup recovery | Extend its durability pattern; do not invent a parallel refit authority |
| `src/app/api/_lib/plan-refit-transaction.ts` | TypeScript transaction seam for plan refit | Include in reader/writer inventory and cross-language contract tests |
| `scripts/producer/assemble.py --auto-base` | Existing assembly compatibility path | Adapt behind render-node receipts; retain as comparator until parity |
| `scripts/producer/graphics/frame_oracles.py` | Existing frame-oracle helpers | Reuse in dirty/full and scene-unit equivalence tests |
| `scripts/producer/edit_scope.py` | Current edit-scope classification | Extend into authorized dependency closure |
| `scripts/producer/gate_policy.py` | Current gate-policy machinery | Reuse rather than creating a second release-policy engine |

The refit specification must preserve the current traversal rule: map an old
output position to source, then into the new output; when content is removed,
search the nearest surviving content in **old output order**, not source-file
order or a newly sorted timeline.

## Existing J-cut and speed behavior

`compile_timeline.py` already models `audioLeadMs` as picture-invariant audio
lead, and `cut_speed.py` already has exact audio-tail replacement behavior.
General L/J support therefore extends current compiler/render/proof/Palmier
coverage. It is not a new timing engine.

Speed is also already meaningful to compilation. The target must make its
authority explicit:

- speed is part of the segment version and compiled timeline-map hash;
- source-relative and output-relative anchors have distinct semantics;
- a speed change invalidates every affected content-relative placement even
  when a stable segment ID survives;
- picture stays on integer delivery frames while audio handles remain integer,
  potentially subframe, samples.

## Current short/long asymmetry

The current product is genuinely mode-aware: long-form has dedicated planning,
smooth-motion grammar, front-loaded pacing envelopes, SRT/chapters, and
graphics-only/audio-only retained paths; shorts have burned-caption, safe-zone,
and split-layout rules.

Three product gaps remain explicit rather than being hidden under “one engine”:

1. short graphic repairs still use the monolithic graphics path, although
   caption-only repairs now reuse the caption-free composite and rebuild only
   dirty bounded alpha shards;
2. `scripts/producer/graphics/pip_takeover.py` exists but is unwired and
   `needsPip` is rejected;
3. `reframe.track` is reserved and accepts only `false`.

The former runtime-closure gap is closed: all 46 registered comps use pinned
vendored GSAP, and a real offline render/decode/measurement probe now produces
46 complete capability rows. Missing, stale, unmeasured, or future
`renderError` rows still fail closed.

The retained long-form graphics/audio fast paths are useful mechanism evidence,
not proof that shorts or a complete 10–14-minute build are optimized.

The complete route and operator-workflow comparison is generated from the
closed machine contract in
[Short-form versus long-form executable matrix](12_SHORT_LONG_EXECUTABLE_MATRIX.md).
Its test inventories every production `route.ts`, requires evidence for every
route group and workflow row, and fails if the generated document drifts.

## Existing render and graphics primitives

| Primitive | Current value | Boundary |
|---|---|---|
| `scripts/producer/fingerprints.py`, `render_effect_registry.py`, `render_stage_roots.py` | Base/video/audio/graphics dispatch plus a closed 31-row plan/manifest effect registry and compiler-owned graph roots; long-form recompose and legacy-caption suppression are explicit cross-lane base inputs, while the video fingerprint still binds the whole `cutTrack` | Retain as the current compatibility comparator; split into finer render nodes only behind the short/LF-14 parity oracle |
| `scripts/producer/graphics/comp_capabilities.py` | Typed capability representation | Reuse |
| `scripts/producer/graphics/comp_catalog_probe.py` | Measured catalog evidence | Reuse and make freshness/completeness release-critical |
| `templates/motion/comp_capabilities.json` | Current measured capability artifact | Treat measured values as physical truth, not declarations in scene JSON |
| `graphics_render.py`, `sealed_graphics_render.py`, `render_cache.py` | Asset proof, sealed render, and cache wiring | Extend for project-scoped bundles and render units |
| `graphics/delivery_geometry.py` and `audit/audit_placements.py` | Exact delivery geometry and placement auditing | Preserve as release gates |

A scene manifest declares an interface—variables, element roles, dependencies,
and intended render mode. It does not prove canvas size, aspect, opacity,
bounding box, fade class, terminal state, or renderability. Those come from a
fresh measured/proved capability artifact.

## Released P3/P4 incremental surfaces

Two later-phase surfaces are now real even though the complete product and
later qualification exits remain blocked.

**P3 range captions are released.** `CaptionTrackV1` compiles stable word
ranges into SRT, chapters, burned output, and baked-regenerable Palmier
projection from one timing authority. Burned captions are independently
cacheable RGBA MOV shards. A caption-only correction retains the caption-free
picture/graphics composite, renders only the changed shard, composites the
proved shards once, and stream-copies mastered audio. Retained real-ffmpeg
traces over synthetic lavfi short `30000/1001` and long-form `24000/1001`
fixtures match forced-full decoded picture while preserving unaffected shard
and audio identities; they do not claim creator-footage or full-project proof.

**P4 governed project-scoped motion is released through the direct CLI.**
`graphics/scene_package_cli.py` stages an authoring packet, validates or
packages an exact `ScenePackageV1`, and renders catalog or content-addressed
project bundles into proved full-scene or unit media. The fire/sparkles
two-card live CLI acceptance renders and decodes both alpha units, persists a
create-once canonical receipt, then projects and reads back actual
baked-regenerable Palmier media. Asset bytes, rights/consent/expiry/
attribution, real-footage readability, exact source generation, unit
equivalence, deterministic seeking, and bounded workers all fail closed.
Local CLI renders strip ambient secrets and lint out remote/network-capable
bundle source, but they do not prove OS-level network denial. Only the
governed `SNIPER_RENDER_IMAGE_ID` OCI branch carries that networkless proof.

That P4 release is the Codex/Claude Code → production CLI workflow, not an Ask
Editor UI route. The mode-`0700` authoring attempt proves only an application
path boundary; its receipt explicitly says that OS sandboxing and model write
isolation are not proved. Continuous subject tracking and animated PIP remain
unsupported. Neither P3 nor P4 qualifies the 90-minute `LF-14-A` hypothesis or
turns the current headless primitives into a complete production controller.

## Headless primitives: valuable but not a finished controller

The audited `scripts/producer/headless/` tree contains 286 files. It supplies
substantial reusable mechanism evidence: durable admission, idempotency,
controller ownership, fences, immutable generations, receipts, snapshots,
sealing, resource controls, and recovery helpers. Graphics code already imports
some of these mechanisms.

It is not yet a general cross-lane render DAG or a fully released production
worker/publisher. The repository's own
`docs/producer/HEADLESS_EMPIRICAL_GATE_LEDGER.md` and
`HEADLESS_MP4_95_CONFIDENCE_EXECUTION_PLAN.md` keep integrated worker lifecycle,
final fence composition, publisher/`CURRENT`, and terminal recovery gates
blocked.

Therefore:

- reuse proved headless primitives behind adapters;
- do not call the headless tree a complete controller;
- do not create another durable admission, sealing, or fencing design;
- do not let its experimental `CURRENT` become a competing project revision
  head without an explicit, proved authority migration;
- keep the proposed render graph a dependency/execution model, not a second
  publication authority.

## Reuse, extend, and replace

| Area | Decision |
|---|---|
| Current cut receipts/reviews | **Reuse + adapt** into compatibility picture lock |
| Timeline compiler, speed, L/J basis | **Reuse + extend** with normative timing and proofs |
| Plan refit and recovery | **Reuse + extend**, preserving old-output-order traversal |
| Coarse fingerprints | **Adapt incrementally** into render-node fingerprints |
| Gate policy, scope, frame oracles | **Reuse** |
| Measured comp catalog and asset proof | **Reuse + harden** freshness/fail-closed rules |
| Headless durability primitives | **Reuse selectively**; do not claim finished controller |
| Global/ghost caption behavior | **Replaced for explicit tracks** by released `CaptionTrackV1`; keep the legacy adapter only for plans without one |
| Open natural-language plan mutation | **Replace behind compatibility adapter** with typed operations |
| Full-duration multi-pass render routing | **Replace incrementally** after dirty/full oracle proof |
| Palmier exact mirror | **Keep**; add separately gated editable hybrid bindings |

## Baseline and migration deliverable

P0 produces a machine-readable inventory containing:

- artifact/schema/version and authority owner;
- every reader, writer, mutation route, and promotion point;
- current hash/fingerprint inputs;
- durability and recovery behavior;
- cold/warm timing and resource trace;
- planned reuse/adapter/replacement disposition;
- parity fixture and rollback/removal condition.

No old reader is removed and no new authority becomes canonical until shadow
projection, exact receipt binding, recovery tests, and output parity pass.

The machine-readable authority inventory is now marked `complete` and its
inventory sub-gate is `passed` within the declared production-source and
primitive scope. Its baseline is independently measured:
`baseline.evidencePaths` names closed
cold/warm traces for both the 45-second short and the 20,139-frame LF-14
fixture. The checker reparses both traces with `validate_trace_document`; a
missing, malformed, synthetic, duplicate-mode, or unclosed trace invalidates
the `measured` claim.

The 45-second short cold run took `45,407 ms`; its immediate warm repeat took
`30,175 ms`. Both decoded exactly 1,350 frames and 2,159,616 audio samples per
channel, and both QC reports passed with zero warnings. Full-frame repeat proof
passed at `0.997547469` mean SSIM / `0.992165` minimum SSIM with exact decoded
audio.

The LF-14 cold run took `566,941 ms`; its immediate warm repeat took
`443,057 ms`, saving `123,884 ms` (`21.851304%`). Both decoded exactly 20,139
frames at `24000/1001` and 40,318,976 audio samples per channel with identical
decoded audio. Full-frame repeat proof passed at `0.997635465` mean SSIM /
`0.986361` minimum SSIM. The timeline map ends at exactly `839.964125`
seconds. Both LF-14 QC reports had zero failures but retained two warnings:
51 detected freeze/hold intervals, longest `51.89 s`, requiring confirmation
as screen-share/slide holds, and one luma jump at `167.75 s`. This is
current-path comparator evidence, not a visual-QC-clean claim, the 90-minute
product SLA, or dirty-fragment proof.

`scripts/producer/current_system_inventory_check.py` machine-checks the bounded
authority-bearing production roots (`scripts/producer`, `src/app/api`,
`src/lib/producer`, and `src/lib/server`). The 2026-07-30 retained audit scans
1,227 Python and TypeScript source files and requires every direct occurrence
of each declared authority path token to have one explicit disposition. All
335 declared matches across 62 artifact families are disposed as owner, reader,
writer, reader/writer, launcher, or non-authority. A new literal call site, a
removed token, a stale listed file, or an unclassified match fails the audit.

The previously named gaps now have explicit rows: current `.render-graph-v1`
generations; template/operator approval; mutation lease and promotion
reconciliation; assembled-media, QC-round, preview-invalidation, and surgical
review receipts; Palmier working/candidate, desktop, live-build, and sync
authorities; the full caption-render receipt; and the scene-authoring-stage
receipt.

The checker also performs a bounded discovery pass over quoted `.sniper*`,
`.palmier*`, and `.render-graph-v1` path literals. The retained audit finds 49,
and every one binds to an artifact row whose own path tokens name that literal.
The former 13-entry backlog is zero. Its nine persistent families now have
reader/writer, lifecycle, promotion, durability, migration, and removal
dispositions; its temporary families are explicit derived/non-authority rows.
A new hidden literal, a stale disposition, a binding to an absent artifact, or
a binding that bypasses that artifact's token audit fails closed.

The mixed `.sniper-learning` root is no longer one vague row. It is split into
immutable doctrine/pipeline run snapshots, template-usage history, create-once
observations, the append-only geometry residual ledger, and retained Palmier QC
history. Admission transaction state, immutable reference admission,
Auto Edit job/launch/log state, quality policy, run-state projection, and the
cut-repair staging cache also have separate rows.

Dynamic and non-hidden discovery now has two additional controls. A retained
manual evidence contract source-checks 10 reviewed records across 29 files for
known digest-derived filenames, caller-supplied roots, external stores, and
non-prefixed authorities. Separately, Python's AST and the TypeScript compiler
AST enumerate the declared filesystem persistence primitives and direct or
selected-wrapper process boundaries in the four roots.

The retained filesystem scan finds 837 calls: 510 Python and 327 TypeScript.
Artifact writers bind 784. The remaining 53 calls across 18 files are retained
reviewed exclusions: 6 test/fixture sites, 28 documentation/build sites, and 19
ephemeral scratch/cache sites. The separate process-boundary scan finds 164
calls: 130 bind to artifact or tool-execution families and the remaining 34
across 24 files are reviewed exclusions: 11 documentation/build and 23
probe/cache sites. Both scans report zero blocking and zero unknown sites.

The formerly blocking direct writers now bind through two explicitly
transitional families: governed production state and editor delivery outputs.
Those rows preserve each member's existing module-local promotion and
durability while requiring eventual replacement with first-class typed
artifacts. Process boundaries are also split honestly: generic command
adapters, macOS picker/open/reveal adapters, a stdout-only Palmier preflight,
and FRAME.IO review reports. The last category records the non-obvious fact
that `review.py` writes mutable `results.json` and `report.html` beside the
selected media.

The checker emits exact file sets, site counts, stable site digests, and the
first 40 `path:line:callee` examples. A newly unbound production writer or
process boundary lands in a blocking category, so `completeness=complete`
cannot survive drift. The bounded scanner still does not infer arbitrary
custom-wrapper call graphs, per-argument output dataflow inside every spawned
program, database/API mutations, or sources outside the declared roots. Those
limits are retained explicitly; family binding is an inventory/migration
contract, not proof that every legacy output is already content-addressed.

That audit also corrected three stale inventory claims:

- compatibility projections publish under
  `producer/compatibility_projections/`, not the previously documented
  `.sniper-compatibility-projections/`;
- the QC-approved final is consumed by `palmier/master.py`; `palmier/sync.py`
  consumes the already-bound sync request rather than reading the QC sidecar;
- compatibility projection publication is performed by
  `compatibility-picture-lock.ts`; the timeline-projection module compiles its
  temporary payload but does not publish the project artifact.

Tests and documentation are excluded from the source scan so explanatory
mentions do not masquerade as production call sites. Indirect module calls are
still named in the artifact reader/writer lists; the exact-token scan is the
drift detector for filesystem authority access, not a claim that text search
proves a dynamic call graph.
