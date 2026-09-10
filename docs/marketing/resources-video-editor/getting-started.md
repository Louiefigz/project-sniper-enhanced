# Getting started

You'll have your first edit in a few minutes. Here's the whole flow.

## What you need

- **A Mac** (macOS — that's where the editor runs today).
- **Project Sniper**, installed — follow the setup steps in the repository [`README.md`](../../../README.md).
- **Palmier Pro** *(optional)* — use it after approval when you want to finish
  or export in an NLE. The dependable handoff is one flat clip containing the
  exact approved video; Palmier does not need to stay open while Sniper renders.
- A short piece of **raw footage** to try it on.

*(Behind the scenes it also uses a couple of free local tools for transcription and rendering — the setup guide installs those once.)*

## The easy way: edit by asking

The simplest way to use the editor is to **open your project in Claude Code desktop** (the app you chat with the editor in) and just say what you want:

> *"Cut a Jaden-produced short from this footage."*
> *"Clean-cut this long recording — just remove the silences and bad takes."*

The AI loads the editor, studies your footage, makes the cuts, adds captions and
graphics, and renders an approved `final.mp4`. Review that result in Sniper.
After approval, you can publish the exact file to Palmier as a single flat
mirror clip. A live editable Palmier build exists as an isolated experiment,
but it is P5-blocked and is not the getting-started workflow.

## Prefer buttons? Use the visual editor

There's also a full visual editor if you'd rather click through it:

1. **Add your footage** and fill in the intent card — a Short with a style, or a Long with a checklist of what you want done.
2. **Auto-edit** — one click. The AI writes the edit and renders it.
3. **Polish** — strike words to cut them, drag graphics, adjust audio, or ask for changes in plain language.
4. **Re-render** — one button; the local dispatcher reuses unaffected work when
   the requested change is eligible, then QC checks the new result.
5. **Ship** — use the approved `final.mp4` directly, or publish its exact flat
   mirror to Palmier for finishing.

## Where your finished video lives

Every project gets its own folder at **`~/ProjectSniper/<your-project>/`**. Your finished video (`final.mp4`) is inside that project's `producer/` folder.

## What's next

- [Make a short →](make-a-short.md)
- [Edit a long-form video →](edit-long-form.md)
- [Use a reference for style guidance →](match-a-reference.md)
