# PRODUCER (Part 3) — AI Video Editor Plan

> Status: DRAFT — awaiting operator review. 2026-07-04.
> Name "PRODUCER" is provisional (SEGMENTER → CLIPPER → PRODUCER).

Turn raw footage (1..N files) + a b-roll pool into **social-ready shorts** (TikTok /
Reels / YouTube Shorts) and **long-form cuts**, with an AI editor brain that sees the
whole picture, audits its own work, and takes natural-language feedback like a human
editor. Two operating modes: a **Claude Code skill** ($0 reasoning, MCP-powered) and a
**live Next.js app** (Anthropic API + Higgsfield Cloud API).

---

## 1. What exists today (foundations we build on — not rebuilt)

| Capability | Where | Reused for |
|---|---|---|
| Deepgram nova-3 word-level transcription (+chunking, offsets) | `scripts/transcribe.py`, `scripts/clipper/clipper_transcribe.py` | All source + speechful b-roll ingestion |
| Word-level KEEP/REMOVE/TRIM edit decisions (forced tool-call, HOOK→MEAT→PAYOFF) | CLIPPER `clip-preview` route + `src/prompts/clipper/default-edit.ts` | Shorts moment selection + dead-air/filler decisions |
| Keep-ranges from word decisions (`computeFinalClips()`) | `src/lib/clipper/export.ts` | Input shape for the new renderer |
| Frame-accurate re-encode / smartcut / concat / mux / seam validation | `scripts/segmenter/multicam_pipeline.py` | Render toolbox patterns |
| Frame extraction + pHash dedup + Claude vision review | `scripts/frameio/` | B-roll cataloging AND post-render QC audit |
| SSE job streaming, venv-aware Python spawn, native file pick | `api/_lib/`, routes | New PRODUCER routes |
| Diarization + stereo isolation + mic-bleed handling | `clipper_transcribe.py`, prompts | Multi-speaker call-in footage |

**Invariants respected:** SEGMENTER's stream-copy export stays untouched (new renderer
is a NEW script package). Model pins stay. Temp-file ownership pattern followed.
Only audio + transcript text + still frames leave the machine (PRODUCER adds
title-card/QC frames to the existing FRAME.IO REVIEW exception — same still-image class).

---

## 2. Core design decision: everything flows through `edit_plan.json`

The single most important architectural choice. The **brain** (API route or Claude Code
skill) never touches ffmpeg. The **renderer** (deterministic Python) never makes
creative choices. Between them sits one declarative, versioned artifact:

```
ingest → asset_manifest.json → BRAIN → edit_plan.json → plan_lint.py (gate)
      → RENDERER → output.mp4 + timeline_map.json → AUDITS → feedback → edit_plan v2 → …
```

Why this shape:
- **Dual-mode parity for free.** Skill mode and live mode both emit the same JSON; one
  renderer, one lint gate, one audit stack serves both. (Mirrors the repo's
  skills-parity pattern: skills import prod logic + runnable gates.)
- **Feedback = a JSON diff.** "Make the hook punchier, drop the b-roll at 0:14" becomes
  a v2 plan; re-render; diff is auditable. Revisions are cheap and traceable.
- **LLM identifier contract enforced** (the identifier-contract
  rule): the brain may only reference `sourceId`s, `assetId`s and
  timestamps that exist in the manifest; `plan_lint.py` validates every reference and
  rejects the plan (retry with errors) — the LLM never invents a pipeline identifier.
- **Reproducible.** Same plan + same assets = same output. Version-control the plans.

### 2.1 `asset_manifest.json` (ingest output)

```jsonc
{
  "sources": [                       // raw footage, 1..N pieces
    { "id": "raw-1", "path": "...", "duration": 1841.2, "fps": 29.97,
      "resolution": [3840, 2160], "audio": {"channels": 2, "sampleRate": 48000},
      "transcriptPath": "raw-1.transcript.json",     // Deepgram, word-level, diarized
      "role": "primary" }
  ],
  "broll": [                         // folder-scanned + Higgsfield-generated
    { "id": "broll-3", "path": "...", "duration": 8.4, "orientation": "landscape",
      "kind": "video|image",
      "description": "hands typing on laptop, dark desk, blue light",   // Claude vision
      "descriptionSource": "vision|generation-prompt|transcript",
      "hasSpeech": false, "hasBurnedText": false }
  ],
  "music": [
    { "id": "music-7", "path": "...", "duration": 95.0, "vibe": ["energetic","minimal"],
      "bpm": 112, "source": "library|higgsfield" }
  ]
}
```

- B-roll cataloging: `ffprobe` metadata + FRAME.IO REVIEW-style frame sampling → Claude
  vision one-line descriptions, **cached** inside the folder (`broll/broll_catalog.json`,
  keyed by path+mtime) so re-runs are free. Speechful b-roll also gets a transcript.
- Music library: folder convention `music/<vibe>/track.mp3` and/or a `music.json`
  sidecar with vibe tags + BPM (ffprobe/aubio-estimated, operator-editable).

### 2.2 `edit_plan.json` (brain output — the EDL)

```jsonc
{
  "planVersion": 1,
  "target": { "mode": "short",            // "short" | "longform"
              "treatment": "produced",    // "clean-cut" | "produced" (default "produced")
              "durationTargetS": 35, "platforms": ["tiktok","reels","shorts"] },
  "cutTrack": [                            // multi-source, ordered output timeline
    { "sourceId": "raw-2", "start": 812.40, "end": 818.92, "speed": 1.1,
      "protectedPauses": [[815.20, 816.10]],          // brain-marked emphasis beats
      "rationale": "hook: caller states the $40k/mo problem" }
  ],
  "cutDecisions": {                        // required before visual planning
    "schemaVersion": 1,
    "removals": [
      { "sourceId": "raw-2", "start": 818.92, "end": 820.40,
        "kind": "false_start", "rationale": "Remove the abandoned first take.",
        "evidence": { "beforeWord": "problem", "afterWord": "Here",
                      "removedText": "um let me restart" } }
    ]
  },
  "reframe": { "strategy": "face",         // "face" | "center" | "blurpad" | "none"(longform)
               "overrides": [ { "outStart": 0, "outEnd": 8.2, "cropCenterX": 412 } ] },
  "titleCards": [ { "outStart": 0.0, "outEnd": 2.5, "text": "He spends $12k/mo on ads. Zero sales.",
                    "style": "hook", "position": "upper-safe" } ],
  "captions": { "burn": true, "style": "karaoke", "emphasisWords": ["zero","$12k"] },
  "brollTrack": [ { "outStart": 9.0, "outEnd": 10.8, "assetId": "broll-3",
                    "reason": "covers jump cut; illustrates 'cold outreach'" } ],
  "music": { "enabled": true, "vibe": ["energetic","minimal"], "assetId": "music-7",
             "variants": ["with", "without"] },
  "ending": { "loopStyle": "narrative+visual", "ctaCaption": "Full breakdown on the channel." },
  "chapters": null                          // longform mode: [{outStart, title}]
}
```

Key contracts:
- **Cuts are approved before retention treatment.** The controller runs a
  dedicated cut-only author process, requires exact transcript evidence for
  every kept range and removal, and persists the successful
  `transcript_cut_contract.py --previsual` receipt. It publishes the approved
  cut to Palmier before starting a separate visual-author process. The final
  transcript-cut gate permits new treatment lanes only when manifest,
  transcript, cut-track, and cut-decision digests still match the approval;
  prompt compliance
  alone cannot bypass this state transition.
- **`target.treatment` picks the engagement stack** (`"clean-cut"` | `"produced"`,
  default `"produced"`). `clean-cut` = editorial ONLY (take/retake selection +
  silence/pause tightening + outtake/false-start removal) plus the mode's base
  reframe + basic captions; the brain leaves `graphicsTrack`/`punchIns`/
  `transitions`/`treatmentMap` EMPTY (render.py skips empty tracks, so no code
  branch is needed — no graphics, motion zooms, seam covers, or hyperframes
  renders). `produced` = the clean cut PLUS the full engaging stack. A middle
  ground (subtle aliveness motion, no graphics) is `produced`-shaped with only the
  `punchIns` aliveness ramps populated. Flags catalog: `producer_config.py`
  TREATMENTS; the skill branches on this field.
- **Caption text is NOT brain-authored.** Captions derive deterministically from the
  kept words + timeline map (compiler-generated ASS). The brain only picks style +
  emphasis words. No transcript divergence possible.
- **All source times validated** against transcripts/durations; all `assetId`s must
  resolve; title-card text validated for length/lines/safe-zone fit. Lint rejects, brain retries.
- `outStart`/`outEnd` for overlays are in **output timeline**; `cutTrack` is in
  **source timelines**. The compiler owns the mapping (see §4.1).

**The zoom / motion track (`punchIns`)** — a top-level section rendered by
`punch_in.py` (NOT part of `graphicsTrack`; zooms are cut treatments). Long-form
runs it as TWO layers; the entry shapes:

```jsonc
"punchIns": [                              // the ZOOM track (punch_in.py)
  { "outStart": 4.1, "outEnd": 5.7, "zoom": 1.21,
    "centerX": 0.52, "centerY": 0.34 },    // static PUNCH — hard step; legal only ON a cut (G6)
  { "outStart": 22.0, "outEnd": 25.4, "zoom": 1.21, "attackS": 0.5,
    "centerX": 0.52, "centerY": 0.34 },    // eased PUSH — smoothstep 1.0→zoom over attackS, then hold (mid-shot, G6)
  { "outStart": 25.4, "outEnd": 33.0, "role": "aliveness",
    "ramp": { "direction": "in", "ratePctPerS": 0.8 }, "ease": "smooth",
    "centerX": 0.52, "centerY": 0.34 }     // ALIVENESS creep — eased ramp under a talking stretch (longform; G1/G2)
]
```

- **The zoom track is TWO layers (long-form).** `punchIns` carries (1) sparse
  **semantic** zooms that land on meaning — static punches, eased pushes, in→out
  brackets (`bracket:true, holdS`, ≤3/video), topic-boundary punch-outs — AND
  (2) a continuous **aliveness creep** (`role:"aliveness"`) that keeps the frame
  moving under every talking stretch so it never freezes (`MOTION_GRAMMAR_STUDY.md`
  G1/G2). A punch ON a cut stays a hard STEP; a mid-shot punch carries `attackS`
  to ease in (smoothstep→hold, G6). Every zoom recomposes toward the face
  (`centerX`/`centerY` from `faceBBoxNorm`) and ramps carry `ease:"smooth"` (G4).
  `role:"aliveness"` windows are EXEMPT from the semantic zoom cadence cap
  (`plan_lint_motion._check_zoom_cadence`) — a background layer, not events.
  Bounds in `producer_config.py` MOTION["zoom"]; full grammar in
  `docs/studies/MOTION_GRAMMAR_STUDY.md`.

---

## 3. The Brain — dual-mode design

### 3.1 Shared substrate (both modes)
- **Prompts as versioned files** — `src/prompts/producer/` (TS, live) mirrored by the
  skill's markdown; single source of truth for editorial doctrine (below).
- **`scripts/producer/plan_lint.py`** — runnable gate (exit 1 = plan invalid): identifier
  resolution, timestamp sanity, duration budget, caption pacing ≤ 5–10 words/s,
  title-card fit inside the universal safe box, hook present in first 3s (short mode),
  b-roll insert lengths 1–5s, music variant validity. Deterministic, $0.
- **Editorial doctrine encoded from research** (defaults in `producer_config.py`, ALL
  tunable — research explicitly flags most numbers as practitioner heuristics, so they
  are config, not constants):

| Parameter | SHORT mode | LONGFORM mode | Basis |
|---|---|---|---|
| Silence threshold | cut gaps > 0.7s (0.3s aggressive), pad cuts 0.1–0.3s | trim only stalls > 1.0s; preserve beats | practitioner + Descript |
| Filler (um/uh/false starts) | remove all | clarity test only — keep conversational cadence | Descript |
| Speech speed | global 1.1x (cap 1.25x); up to 1.5x on marked filler stretches | 1.0x — cut time out, don't accelerate | comprehension data |
| Cut/visual-change cadence | every 2–4s (jump cut, punch-in, b-roll, text) | 10–15s early; no pattern > 60–90s; burst every 2–3min | practitioner |
| Hook | on-screen text promise frame 1, spoken hook ≤ 3s | 0–5s grab / 5–15s promise / 15–30s stakes; open loops | TikTok official + practitioner consensus |
| Captions | burn always, karaoke, 5–10 w/s (TikTok official) | sidecar SRT/CC by default; burn optional | 3Play/Verizon studies |
| Music | optional bed, ducked 18–20dB under voice | subtle or none; -20 to -25dB calm | audio engineering |
| Duration | 15–40s default target (≤ 90s cross-platform, ≤ 3min hard) | 15–20min sweet spot; chapters for topic content | Wistia/AIR |
| B-roll | 1–2s inserts; cover jump cuts; illustrate named nouns; never decorative | contextual, front-loaded 10–15s cadence in opening | practitioner |
| Ending | loop (callback + frame match); CTA in caption text, not video | outro allowed; chapters file | YT loop-views |
| Derivation | select self-contained peak moments (rank ~10–20 candidates) | primary asset | analyst consensus |

### 3.2 Skill mode (build FIRST)
`PROJECT_SNIPER/.claude/skills/producer/` — the primary interface for phases 1–2.

**Command surface (natural-language intents, not syntax):**
| Verb | Operator says | Pipeline |
|---|---|---|
| SEGMENT | "break this recording into segments" | long rec → rough clips (exists) |
| CLIP | "tighten this / cut the filler" | word-level cut → MP4 (first brick) or FCPXML |
| PRODUCE SHORT | "make a social-ready short from these clips" | full package, both music variants |
| PRODUCE LONG | "cut the long-form version" | breathing-room edit, 16:9 + chapters + SRT |
| REVISE / AUDIT | "hook card too wordy; let 0:31 breathe" | plan v(n+1) → re-render → audit diff |

Folder inputs are first-class: a directory of raw clips + `broll/` + `music/` is the
standard invocation shape. Plan review before render is optional per run (operator
can let Audit A/B catch issues instead). Skill-mode cost: $0 reasoning/vision;
Deepgram ~$0.26/hr of footage; Higgsfield credits only when generating.
- Claude Code runs ingest scripts, **reads sampled frames directly** (multimodal — it
  can *look* at the footage and b-roll, which one API call cannot), reasons over all
  transcripts, writes `edit_plan.json`, must pass `plan_lint.py`, invokes the renderer,
  runs audits, iterates with the operator conversationally.
- Higgsfield via **MCP** (`generate_image` / `generate_video` / `generate_audio` — music
  generation is MCP-only; the public Cloud API has no music endpoint).
- Cost: $0 reasoning (subscription); Deepgram + Higgsfield credits only.
- Follows the repo's skill pattern (script-director): assess → ask gaps upfront →
  runnable gate → GO → build.

### 3.3 Live mode (build after the pipeline is proven in skill mode)
- New tool page `/producer` + `api/producer/*` routes (ingest, plan, render SSE,
  audit, revise), following CLIPPER's forced-tool-call pattern for plan generation
  (model: `claude-sonnet-4-6` default, same pin discipline as the rest of SNIPER).
- Higgsfield via **official Node SDK** (`higgsfield-js`, `HF_CREDENTIALS`,
  `subscribe()` auto-polling → fits SSE job pattern). Images/video b-roll only; music
  comes from the library folder (skill mode can pre-generate tracks INTO the library —
  that's the bridge).
- UI: manifest review → plan review (EDL visualized on the transcript, CLIPPER-style)
  → render progress → audit report → feedback box → re-render.

**Recommendation: skill-first.** Editorial quality is the risk, not plumbing. The skill
validates the doctrine on real footage for $0 before we invest in UI.

---

## 4. The Renderer — `scripts/producer/` (deterministic Python + ffmpeg)

Package layout (one concern per file, ≤300-line logic files). Brain-invoked
entry-point CLIs and the shared hubs stay at the package root (run by path, so
`sys.path[0]` is the package root); internal stages + libraries live in
subpackages, imported package-qualified (`from motion.punch_in import …`). A
subpackage CLI run standalone self-bootstraps the package root onto `sys.path`;
`render.py` sets `PYTHONPATH` for the stages it spawns as subprocesses.

```
scripts/producer/
  render.py             # orchestrator: stages, SSE JSON status, resume-from-stage
  compile_timeline.py   # hub: edit_plan → concrete render graph + timeline_map.json
  cut_speed.py          # hub: stage 1 per-range extract w/ atempo/setpts → mezzanine
  producer_config.py    # hub: every tunable default from §3.1 + §4.4 (imported everywhere)
  plan_lint.py / plan_lint_motion.py   # the gate (shared with brain, §3.1)
  ingest.py / ingest_probe.py / ingest_scan.py   # asset ingest + ffprobe
  graphics_planner.py   # graphics/zoom PROPOSAL entry (brain-invoked)
  retake_scan.py        # editorial-brain entry (retake + pause detection)
  selftest.py           # aggregate test runner (suite lives under tests/)
  motion/     punch_in, reframe, face_track, baseline_look, transitions, visual_state
  audio/      master, audio_mix, audio_mix_bed, audio_gain
  captions/   captions_ass, captions_minimal, caption_corrections, overlays, longform_outputs, bake_emoji
  planner/    graphics_planner_{boundaries,density,items,longform,receipts,rules,style,zoom},
              motion_triggers, icon_library, free_space[_sample], graphics_anchors
  graphics/   graphics_stage, graphics_render, pip_takeover
  broll/      broll_pool, broll_insert
  audit/      audit_{probe,checks,frames,glitch,render}
  edit/       pause_scan, render_cut, study_edit_diff
  study/      study_* + zoom_{detect,report,scale}   # offline research tooling, off the render path
  tests/      test_*.py + _common.py                 # unittest suite, split by subsystem
```

(The ASS caption builder is `captions/captions_ass.py` — renamed from `captions.py`
so the module name no longer shadows the `captions` package.)

### 4.1 Timeline compiler — the correctness keystone
The hardest problem in the whole build: **word timestamps live in source time; captions,
title cards, b-roll, and feedback live in output time — after cuts AND per-range speed
changes.** `compile_timeline.py` builds a piecewise-linear bidirectional map
(source↔output) covering every kept range with its speed factor, and emits
`timeline_map.json`. Everything downstream uses it:
- ASS captions generated in output time from kept words (karaoke timing survives 1.1x).
- Overlay enable windows in output time.
- Audit findings reported in output time.
- **User feedback given in output time ("at 0:14…") maps BACK to source ranges** so the
  brain revises the right cut. Without this map the feedback loop cannot work.

### 4.2 Staged rendering (not one mega filter graph)
Multicam already taught this lesson: complex filter graphs are fragile. Stages write
high-bitrate mezzanine intermediates (x264 CRF 12) to the work dir; each stage is
resumable and independently verifiable:
1. **Cut+speed** → continuous dialogue base (audio `atempo`, video `setpts`; de-noise
   before speed per research).
2. **Reframe** → 1080×1920 (short) or passthrough 16:9 (longform). Face windows are
   static per shot (no jittery per-frame tracking), from `face_track.py`; center
   fallback; `blurpad` for uncroppable content.
   **Integration contract (shipped 2026-07-04):** `face_track.py` analyzes the
   STAGE-1 MEZZANINE at output-time ranges — crop centers are in mezzanine pixel
   coords, and `windows.json` is self-contained (reframe needs no timeline_map).
   `render.py` must pass the mezzanine, never the raw source. Dependency landmine:
   `opencv-python-headless>=4.8,<5` — the `<5` pin is load-bearing (OpenCV 5.0
   dropped CascadeClassifier + bundled Haar XML; 4.13 keeps Haar + YuNet).
   **Treatment-selection doctrine (operator, 2026-07-04):** the strategy follows
   the CONTENT'S FOCAL SUBJECT, never a fixed default — human-is-subject
   (talking head) → `face`; screen-is-subject (screen-share/livestream, human as
   corner overlay) → `blurpad` (center crop deletes the human — verified on real
   footage); ambiguous → the brain asks the operator. Phase 2+ candidate:
   alternating webcam-punch-in (talking beats) / blurpad screen (demo beats).
3. **Overlays** → b-roll (scaled/cropped to canvas, `overlay enable=between(t,a,b)`,
   dialogue audio continues underneath), title-card PNGs (Pillow: operator's brand
   style — **white rounded container with black bold-sans text**, 72–120px, inside
   safe box; style tokens in `producer_config.py`), burned ASS captions (54–72px,
   ≤2 lines ≤42 chars, baseline ≤ y≈1340, karaoke word highlight).
4. **Audio** → dialogue bus (light denoise/leveler), music bed (`sidechaincompress`
   ducking 18–20dB under voice, rise in gaps), **two-pass loudnorm to −14 LUFS /
   −1.5 dBTP**. Mux **with-music and without-music variants** — video encodes once,
   muxes twice (cheap).
5. **Master** → H.264 High, closed GOP, CABAC, MP4 faststart, CFR, ~12 Mbps@30 /
   18@60; optional TikTok-specific −11 LUFS loud master (TikTok doesn't normalize);
   first-frame cover PNG (title inside safe box — first frame is the de facto
   thumbnail and loop start). Longform: 16:9 master + `chapters.txt` + sidecar `.srt`
   (+ optional FCPXML handoff for NLE finishing, reusing CLIPPER's writer).

### 4.3 Hook cards — placement, duration, copy (operator-specified 2026-07-04)
- **Copy source**: grounded in the packaged Director library (resources/director) — QUEST archetypes
  (`hook_types.py`) for the *kind*, the packaged Director hook library
  (`hooks_catalog.py`, `format_hooks_for_prompt()`) for proven *instances* —
  score-then-select (mirrors the pipeline's existing hook stage). Never improvised
  from nothing (no-surface-branding doctrine).
- **Length rule (hard, lint-enforced)**: ≤ 2 lines, ≤ 8 words total. Research-consistent:
  at TikTok's official 5–10 words/s reading pace, 8 words reads in ~1–1.6s.
- **Placement**: upper third of the universal safe box (y≈250–560), centered on
  visual center x≈495. Captions own the lower band (y≈1150–1340) — no collision by
  construction. White rounded container, black bold-sans text, 72–120px.
- **Duration**: present ON frame 1 (doubles as cover + loop start), hold 2.5–3.0s
  default (research: ≥1s floor, ~2–3s hook convention, 6s hard max), then exit.
  Never re-enters; the spoken content carries from there.
- **Content contract**: the card states the ONE promise of the short (research: one
  promise, no slow build); brain must derive it from the actual footage's payoff —
  a card the clip can't cash is an Audit A rejection.

### 4.4 Silence/dead-air detection
Hybrid: word-timestamp gaps (already have them) cross-checked with ffmpeg
`silencedetect` (catches non-speech noise the transcript can't see). Candidate cuts
respect `protectedPauses` from the brain and mode thresholds from config.

### 4.5 Partial re-render (operator requirement, 2026-07-05)

"Change this one thing" must NOT re-render the whole video. Design:

1. **Content-addressed segment parts.** Each cut-parts/ piece is named by
   `hash(sourceId, start, end, speed, profile)` — plan v(n+1) reuses every
   unchanged part automatically; only edited ranges re-encode. Concat is
   `-c copy` (near-free).
2. **Per-part pipeline order.** Move reframe (and per-zone layout compositing)
   BEFORE concat — cut→reframe→compose per part, then join — so geometry and
   graphics changes also invalidate only their parts.
3. **Overlay/caption/title-only edits** skip stages 1–2 entirely (already true
   via --resume): regenerate ASS/cards (instant) + composite + master.
4. **Long-form master patching (the big win).** A 14-min master re-encode is
   the real cost. Smartcut-style patching — re-encode ONLY the GOPs covering
   changed output ranges, stream-copy everything else, seam-validate — has
   prior art IN THIS REPO (`multicam_pipeline.py` smartcut + validate_seam).
   Audio is always re-mixed full-length (seconds, and loudnorm needs the whole
   program anyway).
5. **`plan_diff.py`** — diff plan vN → vN+1, emit the invalidation report
   (parts to rebuild, stages to re-run, estimated wall time) BEFORE executing,
   so "change the hook card text" shows as ~15s and "recut segment 3" as ~40s
   instead of a full re-render.

Target UX: operator says "swap the b-roll at 2:10 and fix the card typo" →
timeline map resolves the ranges → diff → only those parts + the final
patch/composite re-run.

**Known pitfalls (2026-07-05 review):**
- **Splice points must land on IDR frames** — closed-GOP 2s cadence gives the
  grid; seam-validate every patch (multicam prior art) or patched players glitch.
- **Loudness is a GLOBAL property** — audio is ALWAYS re-mixed + re-normalized
  full-length (seconds of work). Never patch audio locally: loudnorm gain
  differs per program, so local patches create level jumps at seams.
- **Timeline cascade** — an edit at t=10 shifts every output-time window after
  it (captions, graphics, b-roll). plan_diff must re-derive ALL downstream
  windows through the new timeline map, not just the edited part.
- **Cache keys must cover everything that touches pixels** — spec + template
  content + tokens.css + fonts + renderer version. Anything less = stale reuse.
- **Per-section audio adjustments** ride the plan as an `audioGain` track
  ([{outStart, outEnd, dB}]) applied to the dialogue bus BEFORE ducking and
  loudnorm — order matters; loudnorm re-measure keeps program at −14 while
  relative levels shift. (MG-2 build.)
- **Caption corrections** — Deepgram mishears become burned-in misspellings
  (e.g. "Snyperbot" for "Sniper bot"). Plan gains `captions.corrections` {heard→correct}, logged +
  validated; fixes TRANSCRIPTION errors only, never changes what was said.
  (MG-2 build.)

### 4.6 Render spec sheet (from platform research — `producer_config.py`)
- Canvas 1080×1920; **universal safe box: top 250 / bottom 520 / left 60 / right 150**
  (870×1150 usable); compose critical elements to visual center **x≈495** (right-rail
  asymmetry). Bottom margin is the most fragile number → config, re-validated
  against a live overlay checker when campaigns matter.
- Keep file < 287MB (TikTok in-app cap), duration ≤ 90s for cross-platform discovery
  (≤ 3min hard).

---

## 5. Audits + feedback — "an AI editor that checks its own work"

### Audit A — pre-render, on the plan ($0 + one cheap LLM pass)
1. `plan_lint.py` (deterministic): identifiers, budgets, pacing, safe-zone fit.
2. LLM editorial audit (separate call/agent from the one that authored the plan —
   fresh eyes): hook lands in ≤3s? one promise? pacing curve matches mode doctrine?
   payoff self-contained? b-roll justified (covers cut / illustrates named noun)?
   ending loops? Returns findings ranked; brain revises before any render burn.

### Audit B — post-render, on the MP4
- **Vision pass** (FRAME.IO REVIEW machinery): sample frames → verify title cards
  rendered inside safe box, captions legible/uncut, face framed in crop (no chopped
  foreheads), b-roll actually appears where planned, first frame is strong.
- **Audio measurements** (deterministic): `ebur128` → integrated LUFS within ±1 of
  target, true peak ≤ −1.0dBTP, music-under-voice delta in range, no silence > mode
  threshold surviving, AV duration match across variants.
- **Transcript re-check** (optional, cheap): Deepgram the OUTPUT, diff against
  expected kept words — catches cut words, doubled syllables at joins, speed artifacts.

### Feedback loop (the "AI video editor" behavior)
- Operator notes in natural language, referencing output time ("hook text too long",
  "b-roll at 0:14 is wrong", "let the pause at 0:31 breathe").
- Brain maps output→source via `timeline_map.json`, produces `edit_plan` v(n+1) with a
  **change log** (what changed and why), lint gate, re-render, Audit B, present diff.
- Guardrails: max auto-revision rounds per audit cycle (default 2) then require human;
  plans are append-only versions (v1, v2, …) so any revision can be rolled back.

---

## 6. Multi-source assembly (1, 2, or N raw pieces + b-roll pool)

- The EDL's atomic unit is `{sourceId, start, end}` — a short can open on footage-2,
  cut meat from footage-1, and cover with broll-3. Renderer normalizes mixed
  formats (4K/1080p, 24/30fps, mono/stereo) to a common profile at stage 1
  (generalizing `export_mp4.py`'s outro normalization).
- **The brain sees everything before deciding anything**: all transcripts + b-roll
  catalog + music manifest + target mode in one editorial pass.
- **Context overflow strategy** (N long recordings): hierarchical selection — pass 1
  per source (candidate moments, ranked, with hook/payoff annotations), pass 2 global
  assembly over candidates only. Skill mode can additionally page through transcripts
  incrementally.
- **Take selection**: same content in multiple takes → brain keeps the better take
  (generalizes CLIPPER's mic-bleed "keep the more complete copy" doctrine).
- Shorts derivation follows research: **select self-contained peak moments** (each with
  own hook + payoff), never time-compress a whole segment. Candidate ranking sized
  ~10–20; operator picks or brain auto-picks top-k.

---

## 7. Music

- **Vibe**: operator-specified OR brain-inferred from content mood (config default:
  ask; skill mode literally asks in conversation, live mode shows a picker with the
  inferred suggestion preselected).
- **Sources**: library folder first (`music/<vibe>/` + manifest); Higgsfield
  `generate_audio` (skill/MCP only) when no library match — generated tracks are
  saved INTO the library with vibe tags, so the live app benefits over time.
- **No fuzzy fallback** (repo doctrine): if no library match and generation is
  unavailable, produce the without-music variant and say so — never "closest vibe".
- Handling: loop short tracks with crossfade; fade out at end; trim long tracks at a
  musical-ish boundary (bar estimate from BPM); duck under dialogue (§4.2); music
  never load-bearing (captions carry meaning — sound-off viewing dominates non-TikTok).
- **Always render both variants** (with/without) per the operator's requirement — mux
  cost only.

## 7.5 B-roll doctrine — selection order, density, Higgsfield prompting, folders

### Selection ORDER (fixed — assess before you promise)
1. Canonically ingest the pool, then catalog its admitted snapshots (vision
   descriptions cached). A file added later is unavailable until re-ingest;
   pool filenames remain provenance, never executable media paths.
2. Brain identifies *candidate* b-roll needs from the cut plan — each need cites its
   reason: (a) cover a jump cut, (b) illustrate a concrete named noun, (c) reset a
   pacing lull. "Looks nice" is not a reason (research: purposeful, never decorative).
3. Brain matches needs against the catalog; **skill mode additionally views actual
   frames of shortlisted clips before committing** (suitability check — resolution ≥
   canvas, orientation workable, no burned text near safe zones, tone match).
4. Unfilled needs → Higgsfield generation (skill/MCP; live app skips + reports).
   If neither fits → the slot stays on the talking head. Never force-fit (no-fallback
   doctrine). A script that "calls for 1–2 pieces" gets exactly the pieces that pass
   vetting — possibly zero, stated plainly in the plan rationale.

### Density (config, mode-scaled)
- SHORT: cap ~1 insert per 8–12s of output (2–4 in a 30s short), 1–2s each ("golden
  range"), max 3–5s. NEVER over the hook card; NEVER over the payoff line (payoff
  wants the speaker's face). Visual-variety cadence between inserts comes from
  punch-ins and caption emphasis, not more b-roll.
- LONGFORM: front-loaded (every 10–15s in the opening 60s), then contextual only; no
  single unbroken talking-head pattern > 60–90s.

### Higgsfield prompt engineering (`prompts/broll-gen.md`, versioned)
- **Taxonomy** the brain classifies each need into: literal-illustration |
  conceptual-metaphor | environment/texture | screen/UI | people-doing-things.
- **Hard rules**: NO text-bearing generations (AI text garbles — screens/UI with
  readable text must come from real recordings in the folder); no recognizable faces
  by default (uncanny + brand risk; config-off); no logos/watermarks.
- **Prompt template**: `[subject] [action], [setting], [style block], [camera/lens],
  [lighting], [mood]` + negative constraints. The **style block is per-video, not
  per-prompt** — one consistent look across every generated asset in a video
  (Higgsfield Soul style presets / reused style tokens), so generated b-roll reads
  as one shoot, not a grab bag.
- **Derivation**: subject/action from the transcript line being illustrated; mood
  shared with the music-vibe inference.
- **Stills first**: default = generated still + ffmpeg ken-burns (zoompan) — cheap,
  deterministic; upgrade to image2video (DoP) motion selectively. Generated assets
  land in `broll/generated/` with their prompt saved as the catalog description.

### Folder conventions (human layer; the catalog is the source of truth)
```
broll/
  screens/         # real screen recordings (only legit source of readable UI text)
  people/          # hands, silhouettes, over-shoulder
  environments/    # office, gym, city, ambient texture
  metaphors/       # growth, friction, time-lapse, abstract
  product/         # operator's product/brand footage
  generated/       # Higgsfield output (auto-managed, prompt = description)
broll/broll_catalog.json # cached vision descriptions keyed by path+mtime
```
- Filenames: descriptive kebab-case `subject-action-setting.mp4`
  (`hands-typing-laptop-dark-desk.mp4`). Folder = coarse category tag in the
  manifest; filename seeds the cataloger's prior. **Retrieval never depends on
  naming** — every file gets a vision description at catalog time, so a badly-named
  file is still findable and a well-named one is verified. Renames/moves re-catalog
  via the mtime key.

---

## 8. Edge cases (by stage)

**Ingest**
- VFR footage (phones!) → normalize to CFR at mezzanine or all timestamp math drifts.
- HEVC/10-bit iPhone, mixed 4K/1080p/24/30fps, portrait-shot source (already 9:16 —
  reframe becomes crop-for-16:9 or passthrough), rotated metadata.
- No/corrupt audio track on a "raw footage" file → treat as b-roll, warn.
- Multi-hour 4K files → transcribe from extracted audio (already solved), render only
  kept ranges (never transcode the whole source).
- Duplicate files / same footage added twice → content-hash dedup in manifest.

**Transcription**
- Deepgram partial failure mid-chunk → retry chunk (retry doctrine), else mark gap
  and surface; never silently skip (humanizer silent-skip lesson from flow audit).
- Heavy crosstalk / wrong diarization → CLIPPER's mic-bleed doctrine + operator
  speaker-map override. Non-English → pass detected language through. Music-only or
  silent b-roll → vision description path, `hasSpeech: false`.

**Brain / plan**
- Hallucinated timestamps or asset ids → lint rejects with specific errors, bounded
  retries (LLM identifier contract).
- No strong hook found → say so and present best candidates with scores; never
  fabricate a promise the footage can't cash (no-surface-branding doctrine).
- Content can't fill target duration → shorter output beats padded output
  (completion-rate doctrine); flag it.
- Feedback contradicts platform doctrine ("put the CTA at the end as speech") →
  comply but warn once with the research basis (operator wins; no yes-man lectures).

**Longform→clips→shorts conversion (the operator's core flow)**
- Moment spans a SEGMENTER boundary → candidate selection must run on the source
  transcript, not per-segment silos.
- Hook sentence starts mid-utterance → cut at word level (CLIPPER doctrine), and the
  short's first spoken word must be intelligible cold.
- **Self-containedness test**: payoff depends on setup minutes earlier; pronoun/context
  dependencies ("like I said earlier", "this approach") → candidate is rejected or the
  referenced setup is spliced in; never ship a short that assumes prior context.
- Speaker attribution: a caller's voice with no intro → hook card / caption must
  establish who's talking if it matters to the payoff.
- Clip falls below duration floor (~15s) after silence+filler cuts → merge with
  adjacent beat or drop; never pad with dead content.
- Overlapping candidate moments competing for the same footage → dedupe at ranking.
- Source already has burned-in graphics/lower-thirds → vision flags at ingest; caption
  band must not stack on existing text.
- Loop point lands mid-word → nudge out-point to word boundary (map makes this cheap).
- First frame is unflattering (mid-word mouth) → hook card covers frame 1 anyway; cover
  selection prefers a settled frame (pHash settled-frame logic reused).
- Platform compliance: profanity near the hook (demonetization risk) → flag in Audit A;
  optional caption masking, operator decides.
- Numbers in captions ("$12k/mo", "40%") → formatted as written forms Deepgram won't
  produce verbatim; caption formatter normalizes numerals/currency.

**Face crop**
- No face (screen share / slides) → center crop or blurpad by content type.
- Two faces (host + guest side-by-side) → crop to active speaker per diarization
  windows; if both matter, alternate or blurpad. Face near frame edge → clamp crop
  window, never off-canvas. Face detection confidence low → center + flag in Audit B.

**B-roll**
- Empty folder / no match for a named noun → skip or generate (skill mode); NEVER
  decorative filler (research: purposeful only) and never fuzzy-match.
- B-roll shorter than slot → don't stretch beyond 1.25x; pick another or shorten slot.
- Orientation mismatch (16:9 b-roll on 9:16 canvas) → center-crop if safe, else blurpad.
- B-roll with burned text/watermarks near safe zones → vision flags at catalog time.
- Higgsfield: generation fails/NSFW-flagged/slow → without-b-roll fallback for that
  slot + note; per-run credit cap in config; generated assets cached in the pool.

**Music**
- Track shorter than video → loop w/ crossfade; longer → fade at output end.
- Library track uploaded at wild loudness → per-asset loudnorm before mixing.
- Licensing is operator responsibility (library manifest carries a `licensed` field;
  unlicensed tracks warn in Audit A).

**Render**
- Speed change AV drift → `atempo` and `setpts` derived from the same factor; stage-1
  output duration asserted against compiler prediction (±1 frame).
- Caption/overlay drift after cuts+speed → all overlay math ONLY through
  `timeline_map.json`; Audit B transcript re-check is the backstop.
- Very long renders → stage-resumable; disk-space preflight; work dir in scratchpad.
- ffmpeg version differences → extend existing `check_ffmpeg_version()`.

**Loops / modes**
- Feedback ping-pong → revision cap (2 auto rounds), then human.
- MCP unavailable (headless/cron) → skill degrades to library-only, says so.
- `ANTHROPIC_API_KEY` absent in live mode / `HF_CREDENTIALS` absent → feature-gated
  UI, clear errors (no silent degradation).
- Cross-mode drift (skill doctrine vs live prompts diverging) → both read the same
  config/prompt files; parity checked by a golden-plan fixture test.

---

## 9. Cost model (per ~30s short, estimates)

| Item | Live mode | Skill mode |
|---|---|---|
| Deepgram (source hrs, amortized) | ~$0.26/hr of raw footage | same |
| Plan + revisions (Sonnet) | ~$0.05–0.20 | $0 (subscription) |
| Editorial audit (Sonnet) | ~$0.03–0.10 | $0 |
| Vision QC (~20–40 frames, Haiku/Sonnet) | ~$0.05–0.20 | $0 |
| B-roll catalog (one-time per folder, cached) | ~$0.01–0.05/clip | $0 |
| Higgsfield b-roll/music | credits (API) | credits (MCP) |
| **Total marginal** | **~$0.15–0.50 + credits** | **~Deepgram + credits only** |

---

## 10. Phasing

**Phase 1 — Core skeleton + first real short (skill-first).**
Manifest/ingest scripts, `edit_plan.json` schema + `plan_lint.py`, timeline compiler
(+ the source↔output map), stages 1–2 + captions (cuts, speed, static face crop via
`face_track.py`, ASS karaoke captions), `producer` skill v1, `-14 LUFS` dialogue-only
master, and **`PRODUCER_EDGE_CASES.md` seeded as a living catalog** (this doc's §8 is
the first pass, NOT a completeness claim — precedent: PIPELINE_EDGE_CASES.md grew to
131). **Exit: one real coaching short, phone-checked on all 3 platforms.**

**Phase 2 — Packaging + audits.**
Title cards + cover frame, b-roll folder pipeline (catalog + placement + overlay),
music library + ducking + dual variants, Audit A (lint+editorial) and Audit B
(vision+audio), feedback loop v1 (plan versioning + output→source mapping).
**Exit: end-to-end short with b-roll + music, passes both audits, survives one
feedback revision cycle.**

**Phase 3 — Generation + long-form.**
Higgsfield MCP in the skill (b-roll images/video, music gen → library), long-form mode
(selective filler, breathing-room thresholds, chapters, SRT sidecar, 16:9 master,
optional FCPXML handoff), shorts-from-longs candidate ranking (10–20 moments).
**Exit: one long-form cut + 3 derived shorts from the same raw session.**

**Phase 4 — Live app.**
`/producer` tool page + API routes (plan via forced tool-call, render SSE, audit
report UI, feedback box), Higgsfield Cloud API (`higgsfield-js`), golden-plan parity
fixture between modes. **Exit: same footage produces equivalent output in both modes.**

**Phase 4 navigation requirement (operator, 2026-07-05):** the app's entry point
mirrors the operator's mental model — ONE place to drop footage, then choose:
"Clip it" (rough pieces) / "Make shorts" / "Make the long-form" — with pieces
PROMOTABLE between stages (a segment → short, a short → revision) instead of
today's disconnected tabs. The 2026-07 scaffold (pick → manifest → plan JSON →
render) is the plumbing under this, not the final UX.

### Feature-parity ledger (skill vs live app — no feature ships skill-only without a row)

| Capability | Skill | Live app | App gap closes |
|---|---|---|---|
| Brain (discovery, plans, editor notes, scope round) | ✅ | ❌ plan-JSON paste only | Phase 4 (Anthropic API plan route) |
| Render engine: cuts/speed/reframe/cards/captions/LUFS/auto-audit | ✅ | ✅ same Python — full parity | — |
| SEGMENT rough cuts | ✅ | ✅ (SEGMENTER tab) | — (handoff UX in Phase 4 nav) |
| CLIP → MP4 brick | ✅ | ⚠️ FCPXML only in CLIPPER tab | Phase 4 (add MP4 path) |
| Long-form (SRT/chapters) | ✅ proven | ✅ engine / ❌ UI conveniences | Phase 4 |
| Music machinery | ✅ CLI | ❌ UI | With first music test |
| Motion graphics / layouts / treatment maps | 🔄 MG-1..4 | ❌ | After MG-2 (same plan JSON → engine parity automatic); UI in Phase 4 |
| Partial re-render | designed §4.5 | inherits (same engine) | with MG-2/§4.5 build |
| Higgsfield generation | MCP | Cloud API (higgsfield-js) | Phase 4 |

Verification throughout follows SNIPER's convention (no test suite; walk the flow with
a short real MP4; `npm run build && npm run lint` clean) plus the new deterministic
self-checks (`plan_lint.py`, stage duration assertions, ebur128 measurements).

---

## 10.5 Roadmap: voice enhancement (operator request 2026-07-05 — not a priority)

Reduce background noise (car cabin / room tone) + enhance voice. Tiered plan,
applied to the DIALOGUE BUS pre-mezzanine (before ducking/loudnorm), opt-in
flag per render, A/B'd in the audit:
1. **Free tier (ffmpeg-native, build first):** highpass 80Hz → `afftdn` (FFT
   denoise) or `arnndn` (RNNoise neural model, ffmpeg-native, excellent on
   steady noise like road hum) → light `deesser` → `speechnorm` (level out
   mic-distance swings). Zero deps beyond an .rnnn model file. Car footage is
   the ideal test case.
2. **Strong tier:** DeepFilterNet (open-source neural, better on messy noise)
   as an optional venv dep.
3. **Premium tier (opt-in, costs):** Adobe Podcast Enhance / Auphonic /
   Dolby.io API for studio-grade cleanup — same opt-in prompt-review posture
   as Higgsfield.
Audit addition: before/after SNR estimate + operator listens to a 10s A/B.

## 10.6 Roadmap: lifted from the sibling video-editor drop (2026-07-05)

Operator supplied `video-editor-client.zip` — a mature Claude-as-editor sibling
(WhisperX-based, skill-per-stage). Direct lifts shipped same-day (YuNet model,
bake_emoji.py, global caption-corrections preset, hair-top technique → placement
v2). Concept lifts queued:
1. **Thumbnail generator** — their pattern: face-refs photo library + Higgsfield
   image gen (concepts proposed → operator approves → parallel renders) + PIL
   title burning (never let the model render text — it hallucinates letters).
   We have Higgsfield MCP; needs the operator's face-ref photos + our standard
   prompt-review posture. Natural extension of our cover.png stage.
2. **Brand-kit personalization gate** — <<FILL_ME>> tokens + deterministic grep
   check + SessionStart hook so a fresh install can't ship someone else's brand.
   Directly relevant to productizing PRODUCER for Project Sniper users.
3. **Style packs as preset files** — their presets/ folder (signature-style.md,
   captions-style.md + build.py) formalizes what we do as doctrine-in-docs;
   adopt when IG-minimal/kinetic get a third sibling.
4. **to-premiere / NLE escape hatch** — export the edit_plan as an NLE timeline
   (we already have CLIPPER's FCPXML writer in-repo to lift from) so a human
   editor can take over any cut. High leverage, low effort.
5. Their incremental-graphics parts.json manifest validates our §4.5 partial
   re-render design (overlay-vs-segment rule matches our alpha-mov vs own-screen
   split); no action needed beyond the manifest idea.

## 11. Open questions for the operator

Settled 2026-07-04: hook-card copy grounds in the packaged Director library (resources/director) (QUEST types +
the packaged Director hook library via `format_hooks_for_prompt()`), hard-limited to ≤2 lines /
≤8 words (§4.3); hook cards = white container + black text.

1. ~~Tool name~~ SETTLED 2026-07-05: PRODUCER stays.
2. ~~Caption style~~ RE-CONFIRMED 2026-07-05 after a head-to-head vs IG-minimal
   on identical footage: KARAOKE is the Project Sniper default — the operator prefers
   the gold sweep FOLLOWING the spoken words over static-gold single words.
   `minimal` remains available as a per-plan style option.
3. ~~Music~~ SETTLED 2026-07-05 (operator doctrine, supersedes earlier rec):
   **NO music by default — ever.** Music only when the operator explicitly asks;
   source is then an operator-provided track OR Higgsfield generation (opt-in,
   prompt-review protocol — see MG plan). The brain may RECOMMEND music when a
   treatment zone wants it (e.g. documentary-style needs a bed) but never adds
   it without approval. Generated tracks still save to `music/<vibe>/` for reuse.
4. **Brand kit** — PARTIALLY ANSWERED 2026-07-04: hook cards = white container with
   black text. Remaining: exact font (default bold Inter/Montserrat), corner radius,
   caption colors.
5. ~~TikTok loud master~~ SETTLED 2026-07-05 (rec adopted): skip — single −14 LUFS
   master for all platforms; revisit only if posting analytics show TikTok
   loudness disadvantage.

## Research grounding
Full reports (safe zones, LUFS, editing doctrine, shorts-vs-longs) captured in session
scratchpad: `research-platform-specs.md`, `research-shorts-editing.md`,
`research-longform-editing.md`. Key honesty flag inherited from research: most timing
numbers are practitioner heuristics, not platform-published — hence everything lands in
`producer_config.py` as tunable defaults, with the few hard anchors (TikTok 3–6s hook +
5–10 w/s captions, caption completion lift, −14 LUFS/−1.5dBTP, YouTube encode spec)
treated as non-negotiable.
