# P0 exit audit

> **Verdict: COMPLETE for the stated P0 scope — 15 of 15 exits pass.**
> This is not whole-product, After Effects, native Palmier, or performance-SLA
> qualification.
>
> **Evidence date:** 2026-07-30
>
> [Previous: legacy regression gates](10_LEGACY_REGRESSION_GATES.md) ·
> [Back to the plan index](../COMMAND_DRIVEN_EDITING_EXECUTION_PLAN.md) ·
> [Next: short/long executable matrix](12_SHORT_LONG_EXECUTABLE_MATRIX.md)

This is the evidence ledger for the P0 exits in
[the implementation roadmap](07_IMPLEMENTATION_ROADMAP.md#p0--make-current-contracts-truthful-and-safe).
No single sub-gate establishes the phase exit; the complete 15-row evidence
set does.

## Verdict rules

- **PASS** requires current executable enforcement plus a passing test or a
  retained, freshness-checked evidence artifact.
- **BLOCKED** means at least one part of the exit lacks that proof. A mechanism,
  design, or unit test for one path does not prove a universal statement such
  as “every,” “all,” or “zero.”
- A narrower passing sub-gate is recorded under a blocked exit so that the
  remaining work is not confused with reimplementation.

## Exact exit table

| # | P0 exit | Verdict | Executable or retained evidence | Scope limit |
|---:|---|---|---|---|
| 1 | Current cross-language enums/contracts agree | **PASS** | `producer-schema-enum-parity.test.ts`, `producer-schema-parity.test.ts`, `producer-contracts-v1.test.ts`, and the lane-specific schema-parity tests exercise the released shared JSON Schema, TypeScript, and Python surfaces. Closed parsers reject unknown fields and the canonical enum arrays match their schemas. | This is the released shared contract surface, not authorization for schema-only actions. |
| 2 | Mutation tests cover every current render-affecting field | **PASS** | `render-effect-registry-v1.json` is a closed, schema-checked registry with 31 rows and 42 generated mutations covering every released public plan/manifest root plus the nested cross-lane patterns. `render_effect_discovery.py` walks 204 current imported/path-invoked renderer files, including relative imports and subprocess stages, and audits 263 literal reads across 63 files. It fails on an unregistered reader, stale exception, or path-invoked Python outside that closure. `current_render_toolchain.py` hashes 210 transitive Python files instead of all 775 current non-test Producer Python files; its complete identity has 269 inputs including all 46 composition HTML files. `render_effect_registry.py` rejects unknown and unreleased public roots before lint/render/assemble, and the registry/toolchain tests prove exact compiler roots plus exclusion of unrelated QC/ingress code. | This closes the current Python renderer document surface and avoids invalidating every render for unrelated Producer changes. A future root, reader, dynamic loader, or subprocess convention must join discovery and the mutation gate before release; private `_` execution metadata remains intentionally outside public plan vocabulary. |
| 3 | Graphics cannot cause stale base reuse through recompose/suppression | **PASS** | `graphics_base_effects.py` projects only long-form recompose and legacy-caption suppression dependencies into base/video fingerprints and `plan.base`; ordinary scene copy and `presenterFrame` alpha/format changes stay scene/composite/final-only. Generated cases cover ordinary copy, presenter MP4→MOV, rail side/timing, own-screen and explicit suppression, and cut-driven `exitOnCut`. `test_assemble.py` and `test_final_provenance.py` prove dispatch and base-caption behavior. Fresh real-media controls under `artifacts/p0-render-effect-parity-canonical-closure-v1/{short,lf14}` bind toolchain `1c1898a4…` and registry `8f8bea83…`; both dirtied only scene/composite/final, reused source/timeline/base, and matched isolated forced-full output by byte-identical final SHA-256, exact FrameMD5, decoded PCM, clocks, and 1,394/20,139 decoded frames. The short final hash is `ad7592ea…`; LF-14 is `b7580bae…`. | This proves the released ordinary-graphic dirty closure on the retained short and LF-14 controls. Every future render-affecting reader or invalidation change must rebind the toolchain/registry and rerun its applicable forced-full oracle before release. |
| 4 | All production comps render/decode offline at every measured/released FPS | **PASS** | `hyperframes-rate-matrix-v1.json` retains the complete 46-composition × 8-rate cross product: 368 browser render and full-decode probes at `24000/1001`, `24`, `25`, `30000/1001`, `30`, `50`, `60000/1001`, and `60`. `comp_rate_artifact.py` checks source/tool/capability freshness, exact rational stream rates, codec/alpha/canvas, decoded frames, and receipt hash; `test_comp_rate_matrix.py` passes. | This proves only the graphics-comp catalog at measured/released rates. The broader producer/Palmier FPS matrix remains blocked. |
| 5 | Source mutation during snapshot/decode cannot promote | **PASS** | `external_media_snapshot.py` rejects mutation during copy; the approved-image probe rehashes its immutable snapshot before and after full decode. `external-ingress-registry-v1.json` closes the current surface at 10 families, 24 discovered boundaries, 24 exact owners, and 5 executable invariants. Released render/assemble/Palmier CLIs require admitted authority by default; live-build media import is disabled; reference VTT and scene assets have separate retained authority. Current-render staging, storage, verification, activation, and rollback rehash the exact source-set receipt and snapshots. `test_current_render_graph_candidate.py` proves mutation during review cannot promote, while registry, ingress, Palmier, reference, scene-package, and source-gate tests fail on each removed guard. | Path-based host consumers still have a descriptor-to-subprocess verify/use interval. Mutation there can fail or alter that individual process, but the result cannot activate because final promotion rehashes source authority. |
| 6 | Malformed codec, huge dimensions/frame count, truncated stream, archive bomb, and decoder hang fail in sandbox | **PASS** | `p0-adversarial-ingress-v1.json` is a freshness-checked live cohort against the approved image. It rejects an unknown codec, 8194-pixel dimension, declared 2,000,001-frame stream, truncated MP4, a real decoder exceeding the 90-second bound, and a 129 MiB sealed-manifest expansion. Every row records the intended failure class, publishes no admission receipt, and proves zero retained probe containers. `test_p0_adversarial_ingress_artifact.py` checks source closure, exact case completeness, error semantics, publication, and cleanup. | The cohort proves the listed released media/archive boundaries. It is not a claim that arbitrary future decoder vulnerabilities are impossible. |
| 7 | MP4-only runs make zero Palmier calls | **PASS** | `deliveryPolicy` is a closed, request-identity-bound Auto Edit authority. `auto-edit-mp4-only-delivery.test.ts` drives the production launch and pipeline with every Palmier adapter instrumented: launch discovery/guard, native-primary selection, cut/plan/revision/render and QC-repair checkpoints, and the approved mirror all remain at zero calls. Successful delivery publishes an immutable content-addressed receipt bound to run ID, request key, final hash, the protected boundary set, and `observedPalmierAdapterCalls=0`. Existing Palmier guard, checkpoint, primary, QC, and pipeline-resume tests preserve the hybrid default. | The guarantee applies only to an explicitly selected `mp4-only` request. `palmier-hybrid` remains the backward-compatible default and intentionally retains Palmier behavior. |
| 8 | Short/long docs match executable behavior | **PASS** | `short-long-route-matrix-v1.json` is a closed, complete story-form contract covering all 37 production Producer routes plus 11 operator workflows. Every row records short/long status, exact behavior, blockers, incremental boundary, Palmier boundary, and named executable evidence. `short-long-route-matrix.test.ts` inventories every `route.ts` exactly once, checks every workflow entrypoint/evidence path, and byte-compares the generated `12_SHORT_LONG_EXECUTABLE_MATRIX.md`. | Passing documentation parity does not release rows explicitly labeled `compatibility`, `unqualified`, or `unsupported`; short graphics, PIP, reframe, hybrid Palmier, style mimic, and the long-form SLA keep their exact status. |
| 9 | Every current authority reader/writer has a migration disposition | **PASS** | `current-system-inventory-v1.json`, `p0-authority-path-boundary-evidence-v1.json`, and `p0-persistence-call-dispositions-v1.json` pass `current_system_inventory_check.py`. The retained audit reports 62 artifact/family rows, 50 hidden literals with zero backlog, 839 direct persistence sites (786 artifact-bound and 53 reviewed exclusions), and 166 process boundaries (132 artifact-bound and 34 reviewed exclusions), with zero blocking or unknown sites. | This passes the bounded repository inventory sub-gate only. It does not make the compatibility shadow canonical or prove external-service/database effects. |
| 10 | Baseline telemetry reports stage/resource/cache behavior without presenting 90 minutes as measured | **PASS** | Freshness-checked short and LF-14 current-full-path traces retain stage events, cold/warm cache state, wall time, child CPU, cumulative max RSS, media/QC facts, and repeat equivalence. Short measured `45,407/30,175 ms` cold/warm with clean QC; LF-14 measured `566,941/443,057 ms`, exact 20,139-frame and decoded-audio repeat equivalence, zero QC failures, and two retained visual warnings. `test_baseline_trace.py` passes. [Performance qualification](08_PERFORMANCE_AND_TESTING.md) labels 90 minutes an unproven top-down hypothesis. | The retained runs are current-path baselines, not proof of the target architecture, arbitrary creator footage, visual-QC cleanliness, or the SLA. |
| 11 | `captionsTrack` cannot satisfy coverage before end-to-end render | **PASS** | `caption_plan_pipeline.py` rejects ghost timed arrays; `caption_compile.py` requires exact word coverage; `test_caption_legacy_integration.py` performs a real burn/assemble path and binds Audit B; caption contract, shard graph, and TS schema-parity tests pass. | Legacy plans without an explicit track remain a separately named compatibility adapter. |
| 12 | Cut-authoring prompt vocabulary is generated/checked against canonical enums | **PASS** | `cut-authoring-prompt.ts` imports canonical `MODES` and `SCOPES` and generates the prompt shape from them. `producer-ai-provider.test.ts` accepts `short|longform` and `trim|light|produced|full` and rejects the old `longform|shortform` / `clean|produced` vocabulary. | None for the current prompt surface. |
| 13 | Missing/stale/unmeasured/error comp capability fails closed | **PASS** | `comp_capability_artifact.py` accepts only a fresh, complete artifact bound to the current source closure. `test_comp_capability_artifact.py` covers missing, malformed, stale, tampered, unknown, unmeasured, and render-error cases; `test_plan_lint_comps.py` proves lint receives the failure. | This is physical capability admission, not arbitrary-scene authoring vocabulary. |
| 14 | Channel normalization precedes every mix path, and multi-segment AAC/duration fixtures pass | **PASS** | `program-audio-mix-registry-v1.json` owns 16 consumers: 12 program/derived/control consumers with 12 exact normalization dependencies and 4 explicit asset-only exemptions. It also classifies 3 production no-mix boundaries. `test_program_mix_registry.py` rejects an unowned discovered literal and removal of any dependency token. Real-media tests repair dead-left/dead-right sources before dialogue downmix, per-source cut/J-cut concat, music, transition SFX, source separation, repair splices, and the non-publishing Palmier parity oracle. Content-bound receipts reject a rehashed filter substitution, and each consuming boundary revalidates its held source identity before it can return success. Dialogue and repair receipts embed the channel proof. The four-part `24000/1001` AAC fixture still proves padding cannot extend picture or replace compiled clocks. | The registry scope is the current production Producer graph under `scripts/producer`. Independent music/SFX construction is exempt only when no program/dialogue leg enters. The audio fast path and Palmier finish are classified no-mix handoffs; Palmier maps one authoritative in-house master and rejects a dead stereo side during finished-media QC. A future mix literal or consumer must join the exact registry and dependency gate before release. |
| 15 | All applicable legacy regression gates have owners | **PASS** | `legacy-regression-gates-v1.json` is a complete 13-gate record with owner phases, source lessons, current code, named fixtures, evidence artifacts, receipt bindings, classification, implementation status, and exact known gaps. `p0-legacy-regression-gates.test.ts` parses the closed registry and rejects missing owners, false enforcement, or hidden gaps. The former graphics-over-b-roll uncertainty now has a decoded-pixel positive oracle plus missing-graphic and reversed-order negative controls in `test_graphics_broll_layering.py`. | All 13 mechanism gates are enforced. The layering proof covers generic stage order and alpha visibility; it does not qualify every comp, placement, visual treatment, or any blocked P5 exit. |

## Passing evidence replay

Run from the repository root unless a command changes directory:

```bash
node --import tsx src/lib/producer/__tests__/producer-schema-enum-parity.test.ts
node --import tsx src/lib/producer/__tests__/producer-schema-parity.test.ts
node --import tsx src/lib/producer/__tests__/producer-contracts-v1.test.ts
node --import tsx src/lib/producer/__tests__/producer-ai-provider.test.ts
node --import tsx src/lib/producer/__tests__/p0-machine-contracts.test.ts
node --import tsx src/lib/producer/__tests__/p0-legacy-regression-gates.test.ts
node --import tsx src/lib/producer/__tests__/short-long-route-matrix.test.ts
node --import tsx src/lib/producer/__tests__/auto-edit-mp4-only-delivery.test.ts

cd scripts/producer
../../.venv/bin/python3 current_system_inventory_check.py
PYTHONPATH=.:tests ../../.venv/bin/python3 -m unittest \
  tests.test_comp_capability_artifact \
  tests.test_comp_rate_matrix \
  tests.test_plan_lint_comps \
  tests.test_baseline_trace \
  tests.test_caption_track_contract \
  tests.test_caption_compile \
  tests.test_caption_legacy_integration \
  tests.test_current_render_caption_graph \
  tests.test_render_effect_registry \
  tests.test_current_render_toolchain \
  tests.test_current_render_graph \
  tests.test_current_render_graph_candidate \
  tests.test_current_render_graph_store \
  tests.test_external_ingress_registry \
  tests.test_p0_adversarial_ingress_artifact \
  tests.test_external_media_probe \
  tests.test_sealed_archive_adversarial \
  tests.test_ingest_execution_authority \
  tests.test_channel_normalization \
  tests.test_channel_normalization_mix_paths \
  tests.test_program_mix_registry \
  tests.test_audio_mix_render \
  tests.test_final_provenance \
  tests.test_jcut \
  tests.test_p2_dialogue_stem_render \
  tests.test_p2_dialogue_program_render \
  tests.test_p2_repair_fragment_render \
  tests.test_audio_fast_path \
  tests.test_palmier_audio_finish

```

Additional ingress isolation and policy support can be replayed with:

```bash
PYTHONPATH=.:tests ../../.venv/bin/python3 -m unittest \
  tests.test_headless_import_boundary \
  tests.test_generation_policy_documents
```

To refresh the row 3 controls after a future renderer change, replay them into
a new evidence root (set
`RENDER_EFFECT_BASELINE_EVIDENCE_ROOT` to that empty directory when retaining
the release artifact):

```bash
RUN_LIVE_RENDER_EFFECT_BASELINES=1 \
PYTHONPATH=.:tests ../../.venv/bin/python3 -m unittest \
  tests.live_render_effect_baseline_parity
```

## Completed closure proof

The fresh retained replay under
`artifacts/p0-render-effect-parity-canonical-closure-v1` passed in 530.289
seconds. Both retained graphs bind
toolchain
`1c1898a4b1064e20c46aea1e96c0325dd890fcfc2c45d28710f3e9633668a048`
and registry
`8f8bea83ce9fe6008beea6a64248b748ddfd7153d3a8a8fa1b38152cce98cc3e`.
The short pair is byte-identical at
`ad7592ea4ea4a23085549d0c173b2b91ea5efddf59d9519b800be34db0f5c59d`;
the LF-14 pair is byte-identical at
`b7580bae3caacba297bfce43a37e8ed1c1204a4bcfe392f8522f63914c107843`.
Both also passed exact FrameMD5, PCM, clock, and decoded-frame equality. The
complete Python discovery suite passed its 3,480-case run with one recorded
skip. These facts close only the 15 stated P0 exits on the tested current tree;
they do not release P5–P8, connected or native Palmier, arbitrary After
Effects-equivalent authoring, the 90-minute SLA, or the complete product.
