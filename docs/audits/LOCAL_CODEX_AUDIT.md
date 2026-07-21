# Local Codex/Sol audit

Audit date: 2026-07-12

## Verdict

PROJECT_SNIPER can use **GPT-5.6 Sol with Ultra reasoning** as the editing
brain for SEGMENTER, CLIPPER, and PRODUCER when the GUI is run in local mode.
The preserved live mode still uses the existing Anthropic API and Claude Code
paths.

Sol is not the media renderer. It returns segment boundaries, word-level cut
decisions, or a gated Producer `edit_plan.json`. Existing deterministic local
stages create the actual artifact:

- SEGMENTER: FFmpeg creates MP4 clips and a ZIP.
- CLIPPER: the browser creates FCPXML for Final Cut Pro; it does **not** create
  an MP4 today.
- PRODUCER: Python, FFmpeg, HyperFrames, and optionally Palmier Pro create the
  rendered video.

That separation is intentional. GPT-5.6's current model guidance describes
`gpt-5.6-sol` as the routed Sol model and supports high reasoning levels; actual
generative-video jobs belong to the Sora/Videos API, which is a different
product and is not needed for this edit pipeline:

- <https://developers.openai.com/api/docs/guides/latest-model>
- <https://learn.chatgpt.com/docs/agent-configuration/subagents#choosing-models-and-reasoning>
- <https://developers.openai.com/api/docs/guides/video-generation#overview>

## Capability matrix

| Tool | Local transcription | Local decision brain | Artifact producer | Preserved live path |
|---|---|---|---|---|
| SEGMENTER | whisper.cpp | Codex CLI, `gpt-5.6-sol`, `ultra`, strict segment schema | local FFmpeg; single-camera and multicam MP4 ZIP | Deepgram + Anthropic API |
| CLIPPER | whisper.cpp for separate lavs or truly isolated stereo | Codex CLI, strict cut-decision schema | browser-generated FCPXML only | Deepgram diarization + Anthropic API |
| PRODUCER | whisper.cpp per source | Codex CLI reads the Producer skill, authors and gates the plan | local Python/FFmpeg/HyperFrames; optional loopback Palmier MCP | Deepgram + Claude Code subscription CLI |

Local Clipper deliberately fails on mono or crosstalk camera audio because
whisper.cpp cannot preserve the existing two-speaker diarization contract.
Select separate host/guest lavs, use isolated stereo, or explicitly opt into
Deepgram for that job.

FRAME.IO REVIEW is outside this three-tool migration. It still sends selected
still frames to Anthropic vision when the operator explicitly runs a review.

## Runtime selection

The defaults are mode-dependent:

| Setting | `live` default | `local` default |
|---|---|---|
| Brain | `legacy` | `codex` |
| Transcription | `deepgram` | `local-whisper` |
| Render/export | local | local |

Explicit overrides remain available:

```dotenv
SNIPER_EXECUTION_MODE=local
SNIPER_BRAIN_PROVIDER=codex
SNIPER_CODEX_MODEL=gpt-5.6-sol
SNIPER_CODEX_REASONING=xhigh
SNIPER_TRANSCRIBE_PROVIDER=local-whisper
```

Other CLI-recognized levels must not be assumed valid for this model. On
2026-07-18 the provider-resolved `gpt-5.6-sol-1p-codexswic-ev3` build rejected
`ultra` and accepted `none`; `xhigh` is the conservative production default.

## Local setup

1. Install/update Codex and authenticate with the ChatGPT subscription.
2. Install `whisper-cli` and place an existing model on disk. Local mode never
   downloads one automatically.
3. Start the loopback-only GUI.

```bash
codex --version
codex -c 'model_reasoning_effort="xhigh"' login status
npm run dev:local
```

The default model search includes:

```text
~/.cache/hyperframes/whisper/models/ggml-small.en.bin
```

The GUI runtime badge reports the selected brain, reasoning level,
transcription provider, CLI versions, and a blocked state when Codex login,
the requested reasoning syntax, `whisper-cli`, or its local model is unavailable.

### Verified on this workstation

- `codex-cli 0.144.1` accepts the local `xhigh` setting and reports ChatGPT
  subscription login. A live 2026-07-18 probe proved that local enum acceptance
  is insufficient: the then-resolved build rejected `ultra` at request time.
- Sniper's strict-schema wrapper completed a live structured-output call.
- The same wrapper completed from a non-git Producer job directory, then a
  workspace-write smoke read the Producer adapter and wrote only its job file.
- `whisper-cli 1.9.1` with the cached `ggml-small.en.bin` model transcribed the
  bundled JFK sample through `scripts/transcribe.py` without an API key.

## What “local” means

Local mode is **localhost-safe, not offline**:

- Raw media transcription and rendering stay on the machine when
  `local-whisper` is selected.
- Transcript text, edit instructions, selected repository context, and plan
  output are processed remotely through the authenticated Codex subscription.
- The app does not pass `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, Deepgram keys, or
  unrelated application secrets into Codex.
- An explicit `SNIPER_TRANSCRIBE_PROVIDER=deepgram` opt-in sends audio to
  Deepgram even while the UI is bound to localhost.
- Palmier communication stays on `127.0.0.1:19789`.

## Localhost protections added

- `dev:local` and `start:local` bind Next.js to `127.0.0.1`.
- API middleware rejects non-loopback Host headers, cross-site browser
  requests, mismatched Origin headers, and non-JSON mutation requests.
- API responses receive no-store and browser hardening headers.
- Codex runs ephemerally with user config/rules ignored, web search, apps,
  hooks, and nested agents disabled, approvals disabled, and a restricted
  sandbox.
- SEGMENTER and CLIPPER Codex calls are read-only and schema-constrained.
- PRODUCER can write only in its job workspace; repository skill and script
  files are read-only to that run.
- Manifests and transcripts are labeled untrusted data in prompts so embedded
  text cannot redefine the editing instructions.
- SEGMENTER and CLIPPER clients require validated terminal success events and
  no longer advance on empty, malformed, HTTP-error, or truncated streams.
- CLIPPER probes the primary source and preserves its rational frame rate and
  coded raster in FCPXML instead of silently substituting 30 fps / 1080p.
- URL reference downloads, including yt-dlp's browser-cookie retry, are blocked
  in local mode unless `SNIPER_LOCAL_ALLOW_REFERENCE_FETCH=1` is deliberately
  set.
- Local Whisper fails closed: no model download and no automatic fallback to a
  network provider. A failed GPU attempt may retry locally on CPU.

## Preserved behavior

No live provider implementation was removed. Running the original command
keeps the prior defaults:

```bash
npm run dev
```

In live mode SEGMENTER/CLIPPER still use Anthropic, PRODUCER still uses the
Claude Code subscription skill bridge, Deepgram remains the default
transcription provider, and FRAME.IO REVIEW remains unchanged.

## Remaining risks and next hardening phase

The local boundary substantially reduces browser and LAN exposure, but it is
not an authentication system:

1. A process already running as the same local user can call loopback APIs.
2. Several routes still accept absolute filesystem paths. Replace those with
   opaque, expiring capability handles rooted in the configured workspace.
3. Long-running transcribe/render jobs need a shared job registry with explicit
   cancellation, TTL cleanup, concurrency limits, and reconnectable status.
4. CLIPPER now carries the primary source's exact rational frame rate and coded
   raster into FCPXML, but it assumes secondary cameras are already conformed.
   VFR becomes a constant nominal-rate timeline, and rotation/non-square-pixel
   display transforms are not modeled.
5. Add route-level and browser E2E coverage for cancellation/reconnect behavior
   and representative local-provider media. Current unit coverage now includes
   provider policy, local ASR, terminal-stream failure, media metadata/FCPXML,
   localhost middleware, Segmenter validation, and Producer branching.

These items do not block the requested localhost workflow, but they should be
completed before exposing the GUI beyond loopback or treating it as a
multi-user service.
