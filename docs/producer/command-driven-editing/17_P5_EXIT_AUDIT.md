# P5 exit audit — optimized render graph and hybrid Palmier delivery

> **Verdict: BLOCKED — 6 of 11 exact exits pass; 5 remain blocked.**
>
> **Evidence date:** 2026-07-30
>
> Project Sniper now has an exact 14-minute/50-scene one-unit private-review
> repair, a one-pass 24-overlay compositor, and a 36-cell production promotion
> fault cohort. Local Palmier prerequisites now cover an exact hidden master,
> strict full-stream parity, one-scene replacement, a durable lifecycle
> journal, and immutable pre-mutation crash snapshots. The five connected
> Palmier exits remain blocked.

P2 also has a separate exact-parent surgical picture-repair path. It is
production-wired but deliberately admits only a 30 fps/48 kHz, single-source,
speed-1, zero-residual terminal-silence-reclaim case with no rendered
treatment lanes. Plans containing captions, graphics, b-roll, title cards,
transitions, reframe/punch-ins, music, gain/enhancement, or unknown lanes fail
closed so raw replacement pixels cannot erase burned layers. That narrow path
does not change the P5 count: general layered dirty-window recomposition and
hybrid Palmier delivery remain P5 work.

## Verdict rules

- **PASS** requires current production code plus real-media or connected-editor
  evidence at the exact scope stated by the roadmap.
- **BLOCKED** means a material part of the exit is absent, is covered only by
  isolated tests, or has a smaller fixture than the stated cohort.
- A production-callable CLI is not automatically wired into Ask Editor.
- A Palmier adapter, state-machine test, or simulated readback is not a
  connected Palmier short/long acceptance.

## Exact exit table

| # | P5 exit | Verdict | Current evidence | Exact blocker or scope |
|---:|---|---|---|---|
| 1 | A one-scene change in a 14-minute/50-scene project renders one scene and zero full base encodes during review | **PASS** | The freshness-checked `p5-one-unit-review-repair-v1.json` uses an exact 840-second, 25,200-frame, 1920×1080, 50-scene project. It changes `scene-045`, renders only `unit-right`, reuses `unit-left` plus all 49 unrelated scenes, records one review-fragment encode, zero full-base encodes, and zero full-duration outputs, and leaves the approved base byte authority exact. Exact replay renders zero units. | This is a private review fragment, not universal dirty-window final-master assembly or a connected Palmier mutation. |
| 2 | Twenty-four overlays do not cause three full-duration passes | **PASS** | Production `graphics/composite_core.py` now builds every ordered overlay into one filter graph instead of an eight-overlay chunk loop. The retained real-media `p5-24-overlay-one-pass-v1.json` measures 24 overlays, one FFmpeg command, one picture encode, one reported pass, 120 decoded 1920×1080 frames, exact FrameMD5/PCM/stream equivalence to the former three-encode control, and visible overlay output. | A complete full build still has one full-duration picture encode. This is not universal high-overlay-count or dirty-window-stitching qualification. |
| 3 | Dirty output matches a forced-full oracle | **PASS** | `live_current_render_graph_acceptance.py::test_dirty_scene_matches_independent_forced_full` compares an actual dirty current-render graph against an isolated `--force-full` graph. The new private-review artifact also compares its one-unit window against a separately rendered clean-cache full-scene window: PCM and stream facts match, mean SSIM is `0.999948272`, and minimum-frame SSIM is `0.999944`. | This passes the equivalence invariant on the released current graph and the bounded new review mechanism; it does not make every operation fragment-renderable. |
| 4 | A timing move dirties old and new windows only | **PASS** | The P4 retained scene cohort records exactly old/new windows `[30,210)` and `[60,240)`, reports `mediaReused=true`, reuses both unit media files with an unchanged cache inventory, emits only two `move-placement` operations, and matches an independently forced moved timeline by exact FrameMD5, PCM, and stream facts. | The pass applies when duration, content, FPS, bundle, canvas, and render mode remain unchanged. A duration-changing move has a different closure. |
| 5 | Cancellation, disk failure, stale parent, and bad cache cannot promote mixed generations | **PASS** | `p5-render-graph-fault-cohort.test.ts` drives the production current-render candidate transaction through four fault classes at all nine promotion boundaries. All 36 cells resolve as 9 exact-old, 4 exact-new, or 23 explicit blocked outcomes; every outcome reopens through the production recovery path and rejects mixed graph/media authority. The transaction now binds the exact `.render-graph-v1/ACTIVE.json` candidate/artifact generation during recovery. | These are deterministic local process/disk fault injections, not OS power-loss or remote-filesystem durability proof. |
| 6 | Representative short and long projects have 100% Palmier ledger/readback disposition and zero unexplained mutations | **BLOCKED** | The local live-build path now uses a strict fsynced JSONL lifecycle, explicit mutation allowlist, canonical-input replay fence, fresh candidate observation before receipt refresh, immutable pre-mutation Desktop snapshots, and cross-runtime closed-journal QC. Focused tests cover duplicate/late results, ambiguous applying/failed operations, corrupt/torn/oversized rows, no-delta “applied” results, and manual/foreign drift. | These are local contract and simulated-readback proofs. There is no representative connected short/long Palmier cohort, complete paged long-form readback, bounded timeout, or zero-unexplained-mutation report. |
| 7 | Export fully decodes from the bound Palmier timeline with exactly one audible-route authority and a hidden exact-master reference | **BLOCKED** | The production exporter names the exact timeline ID, requires exactly one video and one encoded audio output stream, runs `ffmpeg -xerror` over the full mapped A/V export, and persists those stream facts for QC revalidation. The local Desktop compiler now has a production-reachable `mastered-stereo` lane: it derives a content-addressed 48 kHz stereo PCM WAV from the trusted approved final, imports and places exactly one full-length standalone clip on a clean dedicated track, derives the exact mute set from fresh readback, and persists route authority only after complete placement and routing readbacks. It separately plans, binds, and proves one hidden/muted/locked exact-master A/V pair for admitted integer-rate projects. Adversarial tests cover stale or changed media, dirty/shared tracks, extra audible routes, wrong duration/master, partial readback, replay, and unrelated video-flag mutation. | One encoded output audio stream does not prove one audible Palmier route. The mastered-stereo lane is locally production-callable but has no representative connected short/long route/export qualification or connected exact-master add/disable evidence. `editable-stems` still lacks stable role/output-bus readback. Non-integer Palmier project-rate scalars fail closed. |
| 8 | Editable-build frames, timing, and audio meet frozen tolerances or carry approved approximations | **BLOCKED** | The local editable-parity contract now freezes full-stream picture, timing, and decoded-audio comparisons and requires hash-bound approval for every approximation; tests reject partial-window evidence, substituted approvals, and out-of-tolerance results. | No representative connected editable short/long build has passed the strict full-stream contract at the required rational rates with exact frame/sample authority and every approximation explicitly approved. |
| 9 | One-scene repair replaces only its Palmier clip | **BLOCKED** | The local scene revision/executor compiles one exact replacement, requires atomic readback of the new binding, and preserves every unrelated clip. P4 and the private-review artifact independently calculate one `replace-media` operation for `scene-045-unit-right`, preserve `scene-045-unit-left`, and record `connectedPalmierMutationCount=0`. | This proves the local replacement contract and proposed binding delta, not a connected Palmier clip replacement followed by complete exact readback. |
| 10 | Apply-before-disconnect and manual-edit preservation pass | **BLOCKED** | The local path now persists immutable pre-mutation snapshots plus a durable applying/applied/failed/not-applied journal. Resume observes Palmier before refreshing the receipt; ambiguous effects, foreign/manual drift, replay, and applied-with-unchanged-fingerprint histories block automatic resume. The blocked state explicitly requires external-operator adoption or an adopted-head fork. | No connected fault cohort disconnects at every real mutation boundary and proves apply-before-disconnect recovery plus preservation or explicit invalidation of a real manual edit. |
| 11 | Channel-normalization mutation, exact rational FPS, frame/sample authority, and multi-segment AAC padding fixtures pass | **PASS** | `program-audio-mix-registry-v1.json` owns every current program-mix consumer and its normalization dependency; its mutation test rejects a removed dependency. Exact timing tests preserve rational rates. The real four-part `24000/1001` fixture prevents AAC padding from extending picture or replacing compiled frame/sample clocks. The new review compositor also rejects a mismatched channel receipt and decodes exactly 180 frames, 288,000 samples per channel, and one encoded audio stream. | This local encoded-stream fact is not a Palmier audio-route authority. New program-mix consumers and editor-native audio lanes must join the same registry and fixtures before release. |

## Production path and caller map

| Surface | Production path | What it currently authorizes |
|---|---|---|
| Editor-ready full render | `src/app/api/producer/render/route.ts` → `src/lib/server/current-render-graph-command.ts` → `current_render_graph_cli.py` → `render.py --skip-graphics` + `assemble.py` | Canonical base/assemble graph execution and final render. It remains full-duration for the broad route. |
| Audio-only cut-repair private render | `cut-repair-private-render.ts` → the current full-render graph with `deferActive=true` → staged candidate → QC promotion | Private candidate construction and staged graph authority through the existing monolithic render path. |
| Bounded picture cut repair | `cut-repair-private-render.ts` → `cut-repair-private-picture-render.ts` → `cut_repair_surgical_terminal.py` → staged five-node graph → QC promotion | Exact-parent raw-fragment replacement only for the narrow no-rendered-treatment subset. Unsupported layered plans fail closed. |
| Render-graph promotion | `src/lib/server/current-render-graph-candidate.ts` → `current_render_graph_candidate_cli.py` | Verify, activate, observe, or roll back the exact staged graph after QC. |
| One-unit scene review | `/api/producer/scene-review` → `scene_review_repair_cli.py` → `scene_review_repair.py` → `scene_package_render.py` + `scene_review_media.py` | The local application route confines inputs to one canonical project, holds the shared writer lease, supports exact idempotent replay, quarantines failures, and process-tree-cancels before lease release. Its create-once review remains private with zero active-project and zero connected-Palmier mutations. |
| Palmier scene/caption/revision lanes | `scripts/producer/palmier/**` plus Producer Palmier routes | Typed projections, ledgers, guards, and focused readback checks. These are not a complete connected short/long release cohort. |
| Legacy layered render | `render.py`: b-roll → overlays → graphics → caption/master | The stage order now has a decoded real-media regression fixture, described below. |

## Retained optimized-render evidence

The freshness-checked artifact is
`contracts/p5-one-unit-review-repair-v1.json`.

- Live execution took **249.955 seconds**. The first targeted repair took
  **39.319 seconds** and exact replay took **5.747 seconds**.
- Its source closure contains **133 files**: the static transitive local Python
  import closure plus dynamically loaded scene schemas, bundle files,
  HyperFrames runtime, vendored GSAP, browser launcher, and Node preload.
- The project is exactly 840 seconds / 25,200 decoded frames at 1920×1080,
  `30/1`, with 50 validated scene packages.
- First repair: logical dirty unit `unit-right`; rendered `unit-right`; reused
  `unit-left` and all 49 unrelated scenes; one scene-window encode; zero
  full-base encodes; zero full-duration outputs.
- Exact replay: both units reused; zero unit renders; zero full-base encodes.
- Output: 1920×1080, `30/1`, 180 decoded frames, 288,000 decoded samples per
  channel, `audioStreamCount=1`, and an `ffmpeg -xerror` full A/V decode.
- The approved base hash, size, and mtime remain exact.
- The independent clean-cache full-scene/window control passes the current
  oracle with exact decoded PCM and stream facts and the SSIM values in exit 3.
- The measured child-process peak RSS is 1,826,750,464 bytes.
- The artifact explicitly excludes universal dirty-window final-master
  assembly, connected Palmier mutation, and native After Effects/Palmier
  parity.

The second freshness-checked artifact is
`contracts/p5-24-overlay-one-pass-v1.json`.

- It composites 24 ordered overlays with one FFmpeg graph, command, picture
  encode, and reported pass.
- It fully decodes 120 frames at 1920×1080 and `30/1`.
- The production output matches the former three-encode control by exact
  FrameMD5, decoded PCM, and stream facts.
- The run took **5.214 seconds**.
- It does not claim that a complete build avoids its one full-duration encode
  or that arbitrarily large overlay counts are qualified.

The runtime media/receipt writer is a first-class
`scene-unit-private-review` row in
`current-system-inventory-v1.json`. It is not hidden under a generic temporary
or delivery-output exclusion.

## Legacy graphics-over-b-roll gate

`graphics-over-broll-layering` is now **ENFORCED** as a mechanism gate.
`test_graphics_broll_layering.py` uses real decoded media and the production
primitives in production order:

1. `apply_broll_inserts` places opaque blue b-roll over a gray base.
2. `composite` places a 50%-alpha graphic over the b-roll.
3. `burn_caption_artifact` burns the caption after the graphic.
4. A second graphic color is rendered without rebuilding the b-roll.

The test verifies:

- a mixed green/blue pixel inside the alpha graphic and unchanged blue pixels
  outside it, proving alpha and graphic-over-b-roll z-order;
- the same visibility oracle rejects both the b-roll-only frame and a real
  reversed pipeline (graphic first, opaque b-roll second), so the assertion
  cannot pass merely because the fixture changed somewhere;
- decoded caption pixels differ from the pre-caption frame while the caption
  overlaps the graphic, proving caption-over-graphic policy;
- the encoded audio stream MD5 is identical across base, b-roll, both graphic
  outputs, and both caption burns;
- the b-roll hash/mtime and caption hash remain exact across the graphic-only
  edit;
- the two graphic variants differ inside their window and match before it.

This closes the former stage-order inference gap. Graphics-over-b-roll remains
a legacy regression gate rather than an additional P5 exit.

## Replays performed

```bash
cd scripts/producer
PYTHONPATH=.:tests ../../.venv/bin/python -m unittest -v \
  tests.test_scene_review_repair \
  tests.test_p5_review_repair_artifact
```

Result: **5/5 passed**.

```bash
cd scripts/producer
PYTHONPATH=.:tests ../../.venv/bin/python -m unittest -v \
  tests.test_p5_compositor_artifact

cd ../..
node --import tsx \
  src/lib/server/__tests__/p5-render-graph-fault-cohort.test.ts
```

The retained 24-overlay artifact passed its freshness/closure test. The
production fault cohort passed all **36/36** fault/boundary cells with the
exact 9 old / 4 new / 23 blocked distribution.

```bash
node --import tsx \
  src/lib/server/__tests__/scene-review-route.test.ts
node --import tsx \
  src/lib/producer/__tests__/project-mutation-routes.test.ts
```

Both application-route suites passed. They cover project-relative path
confinement (including symlink escape), bounded workers, shared-lease
ownership, exact request replay, conflicting request IDs, failure quarantine,
and process-tree cancellation.

```bash
cd scripts/producer
PYTHONPATH=.:tests ../../.venv/bin/python -m unittest -v \
  tests.test_palmier_native_export_decode \
  tests.test_palmier_native_qc_contract \
  tests.test_palmier_primary_auto_edit_contract
```

All **16/16** candidate-export and adjacent authority cases passed, including
real A/V full decode, corrupt-media rejection, multiple-audio rejection, exact
timeline-ID dispatch, and durable revalidation of the
one-output-audio-stream/full-decode facts. This is local output-container
evidence; by itself it proves neither
one audible Palmier route nor the connected hidden-master/short/long cohort
required by exit 7.

```bash
cd scripts/producer
PYTHONPATH=.:tests ../../.venv/bin/python -m unittest -v \
  tests.test_palmier_exact_master_reference \
  tests.test_palmier_exact_master_desktop \
  tests.test_palmier_editable_parity \
  tests.test_scene_binding_revision \
  tests.test_scene_binding_desktop_executor \
  tests.test_palmier_desktop_operation_snapshot \
  tests.test_palmier_desktop_audio_authority \
  tests.test_palmier_live_build
```

All **51/51** local hybrid-prerequisite cases passed. They cover the exact
hidden/muted/locked master pair, strict full-stream parity, atomic one-scene
replacement, content-addressed pre-mutation snapshots, audio-route rejection,
and durable live-build reconciliation. In particular, the audio suite rejects
two audible routes even when an export could contain one encoded stream. These
are not connected Palmier short/long acceptance tests.

```bash
node --import tsx \
  src/lib/producer/__tests__/palmier-live-build-contract.test.ts
node --import tsx \
  src/lib/producer/__tests__/palmier-live-build-reconciliation.test.ts
```

Both TypeScript live-build suites passed. They enforce exact mutation
lifecycle accounting, the explicit mutation allowlist, replay prevention,
oversized/corrupt/torn journal rejection, no-delta rejection, and
external-operator-only resolution for ambiguous or manual/foreign drift.

```bash
cd scripts/producer
PYTHONPATH=.:tests ../../.venv/bin/python -m unittest -v \
  tests.test_graphics_broll_layering
```

Result: **2/2 passed** in 2.078 seconds.

The retained live artifact was refreshed with:

```bash
cd scripts/producer
PYTHONPATH=.:tests ../../.venv/bin/python \
  tests/live_p5_review_repair_acceptance.py \
  --artifact \
  ../../docs/producer/command-driven-editing/contracts/p5-one-unit-review-repair-v1.json
```

The run passed in 249.955 seconds.

The legacy registry parser/path gate is:

```bash
node --import tsx \
  src/lib/producer/__tests__/p0-legacy-regression-gates.test.ts
```

## Required closure work

1. Qualify the locally production-reachable mastered-stereo route and separate
   hidden Exact Master on connected representative short and long projects;
   keep editable stems blocked until stable role/output-bus readback exists.
2. Qualify the locally adversarial-tested complete paged reader against a
   connected capped-caption timeline; add bounded long-form timeout and released
   rational-rate exact-master admission.
3. Run connected representative Palmier short and long projects with complete
   ledger/readback, export/audio/exact-master, editable tolerance, one-clip
   repair, disconnect, and manual-edit-preservation evidence.

Until that cohort is complete, the supported statement is:

> Project Sniper passes the exact optimized-render P5 exits, including a
> 14-minute/50-scene one-unit private repair, a one-pass 24-overlay composite,
> and a complete local promotion fault cohort. Hybrid Palmier delivery remains
> unqualified until the connected short/long cohort passes all five editor
> exits.
