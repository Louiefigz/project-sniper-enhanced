# Render graph, Palmier delivery, and QC

> **Status:** Target architecture plus bounded implemented P0–P4 mechanisms
> and 6-of-11 P5 exits. The exact protocol verdicts are in the phase audits;
> general hybrid delivery and connected Palmier qualification remain open.
>
> [Previous: motion, assets, and references](04_MOTION_ASSETS_AND_REFERENCES.md) ·
> [Back to the plan index](../COMMAND_DRIVEN_EDITING_EXECUTION_PLAN.md) ·
> [Next: edge cases](06_EDGE_CASES.md)

## Content-addressed render graph

Evolve the existing base/video/audio/graphics fingerprints into finer artifact
nodes. Keep current fingerprints as the compatibility comparator until all
readers and parity fixtures migrate:

```text
immutable sources + transcript corrections
  → cut spine + compiled timeline map
      ├── source/cut video segments
      ├── dialogue/room-tone stems
      ├── reframe/base-look shots
      ├── caption shards
      ├── b-roll
      ├── scene/render units
      ├── transition/SFX
      ├── music automation/mix
      └── optional Palmier bindings
             ↓
        dirty-window previews
             ↓
        one complete final composition/encode
             ↓
        deterministic + visual QC
```

### Implemented P1 compatibility slice — 2026-07-29

The current renderer now has a bounded graph bridge rather than only an
in-memory target design:

- `current_render_graph_cli.py` wraps the real current base and assemble child
  commands, revalidates source, plan, toolchain, dependency edges, and retained
  artifact hashes, and stores immutable graph/receipt generations only after a
  successful child;
- the `/producer/render` and `/producer/assemble` controller commands use that
  bridge while preserving their current ffmpeg/browser implementations;
- the auto-edit assemble path passes `--defer-active`, so its private
  `.sniper-qc` candidate is staged without replacing the prior `ACTIVE` graph;
- the approval path reopens the staged generation, verifies the exact candidate
  hash, moves that media into `final.mp4`, activates the graph only if its
  expected parent is still active, and writes QC approval only after graph
  activation succeeds;
- approved-output resume fails closed unless `ACTIVE` binds the current admitted
  source set, plan content, renderer toolchain, and final bytes.

The retained acceptance artifact is
`artifacts/p1-auto-edit-qc-gated-graph-20260729-rerun2/`.
Its actual HyperFrames/ffmpeg statement-card control held the prior graph active
while the changed candidate was private, then activated a receipt classifying
exactly `node-scene-0000`, `node-composite`, and `node-final` as dirty while
reusing source, timeline, and base. The incremental and isolated empty-cache
forced-full outputs were byte-identical, with exact `framemd5`, normalized
PCM, stream facts, and 72 decoded frames. The final SHA-256 is
`dc3ef09b691cb17dec1f0ad51c080a57cc97605fbf51358ed8327e99827caea8`;
the oracle receipt hash is
`91d72c45c2722f60fff2f0326de804d642ccd2d3c001e32012d90c6e2c4d6c7c`.

This evidence qualifies the QC-staged compatibility publication seam only.
The current bridge still schedules coarse legacy stages, not each ffmpeg or
browser substage/dirty window. It does not replace the compatibility revision
shadow. The three-second control is not itself the frozen short/LF-14 proof;
the retained controls below now provide that separate evidence.

### Current render-effect registry and retained parity harness — 2026-07-30

The current renderer now compiles reuse authority from the closed
`render-effect-registry-v1.json` instead of relying on an undocumented
all-purpose plan projection:

- 31 registry rows classify every released plan/manifest root as
  render-affecting, render-irrelevant, authority-only, or unreleased-rejected;
- 42 generated mutations prove exact stage-root changes, base reuse, scene
  format, and cut-derived scene end behavior;
- import-closure discovery fails if a current renderer adds an unregistered
  literal plan/manifest reader, while lint, render, and assemble reject unknown
  public roots at runtime;
- compiler-owned `plan.timeline`, `plan.base`, per-scene, composite, final, and
  manifest roots are bound into the durable graph and pending-base handoff;
- `graphics_base_effects.py` adds long-form rail/recompose and legacy-caption
  suppression dependencies to the base projection while ordinary scene copy
  and `presenterFrame` alpha/format changes retain the existing base.

The fresh retained executions are under
`artifacts/p0-render-effect-parity-canonical-closure-v1/{short,lf14}`. Both use
the actual HyperFrames/ffmpeg assemble path and bind renderer toolchain
`1c1898a4b1064e20c46aea1e96c0325dd890fcfc2c45d28710f3e9633668a048`
plus registry
`8f8bea83ce9fe6008beea6a64248b748ddfd7153d3a8a8fa1b38152cce98cc3e`.
A single ordinary graphic dirtied exactly scene/composite/final and reused
source/timeline/base; an isolated empty-cache forced-full arm produced the same
final SHA-256, exact FrameMD5 picture, exact decoded PCM, and identical stream
facts. The short decoded 1,394 frames and ended at `ad7592ea…`; LF-14 decoded
20,139 frames and ended at `b7580bae…`. The live replay passed in 530.289
seconds.

This closes the P0 graphics/base freshness exit on the current canonical
closure. It still does not make the legacy renderer a fine-grained scheduler,
prove every graphics composition or layer combination, or qualify the
90-minute full-build hypothesis.

### P2 private review and surgical-picture boundary — 2026-07-30

Cut-repair `prepare` now renders the exact proposed review plan through the
current full renderer with a controller-owned private artifact directory and
`--defer-active`. It strictly observes the staged generation and binds its root
`final.plan` digest and output hash to the exact review plan and candidate.
The graph, execution receipt, candidate pointer, strict downstream-QC
descriptor, and `.mp4` bytes are copied into content-addressed preparation
authority for durable replay. The active graph and project `final.mp4` remain
unchanged.

The preparation still classifies the parent graph's smallest audio invalidation
substrate as `dialogue-stem` or `base-segment-fallback`; a graph with neither
fails with `RENDER_GRAPH_AUDIO_NODE_REQUIRED`. That classification is future
incremental scheduling evidence. The currently reviewed artifact is the
complete plan render, so it retains the current renderer's graphics, captions,
music, and mix rather than auditioning the earlier diagnostic splice.

A separate explicit opt-in controller now proves the next audio-only seam. It
creates a real `dialogue-stem` graph artifact from exact
`DialogueTrackV1`/`DialogueMapV1` authority and makes the private stereo
program node depend on that stem plus every declared program-aligned
room-tone, music, and SFX artifact. Its execution receipt distinguishes a
reused sealed dialogue stem from a fresh forced-full stem, while its immutable
program receipt binds all source/auxiliary/tool bytes, exact `B(F)` sample
clock, graph/execution hashes, and final PCM bytes. Real-media incremental and
forced-full outputs are byte-identical for the same inputs.

That graph is not the cut-repair review graph and does not advance it. It
publishes only a sealed `private-unpromoted` audio generation; it does not mux
the current video, create QC/operator evidence, stage `CUT_REVIEW`, activate a
render graph, replace `final.mp4`, or call Palmier. Fine-grained L/J release
still requires that exact audio artifact to enter the governed full-video
candidate, QC, promotion, and selected delivery paths.

The graph bridge separates its graph-store `producerDir` from the private
`artifactDir`. Timeline, caption-shard, caption-free composite, base, and final
evidence are compiled from the isolated child plan while the candidate
generation stays staged under live project authority. Focused coverage now
exercises that path from the cut-repair caller, including exact
graph/receipt/pointer/media replay. This closes the private overwrite and
plan/media-equivalence gaps. That preparation seam alone does not authorize
QC, operator approval, or activation; the bounded lifecycle below supplies
those later transitions.

A later bounded production terminal can promote one exact-parent surgical
picture repair, but only for its released 30 fps, 48 kHz, one-source,
speed-1, zero-residual, terminal-silence-reclaim subset. It reopens and
rehashes the parent graph, media, plan, source, receipt, and toolchain before
copy and again before activation. Captions, graphics, b-roll, title cards,
transitions, reframe/punch-ins, music, gain/enhancement, and unknown lanes fail
closed because the raw replacement fragment cannot preserve them. This is
not universal layered repair or native/connected Palmier editing.

```ts
interface RenderNodeV1 {
  nodeId: string;
  kind: string;
  dependencyNodeIds: string[];
  inputDigests: string[];
  parameterDigest: string;
  toolchainDigest: string;
  fingerprint: string;
  outputProfile: string;
  dirtyWindows: FrameRange[];
  proofPath?: string;
}
```

Node keys include:

- source/asset snapshot hashes;
- normalized parameters;
- canvas, rational FPS, frame/sample range, color/alpha profile;
- segment ID, segment version, speed, and compiled timeline-map or sliced-map
  digest where timing is materialized;
- scene/template, tokens, fonts, runtime, renderer, browser, and policy hashes;
- upstream node hashes;
- deterministic seed;
- style-pack hash where used.

Never render from a mutable pathname after pre-hashing it. Snapshot first,
render from the immutable object, and bind that opened hash to receipts.

## Invalidation examples

| Change | Required invalidation |
|---|---|
| Scene copy/color/content | Owning render unit, dirty preview, optional Palmier media binding |
| Same-duration scene move | Old/new placement windows; reuse scene media |
| Scene duration | Owning unit and overlapping caption/presenter dependencies |
| Caption spelling/text shaping | Overlapping caption content and cue/placement nodes |
| Caption timing/placement/range | Overlapping cue/placement nodes; reuse content texture only when its digest still matches |
| Music gain/cue | Relevant mix nodes; reuse picture |
| Known-word restoration | Local picture/audio segment, seam captions, touching transition |
| Segment speed | Segment/timeline map plus content-relative scene, caption cue, b-roll, transition, SFX, audio, and Palmier bindings within/after the segment wherever the map changes |
| Transcript/content change | Local media plus claim/chapter/beat/b-roll/scene/caption/reference closure |
| Authorized ripple | Timeline map and all materialized timing; reuse still-valid pixel assets |
| Non-ripple child picture lock | Recompile/revalidate every deferred/compiled treatment clause bound to the parent lock; prove unchanged mapping outside closure |
| Graphic changes `presenterFrame` alpha/format | Scene, composite, and final; retain base unless the row separately activates long-form recompose |
| Graphic changes caption suppression | Scene plus overlapping legacy-caption/base or explicit-caption nodes |
| Font/runtime/template | Every bound node |
| Global grade/canvas/reframe | Broad picture closure |
| Unknown structural edit | Governed broad fallback |

Current compatibility base reuse projects long-form recomposition and
legacy-caption suppression through `graphics_base_effects.py`; ordinary
graphics remain excluded. The mechanism, generated mutations, and fresh
short/LF-14 dirty-versus-forced-full controls pass against the current bound
toolchain. Any renderer, invalidation, or dependency change makes that retained
evidence stale and requires replay before release.

Promotion requires both:

1. actual changes are inside the authorized dependency closure; and
2. every computed required invalidation was rebuilt or revalidated.

Every reused node is re-fingerprinted. Mutation tests deliberately remove a
dependency edge and must fail promotion.

## Execution policy

- Run independent scenes/caption pages in bounded parallel workers.
- Admission control uses measured CPU, RAM, disk, browser-process, and file
  limits.
- Merge padded overlapping dirty windows while retaining operation provenance.
- Build one overlay stack per dirty window and encode picture once per window.
- Remove multi-pass behavior where many overlays cause repeated full-duration
  picture passes.
- Use fixed-timebase mezzanine segments with aligned frame/sample boundaries.
- Do not rely on arbitrary H.264 byte splicing.
- Require every program-mixing node that consumes source dialogue/audio to
  depend on the normalized stem; independent music/SFX generation may run in
  parallel.
- Derive authoritative duration from compiled delivery frames/exact rational
  FPS and compiled pre-AAC PCM samples/project sample rate; decoded
  frame/sample/container durations are QC observations.
- Compare dirty output with a clean forced-full oracle during development.
- Final publication always gets one complete assembly/encode, decode, and QC.

The retained P5 private-review mechanism uses an exact 840-second,
25,200-frame, 50-scene project. It changes only the right unit of `scene-045`,
reuses the left unit and all 49 unrelated scenes, emits one
180-frame/288,000-sample review window, performs zero full-base or
full-duration encodes, and leaves the approved base unchanged. Exact replay
renders zero units. The independent control measures `0.999948272` mean /
`0.999944` minimum SSIM with exact PCM. The full retained run took 249.955
seconds; its first targeted repair took 39.319 seconds and replay 5.747
seconds. Separately, 24 ordered overlays now composite in one production
FFmpeg graph/picture encode and match the former three-encode control by exact
FrameMD5, PCM, and stream facts. These are local render proofs, not
active-head or connected Palmier qualification.

The local Desktop production path now binds the approved master’s exact bytes,
full frame window, canvas, audio facts, plan hash, and canonical rational frame
rate. Because Palmier exposes disable controls separately, placement remains
non-promotable until complete readback proves one dedicated, hidden, muted,
sync-locked reference. Desktop Audit B now runs frozen editable-master parity
under stable `desktop-build` authority, and approval reopens current export,
audit, frame, parity, approval, and input bytes rather than trusting mutable
state hashes. This is local production logic, not connected short/long
qualification; real mutation, disconnect/recovery, export, and representative
retained evidence remain open.

## Palmier delivery products

The current connected-editor boundary is narrower than the target below.
Governed native-candidate promotion now uses the durable local/Palmier saga:
it fresh-proves the approved candidate through its pinned native-QC CLI,
reserves a local revision child, activates and exactly reads back Palmier,
publishes the expected-parent local advance, and re-reads both sides before
reporting commit. Startup resumes a nonterminal saga first, while foreign or
partial state becomes blocking reconciliation. This is production protocol
wiring with exhaustive adapter-state tests; it is not a retained connected
Palmier short/LF-14 qualification or the complete editable-build product.

When selected, maintain:

1. **Editable Build:** native source/cut clips where proved; separate
   regenerable scene/title/caption/b-roll clips; segmented dialogue, room tone,
   SFX, and music; native controls only with exact adapter/readback proof.
2. **Exact Master:** current one-clip mirror of the approved Sniper master on a
   separate governed timeline/comparison surface.

Recommended editable layout:

- native or baked-regenerable cut spine at the finest proved granularity;
- separate scene/render-unit clips;
- separate caption-page clips;
- separate b-roll and proved native text;
- source-clip audio detached/muted;
- active ledgered dialogue/room-tone/SFX/music stems;
- locked final-master reference track imported disabled/muted;
- exact master never visibly/audibly stacked with the editable build.

`audioAuthorityMode` permits exactly one audible route: editable stems or
mastered stereo. The Exact Master uses the approved stereo mix. The Editable
Build is not called sample-exact while Palmier actively mixes editable stems.

Current implementation status is deliberately asymmetric and fail-closed:

- `editable-stems` still reports `routing-readback-unsupported` because current
  Palmier readback does not expose bound stem roles and output-bus routing;
- `mastered-stereo` is production-reachable in the local Desktop worklist for a
  trusted approved `final.mp4`. The compiler derives and content-addresses a
  48 kHz stereo `pcm_s32le` WAV, binds the approved final/WAV/tool hashes and
  exact frame/sample duration, imports it, and adds exactly one full-length
  standalone audio clip on a clean dedicated audio track.

The mastered route is not declared authoritative after placement alone. A
complete placement readback must prove the exact new clip/track delta. The next
`manage_tracks` operation is then derived from that fresh timeline: every other
currently audible content-bearing audio route is muted and the mastered route
is left audible and sync-locked. Only a complete second readback proving that
exact routing delta, route identity, unchanged unrelated tracks, and unchanged
video flags may persist `state.audioAuthority`. Replay, a shared or dirty
track, an extra audible route, a wrong or changed WAV/final, a duration
mismatch, or partial readback fails closed.

The hidden Exact Master remains a separate full A/V pair and must independently
remain hidden/muted/locked; it is never reused as the audible mastered route.
Desktop stage advance, QC, and later operations revalidate both invariants.
This is a production-callable local contract with adversarial coverage, not a
retained connected Palmier short/long qualification. An export containing one
encoded audio stream proves a container fact only; multiple audible timeline
routes can mix into that one stream, so stream count never substitutes for the
separate current `audioRouteAuthority` readback receipt.

Each element is labeled:

- `native-exact`;
- `baked-regenerable`;
- `approved-approximation`;
- `unsupported`.

HyperFrames internals stay baked unless a native translation is proved. They
remain command-editable because Sniper can regenerate/replace their bound clip.

## Element ledger

```text
Sniper scene/element/segment/caption ID
  → asset hash + mediaRef + clipId + project/timeline
  → track identity + frame window + trim + transform + version
  → mutation and readback receipts
```

Rules:

- Refresh stable IDs immediately before mutation; track indices are not
  identity.
- CAS before each mutation page and after full readback.
- A timeout with possible mutation is reconciled/quarantined, never replayed
  blindly.
- Manual Palmier edits advance/fork the working head and invalidate stale AI
  approval.
- Sniper never reverse-imports baked internals or silently overwrites drift.
- Native cut/ripple stays disabled until segmented replacement, dependent refit,
  live long-form fidelity/readback/export, and timeout gates pass.
- Failed candidates never replace the approved working head or exact master.

“Everything is in Palmier” means every required source/library asset, cut,
scene, caption, b-roll, audio element, sidecar, and exact master has a
disposition/binding. It does not mean unsupported effects become native.

## Hybrid release fidelity

The first editable release is hybrid, not “native parity.” Baked-regenerable
base segments are acceptable while scenes/captions/b-roll/audio use the finest
proved granularity.

Release requires representative short and long exports with:

- 100% element-to-ledger/readback disposition;
- zero unexplained mutations;
- explicit-timeline export and full decode;
- exactly one audible route proved by a current `audioRouteAuthority` receipt,
  in addition to exactly one encoded output audio stream;
- hidden/disabled exact-master reference;
- frame, timing, and audio comparison against the approved Sniper result under
  frozen tolerances;
- every mismatch blocked or tied to an explicit approved approximation;
- one-scene repair replacing only the ledgered scene clip;
- apply-before-disconnect recovery;
- preservation of manual Palmier changes.

## Revision-invariant proof

Every incremental revision declares expected dirty state before mutation and
proves actual state afterward.

`RevisionInvariantProofV1` includes:

- parent/child revision, plan, request, and operation hashes;
- manifest/source/toolchain hashes;
- before/after compiled delivery frames, exact FPS, pre-AAC PCM sample ranges,
  decoded QC observations, and timeline-map hash;
- parent/child picture-lock and supersession receipt where applicable;
- authorized/actual changed IDs, nodes, fields, and windows;
- unchanged element/node/asset hashes;
- dirty-window evidence;
- complete Palmier inventory/readback diff when selected;
- alignment, caption, audio-seam, and scene filmstrip/animation-map evidence;
- verdict and approved approximations.

Required checks:

1. **Request coverage:** every clause has a canonical state; finalization has no
   unexplained pending/deferred/compiled/candidate-executed clause.
2. **Structural diff:** hash whole non-target plan elements and allowlist only
   declared changed paths. Unknown fields fail closed.
3. **DAG:** actual changes stay authorized; every required invalidation is
   rebuilt/revalidated; reused nodes re-fingerprint.
4. **Palmier:** compare complete versioned readback, including effects,
   blend/mask, transitions, visibility, routing, mute/solo, transforms, and
   gains. A mutation class stays disabled if affected properties cannot be read.
5. **Media:** unchanged segment hashes remain exact; pre-master PCM is exact
   outside the closure; final mastering uses frozen tolerances.
6. **Seam:** complete intelligible words, no duplicate/gap/click, stable room
   tone, lip sync, aligned captions.
7. **Scene:** entrance, first land, middle, exit, extrema, terminal alpha, copy,
   safe zones, collisions, and claim grounding.
8. **Final:** full encode/decode, Audit B, independent composition/editorial
   review, and exact plan/manifest/Palmier authority binding.

Do not demand byte-identical H.264 after a full re-encode. Prove immutable
segment hashes before finalization and decoded visual/audio equivalence
afterward.
