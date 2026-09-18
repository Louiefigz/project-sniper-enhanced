# Project Sniper — working instructions

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

- **The editor brain is the operator's own subscription.** Sniper uses the Codex CLI
  (ChatGPT subscription) or the Claude Code CLI (Claude subscription) that its installer
  pinned in `../runtime/cli/`, each with its own login state (`../runtime/codex-home`,
  `../runtime/claude-config`). The operator's own `codex`/`claude` installation and login
  are not used.
- **One provider per install.** `SNIPER_PROVIDER` (`codex|claude`) and
  `SNIPER_BRAIN_PROVIDER` (`codex|legacy`) in `../runtime/sniper.env` select it; every
  app call — Producer, Segmenter and Clipper — uses that provider and its configured model
  (`SNIPER_CODEX_MODEL`, `SNIPER_CLAUDE_MODEL`). If the two settings disagree the app
  refuses. Switch with `install/use-provider.command codex|claude`, never by hand-editing
  one of them.
- **No API-key billing in the editing workflow.** Producer, Segmenter and Clipper have no
  API-key or SDK route and none may be added. The provider CLI must pass the admission in
  `src/app/api/_lib/subscription-policy.ts` (exact pinned version, subscription sign-in).
  Do not relax it, and do not change a global CLI to make a check pass. An API key,
  environment variable or other login is not permission to spend. If the subscription
  refuses (sign-in, usage limit), report it and stop; never switch provider, key or route.
- **Separately optional paid features, used only when the operator explicitly asks:**
  - *Text Review* (`/frameio-review`) sends still frames to Anthropic's API on the
    operator's own `ANTHROPIC_API_KEY` (from `../runtime/sniper.local.env`); the app refuses
    a run without the operator's explicit opt-in.
  - *Deepgram transcription* uploads audio to Deepgram and bills the operator's own
    Deepgram key. Transcription is local Whisper by default and no app route uses Deepgram;
    it runs only from a transcription script call with the paired
    `--provider deepgram --authorize-paid-asr deepgram` flags (`scripts/asr_policy.py`).
    Add them only when the operator explicitly authorizes Deepgram for the current edit. A
    saved key, an environment variable or a failed local run is never that authorization.
    The operator connects, replaces or removes the key with `../install/setup.command`,
    which saves it privately to `../runtime/deepgram.env`; if a key is missing, point them
    there.
  - Nothing falls back to either of these. Never ask the operator to paste a key into the
    conversation, and never display or copy a key file.
- **No Docker.** The supported route runs natively on macOS.

## What leaves this Mac

The full account, path by path, is `../manual/privacy.html`. In short: transcript and plan
text, and still frames of the rendered edit (the rendered review runs in Auto Edit,
trim-only jobs included), go to the selected provider. Reference links are downloaded with
`yt-dlp`; Chrome cookies are read only when the operator ticks the box for that fetch.
Instructions are not a privacy boundary: when you run with file tools, do not attach or
upload video or audio files to the conversation; work from transcripts, plans and still
frames.

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
Claude Code) or `python3 -B scripts/producer/context.py --project /absolute/project`, then
read the files it identifies. Discovery alone neither reads them nor completes a review.

## Producer work

- Read the Producer skill for editorial work and the pipeline direction for the applicable
  route. Follow the required domain instructions before their steps.
- For selection and paper edits, read the assembled speech as a new viewer would: who and
  what is this about, why does it matter, and does the ending answer the opening? A title
  is not spoken context. Cut repetition before context. Mark source excerpts separately
  from proposed final speech and keep the exact source selections for any proposed deletion.
- Honour the requested duration, destination and scope. A trim-only request must not gain
  graphics, motion, music or any other treatment nobody asked for.
- At video handoff, give the operator both the encoded video and the matching editable
  Studio project, and keep both current after an adjustment.
- Run the applicable gates and QC before claiming anything is complete.

## Not available in this package

- **Palmier Pro** is not configured here (no MCP server is declared). Skill and doc
  sections about Palmier mirrors or editable Palmier candidates do not apply; if the
  operator asks for Palmier, say it is not available and deliver the MP4 plus the Studio
  project.
- The `separate` dialogue-cleanup preset needs software this package does not ship.
- Reproducing another creator's look is not a claimed capability. The reference library
  and reference studies are guidance, never replication.

## Checks

```bash
npm run type-check
npm run lint
npm test
cd scripts/producer && PYTHONPATH=.:tests ../../.venv/bin/python3 selftest.py
```

The Python suite is stdlib `unittest`, not pytest. Both suites must stay green. If a
change cannot be verified this way, say so rather than claiming success.
