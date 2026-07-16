# 🎛️ PRODUCER — Operator's Manual

How to talk to the AI video editor. PRODUCER turns raw footage (one file or a
folder of them) — or a finished long-form you want shorts pulled from — into
**social-ready shorts** and **long-form cuts**. You pick how much treatment:
a **clean cut** (just the edit — take selection, silences, outtakes) or a fully
**produced** version (motion, graphics, transitions, kinetic captions on top).
Either way it cuts dead air, reframes vertical for shorts, burns/writes captions,
audits its own work, and takes your notes like a human editor.

**The shape of every job** (canonical: [`PIPELINE.md`](../PIPELINE.md)): you
**upload footage into PRODUCER**, pick your intent on the card — a **Short** in
one of the studied styles (**Caleb light · Jaden produced · Angela involved**)
or a **Long** with a **checklist of exactly the items you want** (full workflow
or just some of: motion, graphics, transitions, captions, b-roll, credibility,
music, dialogue cleanup) — and the finished edit's destination is **Palmier
Pro**, the NLE that owns the final timeline/color/audio/export. (The built-in
renderer producing `final.mp4` remains the default path; the automated push is
`scripts/producer/palmier/push.py`, verified e2e — status table in PIPELINE.md.)

> The pipeline: [`PIPELINE.md`](../PIPELINE.md) ·
> Full architecture: [`PRODUCER_PLAN.md`](PRODUCER_PLAN.md) ·
> Edge cases: [`PRODUCER_EDGE_CASES.md`](PRODUCER_EDGE_CASES.md)

---

## How to start a session

Open Claude Code in `PROJECT_SNIPER/` and just talk. The `producer` skill picks
up requests like the examples below — no special syntax, folders and files are
first-class.

```
"Produce a short from ~/footage/tuesday — b-roll in ~/broll, energetic music, ~30s."
```

## What you can ask for

Three choices frame every job — an **input**, an **output**, and a **treatment
level**. Say it in plain language; I infer the rest and ask only when it's
genuinely unclear.

**What you give me (input):** raw footage — one file or a folder of them — OR a
finished long-form you want shorts pulled out of.

**What you want back (output):**
- a **long-form** cut (16:9 + chapters + captions sidecar)
- a **short**, or several — 9:16 vertical
- **clips from a long recording** — I segment it into standalone pieces, and can
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
| Best N from a recording | "Pull the 3 best shorts from this recording" | Segments → ranked peaks → 3 produced shorts |
| Rough clips only | "Break this 90-min recording into segments" | Per-topic/guest clips (zip) |
| Iterate | "Hook card's too wordy. Let 0:31 breathe." | Plan v2 → re-render → what-changed diff |

Useful modifiers, all optional:
- **Treatment**: "just clean it up" (edit only) vs "produce it" (full stack —
  the default). "Keep it alive but no graphics" for the in-between.
- **Duration**: "target ~30s" / "keep it under 60s" (default 15–40s for shorts)
- **Music vibe**: "energetic", "chill", "no music" — or say nothing and I'll
  propose one from the content's mood. Both variants render regardless.
- **Platforms**: "TikTok only" (unlocks a louder audio master) — default is
  safe-for-all-three (TikTok/Reels/Shorts).
- **Plan review**: "show me the plan first" (default) or "just render it"
  (audits still run and I'll flag anything ugly).
- **Hook**: "use the hook about the $12k ad spend" — otherwise I derive it from
  the footage's strongest payoff, grounded in the Hormozi 121 swipe file.

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
layers off — the tightened cut, vertical reframe, and captions, but no graphics,
motion, or transitions. A **produced** run adds them: on a produced long-form the
frame stays alive throughout — a subtle, eased push drifts under the talking so
the picture never sits frozen between beats, and tighter punch-ins land smoothly,
on the face, on the lines that carry the point. (That produced motion is
measurably better than a static cut but not yet pro-editor grade — I'll say so.)

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
- Long-form gets breathing room (pauses kept, natural speed); shorts get the
  aggressive treatment (near-zero dead air, 1.1×). Same brand, different gears.
- If the footage can't cash the hook a card promises, the audit rejects the
  card — no clickbait the clip doesn't deliver.

## What it costs

| Mode | Cost |
|---|---|
| **Skill (this manual)** | ~$0.26 per hour of raw footage (Deepgram). All reasoning, vision, rendering: $0. Higgsfield only when generating. |
| **Live app** (Phase 4, later) | Same Deepgram + Anthropic API per plan/audit call (~$0.15–0.50/short) + Higgsfield Cloud API. |

## Requirements

- ffmpeg on PATH (already required by SNIPER)
- `DEEPGRAM_API_KEY` in `.env.local` (already set up for SNIPER)
- Python venv: `.venv/bin/pip install -r requirements.txt` (adds OpenCV for
  face-aware cropping)
- No `ANTHROPIC_API_KEY` needed in skill mode

## UI or no UI?

- **The `/producer` editor (SHIPPED)** — `npm run dev` → localhost:3000/producer.
  The whole loop lives in the UI: pick footage → **intent card** (Short with a
  style · Long with the lane checklist) → **Auto-edit** (one click; the brain
  authors `edit_plan.json`, the gates validate, the render chains) → the
  **editor** (script strike-to-cut, timeline drag/trim, graphic placement +
  scaling, Elements/Audio panels, Ask-Claude bar) → **Re-render** (smart
  dispatch: graphics-only ≈18s · audio-only ≈12s · cut edits ≈3min full rebuild
  with automatic window refit). Verified loop + gotchas: [`HANDOFF.md`](../HANDOFF.md).
- **Headless (no UI)**: this skill, conversationally — or run any stage directly:
  `ingest.py` → `plan_lint.py` → `render.py` → `audit/audit_render.py` are
  standalone CLIs; `edit_plan.json` is the hand-editable project file between them.
- **The other tabs** (same `npm run dev`): SEGMENTER, CLIPPER (FCPXML path),
  FRAME.IO REVIEW — independent tools, unchanged by PRODUCER.
