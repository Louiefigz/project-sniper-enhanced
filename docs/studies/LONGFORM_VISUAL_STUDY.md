# Long-form visual study — "Replaced 5 Content Tools With 1 Production Workflow"

A frame-level audit of a professionally edited 16:15 long-form talking-head video
(1920×1080, 23.976 fps), with special attention to the operator's headline ask:
**the subtle zoom-ins/-outs**. The raw sibling is a 4K **locked** camera, so it is
the zoom BASELINE — the raw has no zooms, therefore every framing change in the
edit is an editor DECISION, and the raw lets us measure the detector's noise floor
directly.

**Bottom line:** the editor never leaves the frame still. Underneath ~9 cuts/min
sits a second, quieter layer — a zoom event every ~28s (35 total) plus a
near-imperceptible slow "creep" under the talking stretches. The zooms are not on
a timer; they are **semantic** — they land on emphasis, contrast, transitions, and
story. The base framing is kept wide (the presenter's face is ~2% of the frame,
the same as the raw locked shot); punch-ins are deliberate *departures* from that
baseline that then resolve back.

Artifacts (all under `scratchpad/study-pair/zoom-graphics/`):
- `data/zoom_map.json` + `data/zoom_map.md` — every zoom event × spoken context
- `data/graphics_inventory.json` — graphic treatments as time-ranged instances
- `data/face_series.json` — 5 fps YuNet face-area series (raw zoom signal)
- `sheets/sheet_00.jpg … sheet_43.jpg` — 44 chronological 4×3 contact sheets (for the lead's taste read)
- `study/fingerprint.json` + `study/report.md` — pacing + 520 unique states
- `validate_*.jpg` — side-by-side frame pairs proving the method

Reusable scripts written for this (in `scripts/producer/`): `study_zoom_faces.py`,
`zoom_scale.py`, `zoom_detect.py`, `study_zoom.py`, `zoom_report.py`,
`study_sheets.py`, `study_graphics.py`.

---

## 1. Method + honesty (read this before trusting the numbers)

**Two signals, because face-area alone lies.** The obvious zoom proxy — the size of
the presenter's face (YuNet, 5 fps) — is far too noisy here: the face is only ~1.9%
of the frame, so YuNet's box jitters **±10%** frame-to-frame on the RAW locked
camera *with no zoom at all*. Measured on two 30 s raw windows, the smoothed
face-area "step" noise reaches p90 ≈ 9–14% and max ≈ 12–24%. A subtle 5% push is
invisible under that.

So the primary zoom signal is a **direct whole-frame scale measurement**
(`zoom_scale.py`): the camera is locked, so between two frames of the same shot the
only global geometric change is the editor's scale keyframe. ORB features on the
static background (shelves, wall, posters) are matched with `estimateAffinePartial2D`
+ RANSAC; the moving head/hands drop out as outliers; the similarity transform's
uniform scale IS the zoom. **Validated on the raw baseline: |scale-1| < 0.2% with no
zoom** — a hundred times tighter than face-area. Face-area is kept only to classify
each shot as talking-head vs cutaway.

Confirmation that face-area would have misled: at 1:52 the face area jumped **1.93×**
but the true whole-frame scale was only **1.06×** — the "jump" was a pose/detector
artifact, not a zoom. See `validate_*.jpg` for four spot-checks that visually confirm
gradual pushes, punch cuts, and the noise floor.

**How each zoom type is measured**
- **Punch-in cut** — a hard cut to a tighter/wider framing of the *same* shot: a
  scale STEP across a cut whose backgrounds still MATCH (ORB locks → high inliers).
  A plain jump cut keeps the framing → scale ≈ 1.0 → *not* counted. A cut to
  different content → ORB can't match → it's a cutaway, not a punch.
- **Animated ramp** — a keyframed push/pull WITHIN one continuous shot: a scale
  change from the shot's first settled frame to its last. The trajectory is probed
  in 6 sub-segments to confirm it ramped *gradually* rather than stepping.
- **scdet under-counts punches (important).** A hard punch-in on a matched
  background barely changes the scene score, so ffmpeg's `scdet` often does NOT
  place a cut there. Those show up as a step concentrated in one sub-segment of a
  "shot"; the detector re-classifies them as punch-in cuts and localizes them to
  where the step happens. This is verified visually (e.g. the 15:40 punch sat ~5 s
  before the scdet boundary). Net: **21 punch-in cuts, more than scdet's boundaries
  alone would suggest.**

**Thresholds (auditable):** ramp gate 2% linear scale, punch gate 3% — both far
above the 0.2% raw noise floor. Cut boundaries from `scdet` threshold 8.

**Stated limits**
- Ramps below ~2% linear over a shot are left uncounted (indistinguishable from
  drift); the operator's "very subtle" pushes at 2–5% ARE captured and listed.
- Sub-0.4 s whip-pans / single-frame flash-cuts are below the 5 fps sampling and
  the 1 s instance floor; they appear only in the raw contact sheets.
- Shot classification uses a frontal face signal; a fully turned head reads as
  "no face" and can shorten a talking-head shot. B-roll durations are ±0.5 s
  (2 fps state extraction).
- The graphic *type* names are deterministic luma buckets; the finer sub-types
  (statement card vs diagram vs title) are a vision read off the sheets.

---

## 2. ZOOM MAP — the headline

**Cadence:** 35 zoom events over 16:15 = **2.15/min**, one every ~28 s.
- 21 punch-in cuts, 14 animated ramps
- Direction **20 in : 15 out (1.33)** — a lean toward pushing IN
- Magnitude (linear scale): min 2.7% · **median 20.8%** · max 51.1%
- Front-loaded: **5 events/min in the first 60 s vs 2.0/min in the body (2.5×)**

Full event × spoken-context table is in `data/zoom_map.md`. The events cluster into
four uses:

### The extracted rules

**Rule 1 — Punch-IN marks a pointed claim ("lean in, this matters").** The hard
push-in lands on the stressed beat of an assertion or a credibility specific:
- 0:19 +6.7% — "you're not inconsistent because you're **lazy**"
- 0:28 +6.0% — "I've been writing **software for about a decade**"
- 0:47 +23.8% — "…solved for the **same exact reason**"
- 10:08 +32.1% — "**Me personally**, I tried to save $50"
- 13:18 **+51.1%** (the biggest) — the product reveal, "you can also give [feedback]"

**Rule 2 — Punch-OUT marks a reset / new beat.** The pull-out lands on section
transitions and topic hand-offs:
- 4:45 −32.6% — "**So once I finally committed to**…"
- 5:17 −22.2% — "…then came **implementation**"
- 5:52 / 6:11 −18% / −26.7% — new tool/story beats ("And drive got", "deal on a tool called Late")
- 0:02 −20.8% — the pull-out right after the opening hook line "write this sentence down"

**Rule 3 — The in→out BRACKET is the signature move.** A punch-in on a key phrase
immediately followed (~2 s) by a punch-out to release it — reserved for the biggest
lines:
- 7:07 **+29.6% → −19.4%** — "everyone online screams that you should actually post"
- 13:18 **+51.1% → −24.5%** — the product-feature reveal
- 15:40 **+40.0% → −27.0%** — the closing callback ("your problem isn't that you're lazy — it's your system"), which pays off the opening line

**Rule 4 — Slow RAMPS put tension under story/explanation.** A barely-perceptible
creep runs through multi-second narrative stretches so the frame is alive even
between cuts:
- 2:06 +43.8% over **25 s** (0.82%/s) — the SEO-company story
- 3:24 +26% over 23 s, 3:53 +24% over 24 s — confidence/turning-point beats
- The genuinely *subtle* ones the operator asked about: **2:31 +6.9%/3 s, 4:18
  +2.7%/5 s, 4:24 −3.7%, 5:39 +4.9%/12 s, 13:09 −4.4%, 14:21 +4.1%** — pushes small
  enough (0.3–1.8%/s) to register subconsciously, not consciously.

**Rule 5 — Zooms depart from a preserved-wide baseline.** The edit does NOT globally
punch in: the median face area (1.9%) equals the raw locked camera's, i.e. the wide
framing is kept as "home." Every punch is a departure that resolves back — which is
why the in→out brackets exist and why the pushes read as intentional rather than as
a cropped-in style.

**Why it works, in one line:** cuts keep the *rhythm*, zooms carry the *meaning*.
The zoom track is a second edit layered on the cut track, spent only where the words
earn it (emphasis, contrast, transition, story) — so a 16-minute locked-camera
monologue never feels static and never feels gimmicky.

---

## 3. GRAPHICS INVENTORY

520 unique on-screen states fold into **62 instances**; the base talking head is
**88% of runtime (861 s)**. Everything else is a graphic layer. Machine-readable in
`data/graphics_inventory.json`; the 18 graphic instances ≥1 s are listed there with
palette + luma. Contact sheets `sheets/sheet_00…43.jpg` are for the lead's taste read.

The design system is cohesive: dark or **animated gradient** backgrounds (navy
`#0a1123`, deep red `#3a0000`, warm orange→purple), **white bold display text with
keywords bolded**, a **magenta/pink glow** accent (underlines, dots), thin
**hand-drawn white connector lines**, and **rounded-square SF-symbol-style icons**.

Catalogued treatment types (with example timestamps):

| Type | What it is | Position / entrance | Tokens | Examples |
|---|---|---|---|---|
| **Kinetic captions** | Burned-in, word-by-word, key words in an accent color. Two emphasis styles: big red/orange **ALL-CAPS bold-italic** (hook) and smaller white sentence-case + **yellow-bold** key words (body). Used in bursts, not continuously. | Lower third, over talking head | Red `#e0332a` / yellow accent, drop shadow | 0:00–0:07, 11:27 "channels and it's just more" |
| **Full-screen statement cards** | Thesis line takeover: centered glass card, white text w/ bolded keywords, small icon above, on a dark→warm-gradient bg. | Full-screen, replaces head; card scales in | White on navy/gradient | 0:11 "…fix half of your **content problems**", 0:16 "…**your system**" |
| **Framework diagrams** | Animated 3D pyramid / hierarchy with numbered tiers, dashed-arc callouts. | Full-screen, tiers build in | White text, red gradient bg | 3:47 & 7:25 "Principle 1/2/3" + "Don't scale delivery until you can say in one sentence who you help" |
| **Title / agenda slides** | Big display title with a magenta glow underline; animated numbered node-link steps. | Full-screen | White + magenta glow, gradient bg | 7:53 & 8:11 & 8:28 "3 Steps" → "1. Pick your target / 2. Get help" |
| **Whiteboard boards** | Miro-style light grid canvas, green nodes → dark caption chips, connectors. | Full-screen, light bg | Green node `#7cf`, grid | 0:40 "And in that time → I've basically launched a YouTube comedy channel" |
| **Logo / brand cards** | White full-screen with a tool's logo (the "5 tools" being replaced). | Full-screen white | Black logo on white | 5:31 Notion "N" |
| **Floating illustrative MG** | Hand-drawn animated arc + app-icon tiles (avatar → building/outcome), floats over the head. | Upper third, flanks head | White arc, rounded icon tiles | 0:02–0:07 "I help who go from pain to outcome" |
| **Cinematic b-roll** | Stock cutaways: editor at a color-grade workstation, robot hand + AI code on a laptop, person w/ a tablet in an industrial setting. Dark, moody, cool. | Full-screen, replaces head | Desaturated, teal/amber | 13:10 editor, 14:32 AI b-roll |
| **Gradient color-wash / flash** | Warm orange→purple gradient overlay at transitions; sub-0.5 s white flash-cuts between beats. | Full-screen, brief | Warm gradient / white | 0:04, 13:36, 14:14 |

Instance counts (luma buckets, `data/graphics_inventory.json`): talking_head 28
(861 s), full_screen_dark 13 (44.5 s — cards/diagrams/titles), broll 13 (20 s),
full_screen_bright 8 (17.5 s — boards/logos/flash).

---

## 4. B-ROLL / CUTAWAY MAP (talking head replaced)

The head is fully replaced **9% of runtime (87.8 s across 17 segments ≥1 s)** — used
sparingly and always motivated by the words. Full list in `data/zoom_map.json`
(`cutaways`) and `data/graphics_inventory.json` (`graphicInstances`). Highlights:

| Time | Dur | What / said |
|---|---|---|
| 0:11–0:18 | 6.5 s | statement card — "…fix half of your content problems this year" |
| 0:38–0:46 | 8.5 s | whiteboard board — self-intro ("in that time…") |
| 1:22–1:27 | 4.5 s | framework/card during the "I had no niche, no offer" story |
| 2:02–3:01 | ~10 s | b-roll + card cluster under the SEO-company story |
| 3:47–3:53 | 6.0 s | "Principle" pyramid diagram |
| 5:31–5:39 | 7.5 s | Notion logo card ("5 tools") |
| 7:25–7:34 | 9.0 s | "3 Steps" title takeover (longest single cutaway) |
| 7:53–8:33 | ~12 s | numbered agenda-step slides |
| 13:10–13:14 | 4.5 s | editor-at-workstation b-roll (the "editors pull your raw footage" beat) |
| 14:32–14:37 | 5.5 s | AI/robot-hand b-roll |

Pattern: cutaways cluster in the **teaching/story middle** (2:00–8:30) where a
diagram or card does the explaining; the hook uses quick card+flash hits; long
"cruise" stretches (e.g. 11:34–12:48, ~73 s) stay on the talking head with only the
subtle zoom track for motion.

---

## 5. PACING — hook vs body

Everything is **front-loaded into the first 60 s, then settles to a sustainable
cruise** (`study/report.md` for the full per-10s curve):

| Signal | Hook (0–60 s) | Body (60 s–end) | Ratio |
|---|---|---|---|
| Cuts | 19 (19/min) | 130 (8.5/min) | **2.2×** |
| Visual-state changes | 67 (67/min) | 453 (29.7/min) | **2.3×** |
| Zoom events | 5 (5/min) | 30 (2.0/min) | **2.5×** |

- Overall **9.17 cuts/min**; shot length p25/p50/p75/p95 = 0.09 / 0.86 / 6.3 / 31.9 s.
- The p25 of 0.09 s is inflated by scdet firing on caption pops/flashes; real camera
  cuts are the p50 ≈ 0.9 s and up. Longest un-cut stretch **95 s**.
- The hook stacks *all* devices at once — dense jump cuts, statement cards, the
  floating arc graphic, a whiteboard board, kinetic captions, and 5 zooms — then the
  body relaxes to ~8.5 cuts/min + a zoom every ~30 s + subtle ramps, so attention is
  bought aggressively up front and *maintained* cheaply after.

**Net "why this works":** three independent motion layers — a steady cut rhythm, a
semantic zoom track, and a sparse but cohesive graphics system — are each dialed hot
in the hook and eased to a repeatable cruise, so a locked-camera monologue reads as
constantly moving without any single device wearing out.
