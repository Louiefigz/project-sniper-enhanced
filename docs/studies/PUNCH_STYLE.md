# PUNCH_STYLE.md — the iampunch shorts grammar (measured)

> **SUPERSEDED 2026-07-09** by
> `scripts/producer/docs/findings/PUNCH_STYLE.md` — the 6-reel GRANULAR
> synthesis (every reel deep-traced, not just DVgWXuXDXdN). It corrects three
> numbers here: scdet cut counts undercount punch cuts ~2x (visible-cut median
> is 17.2/min, not 9.9), §3's "captions carry zero emphasis" is false in 4/6
> reels (inline amber keywords + serif promotion builds), and the 20s still
> tolerance (the longest true no-cut+no-graphic stretch is 10.9s). The
> fingerprint tables below remain valid as fingerprint-level data.

**Creator:** iampunch (Punch Young, Content Strategist, ~299K IG)
**Corpus:** 6 reels, 55.9–150.7s each, all 1080x1920 9:16 talking-head, desk +
laptop + TV-glow set, locked tripod.
**Evidence:**

| Level | Source |
|---|---|
| Fingerprints (ALL 6 reels) | `_references/iampunch/<id>.study/report.md` — scdet cuts, shot lengths, state timeline (fps=2.0), LUFS/crest/silence audio pass |
| Deep frame trace (DVgWXuXDXdN ONLY) | 1fps contact grids + 8fps hook grid (0–10s) + 12fps ±0.55s bursts around all 22 cuts, verified by eye; zoom from face-bbox traces + background-patch SSIM |

Reel IDs: `DVgWXuXDXdN` (150.7s), `DQrbyYRDZGh` (140.9s), `DZ2u2o8qEjV`
(101.2s), `DaGwe1PCFWQ` (88.1s), `DaVNfI1iT1q` (86.3s), `Dafb57RiAjt` (55.9s).

**Confidence policy (per-rule tag):**
- **HIGH** — measured across ≥3 reels, or ≥5 independent occurrences in the deep trace.
- **MEDIUM** — 3–4 occurrences, single deep-traced reel.
- **LOW-CONFIDENCE** — seen <3 times. Flagged explicitly; treat as a hypothesis,
  re-verify on the next deep trace before hard-coding.

Wired into the pipeline: `producer_config.MODES["short"]["pacing_punch"]`
(selected by `target.pace == "punch"`, resolver in
`plan_lint_motion._pacing_profile`). Catalog gaps for the comp library are in §8.

---

## 0. Corpus numbers (all 6 reels, machine-measured)

| Reel | Dur | Cuts | Cuts/min | Shot p25/p50/p75/p95 (s) | Longest static | States | States/min | LUFS int | TP dBTP | Crest | Music bed |
|---|---|---|---|---|---|---|---|---|---|---|---|
| DVgWXuXDXdN | 150.7 | 22 | 8.76 | 3.8 / 5.2 / 8.6 / 16.0 | 16.9s | 169 | 67 | −14.5 | −0.7 | 6.7 | likely |
| DQrbyYRDZGh | 140.9 | 36 | 15.33 | 1.1 / 2.6 / 3.9 / 11.3 | 21.3s | 199 | 85 | −14.6 | −0.0 | 7.6 | likely |
| DZ2u2o8qEjV | 101.2 | 17 | 10.08 | 2.7 / 5.7 / 7.2 / 11.0 | 17.6s | 130 | 77 | −14.6 | −0.5 | 6.9 | likely |
| DaGwe1PCFWQ | 88.1 | 19 | 12.94 | 2.5 / 4.0 / 5.1 / 8.4 | 9.2s | 131 | 89 | −14.6 | −0.6 | 6.8 | likely |
| DaVNfI1iT1q | 86.3 | 14 | 9.73 | 1.1 / 2.7 / 7.1 / 18.1 | 34.6s | 73 | 51 | −14.6 | −0.3 | 6.8 | likely |
| Dafb57RiAjt | 55.9 | 9 | 9.66 | 1.1 / 2.7 / 8.3 / 16.5 | 20.8s | 81 | 87 | −14.7 | +0.4 | 7.7 | likely |

**Medians:** cuts/min **9.9** (range 8.76–15.33) · shot p50 **2.6–5.7s** ·
longest static **~19s** (9.2–34.6) · states/min **~77** (51–89) · integrated
**−14.6 LUFS** (spread 0.2 LU across 6 masters) · silence ratio **0.000, 0 gaps,
6/6**.

The headline: the CUT rate is moderate (~10/min) but the on-screen STATE rate is
7–9× that. Cadence is **states-driven** — the text/graphics layer churns
between cuts, so the camera is allowed to hold ~20s without the video flatlining.

---

## 1. Hook anatomy

**H1 — Blurred-roadmap cold open. [LOW-CONFIDENCE — seen 1×]**
DVgWXuXDXdN 0.0–1.6s: the video's ENTIRE roadmap mindmap (every section title +
mini thumbnails) is on screen at frame 0, the central circle defocused (the
outer yellow section labels are already sharp), and rack-focuses to sharp over
~1.6s while he says "I've never made a video like this"; holds crisp to 5.1s
(cleared by CUT #1). The curiosity object appears before it is legible;
the promise IS the map.
Executable spec: full-canvas graphic (~0.9W × 0.38H, headroom, center y≈0.18)
present at t=0.0; blur ≈24px → 0 over **1.6s**; hold **3.5s** crisp; clear ON
the first cut. Cheap and powerful — but observed once, so verify on a second
reel before templating.

**H2 — The hook is graphics-carried, NOT cut-carried. [HIGH — 6/6 measured]**
Cuts in the first 10s across the corpus: {1, 0, 2, 1, 7, 0}. Four of six reels
open with ≤2 cuts (two with ZERO) while the state layer changes every ~0.5–1.0s
(DVg states 0–7 span 0–10s ≈ 8 states). The front-load lives in the text/graphic
layer. Executable: never force cut density into the hook window to "front-load";
demand a graphic or keyword lockup on screen inside the first **1.6s** instead.
(DaVNfI1iT1q, the one 7-cut opener, is the exception that scales the same rule:
its montage IS the graphic layer.)

**H3 — Promise keywords pop at ~0.9s cadence. [MEDIUM — 5 pops, 1 reel]**
DVg 5.125s "Following" → 6.0s "Brand" → 6.625s "Social Media" (yellow bold,
chest-left x≈0.27 y≈0.63, ~4%H), then 7.6s "???" (headroom-right) → 8.75s arrow
stroke-draws leftward 0.4s → 9.25s "10X" (headroom-left) → 10.0s "In the next
30–90 Days" (lower-third). Spoken payload nouns are promoted to the shout layer
the moment they are said; the goal is drawn as a right-to-left spatial diagram.
The "??? → 10X" spatial goal diagram itself is **LOW-CONFIDENCE (1×)**.

---

## 2. Cut / zoom cadence — the punch-cut grammar

**C1 — ~10 cuts/min, median shot 2.6–5.7s. [HIGH — 6/6]**
Median cuts/min 9.9 (8.76–15.33). Encoded as
`pacing_punch.min_changes_per_min = 10.0`.

**C2 — ALL motion energy is hard punch cuts; zero dissolves / white flashes /
light-leaks. [MEDIUM — exhaustive in 1 deep-traced reel (21/21 cuts)]**
This shorts grammar is the OPPOSITE of the long-form body-creep grammar in
`docs/studies/MEASURED_EDIT_GRAMMAR.md`. Executable: `transitions` track EMPTY; no
`white-flash` / `light-leak` seam covers in a punch plan.

**C3 — TIGHT↔WIDE alternation, face-height step ±5–28% per cut. [HIGH —
21 cuts measured, DVg]**
Every cut lands tighter or wider than the last (e.g. #2 +13%, #3 −23%, #4 −16%,
#5 −22%, #8 −28%). Matches the shorts "rhythmic zoom" doctrine already in
`MOTION["zoom"]["by_mode"]["short"]` (step_median 1.18); punch sits inside it.

**C4 — Cuts land on the FIRST WORD of a pivot. [MEDIUM — 4 verified word-locks]**
DVg 14.5s "That is the wrong thing to do", 15.458s "Because", 47.833s "Which
brings me", 148.08s "Then I just recommend". Executable: cut instants snap to
utterance starts of turn/contrast/section markers, not mid-clause.

**C5 — Locked tripod, zero zoom creep between cuts. [HIGH for "no creep"
(corroborated by 6/6 static-stretch metric); the SSIM 1.000 measurement itself
is single-reel]**
DVg background patches are pixel-identical (SSIM 1.000) across 6.6–8.5s holds
(20.5→29s, 104.0→110.7s — a cut lands at ~104.0s, so the window is bounded by
cuts, not creep). Executable: NO aliveness creep lane — `punchIns` carry
only cut-riding steps (`role != "aliveness"`); no ramps, no brackets.

**C6 — The camera may hold up to ~20s. [HIGH — 6/6]**
Longest static stretch per reel: 16.9 / 21.3 / 17.6 / 9.2 / 34.6 / 20.8s
(median ~19s). Encoded as `pacing_punch.max_still_gap_s = 20.0`. The hold is
legal ONLY because the caption + shout layers keep changing (see §3–4) — a bare
20s hold with no text churn is off-style.

---

## 3. Caption system spec — the "whisper" layer

**[HIGH in-reel — runs continuously for 150.7s of DVg; state churn corroborated
6/6 by the 51–89 states/min band]**

| Property | Value | Evidence |
|---|---|---|
| Size | ~2%H (≈38px on 1920) | DVg whole-reel |
| Face | white medium sans, sentence case | DVg 0.0s+ |
| Treatment | soft shadow, NO box, NO outline weight | DVg whole-reel |
| Position | chest band, center x=0.5, y≈0.57 (0.55–0.64 across framings) | DVg whole-reel |
| Grouping | 1–3 words per cue | DVg 0–5s cue list |
| Timing | replace-per-cue, 0.25–0.9s each | DVg 0–5s cue list |
| Emphasis | **NONE — zero karaoke, zero color** | DVg 5.1–7.5s: spoken "Following/Brand/Social Media" get NO caption emphasis; they are PROMOTED to the shout layer instead |

**Rule: emphasis is externalized.** The caption layer never carries it — payload
nouns leave the captions and reappear as yellow/white lockups in headroom (§4).
This means a punch plan uses `captions_style: "minimal"`-class rendering
(word-at-a-time, chest-anchored) with the karaoke highlight DISABLED — our
shorts default (`karaoke`, gold active word) is off-style. See gap G2 in §8.

---

## 4. Text / graphics vocabulary — the "shout" layer

### 4.1 Position grid (normalized x, y of element centers; DVg measured)

| Zone | x | y | Used by |
|---|---|---|---|
| headroom-left | 0.17–0.38 | 0.06–0.16 | keyword lockups, diagram roots (21.9s, 31.0s) |
| headroom-center | 0.43–0.65 | 0.11–0.33 | apex graphics, "Apply These" (36.575s), triangle (56.3s) |
| headroom-right | 0.80–0.87 | 0.12–0.30 | "???" (7.6s), giant numeral (38.0s), PIP (11.5s) |
| chest-left | 0.20–0.30 | 0.62–0.66 | promise keywords (5.125s), "Styles" (75.3s) |
| lower-third | 0.25–0.55 | 0.65–0.78 | timeframe lockup (10.0s), "Success Story" (44.0s) |
| on-gesture | pinned to hands | — | "2 Thing / 1 Thing" (36.5s) |

Headroom is the graphics canvas; the chest band belongs to captions +
short-lived keyword pops. Graphics never cover the face.

### 4.2 Element vocabulary

**T1 — Two-tier keyword lockup. [HIGH — ≥12 occurrences, 1 reel]**
Yellow chunky ROUNDED SERIF (Cooper-Black class) for the payload word + heavy
white grotesque for the co-word + tiny white "kicker" connectors, arranged as a
staircase (e.g. 12.9s "You are / **Creating** / **Content** / for your niche").
Sizes: payload 4.5–6%H, co-word ~4%H, kickers ~2%H. Dark soft shadow, no box.
IN: pop in ≤1 frame at the 12fps sampling grid (≤83ms — treat as instant).
OUT: instant replace by the next keyword (~0.9s cadence) or cleared ON a cut.
Occurrences: 5.125, 6.0, 6.625, 9.25, 10.0, 12.9, 21.9, 31.0, 36.575, 38.9,
48.9, 74.6, 75.3s.

**T2 — Additive word-locked stack build. [MEDIUM — one 5-stage build; persistence-across-cut is LOW-CONFIDENCE (1×)]**
DVg 40.0–45.5s: "I figure out what" → +"Top 3" → +"Stories" → +"relate too",
then a chest-slot replace-chain "Emotional" → "Relating" → "Success Story"
(the built stack persists above it), one stage per spoken word at ~1.0s
stagger. The stack PERSISTS ACROSS punch cut #7 at 42.667s — the text layer is
independent of framing (**LOW-CONFIDENCE, 1×** but architecturally important:
graphics are output-space overlays, exactly our compositing model).

**T3 — Word-locked progressive diagram builds, ~1.0s node stagger. [HIGH —
5 builds, 1 reel]**
Every diagram assembles node-by-node locked to the spoken list item:
- Finance Space 3-spoke mind-map, 24.9–26.9s (thin white lines + small yellow bold labels);
- Problem/Stories/Application triangle, 56.3–62.9s (white outline pops, splits into 3 cells at 57.5s, labels land per spoken item);
- 6-thumbnail receipts wall, 78.8–85.8s (~1/s stagger);
- IDEA → 3-shorts tree, 115.9–119.9s;
- the T2 stack, 40–45.5s.
Executable: node land times = transcript word times; stagger 0.9–1.1s; each node
IN = pop (no ease-in slide).

**T4 — Receipts wall (thumbnail grid). [MEDIUM — 2 appearances + recall]**
2×3 grid of REAL screenshot thumbnails of his own shorts, each ~0.15W, rounded
corners + shadow, yellow label under each ("Talking Head", "Green Screen", …),
1/s build stagger (78.8–85.8s), cleared by cut #11 at 87.0s, re-enters FULLY
BUILT at ~93.3–94.5s.

**T5 — Giant numeral. [LOW-CONFIDENCE — 2×]**
White numeral at 13–14%H beside the step lockup: 38.0s "1" (headroom-right) +
"Your Life & Career"; 48.9s "2" (x≈0.1) + "Learn how to Speak on Camera" with
staged completion (+"Camera" at 49.9s, +1.0s).

**T6 — Gesture choreography. [MEDIUM — 4 occurrences, 1 reel]**
The body interacts with the graphics layer: "2 Thing"/"1 Thing" labels pin to
his two raised hands (36.5s, ~1.2s); he reaches up and "grabs" the triangle apex
(58–59s); the Finance diagram whip-exits right WITH motion blur synced to his
arm swipe riding cut #5 (30.417s, ~0.35s); IG credibility cards enter on an
upward arm sweep (139.7s). Requires hand-position anchoring we don't have —
gap G8. The whip-exit-with-motion-blur itself is **LOW-CONFIDENCE (1×)**.

**T7 — Exit rules. [HIGH — 7 verified exits]**
A graphic exits INSTANTLY, two legal ways: (a) cleared ON a cut (14.5, 87.0,
99.79, 126.29s — 4×), or (b) instant pop-out mid-hold (33.5, 45.5, 66.0s — 3×).
NEVER a fade-out or slide-out. (Sole exception: the one whip-exit, T6.)
Executable: comp out-animation duration = 0; the compositor clears on the
window end or the cut instant.

**T8 — Build once, recall instantly. [LOW-CONFIDENCE — 2×]**
A previously-built diagram re-enters FULLY BUILT as a callback riding a cut:
triangle complete at 70.125s on "boom, in that order" (cut #10); receipts wall
complete at ~93.3–94.5s. Executable: comps need a `state=final` variant (skip
build stagger) — gap G7.

**T9 — Receipts over claims. [MEDIUM — 3 occurrences]**
Proof is always a REAL screenshot, never a drawn stat: 6 labeled thumbnails of
his actual shorts as the styles list (78.8s), a real 77.3K-view short as the
ideas receipt (98s), his real IG profile card (299K followers) at the CTA
(139.7–143s).

**T10 — Speed over polish (anti-rule). [MEDIUM — 4 on-screen typos]**
"Narative", "relate too", "Comming", "WORHT" — the text is hand-authored fast.
Do NOT replicate typos; DO replicate the implication: plain hand-set lockups
beat over-designed cards. (Our FRAME.IO REVIEW pass would flag all four.)

**T11 — Meme/movie PIP cutaway. [LOW-CONFIDENCE — 1×]**
11.5–14.5s: movie-clip PIP top-right, ~0.35W × 0.07H, rounded + shadow, pops in
on the relatable-status beat, cleared by the cut.

---

## 5. Music doctrine

**M1 — A music bed runs under the ENTIRE reel. [HIGH — 6/6, heuristic detector
at medium confidence each time, but unanimous]**
Encoded as `pacing_punch.music = True` (advisory; plan.music enables it).

**M2 — Master loudness is pinned. [HIGH — 6/6 measured]**
Integrated −14.5…−14.7 LUFS across all six masters (0.2 LU total spread) — our
`AUDIO.lufs_target = -14.0` is compatible. True peak −0.7…+0.4 dBTP: two reels
EXCEED the −1.5 delivery ceiling (DQr −0.0, Daf +0.4) — do NOT copy that;
keep our TP ceiling.

**M3 — No true silence, gaps stay lit. [HIGH — 6/6]**
Silence ratio 0.000 with 0 gaps in every reel; loudness floor p10 −15.3…−16.5
LUFS vs speech median p50 −12.3…−12.9 → the bed sits roughly **3±1 LU under the
dialogue median** in speech gaps. That is a much hotter bed than our default
(`AUDIO.music_gap_db` 10–12 dB rise-in-gaps / 18–20 dB duck): punch reads as a
gentle, constant bed with little audible ducking. Heuristic-derived (the study's
music call is a heuristic, not a classifier) — start at gapDb ≈ 10 and mix
toward the measured floor by ear. **[MEDIUM as an executable number]**

**M4 — Heavily compressed mix.** Crest factor 6.7–7.7 dB, 6/6 — mastered-music
density. Our loudnorm two-pass already lands in this family.

---

## 6. The executable profile (wired)

`producer_config.MODES["short"]["pacing_punch"]`, selected by
`target.pace == "punch"` (resolver `plan_lint_motion._pacing_profile` maps
`target.pace` → `pacing_<pace>`):

| Key | Value | Source |
|---|---|---|
| `min_changes_per_min` | 10.0 | §2 C1 — cuts/min median 9.9 (6/6) |
| `max_still_gap_s` | 20.0 | §2 C6 — longest-static median ~19s (6/6) |
| `hook_front_load` | 1.3 | §1 H2 — front-load lives in the graphic layer; cut density in 0–10s is NOT reliably higher (talking-head-class relaxation) |
| `state_changes_per_min` (advisory) | 70.0 | §0 — 51–89 states/min (6/6); the brain paces the caption+shout layers to this, the lint does not read it |
| `music` (advisory) | True | §5 M1 — 6/6 reels carry a bed |

Plan-authoring checklist for a punch short (brain-side, from §§1–5):
transitions track EMPTY (C2) · every punchIn rides a cut, alternating direction,
step 1.05–1.28 (C3) · cuts snap to pivot-word starts (C4) · no aliveness creep
(C5) · whisper captions minimal/no-karaoke (§3) · payload nouns promoted to
headroom lockups with ~1.0s stagger builds (§4) · graphics exit instantly, on
cuts where possible (T7) · music bed on (§5).

---

## 7. LOW-CONFIDENCE register (seen <3 times — re-verify before templating)

| Rule | Seen | Where |
|---|---|---|
| H1 blurred-roadmap rack-focus cold open | 1× | DVg 0.0–1.6s |
| H3b "??? → 10X" spatial goal diagram + arrow stroke-draw (0.4s) | 1× | DVg 7.6–10.4s |
| T2b text stack persists across a punch cut | 1× | DVg 42.667s |
| T5 giant numeral (13–14%H) step markers | 2× | DVg 38.0s, 48.9s |
| T6b whip-exit with motion blur riding a cut (~0.35s) | 1× | DVg 30.417s |
| T8 build-once / recall-instantly (fully-built re-entry) | 2× | DVg 70.125s, ~93.3s |
| T11 meme/movie PIP cutaway card | 1× | DVg 11.5s |
| C5b SSIM 1.000 tripod measurement | 1 reel | DVg 20.5–29s, 104.0–110.7s |

Everything in §§0, 2 (C1, C3, C6), 3, 5 is corroborated across ≥3 reels or ≥5
in-trace occurrences. The deep trace exists for ONE reel — the next
producer-study pass should burst-trace a second reel (DQrbyYRDZGh, the
15.3-cuts/min outlier) to promote/demote this register.

---

## 8. Catalog gaps — what `templates/motion/compositions/` cannot express yet

Listed for the next wave; DO NOT build in this change. Existing near-misses
noted so the builder extends rather than clones.

- **G1 · display-serif "shout" font token + lemon-yellow.** `tokens.css` has only
  Inter 400/700 (base64) + Georgia italic accent. T1 needs a chunky rounded
  display serif (Cooper Black class — e.g. embedded Chunk Five / Cooper-Hewitt
  Heavy) as `--font-serif-display`, an 800/900 grotesque weight, and the yellow
  (evidence "bright lemon-yellow"; existing `--gold: #FFD400` is close — verify
  against frames before adding a second token).
- **G2 · whisper-caption preset.** `CAPTIONS["MINIMAL"]` is 80px w/ gold
  serif-italic accent words. §3 needs a variant: ~38px (2%H), NO accent color,
  NO karaoke, sentence case, y-center ≈0.57H, cue length 0.25–0.9s, 1–3 words.
- **G3 · keyword-lockup comp (T1).** `text-element.html` is one string, one
  color, house fade/slide-in. Needed: multi-token staircase lockup (kicker 2%H /
  serif payload 4.5–6%H / white co-word 4%H), per-token colors, IN = 0-frame pop,
  OUT = none (compositor clears), replace-chain support (~0.9s cadence).
- **G4 · additive stack-build comp (T2).** `list-build.html` is close (per-item
  land times) but renders check/number chip rows on a card look, eased entrances,
  house fade-out. Needed: bare-text additive stack, mixed styles per stage,
  pop-in per stage, zero exit animation.
- **G5 · overlay mind-map + triangle diagram (T3).** `whiteboard-map.html` is a
  FULL-FRAME OPAQUE graph-paper takeover (own-screen). Punch's spokes/triangle
  are TRANSPARENT overlays on the talking head: thin white 2px connectors,
  staggered ~1.0s node pops, yellow/white labels, no card, no canvas. Triangle
  (3-cell + per-cell labels) has no comp at all.
- **G6 · receipts-wall comp (T4).** No thumbnail-grid comp exists. Spec: 2×3
  grid, image slots ~0.15W, radius ~16px + shadow, yellow label per cell, 1/s
  build stagger, `state=final` instant variant (see G7).
- **G7 · `state=final` recall variant (T8).** System capability: any build comp
  needs a variables flag that renders the FULLY-BUILT end state from frame 0 so
  a callback re-entry skips the stagger. (LOW-CONFIDENCE rule — cheap to add as
  a convention when touching G4–G6.)
- **G8 · gesture-pinned anchors (T6).** `MOTION["face_anchors"]` stops at
  faceBBoxNorm. Hand-pinned labels need per-window hand keypoints (pose pass) +
  an `on-gesture` anchor. Biggest infra lift; park unless a second reel
  confirms frequency.
- **G9 · rack-focus reveal at full canvas (H1).** `blur-tease.html` blurs an
  asset INSIDE a white card with an accent label. H1 needs the frameless
  variant: full-canvas transparent comp, blur 24px→0 over 1.6s, no card, no
  label. (LOW-CONFIDENCE rule — verify first.)
- **G10 · pop/whip animation tokens.** House motion language is fade/slide
  (power3.out) with self fade-outs. Punch needs shared tokens: `pop-in` (≤83ms,
  scale 0.92→1.0 max), `instant-out` (0ms), `whip-exit-right` (~0.35s + motion
  blur, LOW-CONFIDENCE). Comps above should consume these instead of hand-rolled
  eases.
- **G11 · media PIP card comp (T11).** Rounded-corner PIP that PLAYS a clip
  (~0.35W), top-right headroom, shadow. Our b-roll lane is full-frame inserts;
  `canvas-pip-list` is a takeover. (LOW-CONFIDENCE rule.)
- **G12 · giant-numeral comp (T5).** White numeral 13–14%H + adjacent lockup
  slot. Could be a G3 variant rather than a new comp. (LOW-CONFIDENCE rule.)

Near-misses that likely need NO new comp: `avatar-bio-card` covers the IG
credibility-card beat (T9 CTA) with restyle; `whiteboard-connector` may cover
the 0.4s arrow stroke-draw (H3b) as an overlay variant.
