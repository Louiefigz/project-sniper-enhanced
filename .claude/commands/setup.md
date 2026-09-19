---
description: Check this Mac's Sniper install (read-only) and explain the next step in plain words.
argument-hint: (no arguments)
---

You are helping someone check their Project Sniper install. They may not be technical.
Sniper installs, signs in and repairs itself with its own scripts in `../install/`; this
command only checks and explains. Be calm and plain-spoken; run the check yourself and
report back instead of pasting commands at them.

## Step 1 — Run the doctor (it only checks)

Run `../install/doctor.command` from this folder and read its report. It installs and removes
nothing: it only creates the video workspace folder if it is missing (and writes a probe file
there), and rebuilds the render runtime from the shipped patches if that is missing.
If there is no `../install/` folder, this is a developer checkout, not the packaged app:
point them to `CLAUDE.md` § Engineering reference instead and stop.

## Step 2 — Explain what it found

For each line that did not pass, say in one sentence what it is and which script fixes it:

- Not installed, outdated, or a step failed → `install/install.command` (it repeats only
  unfinished steps).
- One of Sniper's own tools is missing, changed or not the one PATH finds (`Sniper's own
  tools`, `ffmpeg`, `whisper-cli`, `tesseract`, `yt-dlp`, `node`, `python3`, `git`) →
  `install/install.command`; it reinstalls them into `~/.project-sniper` from checked
  downloads. Never install these with Homebrew or any other system installer instead.
- Not signed in → `install/sign-in.command`. The operator runs it and signs in themselves
  in the browser window it opens; never sign in, sign out or handle credentials for them.
- They want the other subscription → `install/stop.command`, then
  `install/use-provider.command codex|claude`, then `install/sign-in.command`.

The installer and the provider switch refuse while this editor window is open (it holds the
install in use), so tell the operator to close this window first and run those scripts from
Finder or Terminal, then reopen `install/editor.command`.

Do not install another Codex or Claude CLI, do not run `npm install` or `pip install` in
this folder, do not change `../runtime/sniper.env`, and do not add or copy API keys. The
editing workflow needs no API key. Text Review is the one optional paid add-on (the
operator's own Anthropic API key in `../runtime/sniper.local.env`); mention it only if they
ask about it.

## Step 3 — When everything passes

Confirm it in one or two sentences, then tell them how to use it:

> You're all set. Start the app with `install/start.command`, or just tell me what to
> make — for example "cut a 45-second vertical short from ~/Desktop/raw.mp4" or "clean up
> this long recording: <path>". The finished `final.mp4` and its editable Studio project
> land in your video workspace (`~/ProjectSniper/<project>/` unless you chose another
> folder at install).

Keep the closing short. The full manual is `../manual/index.html`.
