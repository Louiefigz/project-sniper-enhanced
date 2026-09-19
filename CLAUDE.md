# CLAUDE.md — Project Sniper

The working instructions and the product contract are in `AGENTS.md`, imported here so
Claude Code and Codex follow the same text:

@AGENTS.md

Claude Code specifics: the canonical skills are `.claude/skills/<name>/SKILL.md`
(`producer`, `segmenter`, `clipper`, `reference-editor`, `producer-study`,
`sniper-context`); `.agents/skills/<name>/SKILL.md` are the Codex adapters and point back
to them. `.claude/commands/` make routing explicit (`/produce`, `/produce-studio`, `/clip`,
`/segment`, `/reference-edit`, `/producer-study`, `/sniper-context`, `/setup`);
natural-language requests work too.

## Engineering reference

For changes to the application itself. This section records what the code cannot tell
you; read the code for the rest.

### The tools

Buyers use Sniper only through their own Codex or Claude Code opened on this folder: the
skills are the product, `./sniper` runs the engine with Sniper's own tools, and the agent is
the brain. The Next.js app under `src/` (pages and API routes) is the retired web UI; its
libraries are still imported by Sniper's TypeScript commands (`scripts/infra/*.ts`, the
native export), so it ships and must keep type-checking, but no buyer route serves it.
Three tools:

- **Producer** (the main tool): footage → stored intent → agent-authored
  `edit_plan.json` → deterministic gates and independent plan review (fresh subagents) →
  delivery approval (`scripts/infra/mint-delivery-approval.ts`) → render → deterministic and
  visual QC → final. Engine: `scripts/producer/` (module map: `scripts/producer/CLAUDE.md`).
- **Segmenter**: long recording → local Whisper → the agent picks segments → ffmpeg
  **stream-copies** rough clips from one recording (multicam cuts are frame-accurate and
  re-encode at the joins) → zip.
- **Clipper**: one clip → local Whisper → the agent marks filler at the utterance level →
  **FCPXML** for Final Cut Pro.
- Text Review (`scripts/frameio/`, the retired `/frameio-review` page) is not in this release.

### Layout

- `sniper` (repository root): the command the agent runs every engine command through. In a
  package it loads `install/lib/common.sh` settings and the maintenance lock; in a developer
  checkout (no `install/`) it just runs the command here.
- `scripts/infra/project-intent.ts` writes a project's stored intent (the retired app's
  `POST /api/producer/intent`); `scripts/infra/mint-delivery-approval.ts` mints the delivery
  approval from the deterministic gates.
- Retired web UI (kept compiling; not a buyer route): pages
  `src/app/(tools)/{segmenter,clipper,producer,frameio-review}/page.tsx`; API
  `src/app/api/{segmenter,clipper,producer,frameio-review}/*`; shared helpers in
  `src/app/api/_lib/`. Every provider call goes through `_lib/ai-provider.ts` (provider,
  model, filtered environment), `_lib/subscription-invocation.ts` (admission) and
  `_lib/codex-cli.ts` or a Claude process module; Segmenter and Clipper use
  `_lib/subscription-brain.ts` (`runBrainJson`) with `_lib/claude-cli.ts` and the shared
  JSON schemas in `schemas/codex/`. Tool-less provider calls run under
  `_lib/provider-media-jail.ts`.
- `pick-file`/`native-pick` open a macOS file dialog and return a local path; the
  `video` routes stream that local file to the browser. Nothing is uploaded.
- Prompts: Segmenter `src/prompts/segment-system.ts`; Clipper `src/prompts/clipper/*`.
  Shapes: Segmenter `src/lib/types.ts`, Clipper `src/lib/clipper/types.ts` (its
  `WordTiming` has `speaker`), Producer `src/lib/producer/*`, Text Review
  `src/lib/frameio/types.ts`.
- Text Review's Python is `scripts/frameio/` (`extract`, `dedup`, `ocr_dedup`,
  `claude_client`, `review`); the paid-feature gate is `src/app/api/_lib/paid-features.ts`.

### External tools

`ffmpeg`/`ffprobe`, `whisper-cli` with an existing model (never downloaded by a job),
`tesseract` (reference study reads on-screen text and refuses to start without it; also
Text Review's `--mode ocr`) and `yt-dlp` (adding a reference from a link,
`study/fetch_reference.py`). In the packaged app these, Node, Python and git are Sniper's own:
the installer puts them in `~/.project-sniper/runtimes/<lock id>/` from
`install/deps/osx-arm64.lock` (ffmpeg is Sniper's build with zscale and rubberband), and the
`./sniper` puts them first on PATH. Never install or point Sniper at a
Homebrew or system copy instead. API routes that start Python import `spawnPython` /
`pythonInterpreter` / `SCRIPTS_DIR` from `src/app/api/_lib/spawn-python.ts`.

### Invariants — do not "fix" these

- **Subscription only.** The buyer's own Codex or Claude Code is the brain; nothing Sniper
  runs calls a provider, and no SDK client or API key route may be added for editing. (The
  retired app's provider modules — `ai-provider.ts`, `subscription-policy.ts` — stay because
  shipped commands import them; they are not a buyer route.)
- **Segmenter export is stream-copy** (`scripts/segmenter/export_mp4.py`): `-ss` before
  `-i`, cuts snap to the keyframe at or before the padded start, adjacent clips may
  overlap. Do not re-encode or tighten. Clipper's FCPXML path is frame-accurate by design.
- **Multicam cuts are frame-accurate** (`scripts/segmenter/multicam_pipeline.py`,
  default `smartcut`): shared padded window per source via xcorr offsets, per-segment lav
  drift correction, seam validation with full re-encode fallback. Keep the tolerances.
- **Two transcribe workers**: `scripts/transcribe.py` (Segmenter, Producer ingest) and
  `scripts/clipper/clipper_transcribe.py` (stereo isolation, diarization). Do not merge.
- **Temp files belong to their producer** (Clipper audio temps, the multicam zip store,
  Text Review's `<tmpdir>/frameio-*` cache swept after an hour).
- **No general UI cache.** Only the Producer control files (`.sniper-auto-edit-job.json`,
  `.sniper-auto-edit.log`, `.sniper-run-state.json`) persist between steps.
- **Auto Edit** (the retired app's detached worker, `auto-edit/worker.ts`) resumed only from
  hash-current checkpoints; it is not a buyer route and its `.sniper-qc-approved.json` is not
  produced on the agent route.

### Verification

`npm run type-check`, `npm run lint`, `npm test`, `npm run build`, and the Python suite, each
through `./sniper` as AGENTS.md § Checks shows (in a developer checkout `./sniper` runs them
with your own tools). If a change cannot be verified this way, say so instead of claiming success.
