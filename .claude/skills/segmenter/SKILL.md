---
name: segmenter
description: >
  SEGMENTER for PROJECT_SNIPER — rough-cut ONE long recording into many separate
  MP4 clips for downstream trimming, driven from Claude Code (no web GUI, no dev
  server). You transcribe the footage, decide the segment boundaries yourself
  (you are the brain), and a deterministic ffmpeg pipeline stream-copies each
  segment to its own MP4 in an output folder. Trigger on: "rough-cut this
  recording", "break this long footage into segments/clips", "segment this
  video", "split this recording into topic clips", "chop this interview into
  pieces". Do NOT trigger for producing ONE edited/polished video (that is the
  `producer` skill), for word-level filler removal of a single clip (that is the
  `clipper` skill), or for building/modifying the SNIPER app itself.
---

# SEGMENTER — skill v1

You are the **brain** of SEGMENTER. Long recording in → many rough clips out.
You read the transcript and decide where each segment begins and ends; a
deterministic ffmpeg step (`scripts/segmenter/export_mp4.py`) does the cutting. You never
run ffmpeg by hand for the cut.

**This is NOT the producer.** SEGMENTER produces *many rough clips* (one MP4 per
segment, ~5s padding, stream-copied — meant to be trimmed later in an NLE). The
`producer` skill produces *one polished, edited video*. If the user wants a
single finished cut, hand off to `producer`.

## Where output goes

Everything lands in a per-recording folder under the user's home:

```
~/ProjectSniper/<slug>/segmenter/
  transcript.json     # the ASR result you worked from
  segments.json       # your segment decisions (the cut list)
  clips/              # one MP4 per segment, numbered + titled
  clips.zip           # the same clips bundled
```

Pick `<slug>` from the input filename + a short descriptor, kebab-case
(e.g. `founder-interview-2026-07-15`). Run all commands from the repo root.

## The pipeline — do these in order

### 1. Set up the project folder

```bash
SLUG="<slug>"; VIDEO="<absolute path to the recording>"
OUT="$HOME/ProjectSniper/$SLUG/segmenter"; mkdir -p "$OUT/clips"
```

### 2. Transcribe locally (no paid fallback)

Use the installed local Whisper runtime/model. A saved key, provider environment
variable, or missing local model is not permission to use a paid service. Do not
source credential files for local transcription.

```bash
.venv/bin/python3 scripts/transcribe.py "$VIDEO" --provider local-whisper > "$OUT/transcript.raw.jsonl" 2> "$OUT/transcribe.log"
tail -n 1 "$OUT/transcript.raw.jsonl" > "$OUT/transcript.json"
```

The final stdout line is the result: `{"transcript": [ {start,end,text,words:[{word,start,end}]}, ... ]}`.
If that last line has an `"error"` key:
- Missing `whisper-cli` or model → report the dependency; ask before downloading
  or installing. Local transcription does not provide speaker diarization;
  inspect word timing and uncertain speech instead of assuming paid-provider parity.
- Otherwise report the error; do not fabricate a transcript or switch providers.

Only a separate, explicit user authorization for this paid invocation allows
`--provider deepgram --authorize-paid-asr deepgram` together. Never add those
flags under a subscription/local-only request. Keep the distinct segmenter and
clipper media/diarization responsibilities; no raw video egress.

### 3. Decide the segments (you, the brain)

Read `transcript.json`. Using the **word-level** timings in each utterance's
`words[]`, write `segments.json` — a JSON array in `export_mp4.py`'s shape:

```json
[{ "title": "Short descriptive title", "start": 12.34, "end": 58.90 }, ...]
```

Segmentation doctrine (same as the GUI's segment prompt):

- **Word-level precision.** `start`/`end` are word timestamps copied from
  `words[]`, not utterance rounding. Skip leading/trailing filler by moving the
  boundary to the first/last real word.
- **Cover the whole recording.** Segments are contiguous — each one begins where
  the previous ended; the first starts at ~0. Every moment belongs to exactly one
  segment.
- **Carve filler aggressively into its OWN segments.** Host pump-up ("alright
  let's go"), calling for the next guest, mic checks ("can you hear me"), reading
  prep notes, ad reads, and banter each become their own segment titled
  `Filler – …`. Do not roll filler into an adjacent content segment.
- **Title each segment** by its topic so the clip filenames are self-describing.

If the user gave segmentation instructions (e.g. "one clip per question", "only
the parts about pricing"), follow those over the default coaching-show doctrine.

### 4. Export the clips (deterministic)

`export_mp4.py` takes the cut list **as a string argument** and writes a zip;
unzip it into `clips/`.

```bash
.venv/bin/python3 scripts/segmenter/export_mp4.py "$VIDEO" "$(cat "$OUT/segments.json")" "$OUT/clips.zip"
unzip -o -q "$OUT/clips.zip" -d "$OUT/clips"
```

Each clip is stream-copied (no re-encode) with ~5s pre/post padding, snapped to
the nearest keyframe — so clips include extra handles and adjacent clips may
overlap. **This is intentional**: the output is rough footage for NLE trimming,
not final cuts. Do not try to make the boundaries frame-exact here.

For multicam (B/C-cam + lav tracks, pre-synced), use
`scripts/segmenter/multicam_pipeline.py` instead (`--acam/--bcam/--ccam/--lav1/--lav2
--segments --outdir`); it re-encodes frame-accurate synced cuts. Only reach for
it when the user actually has multiple angles.

### 5. Reveal + report

```bash
open "$OUT"
```

Tell the user how many clips you made, where they are, and one line each on what
they contain. Keep it short.

## Notes

- Accepted inputs: mp4/mov/webm/mkv/avi/m4v (video) or common audio files.
- Prerequisites: ffmpeg, `.venv`, installed local Whisper runtime/model. Use
  `/setup` with the user's installation authorization if anything is missing.
- Use subscription-backed agent reasoning. No paid API or credit fallback is
  authorized by a local transcription or segmentation request.
