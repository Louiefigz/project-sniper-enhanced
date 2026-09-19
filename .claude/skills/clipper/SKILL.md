---
name: clipper
description: >
  CLIPPER for PROJECT_SNIPER — polish ONE clip by cutting filler, false starts,
  repetition, and dead air at the word level, driven from Claude Code (no web
  GUI, no dev server). You transcribe the clip, decide which spans to KEEP
  yourself (you are the brain), and a deterministic pipeline renders a finished
  MP4 (−14 LUFS master) AND a Final Cut Pro FCPXML into an output folder.
  Trigger on: "clean up this clip", "cut the filler / tighten this", "remove the
  ums and false starts", "make a clean cut of this", "give me an FCPXML for
  Final Cut". Do NOT trigger for rough-cutting a long recording into many clips
  (that is the `segmenter` skill), for a fully produced video with graphics /
  captions / reframe (that is the `producer` skill), or for building the SNIPER
  app itself.
---

# CLIPPER — skill v1

You are the **brain** of CLIPPER. One clip in → one tight, clean cut out. You
read a word-level transcript and decide which spans to KEEP; deterministic
executors do the rendering. You never run ffmpeg by hand for the cut.

**Scope: word-level cleanup only** — remove filler/false starts/repetition/dead
air, keep the speaker's meaning and words exactly. No graphics, captions,
reframe, b-roll, or music (that is the `producer` skill). If the user wants a
produced short/long, hand off to `producer`.

## Where output goes

In the operator's video workspace — `$SNIPER_WORKSPACE_ROOT`, which the packaged app's settings
set (the folder chosen at install; `~/ProjectSniper` when unset) — in the `clipper/` folder the
app's Clipper also uses:

```
<workspace>/<slug>/clipper/
  transcript.json        # the word-level ASR result you worked from
  keep_ranges.json       # your raw KEEP decisions (editorial)
  keep_ranges.clean.json # frame-snapped + media-clamped (feeds BOTH outputs)
  final.mp4              # rendered clean cut, −14 LUFS master
  final.fcpxml           # Final Cut Pro 10.6+ timeline of the same cut
```

Pick `<slug>` from the clip filename + a short descriptor, kebab-case. Run all
commands from the repo root.

## The pipeline — do these in order

### 1. Set up the project folder

```bash
SLUG="<slug>"; CLIP="<absolute path to the clip>"
OUT="${SNIPER_WORKSPACE_ROOT:-$HOME/ProjectSniper}/$SLUG/clipper"; mkdir -p "$OUT"
```

### 2. Transcribe word-level locally (no paid fallback)

Use installed local Whisper without sourcing credential files. Local-provider
limitations below still apply; a missing capability does not authorize paid ASR
or relaxing the speaker/channel checks.

```bash
.venv/bin/python3 scripts/clipper/clipper_transcribe.py "$CLIP" --provider local-whisper > "$OUT/transcript.raw.jsonl" 2> "$OUT/transcribe.log"
tail -n 1 "$OUT/transcript.raw.jsonl" > "$OUT/transcript.json"
```

The final stdout line is the result with word-level timings
(`{start,end,text,words:[{word,start,end}], speaker?}`). If it has an `"error"`
key:
- The local provider only works for CLIPPER on a
  **video** file (or two separate lav files / truly isolated stereo) — local
  single-file mono cannot diarize and the script rejects it. For dual-lav,
  transcribe with `scripts/clipper/clipper_transcribe.py --lavs <host_lav> <guest_lav>
  --provider local-whisper`. Do not relabel camera stereo as isolated lavs.
- Missing runtime/model → report it and ask before installing/downloading.
- Otherwise report the error; never fabricate words, speaker labels or a transcript.

Only a separate explicit user authorization for this paid invocation allows
`--provider deepgram --authorize-paid-asr deepgram` together. Keys or environment
settings are not authorization. Never add those flags for subscription/local-only
work. Preserve the clipper's existing sample/timing/channel/diarization rules and
keep it separate from the segmenter transcriber; no raw video egress.

### 3. Decide what to KEEP (you, the brain)

Read `transcript.json`. Using the **word-level** timings, write `keep_ranges.json`
— a JSON array of the spans to keep, in original order:

```json
[{ "start": 0.50, "end": 4.00, "text": "the kept words" }, ...]
```

`start`/`end` are word timestamps from `words[]`; `text` is the kept words
(used for the FCPXML clip notes). Everything BETWEEN ranges is cut. Doctrine
(same as the GUI's edit prompt):

- Remove filler, false starts, repetition, and tangents; **preserve the
  speaker's meaning**. Never invent, paraphrase, or reorder spoken words — a KEEP
  range is a verbatim span of the source.
- **Open on the strongest clear moment; end just after the main takeaway.** No
  abrupt cold open, no trailing chatter.
- Cut lines that are only filler, crosstalk, noise, or an unusable fragment.
- If nearby words repeat due to mic bleed, keep the clearest copy only.
- Trim a partly-good utterance by setting the range to just its usable words.
- Keep the result understandable to a first-time viewer.

If the user gave a specific edit request (e.g. "keep only the part about
onboarding", "make it under 60s"), follow that over the default.

Don't fuss over frame-exact boundaries — use the word timings as-is. Step 4
snaps and clamps them for you; your job is only the editorial WHICH.

### 4. Normalize, then render both deliverables (deterministic)

First normalize your ranges (snap to frames, clamp to the media, drop/merge) —
this is REQUIRED. ASR timestamps can overshoot the last frame, and the renderer
hard-errors on the resulting drift; the normalizer makes the ranges frame-safe
without changing what content is kept.

```bash
# 4a. make the ranges frame-safe → keep_ranges.clean.json
.venv/bin/python3 scripts/clipper/clipper_normalize_ranges.py "$CLIP" "$OUT/keep_ranges.json" "$OUT/keep_ranges.clean.json"

# 4b. Clean-cut MP4 master (cut + optional speed, two-pass loudnorm to −14 LUFS)
.venv/bin/python3 scripts/producer/edit/render_cut.py "$CLIP" "$OUT/keep_ranges.clean.json" "$OUT/final.mp4"

# 4c. Final Cut Pro timeline of the same cut (reuses the GUI's exact generator)
node --import tsx scripts/clipper/clipper_fcpxml.ts "$CLIP" "$OUT/keep_ranges.clean.json" "$OUT/final.fcpxml"
```

Notes:
- `render_cut.py` is longform semantics: cut time out, keep the source
  resolution and 16:9, burn nothing. Add `--speed 1.1` if the user wants a
  tighter pace.
- `clipper_fcpxml.ts` handles the common single-cam, camera-audio case. Dual-cam
  and lav-routed FCPXML are GUI-only; if the user needs those, point them to the
  `/clipper` web tool.
- If the user only wants one deliverable, skip the other command.

### 5. Reveal + report

```bash
open "$OUT"
```

Report the final duration, how much you cut, and where the two files are. Keep it
short.

## Notes

- Accepted inputs: mp4/mov/webm/mkv/avi/m4v; local audio requires the supported
  separate-lav/isolated-stereo path above. Unsupported local input fails closed.
- Prerequisites: Sniper's own tools, `.venv` and the local Whisper model, all put
  in place by the installer. When missing, run `../install/doctor.command` (Claude Code's
  `/setup` does the same) and explain its report; the repair is `install/install.command`
  (the operator closes this window first).
- Use subscription-backed agent reasoning; no API/credit fallback by default.
