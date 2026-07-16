# 🎯 PROJECT SNIPER

> AI video editing for Claude Code desktop and Palmier Pro.

An AI video pipeline with four tools that share one UI. Pick a tool from the landing page,
or toggle between them in the top nav.

- **🎬 SEGMENTER (Part 1)** — rough-cut long footage into clips. Transcribe, let the
  configured AI brain identify segments, adjust boundaries, and export MP4 clips
  (single or multicam) as a zip for downstream trimming.
- **✂️ CLIPPER (Part 2)** — refine a clip into a polished cut. Transcribe, let the LLM cut
  filler at the word level, fine-tune in the word editor, and export an FCPXML timeline for
  Final Cut Pro.
- **🎛️ PRODUCER (Part 3)** — **the main pipeline.** Upload raw footage, pick your intent
  on one card — a **Short (9:16)** in a studied style (**Caleb light · Jaden produced ·
  Angela involved**), or a **Long (16:9)** with a **checklist of exactly what you want**
  (full workflow, or just certain items: motion, graphics, transitions, captions, b-roll,
  credibility, music, dialogue cleanup). An AI editor authors a gated edit plan and renders
  it; the optional destination NLE is **Palmier Pro**. Sniper mirrors the exact
  approved visual/audio master there as one verified clip, preserves component
  assets best-effort, and labels which concepts have native controls. Opening the
  mirror hands control to Palmier; there is no lossy two-way plan sync. See the
  honest status in [`docs/PIPELINE.md`](./docs/PIPELINE.md).
- **🔍 FRAME.IO REVIEW** — a standalone QC pass (not a pipeline stage). Scan an MP4 for
  on-screen text errors — typos, spelling, grammar, broken formatting — and review the
  flagged timestamps next to a video player.

**The typical workflow: upload footage into PRODUCER → choose Short (with a style) or Long
(with your item checklist) → review the approved Sniper render → optionally update the
verified Palmier mirror and take manual control there** —
canonical description in [`docs/PIPELINE.md`](./docs/PIPELINE.md). SEGMENTER and CLIPPER
remain useful standalone (rough-cut a long recording into clips; word-level FCPXML polish),
and PRODUCER can ingest SEGMENTER/CLIPPER output — but PRODUCER is the through-line.

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
2. **Download and open Palmier Pro** — the AI-native NLE where your edit shows up.
   It **must be open**: while running it serves the local MCP the pipeline talks to
   (`http://127.0.0.1:19789/mcp`). Setup + the Claude Desktop bridge:
   [`docs/palmier/PALMIER_MCP_SETUP.md`](./docs/palmier/PALMIER_MCP_SETUP.md).
3. **Open this project folder in Claude Code desktop** and just ask — e.g.
   *"cut a Jaden-produced short from this footage"* or *"clean-cut this long recording."*
   Claude loads the **`producer`** skill and drives the whole pipeline (ingest →
   gated `edit_plan.json` → render → optional Palmier mirror); watch it build in Palmier Pro.

**Where your files go:** everything lands under **`~/ProjectSniper/<slug>/`** — your
finished **`final.mp4`** and working files are in that project's `producer/` folder;
reference studies live under `~/ProjectSniper/_references/`.

**More references & docs:** [`docs/README.md`](./docs/README.md).

> The web GUI (the `/producer` editor, below) is an **optional** visual surface for the
> same pipeline — it is not required for the default flow, and you should not need to
> start a dev server just to make an edit.

## What each tool does

### SEGMENTER (`/segmenter`)
1. **Select** your MP4 (and optional B/C-cam + lav tracks) from your local filesystem
2. **Configure** how to segment — default coaching-show prompt or your own
3. **Transcribe + Segment** — local whisper.cpp + Codex/Sol in local mode, or the preserved Deepgram + Anthropic path in live mode
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

- Node.js 20.9+ (Next.js 16 requires `node >=20.9.0`)
- Python 3.9+
- ffmpeg (+ ffprobe, included with ffmpeg)
- Codex CLI — `codex` on PATH with a ChatGPT subscription login; required for the localhost Codex/Sol workflow
- whisper.cpp — `whisper-cli` plus a local model; required for no-audio-egress transcription
- Claude Code CLI — optional preserved live/legacy PRODUCER brain (`claude` on PATH with subscription login)
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

For the localhost Codex/Whisper workflow, API keys are optional. Fill them only
for the preserved live providers or explicit overrides; every runtime knob is
documented in [`.env.local.example`](./.env.local.example):

| Key | Where to get it |
|-----|----------------|
| `DEEPGRAM_API_KEY` | [console.deepgram.com](https://console.deepgram.com) |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |

### 4. (Optional) Run the web GUI locally with Codex/Sol Ultra

> Optional — this starts the **web GUI**. For the default, no-dev-server path,
> see [Start here (the easy path)](#start-here-the-easy-path) above.

```bash
codex -c 'model_reasoning_effort="ultra"' login status
npm run dev:local

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

**Status:** verified 2026-07-12 by type-check, full lint, production build, all
37 TypeScript test files, and a live C0679 restart test: Next restarted while
the same detached ffmpeg worker continued and the browser reconnected to its
running status. See the canonical evidence in
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

### First edit in 5 steps

The verified PRODUCER loop (full walkthrough in [`docs/HANDOFF.md`](./docs/HANDOFF.md);
canonical pipeline doctrine in [`docs/PIPELINE.md`](./docs/PIPELINE.md)):

1. **Ingest** — open the PRODUCER tab, pick your footage, and fill in the **intent
   card**: a Short (with a style) or a Long (with your item checklist). The project
   lands in `~/ProjectSniper/<slug>/`.
2. **Auto-edit** — one click; local mode uses Codex with `gpt-5.6-sol` / Ultra
   to author `edit_plan.json`
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

---

## Notes

- Video files are read directly from your local filesystem. Local-mode media
  transcription and rendering stay local, while transcript/plan context is sent
  to the remote Codex subscription service; local mode is not offline.
- `npm run dev` preserves Deepgram/Anthropic/Claude behavior. FRAME.IO REVIEW
  remains an explicit Anthropic vision call in either mode.

---

## Documentation

- 📚 **Guide index** — [`docs/README.md`](./docs/README.md)
- 🎬 **Pipeline status** — [`docs/PIPELINE.md`](./docs/PIPELINE.md)
- 🎛️ **Palmier setup** — [`docs/palmier/PALMIER_MCP_SETUP.md`](./docs/palmier/PALMIER_MCP_SETUP.md)
