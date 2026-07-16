# 🎯 PROJECT SNIPER ENHANCED

> A local-first AI video editing system for Claude Code desktop, rendered files,
> Final Cut Pro, and editable Palmier Pro timelines.

Project Sniper Enhanced is more than the four-tab web app. The repository ships
with **26 conversational editing/creation skills**, **3 slash commands**, **4 GUI
workspaces**, **46 registered motion compositions**, **36 caption identities**, a
deterministic render pipeline, and an incremental Palmier revision system.

Use it in whichever surface fits the job:

| Surface | Best for | What it produces |
|---|---|---|
| **Claude Code desktop** | Talking to the editor in plain language; reference matching; building directly in Palmier | A governed edit plan, rendered deliverables, or an editable Palmier timeline |
| **Web GUI** | Visual ingest, segmentation, word editing, timeline adjustment, Auto Edit, and text QC | MP4 clips, FCPXML, Producer projects, review reports |
| **Palmier Pro** | Native timeline control and quick changes after an editable build | Stable-ID clips, text, graphic overlays, revisions, and exports |
| **Headless CLIs** | Automation, debugging, CI, and deterministic stage-by-stage execution | The same manifests, plans, renders, audits, and revision receipts |

## Choose the destination first

The requested destination determines the workflow; these are intentionally
different products:

1. **Editable Palmier build** — when the operator asks to build or continue in
   Palmier, Claude Code drives Palmier directly inside a candidate-scoped,
   resumable authority. The cut lands first, visual treatment follows, and
   cards/text remain addressable by stable IDs.
2. **Rendered file** — when the operator asks for an MP4, Sniper's deterministic
   renderer produces and audits `final.mp4`.
3. **Approved flat mirror** — when the operator explicitly wants the approved
   Sniper master mirrored into Palmier, the exact file is placed as one verified
   clip. It is visually exact but its baked layers are not individually editable.

For long-form work, the recommended model is **Editable Build while iterating +
one QC Master when publishing**. Small card/text changes touch only the bound
element; a full master is rendered and audited once the batch is ready to ship.

## Product at a glance

- **🎬 SEGMENTER** — transcribe one long recording, identify topic/guest
  boundaries, adjust them, and export separate single- or multicam MP4 clips.
- **✂️ CLIPPER** — remove filler, false starts, repetition, and dead air at
  word level; export a clean MP4 and/or Final Cut Pro FCPXML.
- **🎛️ PRODUCER** — the primary editing system for shorts and long-form:
  retakes, pauses, reframing, captions, graphics, motion, transitions, b-roll,
  audio, plan review, deterministic gates, rendered QC, feedback revisions, and
  editable Palmier delivery.
- **🔍 FRAME.IO REVIEW** — inspect an MP4 for visible typos, spelling,
  grammar, and broken text formatting using representative-frame selection.
- **🎨 HYPERFRAMES WORKFLOWS** — create motion graphics, explainers, launch
  videos, website videos, PR explainers, music-driven videos, slideshows, and
  custom HTML-rendered compositions.
- **🧪 REFERENCE EDITOR** — study a finished reference or raw+edited pair
  frame by frame, prove reusable templates, compile a style pack, and apply its
  mechanics without copying the source creator's identity or assets.

## Fastest start (Claude Code desktop)

**New here and not sure what to install? Open this folder in Claude Code desktop and type
[`/setup`](./.claude/commands/setup.md).** It checks your machine, tells you exactly what is
missing, and installs only the gaps — asking first before anything big (Homebrew packages, the
~465 MB local speech model). Nothing installs without your yes; if everything is already present
it just reports all-green. When it finishes, you don't start a server — you just ask for an edit:
*"cut a Jaden-produced short from this footage."*

Everything below is the same setup done by hand, for anyone who prefers to run it themselves.

## Start here (the easy path)

**You do not need to run a live dev server.** The simplest way to use PROJECT SNIPER
is inside **Claude Code desktop**:

1. **Set up once** — type [`/setup`](./.claude/commands/setup.md) and let it install the gaps,
   or do it by hand from [Requirements](#requirements) + [Setup](#setup): the Python `.venv`,
   `ffmpeg`, the `claude` CLI (the default brain — you already have it in Claude Code desktop),
   and `whisper-cli` + a local model.
2. **If Palmier is your destination, download and open Palmier Pro.** While it is
   running it serves the local MCP that the editable-build workflow talks to at
   `http://127.0.0.1:19789/mcp`. Rendered-file, Segmenter, Clipper, and review
   jobs do not require Palmier. Setup + Claude Desktop bridge:
   [`docs/palmier/PALMIER_MCP_SETUP.md`](./docs/palmier/PALMIER_MCP_SETUP.md).
3. **Open this project folder in Claude Code desktop** and just ask — e.g.
   *"cut a Jaden-produced short from this footage"* or *"clean-cut this long recording."*
   Claude loads the **`producer`** skill and chooses the requested destination:
   governed editable Palmier build, deterministic rendered file, or approved
   one-clip mirror.

**Where your files go:** everything lands under **`~/ProjectSniper/<slug>/`**.
Rendered outputs and working files are in the project's `producer/` folder;
reference studies live under `~/ProjectSniper/_references/`. Editable Palmier
jobs also keep authority, operation, element-ledger, QC, and resume receipts there.

**More references & docs:** [`docs/README.md`](./docs/README.md).

> The web GUI (the `/producer` editor, below) is an **optional** visual surface for the
> same pipeline — it is not required for the default flow, and you should not need to
> start a dev server just to make an edit.

## Claude Code slash commands

| Command | Function |
|---|---|
| [`/setup`](./.claude/commands/setup.md) | Audits the machine, reports missing dependencies, and asks before installing system tools or the local Whisper model. |
| [`/reference-edit`](./.claude/commands/reference-edit.md) | Runs the meticulous reference-study → template proof → style-pack → apply workflow. |
| [`/produce-palmier`](./.claude/commands/produce-palmier.md) | Runs the staged Claude Code desktop → editable Palmier workflow with durable authority, exact operations, QC, and approvals. |

The commands are conveniences, not the only interface. Plain-language requests
such as *"make a 30-second product launch video,"* *"add cinematic captions,"*
or *"change the text in the card at 6:42"* route to the matching skill.

## Complete agent skill catalog (26)

These are the skills shipped in [`.claude/skills/`](./.claude/skills/). A skill
is an operational contract for Claude Code—not necessarily a separate GUI tab.
Provider-backed features still require their provider credentials; the
deterministic/local fallbacks are documented inside each skill.

### Editing, analysis, and existing-footage workflows

| Skill | Use it for | Main capability |
|---|---|---|
| [`producer`](./.claude/skills/producer/SKILL.md) | Fully editing raw footage into shorts or long-form | Gated plans, cuts, pacing, reframe, captions, graphics, motion, b-roll, audio, QC, feedback, file render, and editable Palmier delivery |
| [`reference-editor`](./.claude/skills/reference-editor/SKILL.md) | Meticulously emulating the mechanics of a reference | Source-cadence frame study, two independent reviews, adjudication, template proof, release-ready style pack, and governed application |
| [`producer-study`](./.claude/skills/producer-study/SKILL.md) | Learning new reusable edit doctrine from examples | Deterministic fingerprints, graphic extraction, rule writing, template building, and verification |
| [`talking-head-recut`](./.claude/skills/talking-head-recut/SKILL.md) | Packaging a playing talking-head/interview/podcast | Timed title, lower-third, data, quote, side-panel, and PIP graphic overlays |
| [`clipper`](./.claude/skills/clipper/SKILL.md) | Polishing one clip | Word-level transcript decisions, clean-cut MP4, −14 LUFS master, and FCPXML |
| [`segmenter`](./.claude/skills/segmenter/SKILL.md) | Splitting one long recording into many clips | Transcript-led topic boundaries and fast single/multicam clip export |
| [`embedded-captions`](./.claude/skills/embedded-captions/SKILL.md) | Adding designed captions to a single-subject clip | 36 identities across rail, embedded/occluded, and full themed caption treatments |

### New-video and composition workflows

| Skill | Use it for | Main capability |
|---|---|---|
| [`hyperframes`](./.claude/skills/hyperframes/SKILL.md) | Any video, animation, or motion-graphic request | Entry router that selects the right specialized HyperFrames workflow |
| [`general-video`](./.claude/skills/general-video/SKILL.md) | Freeform, long, multi-scene, montage, brand, or sizzle work | Input/length-agnostic custom HTML video composition |
| [`faceless-explainer`](./.claude/skills/faceless-explainer/SKILL.md) | Turning text, notes, a topic, or an article into a video | Invented typography, diagrams, data-viz, narration, and shot-sequence storytelling |
| [`product-launch-video`](./.claude/skills/product-launch-video/SKILL.md) | Product, app, feature, SaaS, or company launches | Brand capture, marketing narrative, shot planning, and promo render |
| [`website-to-video`](./.claude/skills/website-to-video/SKILL.md) | Turning a general URL into a tour/showcase/social clip | Browser capture, screenshots, brand assets, and an authored site story |
| [`pr-to-video`](./.claude/skills/pr-to-video/SKILL.md) | Explaining a GitHub pull request | Diff/commit/file analysis rendered as a code-change explainer |
| [`music-to-video`](./.claude/skills/music-to-video/SKILL.md) | Making a beat-synced lyric/slideshow/promo video | One-pass music analysis, beat grid, per-frame plan, and optional supplied media |
| [`motion-graphics`](./.claude/skills/motion-graphics/SKILL.md) | Short design-led animation, usually under 30 seconds | Kinetic type, stat hits, charts, logo stings, callouts, lower-thirds, overlays, and transparent output |
| [`slideshow`](./.claude/skills/slideshow/SKILL.md) | Presentations and interactive decks | Slides, fragment reveals, branches, hotspots, and page-to-deck authoring |
| [`remotion-to-hyperframes`](./.claude/skills/remotion-to-hyperframes/SKILL.md) | Explicitly porting existing Remotion source | One-way Remotion/React → seek-safe HyperFrames conversion with unsupported-pattern guards |

### HyperFrames platform and media domain skills

| Skill | Use it for | Main capability |
|---|---|---|
| [`hyperframes-core`](./.claude/skills/hyperframes-core/SKILL.md) | Building a valid renderable composition | DOM timing contract, tracks, clips, sub-compositions, variables, media ownership, and determinism |
| [`hyperframes-creative`](./.claude/skills/hyperframes-creative/SKILL.md) | Art direction | Palettes, typography, narration, beat planning, brand/style, and composition direction |
| [`hyperframes-animation`](./.claude/skills/hyperframes-animation/SKILL.md) | Motion strategy and runtime selection | Atomic rules, blueprints, transitions, techniques, and seven runtime adapters |
| [`hyperframes-keyframes`](./.claude/skills/hyperframes-keyframes/SKILL.md) | Detailed seek-safe animation | 2D/3D keyframes, paths, masks, SVG morph/draw, FLIP, trails, cursors, and diagnostics |
| [`hyperframes-media`](./.claude/skills/hyperframes-media/SKILL.md) | Audio, transcription, and media generation | Multi-provider TTS, BGM/SFX, Whisper, captions, lyrics/karaoke, and background removal |
| [`hyperframes-cli`](./.claude/skills/hyperframes-cli/SKILL.md) | Developing, inspecting, validating, rendering, or publishing | Complete CLI loop, browser/capture tools, diagnostics, and optional Lambda rendering |
| [`hyperframes-registry`](./.claude/skills/hyperframes-registry/SKILL.md) | Reusable component wiring | Upstream blocks/components; in this repo, documents the local 46-composition catalog contract |
| [`media-use`](./.claude/skills/media-use/SKILL.md) | Resolving BGM, SFX, images, and icons | Cache/catalog lookup, local freeze, content ledger, and stable asset paths |
| [`figma`](./.claude/skills/figma/SKILL.md) | Bringing Figma work into video | Static assets, tokens, components, storyboards, Figma Motion, and shaders |

### Animation runtimes

HyperFrames compositions can use **GSAP** (default), **Lottie**, **Three.js**,
**Anime.js**, **CSS keyframes**, the **Web Animations API**, or **TypeGPU**.
Every runtime must remain paused, seek-safe, and deterministic under the shared
HyperFrames timeline.

## Graphics and caption library

The Producer registry currently contains **46 source-authored HTML motion
compositions** in [`templates/motion/compositions/`](./templates/motion/compositions/).
The catalog includes hook cards, statements, stats, receipts, pipelines,
scoreboards, rails, gauges, lists, maps, quotes, takeovers, PIP-hole layouts,
icons, lower-thirds, section markers, transitions, and 16:9 variants.

The system is expected to choose a form from the beat's **information shape**
(comparison → bars/scoreboard, process → pipeline/rail, evidence →
receipt/ledger, thesis → statement), check geometry against the face/screen,
and avoid repeating the same anatomy consecutively. Operators can also name a
specific composition directly.

<details>
<summary>All 46 registered motion compositions</summary>

```text
agenda-slide                 angela-caption-dual-mode
angela-receipt-cell          angela-staircase-lockup
angela-takeover-deck         avatar-bio-card
blur-tease                   canvas-pip-list
chip-row                     color-wash
container-shape              container-shape-wide
fragment-payoff              glass-lower-third
glass-rail                   glass-takeover-bg
glitch-hit                   icon-badge
icon-badge-wide              jaden-shout-lockup
kinetic-quote                kinetic-quote-wide
list-build                   logo-card
nateherk-bullet-bars         nateherk-ledger-dark
nateherk-pipeline            nateherk-rail
nateherk-scoreboard          nateherk-takeover
schedule-stack               section-marker
section-takeover             stat-card
statement-card               stinger-wipe
stroke-draw-badge            text-element
text-element-wide            underline-circle
versus-split                 whiteboard-connector
whiteboard-list              whiteboard-map
widget-gauge                 widget-pills
```

</details>

Designed captions have **36 identities** in the
[`embedded-captions` catalog](./.claude/skills/embedded-captions/CATALOG.md).
`anchor` is the restrained verbatim default; embedded typography is meant to be
a scarce climax rather than a behind-the-subject effect on every word.

<details>
<summary>All 36 caption identities</summary>

`cream`, `ink`, `editorial`, `keynote`, `documentary`, `loud`, `neon`,
`glitch`, `chrome`, `velocity`, `anchor`, `ordnance`, `terminal`, `neonsign`,
`stardust`, `stomp`, `scoreboard`, `transit`, `vhs`, `arcade`, `dossier`,
`laser`, `thunder`, `hologram`, `biolume`, `aurora`, `spectrum`, `papercut`,
`popup`, `chalkboard`, `graffiti`, `brush`, `inkwater`, `ransom`, `lastpage`,
`nightcity`.

</details>

## Producer functionality

### Inputs, outputs, and treatment

- **Inputs:** one or more raw files, a project folder, a finished long-form to
  mine for shorts, optional b-roll/music, or Segmenter/Clipper output.
- **Outputs:** 9:16 short(s), 16:9 long-form, rough clips, deterministic MP4,
  FCPXML/SRT/chapters where applicable, or an editable Palmier timeline.
- **Scopes:** `trim` → `light` → `produced` → `full`, with independent
  lane overrides for motion, graphics, transitions, captions, b-roll,
  credibility, music, and dialogue cleanup.

### Editorial and visual system

- Word-timed transcription, source manifests, multi-source reasoning, and
  transcript-to-output time mapping.
- Retake detection, abandoned-thought review, false-start/filler removal,
  pause tightening, protected emphasis pauses, and CTA preservation.
- Short-form 9:16 face-aware reframe; long-form breathing room and sparse
  semantic zooms plus subtle aliveness motion.
- Hook cards, graphics proposals, visual-state/face exclusion, full-screen
  cutaways, PIP-hole takeovers, b-roll placement, kinetic captions, section
  changes, and non-stock seam transitions.
- Grounded claims checks, numeric transcript checks, reference-mechanics gates,
  graphic-form variety checks, and stored operator-intent enforcement.
- Dialogue mastering to approximately −14 LUFS, optional music bed/ducking,
  captions, SRT, chapters, cover frames, and with/without-music variants where
  that workflow is configured.

### Review, safety, and reliability

- `edit_plan.json` is the deterministic boundary: the same plan and inputs
  reproduce the same edit.
- Trim/light plans require at least one independent clean review; produced/full
  plans require two clean reviews of the same authority, capped at four rounds.
- Renders are isolated candidates. Audit B, a composition critic, and an
  editorial critic must all pass before promotion.
- Detached Auto Edit workers survive browser/Next restarts, keep bounded logs,
  and resume only hash-current checkpoints.
- Unknown identifiers, stale plans, missing evidence, unsupported lanes, and
  active-project mismatches fail closed instead of guessing.

## Editable Palmier revisions and long-form changes

The editable-build path is designed so a two-word change in a 14-minute video
does not force a 14-minute re-render.

| Requested change | Current route |
|---|---|
| Copy/color/style inside one rendered card | Re-render and replace that one ledger-bound card |
| Presenter missing from a registered PIP-hole card | Rebuild that isolated presenter-card only |
| Same-duration card move | Native move; no asset render |
| Card duration change | Replace that card asset; presenter-dependent timing may broaden the revision |
| Add/remove a card | Stable-ID add/remove with versioned binding/tombstone |
| Native Palmier text copy | One `update_text` revision-sidecar operation |
| Several independent changes | One revision set, up to 256 logical changes, checkpointed in pages of at most 24 mutations |
| Cut/ripple, source replacement, presenter recompose, captions, transitions, audio, or global look | Broader dependency-aware build; local mutation remains fail-closed until live long-form proof exists |
| Final publish | One complete QC master and full-video audit |

Every editable element has a stable plan ID, content-addressed asset, versioned
ledger binding, and exact Palmier clip/media reference. Small revisions render
only pixel-changing elements, reject stale versions before mutation, preserve
unrelated clips, and inspect dirty windows at before/entrance/middle/exit/after
frames. Stopping after import or placement is resumable from verified receipts
without replaying completed work.

**Current proof level:** the first 60-second direct Palmier build was exercised
live; a synthetic 14-minute/50-graphic plan proved bounded multi-card revisions
offline. A live 30–60 minute Palmier endurance/parity run is still outstanding,
so long-duration live-edit performance should not be presented as fully proven.

## What each tool does

### SEGMENTER (`/segmenter`)
1. **Select** your MP4 (and optional B/C-cam + lav tracks) from your local filesystem
2. **Configure** how to segment — default coaching-show prompt or your own
3. **Transcribe + Segment** — local whisper.cpp plus the configured Claude Code/Codex brain in local mode, or the preserved Deepgram + Anthropic path in live mode
4. **Edit** — adjust boundaries: split with ✂️, merge with ✕, rename by clicking the title
5. **Export** — stream-copy each kept segment to its own MP4 with ~5s pre/post-roll padding (cuts snap to keyframes; clips may overlap). Near-instant rough footage, delivered as a zip. Multicam export syncs B/C-cam + lav and re-encodes frame-accurately.

### CLIPPER (`/clipper`)
1. **Select** a clip (single-cam, or A+B pre-synced dual-cam)
2. **Transcribe** — local whisper.cpp for separate lavs/isolated stereo, or Deepgram when diarization is needed
3. **Clip** — the configured AI brain marks filler/fluff to cut at the utterance level
4. **Edit** — fine-tune at the word level in the editor
5. **Export** — generate an FCPXML timeline for Final Cut Pro 10.6+

### PRODUCER references (`/producer`)

Paste a YouTube, Instagram, or TikTok URL, or choose a local polished video.
Sniper fetches/copies it and automatically runs the deterministic deep study
(cuts, motion, transitions, captions/OCR, word lock, audio, and representative
frames). It suggests Short or Long from the source, but the operator must
confirm the format and choose one direction before the reference can be used:

URL intake uses HTTPS and caps downloads at 1080p. URL and local intake both
cap study media at 2 GiB / 60 minutes and require at least 5 GiB of free disk.

- **Mimic this** — apply this asset's measured mechanics to the next edit. It
  stays selected only while every engagement lane remains available to Auto-edit.
- **Extend a style** — add evidence to the closed Caleb/Jaden/Angela short-form
  grammar selected by the operator.
- **New style** — name a provisional candidate tied to this reference; it does
  not silently become a global preset.

The decision is stored beside the study and attached to the next ingest.
Auto-edit reads the server-resolved profile, raw study, and representative
frames, then runs a second deterministic reference gate after normal plan lint.
It copies mechanics only—never the reference's words, branding, assets, or
music. Browser cookies are off unless explicitly enabled for that one fetch.

### FRAME.IO REVIEW (`/frameio-review`)
1. **Select** an MP4 from your local filesystem
2. **Configure** — selection mode, frames/sec, an optional max-representatives cap for a cheap test run, the dedup threshold, and the model (Sonnet for quality, Haiku for cheaper passes)
3. **Run** — ffmpeg extracts frames, then one **representative per on-screen state** is picked (see modes below) and sent to Claude's vision API to flag on-screen text errors. You're asked to confirm before any run over 200 API calls.
4. **Review** — flagged timestamps stream into a sortable list next to the player; click a flag to seek there, filter out low-confidence hits, and read the exact text seen + suggested fix. Consecutive same-text verdicts (fade-in variants, repeated slides) are collapsed into one finding using Claude's own transcription. A `results.json` and a standalone `report.html` (opens with no server running) are written next to your video.

**Selection modes** (how the one frame per on-screen state is chosen):
- **Visual** (default) — perceptual-hash groups near-identical frames and keeps the *settled* frame of each run (the modal pHash, not the first), so a half-rendered fade-in frame isn't mistaken for a typo. Works on any footage, including text composited over moving video.
- **OCR text** — groups frames by tesseract text (rapidfuzz). Only suitable for clean, static slideware; on stylized text over moving video, OCR is too noisy to group reliably.

> ⚠️ Unlike SEGMENTER/CLIPPER (which only send audio + transcript text off the machine), FRAME.IO REVIEW sends **still frame images** to the Anthropic vision API — that's how it reads on-screen text. The full video is never uploaded. (Tesseract, in OCR mode, runs locally and is never sent anywhere — it only chooses which frames to send.)

The Python pipeline is also runnable on its own:
```bash
# full visual pass
.venv/bin/python3 -m scripts.frameio.review --input clip.mp4
# cheap test: cap representatives sent to Claude
.venv/bin/python3 -m scripts.frameio.review --input clip.mp4 --max-reps 15
# inspect the representatives for free (no Claude call), e.g. OCR mode
.venv/bin/python3 -m scripts.frameio.review --input clip.mp4 --mode ocr --fuzz 90 --select-only
```

> For project architecture, conventions, and invariants, see [`CLAUDE.md`](./CLAUDE.md) (auto-loaded by Claude Code).

## Requirements

- Node.js 20.9+ for the Next.js app; Node.js 22+ is recommended when using the
  complete HyperFrames CLI/tooling surface
- Python 3.9+
- ffmpeg (+ ffprobe, included with ffmpeg)
- Claude Code CLI — `claude` on PATH with a subscription login; the default
  Producer editor brain and the conversational desktop surface
- Codex CLI (optional) — `codex` on PATH with a ChatGPT subscription login;
  enable it with `SNIPER_BRAIN_PROVIDER=codex`
- whisper.cpp — `whisper-cli` plus a local model; required for no-audio-egress transcription
- Palmier Pro (optional) — the AI-native NLE. When it's open it serves a local MCP at `http://127.0.0.1:19789/mcp`; a Claude client can drive it directly for interactive live editing. Setup (incl. the Claude Desktop bridge): [`docs/palmier/PALMIER_MCP_SETUP.md`](./docs/palmier/PALMIER_MCP_SETUP.md). The repo's checked-in `.mcp.json` auto-offers this server to Claude Code.
- tesseract — only for FRAME.IO REVIEW's optional `--mode ocr`; the default visual mode does not need it
- macOS — file selection uses a native macOS picker (`osascript`); the app won't be able to pick files on other platforms yet

## Setup

### 1. Install dependencies

```bash
npm install
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The Next.js API routes auto-detect `.venv/bin/python3` and fall back to system `python3` if no venv is present.

### 2. Install ffmpeg

```bash
# macOS
brew install ffmpeg
brew install whisper-cpp       # local-mode transcription
brew install tesseract        # only needed for FRAME.IO REVIEW --mode ocr

# Ubuntu/Debian
sudo apt install ffmpeg
sudo apt install tesseract-ocr # only needed for FRAME.IO REVIEW --mode ocr
```

Place an existing whisper.cpp model at
`~/.cache/hyperframes/whisper/models/ggml-small.en.bin`, or set
`WHISPER_CPP_MODEL` to another local model. Sniper deliberately never downloads
a model during a GUI job.

### 3. Configure environment

```bash
cp .env.local.example .env.local
```

For the localhost Claude/Whisper workflow, API keys are optional. Fill them only
for live providers or explicit overrides; every runtime knob is
documented in [`.env.local.example`](./.env.local.example):

| Key | Where to get it |
|-----|----------------|
| `DEEPGRAM_API_KEY` | [console.deepgram.com](https://console.deepgram.com) |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |

### 4. (Optional) Run the web GUI

> Optional — this starts the **web GUI**. For the default, no-dev-server path,
> see [Start here (the easy path)](#start-here-the-easy-path) above.

```bash
# Local Whisper transcription; Claude Code remains the default editor brain
npm run dev:local

# Optional Codex/Sol brain instead
codex -c 'model_reasoning_effort="ultra"' login status
SNIPER_BRAIN_PROVIDER=codex npm run dev:local

# Production-style local server (build first):
npm run build
npm start           # live-provider defaults
npm run start:local
```

Open [http://localhost:3000](http://localhost:3000) and pick a tool — PRODUCER for the
full pipeline, SEGMENTER/CLIPPER for standalone rough-cut/polish passes.

To retain the original live-provider defaults instead, run `npm run dev`. See
[`docs/audits/LOCAL_CODEX_AUDIT.md`](./docs/audits/LOCAL_CODEX_AUDIT.md) for the exact
capability/data-egress matrix and remaining hardening work.

All four run commands (`dev`, `dev:local`, `start`, `start:local`) use the local
Next supervisor. It gives Next a 3 GiB heap by default (override with
`SNIPER_NEXT_HEAP_MB` in `.env.local`; an explicit `NODE_OPTIONS` heap wins),
forwards shutdown signals to the whole Next process group on macOS/POSIX, and removes any
surviving descendants before restart. A per-repository/port PID lock prevents two
supervisors from spawning duplicate servers. It stops after either three fast
failures in 30 seconds or five unexpected exits in 10 minutes instead of
crash-looping forever. Pass normal Next options after `--`, for example
`npm run dev:local -- --port 3100`; local mode will not allow its loopback
hostname to be overridden.

### Long-running Auto Edit reliability

The current working tree moves each Auto Edit into a detached worker. Once the
job starts, reloading the page or restarting only Next does not stop the edit;
the worker continues while the machine and worker process remain alive. The
project keeps two hidden control files in its `producer/` directory:

- `.sniper-auto-edit-job.json` — worker PID, durable status/events, safe
  checkpoints, and hashes used to decide what may be reused;
- `.sniper-auto-edit.log` — a bounded diagnostic tail of worker stdout/stderr.

If the worker itself stops, the project changes to **Interrupted** and shows a
**Resume Edit** button. Resume reuses only completed, hash-matching checkpoints;
it reruns validation/render work when the plan, manifest, or final file changed.
Do not delete or edit these hidden files while a job is running.

The dashboard also limits background work: visible project statuses share one
serial request queue; running work refreshes quickly, idle cards refresh every
60 seconds, and polling pauses/aborts when the tab is hidden. Palmier status
uses the same no-overlap and hidden-tab rules.

**Historical live proof:** on 2026-07-12, Next restarted while the same detached
ffmpeg worker continued and the browser reconnected to its running status.
The current repository has 109 TypeScript test files; use `npm test`,
`npm run type-check`, `npm run lint`, and `npm run build` as the release gate.
See the evidence trail in
[`docs/PIPELINE.md`](./docs/PIPELINE.md).

### Running more than one project

Projects are fully isolated (`~/ProjectSniper/<slug>/`) and each Auto Edit runs in
its own detached worker keyed to the project folder — so **you can keep as many
projects as you like** and switch between them freely. The only thing blocked is
starting a **second Auto Edit on the *same* project** (you'll get *"Auto Edit is
already running for this project"*). There is **no global limit**, but rendering is
CPU/ffmpeg-heavy and running several projects at once has **not** been stress-tested
(single-operator use only). In practice: keep many projects, but run **one active
edit at a time** and start the next when the current render finishes.

### First GUI-rendered edit in 5 steps

The verified PRODUCER loop (full walkthrough in [`docs/HANDOFF.md`](./docs/HANDOFF.md);
canonical pipeline doctrine in [`docs/PIPELINE.md`](./docs/PIPELINE.md)):

1. **Ingest** — open the PRODUCER tab, pick your footage, and fill in the **intent
   card**: a Short (with a style) or a Long (with your item checklist). The project
   lands in `~/ProjectSniper/<slug>/`.
2. **Auto-edit** — one click; the configured Claude Code or Codex brain authors
   `edit_plan.json`
   (speech cleanup → cuts → graphics/zooms/captions per your scope + style), the
   gates validate it, and the detached render worker continues even if Next
   restarts. If the worker is interrupted, use **Resume Edit** on the project.
3. **Polish in the editor** — strike words in the script to cut them, drag/trim
   blocks on the timeline, reposition graphics, adjust audio, or ask the configured
   AI editor for changes from the Ask-editor bar.
4. **Re-render** — one button; smart dispatch re-renders only what changed
   (graphics ≈ 18s, audio ≈ 12s, cut edits ≈ 3min full rebuild with automatic
   window refit).
5. **Ship** — Reveal `final.mp4` in the project directory.

### First editable Palmier build

1. Open Palmier Pro and the intended project, then ask Claude Code to
   [`/produce-palmier`](./.claude/commands/produce-palmier.md) from footage or an
   existing Producer directory.
2. Sniper binds the exact Palmier project/timeline, authors and gates a cut-only
   previsual, and lands the cut before waiting on the visual plan.
3. In the retained session it selects from the composition catalog, gates the
   full treatment, and executes only the returned content-addressed operations.
4. Give timestamped notes. Same-card copy/style repairs use the one-element fast
   path; multiple independent changes are batched into a resumable revision set.
5. `desktop_cli.py qc` exports and checks the exact candidate. Composition and
   editorial review receipts must both pass before approval.

---

## Notes

- Video files are read directly from your local filesystem. Local-mode media
  transcription and rendering stay local, while transcript/plan context is sent
  to the configured Claude Code or Codex subscription service; local mode is
  private-by-default but not offline.
- `npm run dev` preserves Deepgram/Anthropic/Claude behavior. FRAME.IO REVIEW
  remains an explicit Anthropic vision call in either mode.

---

## Documentation

- 📚 **Guide index** — [`docs/README.md`](./docs/README.md)
- 🎬 **Pipeline status** — [`docs/PIPELINE.md`](./docs/PIPELINE.md)
- 🎛️ **Palmier setup** — [`docs/palmier/PALMIER_MCP_SETUP.md`](./docs/palmier/PALMIER_MCP_SETUP.md)
- 🧩 **Incremental Palmier repairs** — [`docs/palmier/PALMIER_HYBRID_LAYERED_REPAIR_PLAN.md`](./docs/palmier/PALMIER_HYBRID_LAYERED_REPAIR_PLAN.md)
- 🧪 **Reference workflow** — [`reference-editor`](./.claude/skills/reference-editor/SKILL.md)
- 🎨 **Caption catalog** — [`.claude/skills/embedded-captions/CATALOG.md`](./.claude/skills/embedded-captions/CATALOG.md)
