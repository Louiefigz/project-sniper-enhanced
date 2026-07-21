# CLAUDE.md — PROJECT SNIPER

Next.js 16 + Python video pipeline bundling four tools that share one shell:

- **SEGMENTER** (Part 1, `/segmenter`) — long MP4 → selected ASR → configured AI brain picks
  segments → ffmpeg **stream-copies** rough clips (single or multicam) → zip for NLE trimming.
- **CLIPPER** (Part 2, `/clipper`) — a clip → selected ASR → configured AI brain cuts filler at
  the word level → word-level editor → **FCPXML** timeline export for Final Cut Pro.
- **PRODUCER** (Part 3, `/producer`) — **the main pipeline** (see below): upload raw footage →
  intent card → brain-authored `edit_plan.json` → bounded independent plan review +
  deterministic gates → isolated render candidates + deterministic/visual QC → approved
  final. Python engine in
  `scripts/producer/` (module map: `scripts/producer/CLAUDE.md`), canonical doctrine =
  `.claude/skills/producer/SKILL.md` with Codex adapter at `.agents/skills/producer/SKILL.md`.
  Claude Code is the default editor brain; Codex is an explicit configured alternative.
- **FRAME.IO REVIEW** (auxiliary QC, `/frameio-review`) — an MP4 → ffmpeg extracts 1 frame/sec →
  perceptual-hash **dedup** → Claude **vision** flags on-screen text errors (typos/spelling/
  grammar/formatting) → in-tab player + sortable flag list, plus `results.json` + standalone
  `report.html`. It is a standalone QC pass, **not** a pipeline stage — rendered as a smaller
  secondary nav tab (set apart from the three numbered stages).

The SEGMENTER/CLIPPER/FRAME.IO flows are independent (no automated handoff). The landing page
`/` picks a pipeline tool; `(tools)/layout.tsx` adds a shared toggle nav across all of them.

## New here? Read in order

1. `docs/PIPELINE.md` — canonical doctrine (footage in → in-house render → **optional** Palmier mirror out). Wins every contradiction.
2. `docs/HANDOFF.md` — current `/producer` state + how to test.
3. `.claude/skills/producer/SKILL.md` — the editor brain's doctrine (how a plan is authored + gated).
4. `scripts/producer/CLAUDE.md` — the Python engine module map.

User-facing setup + the easiest way to run it: `README.md`. More references/docs: `docs/README.md`.

**Skills layout.** The only active Project Sniper skills are `producer`,
`clipper`, `segmenter`, `reference-editor`, and `producer-study`.
`.claude/skills/<name>/SKILL.md` is the canonical Claude Code doctrine;
`.agents/skills/<name>/SKILL.md` is the Codex adapter and must point back to the
canonical file instead of duplicating it. Commands in `.claude/commands/` make
routing explicit, but natural-language trigger descriptions remain supported.

**SNIPER ↔ HyperFrames — two different worlds.** Raw footage → edit =
**PRODUCER** (`/producer`, `scripts/producer/`, `edit_plan.json`, optional
Palmier). The upstream HyperFrames recipe documents for videos from
text/URL/PR/song/deck are archived under `vendor/hyperframes-skills/` for
provenance only. They are outside `.claude/skills` and `.agents/skills`, are not
agent-discoverable, and are not Project Sniper capabilities. This repo uses
HyperFrames only as the pinned `hyperframes@0.7.33 render` graphics subprocess
(`scripts/producer/graphics/graphics_render.py`). Do not route footage-edit jobs
into the archived recipes or advertise their workflows.

## THE PIPELINE (canonical: `docs/PIPELINE.md` — read it before touching PRODUCER)

**Footage is uploaded into PRODUCER → the operator picks intent → Sniper produces
an approved final; that exact visual/audio master may then be mirrored explicitly
to Palmier Pro for additional manual control.**
The intent card offers: **Short (9:16)** with a style
(**Caleb light · Jaden produced · Angela involved** + generics), or **Long (16:9)**
with a **checklist of items** — full workflow or just certain lanes (motion,
graphics, transitions, captions, broll, credibility + music/audio-enhance).
The brain authors `edit_plan.json` (the determinism boundary). On every plan
review round the controller must pass `operator_intent_contract`, `plan_lint*`,
`hook_contract`, `claims_contract`, and the optional reference gate, then obtain
a fresh independent critic verdict. The in-house `assemble.py`/ffmpeg chain is
the deterministic primary renderer and must not be simplified away.

Palmier Pro is an explicit, one-way visual-mirror destination
(`127.0.0.1:19789`). A managed project needs the durable quality-policy marker,
schema-v2 approval, current full authority digest, and exact master/readback
proof before sync. The visible Palmier shadow contains one byte-identical
approved-master clip; approximate/baked/known-unsupported findings describe
native editability and do not block that exact mirror. Malformed or unknown plan
state does block. Opening the mirror pauses Sniper sync — the code enforces a
compatibility lease (`palmier/sync.py` refuses to sync when ownership is
Palmier's; `palmier/ownership.py` ships `--handoff`/`--reclaim`) — but the
current UI exposes **no** take-control/reclaim ceremony, and the native-promotion
path this lease guards is **not wired yet**
(`docs/palmier/PALMIER_CANONICAL_IMPLEMENTATION_STATE.md`). Never read Palmier edits back
into `edit_plan.json`. Keep
`docs/PIPELINE.md` and `docs/palmier/PALMIER_PARITY_CONTRACT.md` aligned with this model.

**Interactive live-drive (a DIFFERENT path from the one-way mirror above).** The
repo ships a project-scoped `.mcp.json` declaring the `palmier-pro` MCP server
(`http://127.0.0.1:19789/mcp`); when Palmier Pro is open, a Claude client can drive
it **directly** (`add_clips`/`add_texts`/`set_keyframes`/`apply_color`/
`import_media` → `export_project`) — a fast, hands-on editing loop the operator
watches populate live, and the fastest way to build/adjust a timeline by hand. Give
Claude the footage as an **absolute path** (Palmier's `import_media` reads it
locally — bytes never leave the machine); pull words with `get_transcript`. Load the
`producer` skill for the editing doctrine. This is a **manual workflow, NOT an
automated pipeline stage** — do not conflate it with the gated GUI mirror, and do
not claim the app drives Palmier by agent on its own (it does not; see
`docs/palmier/PALMIER_LIVE_BUILD_SPEC.md`). Setup + Claude Desktop bridge:
`docs/palmier/PALMIER_MCP_SETUP.md`.

See @README.md for user-facing setup. This file is for things Claude can't infer by reading the code.

## Layout

- Route group `src/app/(tools)/` holds all tool pages: `segmenter/page.tsx`,
  `clipper/page.tsx` (+ `clipper/actions/validate-assembly.ts` server action),
  `producer/page.tsx`, `frameio-review/page.tsx`. URLs stay `/segmenter`, `/clipper`,
  `/producer`, `/frameio-review` (route groups don't affect the path).
- API is namespaced: `src/app/api/segmenter/*` (`segment`, `transcribe`, `export-mp4`,
  `multicam-export`, `multicam-download/[id]`, `pick-file`), `src/app/api/clipper/*`
  (`clip-preview`, `transcribe`, `native-pick`, `video`), `src/app/api/producer/*`
  (22 route dirs — the whole editor surface: `ingest`, `intent`, `auto-edit`, `render`,
  `assemble`, `save-plan`, `ai-edit`, `speech-cleanup`, `lint`, `plan`, `projects`,
  `project-status`, `references`, `transcript`, `words`, `waveform`, `filmstrip`,
  `source-frame`, `comps`, `comp-html`, `pick-file`, `reveal`), and
  `src/app/api/frameio-review/*` (`pick-file`, `review`, `video`, `frame`). Shared
  helpers live in `src/app/api/_lib/` (`spawn-python.ts`, `multicam-store.ts`).
  - `pick-file` / `native-pick` open a **macOS-only** `osascript` file dialog and return an
    absolute local path (no upload). `api/clipper/video` and `api/frameio-review/video` stream
    that local file to the browser with HTTP range support — still local, nothing is uploaded.
  - `api/frameio-review/review` is an **SSE** route that spawns `scripts/frameio/review.py
    --server` and forwards its NDJSON events as-is. `api/frameio-review/frame` serves extracted
    thumbnail JPGs, restricted to files under `<tmpdir>/frameio-*` ending in `.jpg` (no
    traversal) — not a generic local-file read primitive.
- Components: `src/components/segmenter/*`, `src/components/clipper/*`,
  `src/components/producer/*` (project browser, `intent-card`, stage strip, references +
  the whole timeline editor under `producer/editor/*`), `src/components/frameio-review/*`
  (`file-browser`, `config-step`, `review-workspace`),
  shared shadcn primitives in `src/components/ui/`, shared `src/components/shared/nav.tsx`
  (FRAME.IO REVIEW lives in that file's `UTILS` array, separate from the numbered `TOOLS`).
- Libs/prompts: SEGMENTER uses `src/lib/types.ts` + `src/prompts/segment-system.ts`. CLIPPER
  is self-contained under `src/lib/clipper/*` (incl. `editor/`) + `src/prompts/clipper/*`.
  CLIPPER's `types.ts` is kept separate (its `WordTiming` carries an extra `speaker` field).
  PRODUCER's pure TS logic is `src/lib/producer/*` (`edit-plan`, `cut-track`,
  `intent-presets`, placement/timeline geometry + `__tests__/`); its Python engine is
  `scripts/producer/` — **module map: `scripts/producer/CLAUDE.md`, read it before
  writing any producer code**.
  FRAME.IO REVIEW shapes live in `src/lib/frameio/types.ts`; its prompt + model constant live
  in the Python `scripts/frameio/claude_client.py` (the vision call is Python-side, not a TS route).
- FRAME.IO REVIEW Python lives in a package, not a flat script: `scripts/frameio/` with one
  concern per file — `extract.py` (ffmpeg → 1 JPG/sec named by timestamp), `dedup.py`
  (imagehash pHash dedup; each kept frame carries its visible time range and the
  representative is the **settled** frame of the run — modal pHash, tie-break middle-by-time,
  NOT the first frame, so a mid-fade-in frame isn't picked), `ocr_dedup.py` (alternate
  selector for `--mode ocr`: groups frames by tesseract text via rapidfuzz token_set_ratio,
  modal rep per run, fade-fragment merge, empty-OCR fallback), `claude_client.py` (anthropic
  vision, forced-JSON tool, 429/529 backoff), `review.py` (orchestrator: CLI with
  `results.json`/`report.html` AND `--server` NDJSON mode for the tab), `util.py` (stderr log).
- **Selection is `--mode` (default `visual`).** `visual` = pHash settled-frame (works on any
  footage, incl. text over moving video); `ocr` = tesseract-text grouping (clean slideware
  only — OCR is too noisy on stylized/moving footage, validated). `--select-only` prints the
  representative table and exits before any Claude call (free). `--max-reps N` caps reps sent
  (cheap test runs; default none). Before flags are emitted, `review.py` **drops no-op flags**
  (`exact_text_seen` == `suggested_fix`) and **downgrades self-identified cut-off/incomplete
  flags to low confidence** (`_clean_errors`). After judging, `review.py` runs a **verdict-dedup**:
  consecutive flags whose Claude `exact_text_seen` is fuzzy-equal (token_set_ratio ≥ 90) are
  collapsed to one finding (`merged_count`), folding fade-variants/repeats using the model's
  own transcription rather than pHash/tesseract. The tab swaps its live raw flags for this
  deduped `done.flags` set on completion.

## Build, lint, run

```bash
npm install
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # deepgram-sdk, numpy, scipy, Pillow, imagehash, anthropic, pytesseract, rapidfuzz

npm run dev      # supervised Next 16 + Turbopack, http://localhost:3000
npm run dev:local # supervised, loopback-only Codex/Sol + local-whisper defaults
npm run build
npm start         # supervised production Next
npm run start:local # supervised production Next, loopback + local providers
npm run lint     # ESLint via next config
npm test         # TS unit tests — clipper/producer/segmenter/server suites

# Python test suite (PRODUCER engine, stdlib unittest, no pytest):
cd scripts/producer && PYTHONPATH=.:tests ../../.venv/bin/python3 selftest.py
```

`ffmpeg` and `ffprobe` must be on PATH. Local mode additionally needs `codex`,
`whisper-cli`, and an existing whisper.cpp model; it never downloads one.
`tesseract` must also be on PATH **only** for FRAME.IO REVIEW's `--mode ocr`
(the default `visual` mode doesn't need it). The Next API routes auto-detect
`.venv/bin/python3` via `src/app/api/_lib/spawn-python.ts` and fall back to system `python3`.

### Next supervision and Auto-edit durability

- `npm run dev`, `dev:local`, `start`, and `start:local` all go through
  `scripts/infra/next_supervisor.mjs`. It sets `NODE_OPTIONS=--max-old-space-size=3072`
  unless a heap flag already exists; `SNIPER_NEXT_HEAP_MB` from Next's normal
  `.env*` load selects the injected limit. On macOS/POSIX it starts Next in a
  separate process group, forwards `SIGINT`/`SIGTERM`/`SIGHUP` to the full tree, removes residual
  descendants before restarting, and uses a per-repo/port PID lock to reject a
  duplicate supervisor. The circuit opens after three fast exits in 30 seconds
  or five unexpected exits in 10 minutes. Next arguments forward normally after
  npm's `--`; local mode rejects hostname overrides. Do not replace these npm
  scripts with raw `next dev/start` in normal local operation.
- Auto Edit is intentionally not a child lifecycle of Next. The route validates
  and leases the job, then starts `auto-edit/worker.ts` with repo-local Node/tsx
  in a detached process group. Its PID and monotonic checkpoints are atomically
  stored in `<producer>/.sniper-auto-edit-job.json`; stdout/stderr go to the
  bounded `0600` `<producer>/.sniper-auto-edit.log`. A browser disconnect or
  Next restart leaves that worker running.
- Checkpoint reuse must remain hash-bound. `plan_reviewed` may be reused only
  when the reviewed plan, manifest, and optional reference profile still match.
  `rendered` refers to an isolated candidate whose plan/manifest hashes and
  assembled-authority proof still match—not an arbitrary `final.mp4`. A final
  is reusable only when its `.sniper-qc-approved.json` matches the current plan,
  manifest, final bytes, and completed job. Changed authority invalidates every
  downstream checkpoint. Stale worker tokens are fenced. A dead owner becomes
  `interrupted`, and the GUI's **Resume Edit** sends `resume:true` to continue
  from the last safe checkpoint.
- Recent Projects does not create one timer per card. Visible dirs share the
  serial/deduplicated queue in `use-project-status.ts`; only `run.status ===
  "running"` uses the 2.5s loop, idle status is 60s, and hidden tabs abort/pause.
  Palmier probe/preflight follows the same non-overlap, abort, and cleanup rule.
- **Historical restart evidence (2026-07-12, before the bounded review/QC
  controller):** the then-current detached path passed its automated checks and
  a live C0679 restart exercise. Next was terminated during ffmpeg rendering,
  restarted ready in 813 ms, the same detached worker continued emitting
  checkpoints, and the browser reconnected. This proves worker independence;
  it is not live-render evidence for the newer planning/QC loops. Keep
  `docs/PIPELINE.md` synchronized with future changes and record new live
  evidence only after it is actually run.

## Environment (`.env.local`)

- `SNIPER_EXECUTION_MODE=local` — loopback-safe GUI defaults: Codex brain + local whisper.cpp. `npm run dev:local` sets it.
- `SNIPER_BRAIN_PROVIDER=legacy|codex`; Codex defaults to `gpt-5.6-sol` + `xhigh` and is configurable with `SNIPER_CODEX_MODEL` / `SNIPER_CODEX_REASONING`. (`ultra` was rejected at request time by the provider-resolved build on 2026-07-18 — see `docs/audits/LOCAL_CODEX_AUDIT.md`.)
- `SNIPER_TRANSCRIBE_PROVIDER=deepgram|local-whisper`; mode defaults are live→Deepgram, local→Whisper. Explicit override wins.
- `ANTHROPIC_API_KEY` — required only for live SEGMENTER/CLIPPER and FRAME.IO REVIEW.
- `DEEPGRAM_API_KEY` — required only when Deepgram transcription is selected.
- `ANTHROPIC_MODEL` — optional live SEGMENTER override; default `claude-sonnet-4-6`. CLIPPER's live/legacy branch remains pinned to `claude-sonnet-4-6`; local mode uses the Codex settings above.
- `NEXT_PUBLIC_SNIPER_DEBUG` / `SNIPER_DEBUG` — debug tracing, **ON by default**. `NEXT_PUBLIC_SNIPER_DEBUG=0` silences the TS `dlog`/`derror` (client + server, `src/lib/debug.ts`); `SNIPER_DEBUG=0` silences the Python workers' `[SNIPER:*]` stderr. CLIPPER and FRAME.IO REVIEW forward client `dlog`s to their `debug-log` route so the whole flow (browser + server + python) shows in the `npm run dev` terminal. FRAME.IO REVIEW additionally surfaces the same trace **in the tab** — `api/frameio-review/review` forwards each python stderr line over SSE as a `log` event, rendered in the review view's collapsible **Diagnostics** panel (with copy-to-clipboard).
- `CLIPPER_DUMP_FIXTURE=1` — optional dev flag; dumps `clip-preview`'s LLM tool-call JSON to a fixture for prompt iteration.
- `MULTICAM_DEBUG=1` — optional dev flag; `scripts/segmenter/multicam_pipeline.py` writes verbose per-step tracing (every ffmpeg/ffprobe command + timing, keyframe/smartcut decisions, per-clip method + fallback reasons, seam-validation results, per-segment padding) to **stderr**. The multicam-export route mirrors stderr live to the `npm run dev` console. Run `MULTICAM_DEBUG=1 npm run dev` (or add it to `.env.local`) to capture a full render log.

## Invariants — DO NOT "fix" these

- **Provider/model pins.** The live/legacy `claude-sonnet-4-6` defaults remain intentional and must not be removed or silently changed. Local mode intentionally selects the Codex subscription bridge with `gpt-5.6-sol` + `xhigh`; do not silently downgrade it. (`xhigh` replaced `ultra` deliberately: on 2026-07-18 the provider-resolved `gpt-5.6-sol-1p-codexswic-ev3` build rejected `ultra` with HTTP 400, allowing only `none|low|medium|high|xhigh` — evidence in `docs/audits/LOCAL_CODEX_AUDIT.md` and `docs/producer/HEADLESS_EMPIRICAL_GATE_LEDGER.md`; regression check in `src/lib/producer/__tests__/producer-ai-provider.test.ts`.) FRAME.IO REVIEW remains Anthropic vision and is outside the three-tool migration.
- **SEGMENTER export is stream-copy, not re-encode** (`scripts/segmenter/export_mp4.py`). `-ss` BEFORE `-i` is input-side fast seek; clips snap to the nearest keyframe at-or-before the padded start, so adjacent clips may overlap. This is intentional — output is rough footage for NLE trimming. YOU MUST NOT switch to re-encode, move `-ss` after `-i`, or "tighten" boundaries to make cuts exact. (Scope: ONLY `scripts/segmenter/export_mp4.py`.) **CLIPPER's FCPXML path is frame-accurate by design** — don't "optimize" it to stream-copy.
- **Multicam cuts are frame-accurate standalone clips, default cut method `smartcut`** (`scripts/segmenter/multicam_pipeline.py`). Each source is cut to the same padded window (`PAD_SECONDS = 5.0`) translated by its xcorr offset, so angles line up on their own with no NLE alignment. The **video** sources (A/B/C) define the common pre/post-roll (each must cover the segment core, else it's dropped — video can't be fabricated); **audio** sources (lavs) adapt to that window — a small shortfall (≤ `AUDIO_SILENCE_PAD_MAX`, 0.5s) is filled with silence on the short end via `cut_audio_segment_window` (real samples keep their timeline position; status `audio_padded`) and only a larger gap drops the track (status `source_dropped`). **Per-segment audio drift correction is ON by default** (`--audio-drift-correction` / `--no-audio-drift-correction`): a single global xcorr offset is exact only where it was measured, so a separate recorder whose clock runs slightly fast/slow slides out of sync across a long take. Before cutting each lav for a segment, `refine_audio_offset` re-measures that lav's offset *locally* around the segment (seeded by the global offset, searching ±`--audio-drift-window`, default 2.0s, with a `--audio-drift-probe` default 15s window) and cuts with the refined offset (status `audio_drift_corrected`). It only trusts a refined offset when the normalized-correlation peak clears `AUDIO_DRIFT_MIN_CONFIDENCE` (0.10) and isn't at a search-window edge — otherwise it keeps the global offset (silence / non-matching audio / out-of-window drift never push a good track out of sync). This is what keeps lavs inside the strict `--tolerance-frames` (1.5) sync check; DO NOT replace it with a looser tolerance or a single global offset. `smartcut` re-encodes only the partial GOPs at each boundary (libx264 **CRF 18**) and stream-copies the whole GOPs between (H.264 sources only; TS-protocol concat; copy tail isn't frame-exact, so `smartcut_video` measures the copy's real length and re-encodes the remainder so head/copy/tail are contiguous). `validate_seam` checks the whole-clip frame count (packet count, no decode) and decodes only a ±`SEAM_PROBE_PAD` window around each splice junction (`smartcut_video` returns the seam positions; the copied middle is lossless so only junctions can glitch) — on any **decoder** error (the benign `non monotonically increasing dts to muxer` warning is ignored) or frame-count mismatch it auto-falls-back to `full_reencode_segment` (the legacy full libx264 CRF 18 path, also forced by `--cut-method reencode`). DO NOT make the smartcut middle stream-copy the boundary frames, "tighten" the measure-and-fill, switch off the H.264 gate, or remove the full-reencode fallback. Frame accuracy + clean seams are the point — don't trade them for speed (no VideoToolbox/`-c copy` of whole segments). Segments are cut concurrently (`--workers`, default `min(4, cpu)`); `log_status` is lock-serialized because each line is one SSE JSON object.
- **Two transcribe workers.** `scripts/transcribe.py` (SEGMENTER) and `scripts/clipper/clipper_transcribe.py` (CLIPPER) are distinct; CLIPPER's adds stereo-channel isolation + diarization. Don't merge them.
- **Temp files are owned by their producer.** CLIPPER's audio temps — `/tmp/clipper-audio-*.mp3` (mono extract), `/tmp/clipper-chunks-*/` (10-min chunks), `/tmp/clipper-ch{1,2}-*.mp3` (isolated stereo channels) — are all cleaned by `clipper_transcribe.py`'s `finally` blocks. SEGMENTER's multicam export zip is held in `multicam-store.ts` (1-hour TTL) and deleted by `multicam-download/[id]` after it's sent. CLIPPER export writes **no** server temp — the FCPXML and example `.txt` are built and downloaded client-side. FRAME.IO REVIEW's extracted frames live in `<tmpdir>/frameio-<sha1(input+mtime+fps)>/` — a **deterministic cache** so a "proceed anyway" re-run reuses them instead of re-extracting; they're intentionally NOT deleted at end-of-run (the in-tab thumbnails + `report.html` read them), and `review.py` sweeps any `frameio-*` dir older than 1h at the start of each run. Do not add manual cleanup elsewhere or move it. (`results.json` + standalone `report.html` are written next to the input video, or to `--out-dir`.)
- **No full-video egress.** Local Whisper keeps ASR audio on-device; explicit Deepgram sends audio to Deepgram. Transcript/plan context goes to the selected remote brain (Codex subscription or Anthropic/Claude). Never route raw video to a third party or cloud store. **FRAME.IO REVIEW is the deliberate exception for selected still JPEGs** sent to Anthropic vision; the full MP4 remains local.
- **No general on-disk UI cache between steps.** Transcript, segments, and ordinary edit state live in React state. The narrow PRODUCER reliability files (`.sniper-auto-edit-job.json`, `.sniper-auto-edit.log`, and `.sniper-run-state.json`) are intentional control-plane exceptions; do not delete, repurpose, or broaden them into a general cache/DB without an explicit request.
- **Python launcher reuse.** API routes that shell to Python MUST import `spawnPython` / `pythonInterpreter` / `SCRIPTS_DIR` from `src/app/api/_lib/spawn-python.ts`. Do not hardcode interpreter paths.

## Code style

- TypeScript strict. SEGMENTER shapes (`TranscriptEntry`, `SegmentGroup`, `WordTiming`) live in `src/lib/types.ts`; CLIPPER shapes (`LineDecision`, `EditableWord`, `Source`, `SpeakerMap`, `AppStep`, …) live in `src/lib/clipper/types.ts`. Update the relevant one first when changing a transcript/segment shape.
- SEGMENTER segmentation prompt: `src/prompts/segment-system.ts` (route user-message structure in `api/segmenter/segment/route.ts`). CLIPPER edit prompt: `src/prompts/clipper/default-edit.ts`.
- UI: Tailwind v4 + shadcn/ui primitives in `src/components/ui/` (`badge`, `button`, `card`, `dialog`, `input`, `progress`, `scroll-area`, `separator`, `tabs`, `textarea`). Add others via `npx shadcn add <name>` rather than hand-writing. `lucide-react` is available for icons.

## Verification

Two test suites, both must stay green:

- **Python (PRODUCER engine)**: `cd scripts/producer && PYTHONPATH=.:tests
  ../../.venv/bin/python3 selftest.py` — stdlib unittest (no pytest).
  Single file: `PYTHONPATH=.:tests ../../.venv/bin/python3 tests/test_<name>.py`.
- **TypeScript**: `npm test` — Clipper media contracts, Producer logic/provider
  branching, Segmenter flow validation, and localhost request policy.

After non-trivial changes, also run `npm run dev` and walk the relevant flow against a short MP4: SEGMENTER (Transcribe → Edit Segments → Export zip), CLIPPER (Transcribe → Clip → Edit → Export FCPXML), FRAME.IO REVIEW (Choose MP4 → Configure → Run → review flags), and/or PRODUCER (producer tab → pick footage → intent card → initial plan → bounded plan review/gates → isolated candidate → Audit B + two visual critics → approved `final.mp4`; then explicit exact-master Palmier mirror, Open & take control, and reclaim states when that integration changed). `npm run build` + `npm run lint` must pass clean (the build is the surest check that import/fetch paths across the namespaces still resolve). If a change can't be verified that way (e.g. server-only refactor), say so explicitly instead of claiming success.

FRAME.IO REVIEW's Python is independently runnable without the UI (modular per its spec): `.venv/bin/python3 -m scripts.frameio.review --input clip.mp4` extracts → selects representatives → prints the API-call estimate + rough cost (asks before >200) → analyzes → verdict-dedups → writes `results.json` + `report.html`. Use `--max-reps N` (cap reps sent) and/or `--max-frames`/`--fps` for a cheap test pass, `--select-only` to print the representative table for free (no Claude call), and `--mode ocr --fuzz N` for the tesseract selector. The `--server` flag switches it to the NDJSON event stream the tab consumes.
