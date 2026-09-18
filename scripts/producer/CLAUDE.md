# CLAUDE.md — PRODUCER (`scripts/producer/`)

September 16 enforced native export: `studio/native_export.py` is the public
Short/Long selector and common owner admission boundary. The installed native
SDK CLI and capture workers require a live shared owner. `native_long_prebuild.py`
uses the existing TS prebuild validator for complete-project review; Short new
exports call strict `check-export`, while historical reads remain available.
`native_export_history.py` serializes immutable per-project discovery;
`native_long_autoresume.py` and `native_short_autoresume.py` select exact terminal
stages without a resume flag, through their format-specific proof readers.
Short discovery also retains qualified partial picture and float/AAC audio;
the ordinary worker consumes these bindings before any new picture work.
The shared review reader/bundle supports the actual long export protocol.
Compatibility HTTP render/assemble routes delegate to the existing saved-plan
review/QC controller. See `docs/producer/WORKFLOW_ENFORCEMENT_AUDIT_2026-09-16.md`.
`npm test` now includes `npm run test:native` so the native Node guard, clock,
cache and QC regressions run with the ordinary repository checks.

September 16 native long reliability: `studio/native_long_export.py` is the
landscape adapter over `native_short_pipeline.py`'s shared lifecycle.
`native_long_contract.py` validates exact scenes/audio; `native_long_worker.py`
orchestrates phases and reuses shared float/AAC gates; `native_long_capture.mjs` checks full-context
seams and reverse seeks before master; `native_long_sources.mjs` admits projected
allocations and observes real source-frame publication. `native_long_recovery.py` seals picture separately and
resumes exact completed stages. `native_workload.py` and `native_run_admission.py`
add bounded long-job deadlines/progress and capacity waits without weakening the
existing resource owner. The SDK CLI/capture-library patch makes video windows
half-open on both forward and reverse seeks and bounds source-task concurrency.
See `docs/producer/NATIVE_LONG_EXPORT.md`
and its implementation evidence for commands, supported scope and qualification.

September 15 review handoff: Shorts and long-form require both the local checked
MP4 review and a live editable HyperFrames Studio view by default. The owning
interactive task follows `docs/producer/STUDIO_REVIEW_LANE.md` → "Required review
handoff: local playback and Studio"; an export receipt or project file link alone
does not complete that handoff.

September 11 native Shorts entry points: `native-short.ts` prepares local request
packets, builds explicit native strategies and cold-checks projects.
`studio/native_short_export.py` owns local export, shared dialogue delivery and
native/encoded picture checks. It delegates to `native_run.py` with the existing
work lease and resource/ownership utilities. Runtime patches and file transport
live in `studio/runtime/`; generated `.sniper-native-runtime` caches are excluded
from code snapshots. See `docs/producer/NATIVE_SHORTS_WORKFLOW.md` and the
September 11 integration report for the measured three-case scope and limitations.

September 16 upstream review: `src/lib/producer/visual-storytelling.ts` supplies
the shared short/long author and critic criteria. Native Short builds use
`src/lib/server/native-short-prebuild-review.ts` before direct/guided dependent
assembly: strict existing plan-review pass, full authored-input digest, seven
coverage assessments and pinned evidence. `native-short-project.ts` retains and
cold-checks `PREBUILD-REVIEW.json`; historical projects remain explicitly
unreviewed. Only the review reference and generated transport bindings are
excluded from the creative digest; proposal/media checks remain independent.
This verifies a recorded review, not reviewer identity or actual pixel quality.
New native long exports now require the equivalent complete-project review
through `native_long_prebuild.py`; this does not implement a creative controller.
Follow
`docs/producer/NATIVE_PREBUILD_STRATEGY_2026-09-10.md` for the complete brief,
asset/transition plan, independent critique and conditional worker assignments.

September 15 export recovery: `native_short_pipeline.py` coordinates sequential
render, native-capture and encoded-verification owners. Each retains the existing
600-second owner limit and shared heavy lane. `native_short_resume.py` admits an
exact completed render for a fresh `--verify-from .../render-stage.json` attempt;
`native_stage_evidence.py` supplies reusable hash-bound stage/cleanup evidence for
native adapters. Final export status is `delivery.json`; a sealed render alone
is still awaiting QC. The generic `native_run_lifecycle.py` restores owned signal
handlers between stages. Reuse shared audio, exact clocks, resource ownership and
these evidence helpers; keep format-specific picture checks in their adapters.

September 15 optimization: `native_short_capture_resume.py` supplies automatic
capture sealing/reuse to the standard exporter and the thin `resume_final_qc.py`
compatibility command. `--resume-from <attempt>` retains later successful capture;
invalid present seals fail explicitly. `audio/native_master_preparation.py` and
`native_audio_donor.py` check the exact reusable audio before picture; shared
final AAC/AV checks remain. `native_short_dialogue.py` owns source/clock assembly.
`native_selected_frames.py` streams all selected RGB through the shared bounded
pipe reader; `native_picture_references.py` keeps unchanged pixel/reverse checks;
`native_render_storage.py` admits planned allocation plus the existing reserve.
`native_review_{bundle,contract,html,media,recognition}.py` replaces dated review
builders with manifest-driven preparation and separates raw ASR diagnostics from
timing approval. Long-form geometry/clock helpers are shared; actual checked
delivery admission currently uses the native Short receipt protocol. Production
timings use the existing journal and union coverage report, never a quality gate.
See `docs/producer/SHORTS_OPTIMIZATION_IMPLEMENTATION_PLAN_2026-09-15.md` for the
target operating schedule and measured qualification limits.

September 15 selected media: `edit/selected_sources.py` supervises and seals
reusable source ranges; `selected_sources_contract.py` merges bounded handles and
`selected_sources_media.py` preserves picture packets and extracts float audio.
`src/lib/server/native-selected-sources.ts` binds the small assets and executable
offsets while retaining original editorial clocks. Direct `native-short.ts build`
prepares missing media; `prepare-media` allows explicit preparation/reuse first.
`studio/native_selected_sources.py` shares receipt admission and selected-audio
inputs with export. Legacy projects remain readable. Do not substitute prepared
bytes for original source evidence or bypass the shared native work owner.

September 15 native long-form preparation: `studio/long_sources.py` adds explicit
prepare/check/managed-preview commands for separate selected-media projects.
`long_sources_html.py` translates only media URLs/source offsets;
`long_sources_project.py` preserves the original inventory and complete-program
WAV, binds the shared source package, and cold-verifies the new project. See
`docs/producer/NATIVE_LONG_SELECTED_SOURCES.md`. Working cut-base pipelines and
qualified archived long-form exports remain on their existing paths.

September 9 native-work resource rule: use `studio/managed_preview.py open`
for authored HyperFrames projects, or the existing Studio open command which
now delegates to it. It reuses one current preview across draft folders and
verifies retained descendant cleanup before replacement. Managed preview uses
the existing qualified `studio/native_runtime.py` adaptation, with exact-runtime
identity checks before server reuse. Stock Studio can skip HTML/media handling
in embedded browsers; export and preview must share these compatibility fixes.
Do not start raw SDK
preview daemons. Native rendering and browser/media QC must acquire the shared
`native_work_lease.NativeWorkLease` heavy lane and use resource admission plus
continuous owned-tree monitoring; release only after verified cleanup. These
controls are independent of the legacy renderer described below. See
`docs/producer/C0679_END_TO_END_OPTIMIZATION_AUDIT_2026-09-09.md` for the failed
attempts, tested controls, current native direction and remaining limitations.

For explicitly selected native-project work, the conservative static preflight
is `studio/native_preflight.py <canonical-staged-project> --output-dir <new-evidence-dir>`.
Use the installed `SNIPER_NODE_PATH`. It reuses official SDK project lint and
path resolution without network, probes, rendering or project edits. Run it
after asset staging and before guarded sample/master work; its pass is never
render/quality admission. Animated sample and full-output QC remain required.
See `docs/producer/NATIVE_PREFLIGHT.md` for scope, bounds and failure semantics.

The AI video editor: raw footage + a brain-authored `edit_plan.json` → a finished
short/long via a deterministic Python + ffmpeg/hyperframes renderer, then Audit B.

**Destination (canonical: `docs/PIPELINE.md`):** footage is uploaded into
PRODUCER (intent card: Short w/ style · Long w/ lane checklist), the gated plan
is authored here, and the in-house `render.py`/`assemble.py` + ffmpeg bus is the
**primary, canonical renderer** — it produces the controller-approved `final.mp4`.
**Palmier Pro is an OPTIONAL, post-approval, one-way exact-master MIRROR**, not a
native-translation destination: the wired push (`palmier/sync.py` →
`palmier/mirror.py`) delivers ONE byte-identical clip of the approved `final.mp4`
(it requires a `mirror` lane and rejects a `cuts` lane — `sync.py`). Don't add NEW
composite capability (timeline assembly, color, export) that PIPELINE.md assigns
downstream without checking there first.

`palmier/` (~57 files) is the Stage-4 mirror + native-candidate + authority
subsystem — far more than the original translator. Entry points: `push.py`
(executor CLI), `translate.py` (PURE plan→steps math, loud errors on
untranslatable vocabulary), `mcp_client.py` (HTTP JSON-RPC session,
`127.0.0.1:19789`). Mirror/authority core: `mirror.py`, `shadow.py`, `sync.py`,
`parity.py`, `ownership.py`, `preflight.py`, `native_candidate_lifecycle.py`,
`native_qc*.py`, `timeline_authority.py`, `candidate_qc_contract.py`,
`checkpoint*.py`, `verify*.py`. Wired contract: `docs/palmier/PALMIER_PARITY_CONTRACT.md`
+ `docs/palmier/PALMIER_MIRROR_HANDOFF.md`; what is/isn't wired yet:
`docs/palmier/PALMIER_CANONICAL_IMPLEMENTATION_STATE.md`.

**How these CLIs are driven (GUI):** a detached auto-edit worker
(`src/app/api/producer/auto-edit/worker.ts`; `docs/producer/AUTO_EDIT_LANE.md`) spawns the
`claude`/`codex` CLI to author the plan, runs a bounded plan-review loop (a fresh
independent critic each round) + the deterministic gate bundle, renders isolated
candidates under `.sniper-qc/<token>/round-N/`, and promotes a passing one via
`.sniper-qc-approved.json`. Hand-running the CLIs below reproduces the same stages
without the controller.

**Gate/contract modules (top-level, run each plan-review round):**
`operator_intent_contract.py`, `plan_lint.py` (+ `plan_lint_motion` / `_audio` /
`_reframe` / `_smooth`, `plan_lint_broll.py`, `plan_lint_overlays.py` —
title-card + b-roll window checks called from `lint`), `hook_contract.py`,
`claims_contract.py`, `reference_profile_lint.py`, `transcript_cut_contract.py`
(+ `_evidence` / `_quality`), `template_usage_contract.py` (+ `_approval`),
`intro_transition_contract.py`, `brand_lint.py`; `assemble_lock.py` guards
concurrent assembles.

**READ THIS BEFORE WRITING A NEW FILE.** This is the module index so a session
reuses what's built instead of reinventing it. The brain (you, in the skill) makes
the editorial decisions; these modules PROPOSE (measure/detect) and EXECUTE
(render). If a capability below already exists, extend it — don't clone it.

Operational how-to lives in `.claude/skills/producer/SKILL.md`; the design record
in `docs/producer/PRODUCER_PLAN.md`. This file is the code map.

## The pipeline (what `render.py` orchestrates, in order)

1. **cut+speed** → `cut_speed.py` — trims the cutTrack's ranges, applies per-seg
   `speed`, concatenates to a mezzanine. Executes the cutTrack; does NOT detect
   silence (that's the edit brain, below).
2. **channels / baseline** → `motion/baseline_look.py` — chest-up recrop + warm grade.
3. **face_track → reframe** → `motion/face_track.py`, `motion/reframe.py` — 9:16
   face-aware vertical cut (shorts).
4. **overlays** → `captions/overlays.py` — hook title cards.
5. **graphics** → `graphics/graphics_stage.py` — composites MG entries (renders each
   comp via `graphics/graphics_render.py`; per-entry offset resolution —
   explicit pin / rail / own-screen / Placement v2 — lives in
   `graphics/stage_placement.py`, which places via `planner/graphics_anchors.py`;
   the plan-time comp-size gate's geometry rules live in
   `graphics/comp_measure_rules.py`, orchestrated by `graphics/comp_measure.py`).
6. **punch-ins / motion** → `motion/punch_in.py` — zooms, ramps, brackets, aliveness.
7. **enhance → transitions → gain / master** → `audio/audio_enhance.py`
   (plan.audioEnhance dialogue cleanup, pre-gain) runs FIRST, on the pure
   dialogue bus — BEFORE `motion/transitions.py` amixes the whoosh SFX, so
   `separate` (Demucs, residual −60dB) / voice-rnn can never delete authored
   transition sound; then transitions (seam covers), `audio/audio_gain.py`,
   `audio/master.py` — −14 LUFS master + cover frame. Music (plan.music) is
   NOT a base stage — it's applied at ASSEMBLE time (`audio/music_stage.py`,
   below). A monolithic render with plan.music.enabled emits a loud
   `music_not_applied` warning (assemble applies it).
8. **captions** → `captions/captions_ass.py` — burned karaoke/line captions.
9. **audit** → `audit/audit_render.py` (Audit B) — post-render QC.

`compile_timeline.py` is the **source↔output time map** — the correctness keystone
every planner/caption/graphic depends on to convert a source second to an output
second through the cutTrack. Reuse it for any time mapping; never hand-roll.

## Edit brain — deciding WHAT to cut (`edit/`)

The renderer executes a cutTrack; these BUILD one from a raw take. Silence removal
happens HERE, upstream — not in the renderer.

- `edit/pause_scan.py` — **PROPOSES** which inter-sentence gaps to tighten (raw take
  → trims, each down to a kept breath; protects emphasis pauses). Primary length
  lever for longform (62% of reduction is silence).
- `edit/apply_pauses.py` — **APPLIES** the edit-brain proposals: folds `pause_scan`
  trims AND (via `--retakes`) `retake_scan` cut spans into a clean cutTrack
  (`cut_track_from_pauses`), also dropping an abandoned cold-open fragment. This is
  the wire between propose and execute. Use it to build the cutTrack; don't
  hand-author a single raw segment (leaves dead air + false starts in).
- `edit/retake_scan.py` (top-level `retake_scan.py`) — PROPOSES retake/false-start
  drops from one raw take.
- `edit/speech_cleanup.py` — ONE-SHOT wire (the UI's Speech-cleanup button):
  `speech_cleanup.py <manifest.json> [--source-id ID] [--out f.json]` runs
  pause_scan + retake_scan on the source's transcript and folds both through
  `cut_track_from_pauses` (incl. the cold-open drop). NDJSON events, final line
  `{"status":"done","cutTrack":[...],"segments":N,"removedS":X}`. Doctrine:
  `needsOperator` retakes are SKIPPED unless `--all-retakes` (never auto-cut a
  minute of footage on fuzzy evidence). Wraps the brains above — reimplement
  nothing here.
- `edit/render_cut.py` — standalone CLIPPER-ranges → finished master (quick win; no
  reframe/captions). Consumes ALREADY-decided keep ranges.
- `edit/cut_repair.py` + `target_resolver.py` + `non_ripple.py` — P2
  occurrence-aware `cut.restoreSpeech` analysis. They enumerate bounded
  duration-neutral candidates or return `NON_RIPPLE_IMPOSSIBLE`; they never
  mutate the current picture lock.
- `edit/repair_fragment.py` + `repair_composite.py` — P2 media executor. The
  first renders one exact dirty frame/sample unit; the second must rebuild and
  fully decode the complete candidate, enforce terminal pre-AAC `B(F)`, and
  prove decoded picture/PCM outside the authorized closure before the
  controller can call the candidate proved.
  Ask Editor promotion uses a separate durable
  `PICTURE_LOCKED → CUT_REVIEW → PICTURE_LOCKED` TypeScript transition. It
  accepts only a content-addressed execution package containing the exact
  Python candidate plus real QC/operator receipts. The Python repair action
  stays bound to its original parent; never rebase it onto the review child or
  manufacture the missing acoustic/audition package.
- `edit/study_edit_diff.py` — learns the editor's cut policy by diffing RAW vs EDITED.
- `edit/cover_select.py` — LL-008 slip-cover window scoring (operator review
  2026-07-10: the v2 45.3-47.8s wide cover read as an OUTTAKE — silent,
  mouth-closed, motionless). `score_cover_windows(manifest, span)` scores
  candidate source windows by MEDIAN motion energy (frame-diff) + lower-half
  gesture presence, hard-excludes retake_scan spans ±2s and silent+static
  windows; nothing above the floor → cover the seam with a graphic takeover
  (LESSON-008). Pure scorer (`score_windows`) split from the ffmpeg probe
  (`motion_profile`); knobs in `producer_config.COVER_SELECT`.

## Graphics — the auto-graphics system (`planner/` + `graphics/`)

The brain says WHAT a graphic is; code owns WHERE/WHEN. **`graphics_planner.py` is
the PROPOSER hub** — add a new graphic lane as a `planner/graphics_planner_*.py`
module and wire it into the hub, mirroring the existing lanes. The hub is
**scope-aware**: `_apply_scope` (via `edit_scope`) emits only the lanes the
operator's `target.scope`/`target.lanes` activated — `trim` proposes nothing,
`light` keeps the aliveness creep only, `produced`/`full` are unchanged. A new lane
should slot into the same gate (graphics / broll / motion family).

- `planner/motion_triggers.py` — deterministic candidate detector (the shared
  trigger vocabulary all lanes read).
- Lanes: `graphics_planner_receipts.py` (b-roll receipts), `_sequences.py`,
  `_boundaries.py` (section markers), `_gauge.py` (milestone gauges),
  `_illustration.py` (concept b-roll), `_zoom.py` (punch/aliveness carpet),
  `graphics_reference.py` (deixis → placed comp, cross-format), `_density.py`
  (trim to budget), `_items.py`/`_style.py`/`_rules.py` (shared helpers).
- `graphics_copy.py` — deterministic converge points: brain-written copy + code
  timing → a placed candidate (`fill_list_spec`, `fill_illustration_spec`). The
  `fill_*_spec` seam is where brain copy meets code timing. No LLM calls here.
- `graphics/catalog_discovery.py` (+ `_sources`, `_records`, `_cli`) — READ-ONLY
  discovery over the WHOLE recorded catalog: the vendored mirror index/lock/
  sources (`vendor/hyperframes-catalog/`), the mechanism study
  (`docs/producer/catalog-study/`) and the integrated registry, joined to the
  MEASURED matrix through the existing `comp_capability_artifact` reader (never
  a second validator, never the probe). `catalog_discovery_cli.py search
  "<need>" [--type --declared-aspect --status --tag --limit]` / `lookup <name>`
  → JSON or text with per-item status (`reference` / `reference-missing-source`
  / `integrated-measured` / `integrated-unmeasured`), source path + existence,
  declared vs measured canvas kept separate, evidence-backed adaptation notes,
  loaded provenance + lock/study/disk disagreements. The explicit
  `PORTED_KINDS` mapping joins a local kind to its upstream item only when the
  template declares its provenance; same-named items never share capability.
  Evidence, not admission — the plan/scene adapters and gates still decide.
  Tests: `test_catalog_discovery.py`, `test_catalog_discovery_fixtures.py`.
  `inventory` returns the entire recorded inventory with source hashes and full
  annotations for strategy, without ranking/limit or native execution approval.
  `test_catalog_inventory.py` covers completeness and source drift.
- `graphics/reference_reuse_map.py` / `reference_reuse_validation.py` — explicit
  reference-shot/style planning shared by Short and Long. Existing catalog search
  freezes shot candidates and source bytes; authored inspections choose reuse,
  configure, compose, bounded custom or blocked. Supports retaining a component
  while filling its specific gap. No visual/execution approval or model calls.
  `reference_reuse_cli.py prepare <request> --output <map>` / `check <map>`.
  `studio/native_reference_reuse.py` binds optional `--reference-map` evidence to
  shared native preflight and Short export/resume; absent maps load no catalog.
  See [workflow and schema](../../docs/producer/REFERENCE_SHOT_REUSE.md).
  Tests: `test_reference_reuse_map.py`, `test_reference_reuse_cli.py`,
  `test_native_reference_reuse.py`.
- `graphics/reference_study_bindings.py` — `reference_reuse_cli.py save-study`
  retains inspected matches beyond their original project; `check-study` verifies
  exact reference/candidate bytes without discovery. New requests opt in with
  `studyBindings` and per-shot `studyMatch`, retaining previous inspections and
  decisions as evidence while requiring a new adaptation decision. Tested across
  Short → long-form in `test_reference_study_bindings.py`.
- `native-short.ts prepare-longform` / `check-longform` reuse existing ingest,
  intent, reference selection and shared catalog through server helpers
  `native-longform-request`, `reference-strategy-library`,
  `longform-reference-inputs` and `longform-strategy-packet`. They freeze the full
  research/catalog indexes and complete selected event sequence into a local
  1920×1080 strategy request; no provider, automatic style qualification or render.
  See `REFERENCE_SHOT_REUSE.md`; TS test `native-longform-request.test.ts`.
- Placement: `planner/free_space.py` (absolute free-space map, SAFE_BOX-clamped) +
  `planner/graphics_anchors.py` (`resolve_offset_v2` measures + places into the
  emptiest legal region; v1 fallback). Reuse for any placement — it already clamps
  to safe margins.
- `planner/icon_library.py` — fetch/cache brand icons (chip-row / icon-badge
  marks) + `resolve_name` (the COMBINED icon order: Simple Icons brand mark
  wins, vendored Lucide glyph falls back as `"lucide/<name>"`, unknown fails
  loudly). `planner/icon_lucide.py` — the vendored Lucide glyph subset (~55
  generic marks: check/arrow/database/cpu/globe/lock/chart…, ISC, pinned
  `lucide-static@0.525.0`) at `templates/motion/icons/lucide/` (+ manifest +
  PROVENANCE.md); comps take `iconFile: "lucide/check"` with zero changes.
- Render: `graphics/graphics_render.py` (hyperframes + content-hash cache),
  `graphics/graphics_stage.py` (compositing; an entry may carry
  `"takeoverBase": "blur-desat"` — G5 punch treatment: the FOOTAGE gaussian-
  blurs + desaturates under the window, 1-frame apply/restore via enable
  gating), `graphics/exit_on_cut.py` (G4 THE EXIT LAW: `"exitOnCut": true`
  clamps an entry's outEnd to the next cutTrack seam — shared by lint,
  render.py and assemble.py so they can't drift), `graphics/pip_takeover.py`
  (longform glass takeover move). Comps are HTML under
  `templates/motion/compositions/` (punch pack: `punch-shout-lockup` +
  tokens.css `--lemon`/`--font-serif-display`/pop tokens + `motion-tokens.js`).

## Incremental graphics — the render → lock → composite loop (`assemble.py`)

For iterating graphics WITHOUT a full re-render each tweak (ported from the
video-editor's `workflows/incremental-graphics.md`). Because punch-in runs BEFORE
graphics, our graphics are output-space overlays → the base cleanly separates:

1. **BASE** — `render.py --skip-graphics <plan> <manifest> <base_dir>` masters the
   whole pipeline EXCEPT the graphics composite → `base_dir/final.mp4` +
   `base.fingerprint.json` (a hash of every base-shaping plan field). Rendered once.
2. **ASSEMBLE** — `assemble.py <base.mp4> <plan> <out.mp4> [--fingerprint …]`
   renders each `graphicsTrack` entry (content-hash cached) and overlays them onto
   the base in ONE ffmpeg pass (audio stream-copied from the mastered base). An
   ordinary graphic edit rerenders only that clip and the composite; graphics that
   change long-form recomposition or legacy-caption suppression correctly rebuild
   the base.

**Fingerprints are SPLIT** (`fingerprints.py`, shared by render + assemble):
`base_fingerprint` (legacy full print — graphics/planVersion/music excluded via
`_NON_BASE_KEYS`), `videoFingerprint` (base fields EXCEPT audioEnhance/audioGain;
transitions stay video-side — their flash frames are baked into the picture) and
`audioFingerprint` ({audioEnhance, audioGain}). `base.fingerprint.json` records
all three; when the `base_plan.json` snapshot sits beside it (every writer
stores both), `recorded_fingerprints` RECOMPUTES the prints from the snapshot,
so old bases survive hash-function changes and pre-split files gain their
prints. Hashing goes through `json_canon` (integral floats → ints, bools kept):
the editor's save-plan writes via JS `JSON.stringify`, which collapses `30.0`
→ `30` — without canonicalization a zero-change UI save flipped the base
fingerprint into a spurious ~3 min rebuild (fixed 2026-07-09; the graphics
`content_hash` cache key canonicalizes the spec the same way). Guards ported
from the reference: `eof_action=pass` on every overlay
(the 1-in-4 duplicate-frame stutter) + the YDIF dup-ratio FAIL ≥ 8% — the probe
now rides INSIDE the composite pass (a signalstats `metadata=print` tap on a
split of the final label; PRE-encode frames, same 0.08 threshold;
`_ydif_dup_ratio` remains for the passthrough/standalone paths). Perf notes
(2026-07-09): `graphics_stage._probe_frames` counts PACKETS, not decoded frames
(identical 2598 on our H.264 MP4s, 0.085s vs 16.5s), and the composite encodes
with `ENCODE["composite_preset"]` = veryfast (16.9s→9.4s; CRF 12 still governs
quality — VideoToolbox rejected: slower AND loses CRF).

**The graphics/base boundary is explicit, not mode-wide.**
`graphics_base_effects.py` projects only long-form rail/recompose geometry and
legacy-caption suppression windows into the base/video fingerprints. In a
`--skip-graphics` render, those windows remove legacy ASS cues before the base
encode; explicit `CaptionTrackV1` captions remain post-base shards. Ordinary
scene copy and `presenterFrame` alpha/format changes retain the base in both
short and long-form workflows.

**The render-effect vocabulary is closed.**
`render-effect-registry-v1.json` owns every released public plan/manifest root;
`render_effect_registry.py` rejects unknown or unreleased roots and
`render_effect_discovery.py` scans the current renderer import closure for
unregistered literal readers. `render_stage_roots.py` compiles domain-separated
timeline, base, per-scene, composite, final, and manifest roots into the current
`RenderGraphV1` bridge. Generated registry mutations are the authority for which
roots move and whether base reuse is legal; add a registry row and mutation
before teaching the renderer a new public field.

**`--auto-base` is the smart re-render dispatch** (the editor's one button):
`assemble.py <base> <plan> <out> --fingerprint base.fingerprint.json --auto-base`
checks the base state — `current` composites fast; `audio_stale` (video print
matches, audio print changed) takes the **AUDIO-ONLY fast path**
(`audio/base_audio.py`): the base keeps its video stream and only the audio bus
is rebuilt — enhance → gain → two-pass loudnorm re-master (via `master.py`'s
public `build_pass2_afilter` seam), `-c:v copy` at every step — then, when the
existing final.mp4's `.assembled.json` sidecar proves its composite is current
(same videoFingerprint + graphicsTrack), the new audio is MUXED onto it (no
recomposite; music still applies after). HONEST fallbacks (loud
`audio_fast_path_skipped` → full rebuild): audio fields already baked into the
base (can't un-bake — a SECOND tweak of the same field costs a full rebuild),
and audioEnhance on plans with sfx transitions (enhance runs BEFORE the whoosh
amix in the pipeline, but the whooshes are baked into the base audio; gain-only
stays fast — gain runs AFTER the amix, so the mastered bus reproduces the order
exactly). `stale`/`missing` first refits the plan's output-time windows to the
edited cutTrack via `edit/plan_refit.py` (old timebase from the
`base_plan.json` snapshot; pure arithmetic through the source↔output map,
dropped windows reported loudly). The refit is TRANSACTIONAL: staged to
`<plan>.refit.json` and promoted over the operator's plan only after the
rebuild succeeds — a failed rebuild leaves the plan untouched so a retry
re-runs the identical refit (no double shift). Then it re-runs
`render.py --skip-graphics` (~3 min, manifest from `--manifest` or the
`manifestPath` recorded in the fingerprint file) and composites. Measured on
the 108s e2e longform (2026-07-09): graphics-only fast path **19.9s** incl. the
3.0s proxy (was 60.9s); audioGain tweak **11.7s** end-to-end (was ~158s); full
base rebuild still ~190s.

**Preview proxy** — after every successful assemble, `preview_proxy.py` writes
`final.proxy.mp4` next to the output: short side 480 (even dims), x264 CRF 28
veryfast, keyframe every 24 frames (scrub-dense), AAC 96k, faststart. Measured
2.7-3.0s / ~27x smaller on the 108s final; 0.25s on a 5s short. Emits
`{status:"proxy", path, ms, bytes}`; failure is the ONE documented
warn-and-continue exception (`proxy_failed`) — the deliverable already
succeeded, a broken preview must not fail the render.

**Draft mode** — `draft_render.py <plan> <manifest> <producer_dir>` = the
pre-review-wall WATCHABLE candidate (geometry-contract v3 item #8): subprocesses
`render.py` into `<producer_dir>/draft/` with `--approval-dir <producer_dir>`
(same delivery-approval receipt the final render enforces; Audit B skipped by
default, `--audit` opts in), then one fast drawtext pass (veryfast, `-c:a copy`,
knobs in `producer_config.DRAFT`) burns a center + corner DRAFT watermark into
`draft/draft.mp4` and deletes the unwatermarked `final.mp4` + its
`.assembled.json`. A draft can never ship: wrong name/dir for
`palmier/master.py`'s `final.mp4` path key, no provenance, and it never writes
`.sniper-qc-approved.json` (refuses to run if one appears in `draft/`).

**Music at assemble** — after the composite + YDIF check, `plan.music =
{enabled, path|assetId, duck (default true), gapDb}` is applied by
`audio/music_stage.py`: resolve the track (`path` absolute, or `assetId` via an
explicit `--manifest` (wins) or the fingerprint's recorded manifest — music
manifest entries carry file paths; any miss fails loudly), then `audio/audio_mix.py` lays the bed (pre-norm to dialogue−gapDb,
mandatory sidechain duck whenever dialogue exists, re-master to −14 LUFS) audio-only over the
assembled output — the video stream is copied. Music edits never rebuild the base.
At Palmier handoff this mastered bus replaces the NLE's raw linked audio; see
`docs/findings/AUDIO_AUTHORITY_AT_NLE_HANDOFF.md`.

## Motion, audio, captions, b-roll

- `motion/` — `reframe`, `reframe_split`, `face_track`, `punch_in` (zoom engine),
  `baseline_look`, `transitions` (seam covers: flash/leak ONLY — the stock
  ffmpeg-xfade family was operator-rejected and REMOVED 2026-07-11
  (FAILURE_LEDGER LL-014); longform seams use Sniper's seam grammar
  (`docs/studies/MODULE_STUDY.md` §2, `EDITCRAFT_LESSONS.md` §2.7):
  panel sweeps, face-bridged recompose, under-panel cuts, blur-recede,
  seam-role zoom-pulls — `plan_lint_motion` hard-ERRORs any `xfade:*` kind in
  every mode; the SFX slot takes `true|false|"<pack-name>"` resolved
  through `audio/sfx_library`), `visual_state`, `recompose`
  (FACE-ANCHORED RECOMPOSE, defect report 2026-07-10 §1: a rail/panel entry
  declares `recompose: {clearX: [x0,x1]}` → a synced `role:"recompose"`
  punchIns push window that scales+pans the footage, eased 0.4s with a 0.12s
  lead, so the face lands at the clear-region midpoint; both edges eased via
  punch_in's `releaseS`; `motion/recompose.py <plan>` stamps rail kinds on
  longform + rebuilds the windows idempotently — run it in SKILL step 4a).
- **Reframe layouts** (`plan.reframe.layout`, 2026-07-09): `"fill"` (default,
  layout absent = today's strategy path) or `"split"`. `split` = Opus-Clip
  "Layout: Split" for StreamYard-style screen-share sources (webcam inset +
  shared screen baked into one 16:9 frame): TWO normalized `[x,y,w,h]` crops of
  the same source — `reframe.split.top/bottom.crop`, `top.frac` (0.3–0.7, default
  0.5) = top cell's share of output height — each scaled to COVER its cell
  (center-crop, never letterbox), vstacked to 1080x1920. 9:16 shorts ONLY.
  Sibling: fill-mode `reframe.crop` manual override — wins over the automatic
  face crop, scale-to-cover the full canvas. Both dispatch in `render.py`'s
  `reframe_stage` to `motion/reframe_split.py` (face_track skipped; geometry is
  denorm + even-snap + fail-loud on out-of-frame rects — never clamp; rects
  denorm against DISPLAY dims — `cut_speed.display_dims`, edge I9: rotation
  side data swaps the canvas and ffmpeg autorotates). Bounds
  live in `producer_config.REFRAME_SPLIT`; lint = `plan_lint_reframe.py`.
  Manual crop/split + `plan.baselineLook` is a lint ERROR (v1): crops are drawn
  on the raw source frame but baseline_stage recrops BEFORE reframe — no
  coordinate transform yet, fail loud.
  `reframe.track` is reserved (only `false` accepted — tracker not yet wired).
  reframe is BASE-side: any layout/crop edit flips the base fingerprint.
- `audio/program_finish_contract.py` + `audio/program_finish_bus.py` — **source-float-v2
  audio finishing** (2026-09-08). On the v2 path `audioEnhance`, `audioGain` and
  `transitions[].sfx` are NOT base stages: `render.py` skips the legacy enhance/gain
  stages and strips seam SFX from the transitions stage once the source-float
  admission holds, and assemble applies them on the retained float dialogue bus at
  program-master time (`program_mix_bus.build_program_mix` → `render_finishing`):
  cleanup (catalog ffmpeg chain; `separate` is refused, it needs a downloaded
  Demucs runtime) → measured-latency removal (afftdn/arnndn are not latency-free
  and do not flush their tail; the chain input is padded by the measured delay +
  100 ms guard, then the delay is trimmed) → the existing trapezoid gain windows
  (`audio_gain.build_filter`, evaluated every 256 samples) → authored SFX summed
  sample-exactly (engine whoosh via `motion.transitions.synth_whoosh`, pack items
  via `sfx_library.resolve`; hit lands on the seam) → music bed ducked by the
  finished dialogue WITHOUT SFX → the single whole-program master. Everything stays
  pcm_f32le at the bus clock. `audio_policy_reason(plan, "source-float-v2")` now
  validates finishing (`finishing_reason`) instead of refusing it; v1 still refuses.
  The program-master receipt carries `finishing` (settings, filters, measured delay,
  model/SFX sha256s, finished stem identities) and `audioProgramInputHash` digests
  it, so a finishing revision invalidates excerpts/pointers/graph node-final while
  the raw bus (cutTrack+target domain) and the base stay current
  (`assemble._finishing_invariant_current`, `cut_delivery_authority.base_plan_lineage_digest`,
  `assemble_picture_reuse` use `finishing_free_plan`). `assemble_source_audio` reuses
  the retained program master for non-audio revisions after `load_program_master`
  re-proves it (`programMasterReused`). Tests: `test_program_finish_contract.py`,
  `test_program_finish_media.py`, `test_assemble_finishing_media.py`.
- `audio/` — `master` (encode + loudnorm + cover), `audio_enhance` (plan.audioEnhance
  dialogue cleanup — the SINGLE entry point the renderer calls; presets in
  `producer_config.AUDIO_ENHANCE`: `voice`/`voice-strong` (afftdn — steady noise
  only), `voice-rnn` (RNNoise `arnndn`, model vendored `audio/models/bd.rnnn`,
  `{models}` token substituted by `build_filter`), `separate` (dispatch sentinel →
  `audio_separate`)), `audio_separate` (Demucs two-stem: extract 48k wav → demucs
  → remix vocals + residual at `--residual-db`, default −60 ≈ mute; needs
  `pip install demucs torchcodec`, first run downloads weights), `audio_gain`
  (per-section bus; its `parse_windows` is also the lint validator — see
  `plan_lint_audio`), `audio_mix`/`audio_mix_bed` (music bed + ducking; `MixSpec`
  carries the plan.music `duck`/`gap_db` knobs; `--no-duck` is music-only,
  `--gap-db` controls the voice-priority rest margin),
  `music_stage` (assemble-time plan.music application — see assemble section),
  `base_audio` (the AUDIO-ONLY base fast path: eligibility + bus rebuild + mux —
  see the `--auto-base` section; reuses enhance/gain/master, duplicates none),
  `sfx_library` (the starter SFX pack: catalog + resolve + deterministic
  `build` — seeded ffmpeg synthesis into `assets/sfx/` with PROVENANCE.md;
  each name carries a `lead_s` so the renderer lands the HIT on the seam).
- `captions/` — `captions_ass` (burned karaoke; aspect-aware geometry via
  `caption_cfg_for_aspect`), `captions_minimal`, `captions_whisper` (the punch
  base layer, `captions.style: "whisper"` — 1-3 word sentence-case replace
  cues, no karaoke, inline amber tier-A emphasis; `CAPTIONS["WHISPER"]`),
  `overlays` (hook cards),
  `caption_corrections`, `bake_emoji`, `longform_outputs` (SRT + chapters — WIRED
  into `render.py` `longform_sidecar_stage`; longform ships the SRT even when not
  burning, so a longform is never caption-less). Explicit `CaptionTrackV1`
  authority uses `caption_plan_pipeline` → `caption_shards` (cue-local,
  font-byte-bound RGBA clips) → `caption_shard_composite`; the same compilation
  writes SRT, semantic chapters, regenerable Palmier bindings, authority, and
  Audit B evidence. Caption-only changes restore the proved caption-free
  composite and rebuild only dirty shard keys.
- **`graphics/pip_takeover.py` is UNWIRED** (the ANIMATED shrink-to-PIP,
  MODULE §5 item 10) — `render.py` never calls it; `plan_lint_motion` still
  HARD-REJECTS `needsPip`/`canvas-pip-list` entries. BUT the STATIC
  face-in-PIP takeover IS wired (§5 item 9, operator-adjudicated legal for
  longform 2026-07-10, banned for shorts): hole-comps
  (`graphics/pip_hole.py` registry — `module-takeover`) render the frame
  around a transparent face hole with alpha forced by
  `graphics_render.format_for`, and `graphics_stage` scales the base footage
  into the hole at composite time (`pipHole` branch). Gates in
  `plan_lint_module.py` (longform-only + own-screen; also lints the
  `glass-rail` `spec.entrance: "rail-push"` move, §5 item 8).
- `broll/` — `broll_pool` (operator's pool: vision cataloging + resolve),
  `broll_insert` (receipts ride on top, never touch audio).

## Gates & QC — mode-aware, run for shorts AND longs

- `plan_lint.py` — editorial gate between brain and renderer (both modes).
- `plan_lint_reframe.py` — reframe-section lint (called from `plan_lint`):
  strategy rules + the fill/split layout contract (layout enum, split = shorts
  only with BOTH cells, crop rects 4 numbers in [0,1] w/h ≥ 0.05 inside the
  frame, frac in [0.3,0.7], `track` only false, reframe must be an object,
  manual crop/split rejected alongside `baselineLook`).
- `plan_lint_audio.py` — audio-field lint (called from `plan_lint`, mirrors
  `_motion`): `audioEnhance.preset` must be in the AUDIO_ENHANCE catalog;
  `audioGain` validated through `audio_gain.parse_windows` (the executor's own
  validator — lint and renderer can't drift) + bounds/overlap; `music.path`
  (absolute existing file) accepted as the assetId alternative, plus
  `duck`/`gapDb` sanity; `gapDb` must keep voice at least 3 dB above the bed.
- `hook_contract.py` — the **Hook Contract**: content-derived, scope-aware HARD
  gate that FAILS a plan whose intro is MISSING an owed element (named tool→graphic,
  credibility claim→PIP/card, strong beat→push, captions). Derives obligations from
  the transcript so a forgetful brain gets caught; run in the skill's planning-
  convergence loop (SKILL step 4) alongside `plan_lint`. Reads `edit_scope`.
- `claims_contract.py` — the **Claims Contract** (truth gate, MODULE_STUDY
  §5.6): pre-render, every NUMERIC token in card copy (`graphicsTrack[].spec`
  strings + `titleCards[].text`) must be SPOKEN in the card's window —
  arithmetic string/number match (K/M/B scales, spelled cardinals via lookup),
  never regex semantics; `evidence*`/`icon*` slots exempt. The brain owns
  paraphrase faithfulness (SKILL step 4b). Same CLI shape as `hook_contract`.
- `planner/word_lock.py` — word-locked seams (MODULE_STUDY T-G):
  `snap_to_word_boundary` / `snap_plan_seams` move `transitions[].outTime` and
  translate `graphicsTrack[]` windows onto kept-word boundaries at plan time;
  `plan_lint_motion.check_word_lock` WARNs on seams >150ms off-boundary
  (runs when `plan_lint.py` gets the optional `[transcripts_dir]` arg).
- Narration-paced module builds (MODULE_STUDY §5.4): the brain picks WHICH
  kept words a card's modules land on, `graphics_copy.fill_module_lands`
  converts them to comp-relative `spec.moduleLands` (the comp schedules its
  builds off it); `plan_lint_motion` validates lands (increasing, ≥0.25s
  apart — `MOTION["module_lands"]` — inside the hold).
- `review_packet.py` — the skill review wall's hash-bound critic evidence
  packet (SKILL step 4): plan + manifest byte hashes, the cut-segment table
  with rationales, kept words remapped via `compile_timeline`, cut-boundary
  neighbor words, the plan_lint/hook_contract/claims_contract verdicts +
  `gateDigest`, and the pacing report, sealed under a deterministic
  `contentDigest` (same inputs → same digest). Build ONCE per review round;
  round-1 concurrent critics all read the SAME packet instead of re-deriving
  the transcript (mirrors the GUI's `plan-review-packet.ts`). CLI:
  `review_packet.py <plan> <transcripts_dir> <manifest> --out packet.json`.
- `edit_scope.py` — resolves the operator's `target.scope` (trim/light/produced/
  full) + `target.lanes` per-lane directives into the active-lane map. Single source
  of truth for "what did the operator ask for"; the contract + planners key on
  `lane_required()`. Back-compat: `treatment` maps onto a scope.
- `plan_lint_motion.py` — MG-track lint (graphics/treatment/audio/zoom cadence);
  `if mode == "longform"` branches, shorts get a uniform cut-driven budget.
- `plan_lint_smooth.py` — SMOOTH LONGFORM grammar (defect report 2026-07-10,
  called from `check_motion`, longform only): every punchIns boundary whose
  scale steps discontinuously (computed from punch_in's own pure mirrors)
  must land ON a cut seam — off-seam pops are shorts grammar (ERROR); pushes
  ease ≥0.25s in AND out; footage never punches under a live non-own-screen
  panel (ERROR, defect 4); rail windows without a synced recompose, >3 layout
  families (`MOTION["layout_families"]`), and flash/leak transitions WARN.
  Plus LL-007 (operator, v2 showpiece): an in→out zoom pair resolving within
  `gap_pair_max_s` (4s) that overlaps NO graphic and carries NO emphasis
  trigger/evidence WARNs — zooms are not gap-fillers; `pacing.suggest_fills`
  longform fills now propose graphic/panel-extension, never a punch.
  Knobs in `producer_config.MOTION["longform_smooth"]` / `["recompose"]`.
- `plan_lint_visual.py` — LEARNING-LOOP visual lint (showpiece QC 2026-07-10,
  called from `check_motion`; each rule names its `docs/findings/
  FAILURE_LEDGER.md` row): first DECLARED content land (moduleLands[0]/min
  atN) within `MOTION["first_land"]` of outStart (own-screen ERROR 0.6s,
  panel WARN 0.9s — empty-chrome staging, LL-002); WCAG accent-vs-bg
  contrast ≥3:1 for cataloged kinds (`MOTION["contrast"]["kind_bg"]`,
  LL-004); left-column own-screen holds >5s WARN (LL-005); FORM SELECTION +
  VARIETY (MODULE_CARDS §1.4/§2, LL-015/LL-016): `check_form_shape`
  (transcript-armed path only — comparison-shaped info, ≥2 numeric spec
  tokens + a spoken comparative marker, on a kind outside
  `MOTION["card_form_map"]["comparison"]` WARNs) and `check_variety`
  (consecutive same-kind WARN, caption layers + statements[] chains exempt;
  produced/full longform ≥6 windows below the `MOTION["variety"]`
  distinct-kind floor WARNs). Sibling LL-001
  (blur-recede seam runway) lives in `graphics/exit_on_cut.py`
  (`EXIT_RUNWAY_S`); LL-003 (unspoken >2-word phrases) in `claims_contract`
  phrase grounding + `STRUCTURAL_LABELS`.
- `ledger_lessons.py` + `docs/findings/FAILURE_LEDGER.md` — the LEARNING
  LOOP's memory: append-only defect ledger (id/defect/root cause/caught-by/
  encoded-as/status) + the "## Brain lessons" section (LESSON-id lines) that
  the auto-edit authoring prompt AND SKILL step 4 are contractually bound to
  obey. `parse_lessons()`/`parse_rows()`; `sync-checklist` regenerates the
  derived failure-modes block of `docs/findings/QC_CHECKLIST.md` (the
  standing QC-panel brief — future QC panels read it first). Every new
  QC/operator defect = a ledger row + an encoding (lint rule/test/LESSON).
- `audit/audit_render.py` (Audit B) → `audit/audit_motion.py` (pacing/presence/
  smoothness, WARN-only), `audit_frames`, `audit_glitch`, `audit_probe`.
- Budgets (floors, per-mode) live in `producer_config.py` — e.g. shorts
  `pacing.min_changes_per_min: 12.0`, `max_still_gap_s: 8.0`. Change a threshold
  there, never inline. Longform still-gap is **region-aware** (`hook_still_gap_s: 4`
  vs `max_still_gap_s: 20`): the hook must stay dense, the body may breathe — the
  front-loaded envelope from `docs/studies/PRODUCTION_ENVELOPE_STUDY.md`. Don't flatten it
  back to one ceiling.

## Study — learning from reference videos (`study/`)

- `study/study_video.py` — the STUDY fingerprint (pacing / states / audio);
  submodules `study_cuts` / `study_states` / `study_audio` / `study_transcribe`.
- `study/study_deep.py` — the DETERMINISTIC deep extractor: P1 fingerprint
  (auto-runs study_video if absent) → P2 per-frame motion signals (d-metric,
  Haar face track + width zoom proxy, phaseCorrelate pan, dark/bright, YDIF==0
  freezes) → P3 unified events[] (cut/zoom/pan/panel/graphic/freeze/flash with
  bbox, transition class hard-cut/sweep/fade/flash/pop, direction+frames,
  ACTIVE-SPAN easing fit linear/power2-out/power3-out/bell) → P4 tesseract
  text (per-graphic OCR + colors + per-word timing, caption-system stats
  incl. karaoke) → P5 word-lock stats (reuses `planner/word_lock`) → P6
  OPT-IN `--semantics` agent micro-layer (schema-forced `claude -p` per
  graphic event; core runs with ZERO AI). One canonical `deep_study.json` —
  schema in `study/DEEP_SCHEMA.md`; thresholds in `study/deep_config.py`
  (never inline). The EVENT layer (rebuilt after the acid audit 2026-07-10)
  is three-tier: impulses + runs + a freeze-sided POP SCAN (`deep_pops` —
  keyword pops sit at d≈3-4 on a ≈2 talking-head floor, only a per-pixel
  freeze/extreme-luma region diff finds them); cuts are scdet-anchored with
  punch magnitude from the faceW step (`deep_face` — NEVER ORB across a cut,
  91% error); a ≤3-frame motion is a STEP (a cut), never an eased zoom; runs
  separate by region/signal family (`deep_face` glide/zoom + `deep_chrome`
  panel/rail/takeover per-region timelines + `deep_classify_motion` faceless
  probes) so a rail push never conflates with the face glide and lower-third
  out it rides with. Submodules: `deep_frames` (ffmpeg rawvideo decode),
  `deep_signals`, `deep_events` (low-percentile baseline — a rolling MEDIAN
  swallows 20-30 frame motions; scdet forcing + family dedup), `deep_classify`
  (+`_motion`), `deep_face`, `deep_chrome`, `deep_pops`,
  `deep_regions(+_inout)`, `deep_easing`, `deep_text`, `deep_captions`,
  `deep_wordlock`, `deep_semantics`. Ground-truth tests:
  `tests/test_study_deep.py` + `tests/_deep_synth.py` (constructed clip with
  known cut/pop/jump-cut/sweep/zoom/easing/OCR) + `tests/test_deep_units.py`
  (per-fix pure-function units).
- `study/study_zoom.py` (+`study_zoom_faces`/`zoom_scale`/`zoom_detect`) — the
  ZOOM MAP of an edited cut vs its cut list (punch-in cuts + animated ramps).

## Ingest & test

- `ingest.py` / `ingest_probe.py` / `ingest_scan.py` — build `asset_manifest.json`.
  Canonical Producer ingest first routes raw sources, input-project b-roll, and
  input-project music through `ingest_admission.py`; manifest executable paths
  name immutable snapshots and bind a content-addressed source-set receipt.
  `render.py`/`assemble.py` reverify that receipt when present. Every
  `broll_pool.py` command requires the manifest, rejects late additions until
  canonical re-ingest, and probes/extracts only admitted snapshots. Reference
  video intake has a separate retained admission authority, and canonical
  `music.path` is restricted to admitted manifest rows. Reference text
  sidecars, legacy no-flag CLI calls, and Palmier live-build imports remain
  separate boundaries; see
  `docs/findings/INGEST_ADMISSION_IS_NOT_ALL_INGRESS_ADMISSION.md`.
  Repo-bundled starter beds (`PROJECT_SNIPER/assets/music/*`) auto-register into
  `manifest.music` AFTER the project's own `music/` (ids continue `music-N`,
  `source: "builtin"`), so `plan.music.assetId` resolves out of the box.
- `make_test_footage.py` — synthetic clips for tests.
- `selftest.py` + `tests/` — stdlib `unittest` (no pytest). Run
  `PYTHONPATH=.:tests ../../.venv/bin/python3 selftest.py`. Shared fixtures +
  module aliases in `tests/_common.py` — add new tests there, reuse the aliases.

## House rules (see repo memory / CLAUDE.md at root)

- **Skills-only.** No feature flags, no live/paid API calls in pipeline code. The
  brain does LLM work in the skill flow ($0).
- **No regex for semantics.** Deterministic code finds WHERE (beats/timing); the
  brain writes WHAT (copy). Numeric magnitude parsing is arithmetic, not semantics.
- **No fallback matching** — fix upstream, don't fuzzy-match over a data mismatch.
- Line limits (logic files): 300 lines / 50-line funcs / 4 params / 2 nesting. Data
  catalogs and comments are exempt.

Long-form research OCR: `study/study_deep.py --text-scope states` retains every motion event and transcript word-lock while reading all visual state representatives. Per-event OCR timing is explicitly unmeasured; the default full text scope is unchanged. `test_study_text_scope.py` covers this boundary. See `study/DEEP_SCHEMA.md`.
