# Project Sniper — working instructions
## Current visual source rule

Read `docs/producer/VISUAL_SOURCE_POLICY.md` before visual planning or execution.
Use the complete HyperFrames catalog first. Retired house templates and global
style presets cannot execute, including renamed release variants. Reference
adaptations need this job’s selected reference; custom work needs an inspected
capability or quality gap. Native Shorts stage `catalogFiles` and `catalogTitle`.
This source rule replaces historical template/style recipes below.


These are the instructions for whichever agent drives this editor. Codex reads this
file; Claude Code reads `CLAUDE.md`, which imports this file, so both agents receive
the same contract. This folder is self-contained: nothing here refers to a parent
repository, a sibling checkout or a developer's machine.

## Apply the instructions before presenting work

For each task, identify the applicable requirements and verify them against the actual
result before handing it back. Reading an instruction is not proof that the result
satisfies it. Preserve the operator's decisions and the remaining requirements across
revisions and context handoffs.

## The product contract

- **You are the editor.** The operator opened this folder in their own Codex or Claude Code,
  signed in to their own subscription. There is no Sniper web app, no Sniper copy of Codex
  or Claude and no Sniper sign-in: you do the editorial thinking in this conversation, and
  Sniper's commands do the media work on this computer. Nothing Sniper runs calls a provider.
- **Run every Sniper command through the platform launcher, from this folder:** `./sniper`
  on macOS or `sniper.cmd` on Windows. It finds Sniper's own
  Python, Node, ffmpeg, Whisper and rendering browser, loads the install's settings and holds
  the install's lock while the command runs. Commands in the skills and docs use `./sniper`
  as shorthand; on Windows replace it with `sniper.cmd`. Translate bare commands on macOS
  like this: `python3 scripts/x.py` → `./sniper python3 scripts/x.py`,
  `.venv/bin/python3 scripts/x.py` → `./sniper python3 scripts/x.py`,
  `node --import tsx scripts/x.ts` → `./sniper node --import tsx scripts/x.ts`; use the same
  arguments after `sniper.cmd` on Windows. Never run them with another Python, Node or ffmpeg.
  Project folders go under the path printed by `./sniper workspace` or `sniper.cmd workspace`.
- **Setting up.** If the launcher says Sniper is not set up, run `./sniper setup` on macOS or
  `sniper.cmd setup` on Windows (it downloads
  about 1.2 GB and takes several minutes; run it in the background, tell the operator what it
  is doing and report its last lines). Run `./sniper doctor` or `sniper.cmd doctor` to check
  the install and name the fix for anything wrong.
- **Media sandbox.** Sniper decodes every video inside its own media jail: macOS Seatbelt on
  Mac and a no-network AppContainer on Windows. macOS does not let a sandbox start inside
  another one. On macOS, if a Sniper command fails with
  `sandbox initialization failed` or `Operation not permitted` while your own sandbox is on,
  ask the operator to approve running that same command outside your sandbox. Never skip,
  weaken or work around Sniper's own media check.
- **No API-key billing.** Your conversation runs on the operator's subscription. Sniper has
  no API-key route for editing and none may be added. An API key, environment variable or
  other login is not permission to spend. If the subscription refuses (sign-in, usage limit),
  report it and stop.
- **Deepgram transcription is the one optional paid feature, used only when the operator
  explicitly asks.** It uploads audio to Deepgram and bills the operator's own Deepgram key.
  Transcription is local Whisper by default; Deepgram runs only from a transcription script
  call with the paired `--provider deepgram --authorize-paid-asr deepgram` flags
  (`scripts/asr_policy.py`). Add them only when the operator explicitly authorizes Deepgram
  for the current edit. A saved key, an environment variable or a failed local run is never
  that authorization. The operator connects, replaces or removes the key by double-clicking
  `install/setup.command` (a hidden prompt in Terminal); if a key is missing, point them
  there. On Windows use `sniper.cmd connections`. Never ask the operator to paste a key into
  the conversation, and never display or copy a key file. Nothing falls back to Deepgram.
- **No Docker.** The supported route runs natively on macOS and Windows x64.

## What leaves this computer

The full account, path by path, is `manual/privacy.html`. In short: what you read and write
in this conversation (transcripts, plans, still frames you or a reviewer look at) goes to
your provider under the operator's account, like any conversation. Sniper's own commands send
nothing anywhere, except: reference links are downloaded with `yt-dlp` (Chrome cookies are
read only when the operator asks for that fetch); public-web b-roll capture, when a Short's
media sources are set to public web, loads the pages the plan names
(`scripts/producer/studio/web_capture.py`); `scripts/producer/planner/icon_library.py` downloads
brand icons by name from `cdn.simpleicons.org` (`resolve` only for a mapped brand not yet local,
`fetch` every time it is run);
and Studio's page loads one GSAP file from `cdn.jsdelivr.net`. Studio is served from Sniper's adapted runtime, whose analytics are
switched off. Open Studio only through Sniper (`install/studio.command` on macOS or
`install\studio.cmd` on Windows for a Producer edit, or the platform launcher followed by
`python3 scripts/producer/studio/managed_preview.py open <project>` for a native
project), never with the stock `hyperframes preview`, which would send HeyGen's analytics. Instructions are not a
privacy boundary: do not attach or upload video or audio files to the conversation; work
from transcripts, plans and still frames.

## Where the doctrine lives

| Read this | For |
|---|---|
| `docs/PIPELINE.md` | The canonical route. It wins every contradiction. |
| `.claude/skills/producer/SKILL.md` | The editing doctrine: how a plan is authored and gated. Codex adapters in `.agents/skills/` point to the same canonical skills. |
| `docs/producer/command-driven-editing/12_SHORT_LONG_EXECUTABLE_MATRIX.md` | Current route behaviour and its explicit blockers. |
| `resources/references/README.md` | The packaged reference library: original worked examples rendered from Sniper's own templates. |
| `resources/director/README.md` | The original Director hook and format library. |
| `scripts/producer/CLAUDE.md` | The Python engine's module map. Read before adding or duplicating engine functionality. |
| `docs/producer/STUDIO_REVIEW_LANE.md` | The required review handoff: local playback **and** the editable Studio project. |
| `docs/producer/SHORTS_JOURNEY_SELECTION_PLAYBOOK.md` | Selection and paper-edit rules before showing the operator candidates. |
| `CLAUDE.md` § Engineering reference | Layout and invariants, for changes to the application itself. |

Start or resume with the context skill (`$sniper-context` in Codex, `/sniper-context` in
Claude Code) or `./sniper python3 -B scripts/producer/context.py --project /absolute/project`,
then read the files it identifies. Discovery alone neither reads them nor completes a review.

## Producer work

- Read the Producer skill for editorial work and the pipeline direction for the applicable
  route. Follow the required domain instructions before their steps.
- For selection and paper edits, read the assembled speech as a new viewer would: who and
  what is this about, why does it matter, and does the ending answer the opening? A title
  is not spoken context. Cut repetition before context. Mark source excerpts separately
  from proposed final speech and keep the exact source selections for any proposed deletion.
- Honour the requested duration, destination and scope. A trim-only request must not gain
  graphics, motion, music or any other treatment nobody asked for.
- Save the operator's request as the project's stored intent before planning:
  `./sniper node --import tsx scripts/infra/project-intent.ts <project> --intent '<json>'`
  (render and delivery read it and refuse without it).
- Before any ordinary final render or assembly, including trim and graphics-off, record
  current independent reviews and preview evidence, then mint readiness with
  `./sniper node --import tsx scripts/infra/mint-delivery-approval.ts <project>/producer`.
  Follow `docs/producer/RENDER_READINESS.md`: first mint separate `--draft` admission,
  then run `ordinary_previews.py` for continuous context clips. Pass its prior
  `ordinary-previews.json` with `--previous` on revisions. Inspect/revise those clips
  before final admission; the command never grants an editorial review.
- Independent reviews (plan critics, the rendered review of still frames) are run by you as
  fresh subagents that did not author the plan, as the Producer skill describes.
- At video handoff, give the operator both the encoded video and the matching editable
  Studio project (`install/studio.command open <project>/producer` on macOS or
  `install\studio.cmd open <project>\producer` on Windows), and keep both current
  after an adjustment.
- Run the applicable gates and QC (`./sniper python3 scripts/producer/audit/audit_render.py <out_dir>`)
  before claiming anything is complete.

## Not available in this package

- **Palmier Pro** is not configured here (no MCP server is declared). Skill and doc
  sections about Palmier mirrors or editable Palmier candidates do not apply; if the
  operator asks for Palmier, say it is not available and deliver the MP4 plus the Studio
  project.
- The `separate` dialogue-cleanup preset needs software this package does not ship.
- Reproducing another creator's look is not a claimed capability. The reference library
  and reference studies are guidance, never replication.
- **Not in this release** (they needed the retired web app): Text Review, Clipper's
  dual-camera/lav Final Cut export, and the guided checkpoint and Native Director routes
  (`guided-*`, `native-director-*`). Skill and doc sections about them do not apply; use the
  native HyperFrames route or an ordinary plan instead. Docs that tell you to POST to an
  `/api/...` URL or open a `localhost` page do not apply either: use the command-line
  equivalent named above, or say the step is unavailable.

## Checks

```bash
./sniper npm run type-check
./sniper npm run lint
./sniper npm test
./sniper /bin/sh -c 'cd scripts/producer && PYTHONPATH=.:tests python3 -B selftest.py'
```

(The Python suite needs `PYTHONPATH`, which `./sniper` clears for every other command, and
runs from `scripts/producer`.) In a developer checkout (no `install/`), `./sniper` runs them
with your own tools. The
Python suite is stdlib `unittest`, not pytest. Both suites must stay green. If a
change cannot be verified this way, say so rather than claiming success.
