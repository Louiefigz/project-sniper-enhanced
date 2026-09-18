# 🎛️ PRODUCER — Operator's Manual

> **Status:** operator guide for the current compatibility pipeline, not a
> complete-product qualification claim. P7/P8 remain blocked; use the
> [short/long executable matrix](command-driven-editing/12_SHORT_LONG_EXECUTABLE_MATRIX.md)
> for released, compatibility, unqualified, and unsupported boundaries.

How to talk to the AI video editor. PRODUCER turns raw footage (one file or a
folder of them) — or a finished long-form you want shorts pulled from — into
**social-ready shorts** and **long-form cuts**. You pick how much treatment:
a **clean cut** (just the edit — take selection, silences, outtakes) or a fully
**produced** version (motion, graphics, transitions, kinetic captions on top).
Either way it cuts dead air, applies bounded vertical framing for shorts,
burns/writes captions, audits its own work, and takes your notes like a human
editor. Vertical framing uses a detected face when available, then center-crop
or blur-pad fallback; it is not continuous subject tracking.

**The shape of every job** (canonical: [`PIPELINE.md`](../PIPELINE.md)): you
**give the Producer skill footage and a brief** (or use the optional intent
card) — a **Short** in
one of the studied styles (**Restrained light · Punch produced · Slideware involved**)
or a **Long** with a **checklist of exactly the items you want** (full workflow
or just some of: motion, graphics, transitions, captions, b-roll, credibility,
music, dialogue cleanup). Use **HyperFrames Studio** for graphics review and
adjustment. The dependable handoff is the
approved exact `final.mp4`, optionally published as one flat Palmier mirror
clip. The native editable/hybrid candidate protocol is wired locally but
remains isolated and P5-blocked pending representative connected short/long
qualification; it is not the default delivery. See the status table in
`PIPELINE.md`.

> The pipeline: [`PIPELINE.md`](../PIPELINE.md) ·
> Full architecture: [`PRODUCER_PLAN.md`](PRODUCER_PLAN.md) ·
> Edge cases: [`PRODUCER_EDGE_CASES.md`](PRODUCER_EDGE_CASES.md)

---

## How to start a session

Open Codex or Claude Code in `PROJECT_SNIPER/` and just talk. The `producer` skill picks
up requests like the examples below — no special syntax, folders and files are
first-class.

```
"Produce a short from ~/footage/tuesday — b-roll in ~/broll, energetic music, ~30s."
```

## What you can ask for

Three choices frame every job — an **input**, an **output**, and a **treatment
level**. Say it in plain language; I infer the rest and ask only when it's
genuinely unclear.

**First, choose the edit itself:** “segment this,” “clean this up” (with or
without segmentation), or “assemble standalone Shorts.” If that choice is
unclear, the editor asks once and keeps the answer for revisions. See
[edit scope and examples](SHORTS_JOURNEY_SELECTION_PLAYBOOK.md#establish-the-edit-the-user-wants).
A podcast excerpt can preserve the original exchange while using a good opening
and natural ending. Nonlinear payoff-first assembly applies when that kind of
Short is wanted. Choose graphics and visual treatment separately.

**What you give me (input):** raw footage — one file or a folder of them — OR a
finished long-form you want shorts pulled out of.

**What you want back (output):**
- a **long-form** cut (16:9 + chapters + captions sidecar)
- a **short**, or several — 9:16 vertical
- **clips from a long recording** — I extract the requested sections, and can
  then turn any of them (or the best N) into finished shorts

**How much treatment (the key choice):**
- **Clean cut** — I only fix the edit: pick the right takes, remove the silences
  and dead air, drop the outtakes and false starts. You still get the format
  basics (vertical reframe + captions on shorts, a captions sidecar on
  long-form). No graphics, no zoom motion, no transitions — fast and cheap. Say
  *"just clean this up"* / *"only remove the silences and bad takes"*.
- **Produced** — the clean cut plus everything that makes it engaging: motion
  (the frame stays alive with subtle pushes), graphics (whiteboards, callouts,
  receipts), transitions, kinetic captions. The default when you want it to pop.
  *(Honest: the produced motion is a real step up from a static cut but not yet
  pro-editor grade — I'll tell you where it stands.)*
- **In between** — *"clean cut but keep it alive"*: the cut plus the subtle
  motion layer, no graphics.

### Say something like

| You want | Say something like | You get |
|---|---|---|
| Clean up a long-form | "Clean cut this session — just takes and silences" | 16:9 master + chapters + .srt, no graphics |
| Produce a long-form | "Cut and produce the long-form version of this" | 16:9 master + motion + graphics + chapters/.srt |
| A short from clips | "Produce a short from these two clips" | 9:16 MP4 ×2 (with/without music), cover, audit |
| A clean short | "Just a clean vertical cut of this moment, no graphics" | 9:16 MP4 + captions, no graphics/motion |
| Best N from a recording | "Pull the 3 best shorts from this recording" | Ranked source moments → selected cuts → produced shorts |
| Rough clips only | "Break this 90-min recording into segments" | Per-topic/guest clips (zip) |
| Iterate | "Hook card's too wordy. Let 0:31 breathe." | Plan v2 → re-render → what-changed diff |

Useful modifiers, all optional:
- **Treatment**: "just clean it up" (edit only) vs "produce it" (full stack —
  the default). "Keep it alive but no graphics" for the in-between.
- **Duration**: "target ~30s" / "keep it under 60s" / "up to 90s". Choose the
  shortest complete explanation within the current brief; Aaron's standing
  produced-clip allowance is up to 90s, not an automatic target.
- **Music vibe**: "energetic", "chill", "no music" — or say nothing and I'll
  recommend one from the content's mood. Music is off unless you approve it;
  multiple mix variants render only when requested.
- **Platforms**: "TikTok only" (unlocks a louder audio master) — default is
  safe-for-all-three (TikTok/Reels/Shorts).
- **Plan review**: "show me the plan first" (default) or "just render it"
  (audits still run and I'll flag anything ugly).
- **Hook**: "use the hook about the $12k ad spend" — otherwise I choose a strong,
  truthful opening within the agreed edit. Standalone story selection works
  back from the payoff; a fixed excerpt's framing stays faithful to that section.
- **Reference video**: ask the editor to study one for measured pacing/layout
  guidance. Treat the result as reference-inspired; verified mimic remains P6
  **0/7**, so an exact style match or complete replication is not promised.

## Long-form to finished shorts

This section covers standalone Short assembly. For segmentation or cleanup of
requested sections, use the agreed edit scope and preserve the conversation;
the source-wide rebuilding method below is not automatic.

Use Producer for the whole repurposing job: source review → candidate selection
→ precise cut → vertical visual storytelling → Studio review and final export.
This applies to a finished long video as well as an unedited recording. It is
an agent-directed workflow using existing tools; the Segmenter API returns topic
boundaries, not ranked short candidates, and no dedicated batch-ranking endpoint
is claimed. Follow the selected execution route's current capabilities and gates.

### Find a moment that works for a new viewer

For conversations, work sessions and journey updates, use the
[journey selection playbook](SHORTS_JOURNEY_SELECTION_PLAYBOOK.md) before ranking.
Select the complete assembled message across the recording: its goal, context,
reasoning and payoff can come from different timestamps. A specific current
experiment and its reason can resolve a journey episode before results exist.
Plan supporting examples and temporary presenter/detail layouts at the moments
where seeing the board, relationship or evidence improves understanding.

Reuse the admitted source manifest and its matching word-timed transcript, or
ingest/transcribe locally once. Read the complete source before selecting; for
sources larger than context, keep a timestamped coverage map across overlapping
sections and compare the candidates globally. A segment boundary must not hide
the setup or payoff in its neighbor. Inspect the complete shortlisted moments
and their nearby context in the actual footage before committing to a cut.

Compare candidates against the requested audience and outcome, using the existing
brief when available. A useful shortlist records the following in the existing
plan/review notes; it does not require another report or a new plan schema:

| Decision | Evidence to retain |
| --- | --- |
| Source and proposed cut | Actual source IDs and word-aligned ranges; exact opening and payoff quotes; estimated duration after trimming |
| Cold-viewer clarity | One clear viewer question and the minimum setup needed; resolve references such as "this" or "as I said" |
| Hook and payoff | Why the opening earns attention and which retained words/actions answer its promise |
| Evidence and usefulness | A specific explanation, example, demonstration or actionable takeaway supported by the source |
| Visual feasibility | What can be shown in portrait, including the speaker, screen content and existing baked text |
| Selection | Relative rank, a concrete reason, unresolved uncertainty and any overlapping candidate it replaces |

**Aaron chooses the moment before production.** Present the ranked shortlist
with source timestamps, watchable source previews, hook/payoff excerpts,
estimated edited length, selection rationale and a brief visual-storytelling
idea for each. Recommend the strongest option, but wait for his choice before
trimming or producing it. Use seekable source playback where available; create
lightweight review excerpts only when needed for viewing, not fully treated
candidate renders. Do not claim a timestamp or transcript is a playable preview.
An already selected moment or an explicit instruction to choose and proceed
satisfies this step; do not ask him to choose again. This is Aaron's default,
not an extra approval requirement for unrelated users or delegated selections.

Prefer a small, meaningful comparison over a fixed candidate quota. These are
editorial judgments, not virality scores or measured audience-retention forecasts.
A high-energy sentence with no answer is insufficient. Deduplicate both overlapping
footage and repeated ideas before choosing multiple shorts. Add only the setup
needed to make the winner self-contained; reject it if that setup consumes the
requested duration. Preserve qualifications and causal order when combining
noncontiguous passages. Do not invent a spoken hook, result or CTA absent from
the source. If fewer good moments exist than requested, report that honestly.

### Trim from the source without a chain of intermediate videos

Keep selection as source ranges until a candidate is chosen. Producer can build
its `cutTrack` directly against the original admitted media and transcript;
Segmenter's padded/keyframe-snapped exports are for requested rough clips, not
mandatory inputs to Producer. Avoid retranscribing those exports or rendering
every candidate. Source admission and required full-source checks still apply.

Use the existing pause/retake tools and current cut gates. For already edited
footage, treat scanner output as proposals: repeated lines may be a callback,
comparison or intended emphasis. Review removals before folding them into the
cut; check the assembled speech again because automatic lead-fragment removal
can change the opening. Start from natural speech speed for a finished source;
do not force 1.1× or squeeze an entire lesson into the duration. Explicit speed
requests must fit the selected route's supported profile.

Copy real word boundaries, preserve breaths that carry meaning, and end after
the promised answer. Derive output word timing and duration from the actual cut
map. Optional context splices must preserve the claim and speaker attribution.
Do not set the longform-only `excerpt` flag to work around a short-mode gate.
Existing controller-owned cut stages retain their exact writable fields and
command restrictions; defer visual work until the cut is ready for that stage.

### Apply the student-kit storytelling method to that cut

Use the canonical Producer **Visual storytelling** instructions already adopted
from `short-form-edit`, `video-storytelling` and `hyperframes-video-beats`. In the
existing scene notes, connect the opening promise → visible evidence or developing
explanation → source-supported payoff. Choose visuals for what they explain:
an action and result, an evolving diagram, a comparison or a precise highlight.
Time changes to the kept speech, allow reading time, and inspect adjacent shots
for repetition. Preserve the user's treatment, brand and presenter preferences.

Compose for portrait from the beginning. Inspect the actual crop throughout the
kept footage; if a screen demonstration or meaningful gesture cannot survive it,
use an admitted readable layout or choose another candidate. Do not label a
cropped landscape card vertical-ready. Existing baked captions/graphics cannot
be made editable by cropping: reuse a clean source when already available, or
design around the actual pixels without hiding evidence or stacking duplicate
text. Captions follow the kept word timings and the requested caption policy.

Account for music/effects already mixed into a finished source. Adding a second
bed does not replace them, and a "no added music" export is not dialogue-only.
Use authorized clean stems when available; otherwise disclose the actual mix.
Keep native editable visual layers when that destination is requested, using
current installed HyperFrames tooling. The kit's old scaffold, runtime and draft
landscape cards are not prerequisites or automatically admitted assets.

### Complete the short and verify the result

For a production request, continue through the selected cut/treatment workflow
under the user's existing authorization after their requested moment selection.
Honor Aaron's selection preference above, a requested shortlist-only or
plan-first stopping point, and any existing explicit review gates. Shortlist
notes add no further approval round after the moment is selected. Apply scoped
revisions to the selected short, preserving the long-form master and unrelated
work.

View and listen to the entire actual output as a cold viewer: hook clarity,
complete payoff, natural joins, caption accuracy/readability, presenter/action
framing, purposeful graphics, and intelligible audio. Check actual native
playback and exported media where native delivery is requested. Retain the
source ranges and report measured discovery, cut, visual, review/revision and
export time, separating reused preparation. Do not report full-workflow quality,
turnaround or audience performance from a prompt update or renderer-only test.

## What to give me

```
your-project-folder/
  clip1.mp4  clip2.mov ...     # raw footage — 1..N files, any mix of lengths
  broll/                        # optional — see taxonomy below
  music/                        # optional — tracks sorted by vibe
```

- **Raw footage**: anything ffmpeg reads (mp4/mov/mkv…). Mixed resolutions and
  frame rates are fine — everything is normalized at render.
- **B-roll folder** (optional): subfolders help me and you, but nothing breaks
  without them — every clip gets a vision description at catalog time, so
  retrieval never depends on file names.
  `broll/screens/` (real screen recordings — the only source for readable UI text),
  `people/`, `environments/`, `metaphors/`, `product/`, `generated/` (auto-managed).
  Name files descriptively when convenient: `hands-typing-laptop-dark-desk.mp4`.
- **Music folder** (optional): `music/<vibe>/track.mp3` (e.g. `music/energetic/`).
  Tracks you don't have rights to will be flagged, not policed.
- No b-roll or music? Say "generate b-roll" / "generate a track" and I'll use
  Higgsfield (costs credits), saving results into your folders for reuse.

## What you get back

Every PRODUCE SHORT run outputs, next to your footage:
```
out/<name>/
  short_with_music.mp4      # 1080x1920, captions burned, hook card, -14 LUFS
  short_no_music.mp4        # same cut, dialogue-only mix
  cover.png                 # strong first frame (hook card visible)
  edit_plan.json            # the whole edit as data — the project file
  audit_report.md           # what the QC pass checked and found
```
Long-form runs swap in a 16:9 master + `chapters.txt` + `.srt`. The `edit_plan.json`
and `audit_report.md` come out of every run.

**Clean cut vs produced.** A clean cut ships the same files with the engaging
layers off — the tightened cut, bounded vertical framing, and captions, but no
graphics, motion, or transitions. A **produced** run adds them: on a produced
long-form the frame stays alive throughout — a subtle, eased push drifts under
the talking so the picture never sits frozen between beats, and tighter
punch-ins land smoothly, on the face, on the lines that carry the point. (That
produced motion is measurably better than a static cut but not yet pro-editor
grade — I'll say so.)

## Giving feedback (the part that makes it an editor)

Reference the **output video's timestamps** — I map them back to the source:
- "The b-roll at 0:14 doesn't fit — use something with a laptop."
- "Hook card should say 'He spends $12k/mo. Zero sales.'"
- "Too choppy between 0:20–0:28, let it breathe."
- "Swap the music, something calmer. Actually render me both vibes."

Each round produces a new plan version (v2, v3…) — every revision is diffable
and reversible. After 2 automatic revision rounds I'll stop and ask rather than
loop.

## House rules (what I will and won't do)

- Hook cards: white container, black text, **≤2 lines, ≤8 words**, on screen
  from frame 1 for ~3s. Copy is grounded in your RAG hook library, never
  improvised.
- B-roll is purposeful only — it covers a cut or illustrates something named.
  If nothing in your pool fits, the slot stays on you talking; I'll say so.
  I don't fuzzy-match.
- Captions come from the transcript, word-timed — I can't accidentally
  paraphrase you.
- Short pacing follows the selected content and brief. Raw-footage presets can
  tighten aggressively; finished-source repurposing preserves natural speed and
  meaningful pauses unless a supported, deliberate change improves the cut.
- If the footage can't cash the hook a card promises, the audit rejects the
  card — no clickbait the clip doesn't deliver.

## What it costs

| Operation | Spending policy |
|---|---|
| **Transcription/rendering** | Installed local Whisper and local media tools by default; no paid ASR fallback. Verify word timing and audiovisual output. |
| **Reasoning/visual review** | Subscription-backed agent tools; CLI paths require qualified subscription admission. Unknown auth or exhausted usage stops the invocation. |
| **Optional paid services** | Separate explicit approval required for paid ASR, generated media, API calls or credits. Neither saved keys nor a CLI login authorizes spending; subscription overage is not proven absent by an auth check. |

## Requirements

- ffmpeg on PATH (already required by SNIPER)
- Installed local Whisper runtime/model for new transcription; no Deepgram key
  is required by the default path. Ask before downloading missing dependencies.
- Python venv: `.venv/bin/pip install -r requirements.txt` (adds OpenCV for
  face-aware cropping)
- No `ANTHROPIC_API_KEY` needed in skill mode

## UI or no UI?

- **Primary: Codex/Claude skill → local CLIs → HyperFrames Studio.** Follow
  [the Studio lane](STUDIO_REVIEW_LANE.md); no custom web UI is required. Scoped
  changes preserve unrelated edits and rerun the applicable review/QC walls.
- **Optional `/producer` compatibility editor** — `npm run dev` → localhost:3000/producer.
  The whole loop lives in the UI: pick footage → **intent card** (Short with a
  style · Long with the lane checklist) → **Auto-edit** (one click; the brain
  authors `edit_plan.json`, the gates validate, the render chains) → the
  **editor** (script strike-to-cut, timeline drag/trim, graphic placement +
  scaling, Elements/Audio panels, Ask-Claude bar) → **Re-render** (smart
  dispatch by change class). Caption shards and governed scene units can rebuild
  locally; cut/zoom/reframe changes and legacy short-form graphics can still
  require a broader or full rebuild. The executable short/long boundaries are
  in [`12_SHORT_LONG_EXECUTABLE_MATRIX.md`](command-driven-editing/12_SHORT_LONG_EXECUTABLE_MATRIX.md).
  [`HANDOFF.md`](../HANDOFF.md) is a historical 2026-07-10 snapshot, not current
  release evidence.
- **Headless (no UI)**: this skill, conversationally — or run any stage directly:
  `ingest.py` → `plan_lint.py` → `render.py` → `audit/audit_render.py` are
  standalone CLIs; `edit_plan.json` is the hand-editable project file between them.
- **The other tabs** (same `npm run dev`): SEGMENTER, CLIPPER (FCPXML path),
  FRAME.IO REVIEW — independent tools, unchanged by PRODUCER.
