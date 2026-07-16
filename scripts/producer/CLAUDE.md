# CLAUDE.md — PRODUCER (`scripts/producer/`)

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
`_reframe` / `_smooth`, `plan_lint_broll.py`), `hook_contract.py`,
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
   comp via `graphics/graphics_render.py`, places via `planner/graphics_anchors.py`).
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
  `"takeoverBase": "blur-desat"` — G5 jaden treatment: the FOOTAGE gaussian-
  blurs + desaturates under the window, 1-frame apply/restore via enable
  gating), `graphics/exit_on_cut.py` (G4 THE EXIT LAW: `"exitOnCut": true`
  clamps an entry's outEnd to the next cutTrack seam — shared by lint,
  render.py and assemble.py so they can't drift), `graphics/pip_takeover.py`
  (longform glass takeover move). Comps are HTML under
  `templates/motion/compositions/` (jaden pack: `jaden-shout-lockup` +
  tokens.css `--lemon`/`--font-serif-display`/pop tokens + `motion-tokens.js`).

## Incremental graphics — the render → lock → composite loop (`assemble.py`)

For iterating graphics WITHOUT a full re-render each tweak (ported from the
video-editor's `workflows/incremental-graphics.md`). Because punch-in runs BEFORE
graphics, our graphics are output-space overlays → the base cleanly separates:

1. **BASE** — `render.py --skip-graphics <plan> <manifest> <base_dir>` masters the
   whole pipeline EXCEPT the graphics composite → `base_dir/final.mp4` +
   `base.fingerprint.json` (a hash of every non-graphics plan field). Rendered once.
2. **ASSEMBLE** — `assemble.py <base.mp4> <plan> <out.mp4> [--fingerprint …]`
   renders each `graphicsTrack` entry (content-hash cached) and overlays them onto
   the base in ONE ffmpeg pass (audio stream-copied from the mastered base). Edit a
   graphic → only that clip re-renders → re-assemble in seconds; the base is reused.

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
**Longform-first**: graphics composite after master, so burned-caption suppression
under an own-screen takeover (shorts) isn't available here yet — shorts keep the
monolithic path.

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
  (FAILURE_LEDGER LL-014); longform seams use the studied reference grammar:
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
  `caption_cfg_for_aspect`), `captions_minimal`, `captions_whisper` (the jaden
  base layer, `captions.style: "whisper"` — 1-3 word sentence-case replace
  cues, no karaoke, inline amber tier-A emphasis; `CAPTIONS["WHISPER"]`),
  `overlays` (hook cards),
  `caption_corrections`, `bake_emoji`, `longform_outputs` (SRT + chapters — WIRED
  into `render.py` `longform_sidecar_stage`; longform ships the SRT even when not
  burning, so a longform is never caption-less).
- **`graphics/pip_takeover.py` is UNWIRED** (the ANIMATED shrink-to-PIP,
  NATEHERK §5 item 10) — `render.py` never calls it; `plan_lint_motion` still
  HARD-REJECTS `needsPip`/`canvas-pip-list` entries. BUT the STATIC
  face-in-PIP takeover IS wired (§5 item 9, operator-adjudicated legal for
  longform 2026-07-10, banned for shorts): hole-comps
  (`graphics/pip_hole.py` registry — `nateherk-takeover`) render the frame
  around a transparent face hole with alpha forced by
  `graphics_render.format_for`, and `graphics_stage` scales the base footage
  into the hole at composite time (`pipHole` branch). Gates in
  `plan_lint_nateherk.py` (longform-only + own-screen; also lints the
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
- `claims_contract.py` — the **Claims Contract** (truth gate, NATEHERK_STUDY
  §5.6): pre-render, every NUMERIC token in card copy (`graphicsTrack[].spec`
  strings + `titleCards[].text`) must be SPOKEN in the card's window —
  arithmetic string/number match (K/M/B scales, spelled cardinals via lookup),
  never regex semantics; `evidence*`/`icon*` slots exempt. The brain owns
  paraphrase faithfulness (SKILL step 4b). Same CLI shape as `hook_contract`.
- `planner/word_lock.py` — word-locked seams (NATEHERK_STUDY T-G):
  `snap_to_word_boundary` / `snap_plan_seams` move `transitions[].outTime` and
  translate `graphicsTrack[]` windows onto kept-word boundaries at plan time;
  `plan_lint_motion.check_word_lock` WARNs on seams >150ms off-boundary
  (runs when `plan_lint.py` gets the optional `[transcripts_dir]` arg).
- Narration-paced module builds (NATEHERK_STUDY §5.4): the brain picks WHICH
  kept words a card's modules land on, `graphics_copy.fill_module_lands`
  converts them to comp-relative `spec.moduleLands` (the comp schedules its
  builds off it); `plan_lint_motion` validates lands (increasing, ≥0.25s
  apart — `MOTION["module_lands"]` — inside the hold).
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
  VARIETY (NATEHERK_CARDS §1.4/§2, LL-015/LL-016): `check_form_shape`
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
