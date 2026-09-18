# PRODUCER Editor — historical handoff (2026-07-10)

> **Historical snapshot, not current release evidence.** Several counts,
> timings, capability claims, and gap lists below describe the 2026-07-10 tree.
> Use [`AUTO_EDIT_LANE.md`](producer/AUTO_EDIT_LANE.md),
> [`PIPELINE.md`](PIPELINE.md), and the
> [short/long executable matrix](producer/command-driven-editing/12_SHORT_LONG_EXECUTABLE_MATRIX.md)
> for current behavior. In particular, the current controller uses detached
> `claude`/`codex` workers plus bounded plan/render review, the in-house approved
> MP4 is canonical, and connected editable Palmier delivery remains
> qualification-gated.

The "poor-man's NLE": a skills-only AI video editor at `localhost:3000/producer`.
Raw footage → brain-authored edit → human polish in the editor → `final.mp4`.
The historical local-mode path used the subscription-authenticated
`claude`/`codex` CLI rather than a usage-metered API key. That is not an offline
claim: transcript/plan context still leaves the machine for the selected model
service.

**Destination (canonical: `PIPELINE.md`):** upload into PRODUCER → intent card
(Short w/ style: Restrained/Punch/Slideware · Long w/ item checklist, full workflow or
à la carte) → gated plan → the in-house render chain produces the approved
**`final.mp4`** (the primary, canonical output). **Palmier Pro is an OPTIONAL,
post-approval, one-way exact-master mirror:** `scripts/producer/palmier/push.py
<plan> <manifest> [--export]` (`--export` → `<project>/final.palmier.mp4`) mirrors
that approved master as one flat clip. The C0679 frame check cited by the
original handoff is historical evidence for that earlier tree, not current
connected P5 qualification.

Start: open the project in **Claude Code desktop** (the easy path — see the repo
`README.md`). The web GUI is optional: `npm run dev:local` (server may already be
running, detached).
Full session-by-session state lives in Claude's memory file
`project_producer_editor_ui.md`; module map in `scripts/producer/CLAUDE.md`.

## Historical loop snapshot

1. **Ingest** — producer tab → pick footage → **intent card** (Short|Long, preset
   chips incl. style presets, lane checkboxes) → lands in `~/ProjectSniper/<slug>/`
   (source copied ≤2GB), registered in the project browser with origin tag
   (raw/segmenter/clipper) + disk-derived stage checkmarks.
2. **Auto-edit** — one click; the detached worker spawns the headless
   `claude`/`codex` brain to author `edit_plan.json` (speech cleanup → cuts →
   graphics/zooms/captions per scope+style), then runs a **bounded plan-review
   loop** — a fresh independent critic each round + the deterministic gate bundle
   (`operator_intent_contract`, `plan_lint*`, `hook_contract`, `claims_contract`,
   `reference_profile_lint`) — renders an isolated candidate, and runs Audit B +
   two visual critics before promoting. (Original single-pass timing: 578s
   raw→finished on real footage; the controller adds the review/QC rounds.)
3. **Edit** — script strike-to-cut (captions follow), drag/trim/snap blocks on the
   zoomable timeline, drag graphics to exact frame positions (safe-zone guides) and
   corner-scale 0.25–1.5×, Elements panel with live animated previews + primitives
   (text/container), Audio panel (volume, voice/voice-rnn/Demucs-separate, music
   with auto-duck), Ask-Claude bar (timestamps prefill from ruler range-select),
   speech-cleanup button, undo/redo, ⌘Z/space/arrows, Reveal final.mp4.
4. **Re-render** — ONE button, dispatched by change class. The original
   handoff measured roughly 18s graphics-only, 12s audio-only, and 3min
   cut/zoom rebuilds on its fixtures; those are historical observations, not
   current SLAs or proof that every repair stays local.

## Architecture invariants

- **Brain owns WHAT, code owns WHERE/timing.** LLMs never do timeline math.
  The plan is the determinism boundary. Current equivalence claims use the
  retained byte, FrameMD5, PCM, or codec-floor oracle named by each gate; a
  general same-plan → byte-identical-video claim is not made.
- Plan contracts: `cutTrack` = SOURCE seconds; graphics/motion = OUTPUT seconds;
  `plan_refit.py` auto-remaps on cut edits (idempotent, tested). Fingerprints:
  video/audio/legacy in `base.fingerprint.json` (JSON canonicalized — JS/py number
  drift was a real bug, fixed). Music + graphics apply at assemble (fast path);
  audioEnhance/audioGain are base-side.
- Concurrency: per-dir route guard (409) + `.assemble.lock` (pid-checked) +
  UI mutual exclusion. The check-then-write lock race is CLOSED (2026-07-11):
  acquire is serialized by a kernel flock on `<lock>.mutex` (crash-safe,
  race-tested 8-way in `test_assemble_lock`).
- Graphic identity: the editor addresses every graphic by a stable, code-stamped
  `id` (never array index) — `edit-plan.ts reconcileGraphicIds` normalizes ids
  at every disk↔memory crossing (load, reload, save-plan, ai-edit), so a
  mid-drag AI edit that inserts/removes a graphic can no longer shift the target
  under a gesture; a vanished id drops the edit loudly instead of mis-writing
  its old slot. Ids are code-owned (the ai-edit prompt is told to preserve, not
  invent them; impostors are re-minted). `plan_lint` ERRORs on duplicate ids;
  `graphics_fingerprint` strips `id` so stamping never triggers a recomposite.
- Gates (plan_lint, plan_lint_motion, plan_lint_audio, plan_lint_reframe,
  hook_contract) encode MEASURED numbers from reference studies; thresholds live in
  `producer_config.py`, never inline.

## Style system (the calibration loop)

Paste reels → yt-dlp fetch (chrome-cookie fallback) → `study/study_video.py`
fingerprint → granular frame-by-frame study (vision agents) → grammar doc with
receipts → executable pacing profile → style preset.

- **docs/studies/RESTRAINED_STYLE.md** (`pacing_restrained`, Light-short calibration): restraint pole —
  9 cuts/146s, zero zooms/music, retention = 72–87 whisper cues/min + one pinned title.
- **docs/studies/PUNCH_STYLE.md** (`pacing_punch`): tripod, breath-gap punch-cuts (NOT
  beat-timed, measured), two-layer whisper/shout text, ≤2-frame pops.
  Comprehension audit: 50/53 rules frame-verified; reproduction render brackets his
  cuts/min, matches his punch band 1.30–1.45, Audit B 22/22.
- **docs/studies/SLIDEWARE_STYLE.md** (`pacing_slideware`): lime takeover-deck slideware; 4 of her
  elements authored as our comps (`slideware-*.html`, brandable via `accent` token).
- Punch delta kit shipped: `punch-shout-lockup` comp (ChunkFive OFL + `--lemon`),
  `CAPTIONS.WHISPER` preset, pop-in/instant-out motion tokens, `exitOnCut`,
  blur-desat `takeoverBase`, per-style punch ceiling (1.45), builtin music bed
  auto-registered at ingest.
- Presets in the intent card: **Restrained light · Punch produced · Slideware involved**
  (+ 4 generics). `target.style` tells Auto-edit to read the grammar doc first.

## Historical test state (2026-07-11)

816 python tests green as of 2026-07-11 (stdlib unittest: `cd scripts/producer &&
PYTHONPATH=.:tests ../../.venv/bin/python3 selftest.py`), tsc/build clean,
tsx harnesses for all pure UI geometry. Three adversarial review rounds ran on the
editor (33 findings found → 33 fixed + independently closed).

## Historical gap list

Do not use this list as current status; see `PIPELINE.md` and the stop-gated
roadmap/audits linked there.

1. ~~`edit_plan.json` → Palmier Pro MCP translator.~~ DONE (2026-07-11) —
   `scripts/producer/palmier/` (client + pure translate + push CLI), verified
   e2e on the real C0679 plan. Remaining Palmier sub-gaps in `PIPELINE.md`:
   transitions lane (errors by design), ramp/bracket punches, a UI button.
2. ~~Stable graphic IDs (index-addressing race with mid-drag AI edits).~~ DONE
   (2026-07-11) — code-stamped ids, id-addressed editor, duplicate-id lint; see
   the "Graphic identity" invariant above.
3. ~~Reference URL-paste field in the References UI.~~ DONE (2026-07-11) —
   `study/fetch_reference.py` (yt-dlp wrapper, NDJSON, chrome-cookie retry) +
   SSE route `api/producer/references/fetch` + UI field; verified e2e.
   (NOTE: the "yt-dlp wire exists CLI-side" premise was wrong — it was a
   documented convention run by hand, not code; the wrapper is the wire now.)
4. Sustained multi-project load testing (never stress-tested beyond one operator).
5. Tracker:ON for split layout (face-tracked person cell; face_track exists).
6. WebCodecs source scrub (Mediabunny, MPL-2.0, ~2 days), timeline drag-trim of
   cut segments, per-window volume UI, Captions/B-Roll/Brand panels.
7. Parked: pip_takeover wire (#39), Lottie (#44), manual-crop+baselineLook
   coordinate transform (currently a loud lint error).

## Gotchas

- Session limits are the ceiling on heavy study waves (vision agents); workflows
  resume from cache (`resumeFromRunId`) — nothing is lost on a limit hit.
- Synthetic test footage needs temporal noise (`noise=alls=6:allf=t`) or the YDIF
  stutter gate false-positives (static frames are "duplicates" by design).
- The shallow fingerprint's music detector false-positives on compressed speech;
  trust the spectral check from granular studies.
- Comps register PAUSED GSAP timelines — previews drive them via `hf-seek`
  postMessage; they never autoplay.
