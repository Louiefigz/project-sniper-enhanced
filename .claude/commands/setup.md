---
description: Set up or check this Mac's Sniper install and explain the next step in plain words.
argument-hint: (no arguments)
---

You are helping someone set up or check Project Sniper. They may not be technical. They opened
this folder in their own Codex or Claude Code; there is nothing else to sign in to. Sniper
installs and repairs its own tools with `./sniper setup`. Be calm and plain-spoken; run the
commands yourself and report back instead of pasting commands at them.

If there is no `install/` folder here, this is a developer checkout, not the packaged app:
point them to `CLAUDE.md` § Engineering reference instead and stop.

## Step 1 — Is it set up?

Run `./sniper doctor` and read its report. It installs and removes nothing: it only creates
the video workspace folder if it is missing (and writes a probe file there), and rebuilds the
render runtime from the shipped patches if that is missing.

If it says Sniper is not set up yet, or a line says to run the installer, run `./sniper setup`.
It downloads Sniper's own tools and the speech model (about 2 GB) and takes several minutes:
run it in the background, tell them what it is doing, and report its last lines when it ends.
It asks nothing and never touches their own Codex, Claude, Node, Python or Homebrew. If your
sandbox blocks its downloads or its writes to `~/.project-sniper`, ask them to approve running
it outside your sandbox. Then run `./sniper doctor` again.

## Step 2 — Explain anything still failing

For each line that did not pass, say in one sentence what it is and what fixes it:

- A step failed or a tool is missing, changed or not the one PATH finds (`Sniper's own tools`,
  `ffmpeg`, `whisper-cli`, `tesseract`, `yt-dlp`, `node`, `python3`) → `./sniper setup`; it
  redoes only what is unfinished, from checked downloads. Never install these with Homebrew or
  any other system installer instead.
- `media admission` fails while your own sandbox is on → run `./sniper doctor` again outside
  your sandbox, with their approval (macOS does not nest sandboxes).
- `install in use` → a Sniper command is still running; let it finish.

Do not run `npm install` or `pip install` in this folder, do not change `runtime/sniper.env`,
and do not add or copy API keys: editing runs on their own subscription. Deepgram
transcription is the one optional paid add-on; if they ask for it, tell them to double-click
`install/setup.command` in Finder to enter their Deepgram key privately. Never ask for a key
in this conversation.

## Step 3 — When everything passes

Confirm it in one or two sentences, then tell them how to use it:

> You're all set. Just tell me what to make — for example "cut a 45-second vertical short
> from ~/Desktop/raw.mp4" or "clean up this long recording: <path>". The finished
> `final.mp4` and its editable Studio project land in your video projects folder
> (`$(./sniper workspace)`: the `projects` folder inside Sniper unless you chose another).

Keep the closing short. The full manual is `manual/index.html`.
