# RESTRAINED_STYLE.md — the restrained SIMPLE-CUTS grammar (3-reel granular synthesis)

**September 10 scope note:** the measurements below describe this specific July
cohort. They are not a creator-wide prohibition on reframes, inserts or framework
cards. A different three-reel sample includes those choices; see
[Shorts style selection](SHORTS_STYLE_SELECTION_2026-09-10.md). Preserve the
historical measurements and pinned jobs; choose new treatments from the actual
source and brief rather than imposing these cohort rules universally.

**Creator:** restrained (reference corpus `~/ProjectSniper/_references/restrained/`) —
podcast-clip + selfie shorts; the on-screen brand promise is "BUILD A BRAND
THAT STANDS OUT".
**Corpus:** 3 reels, 36.5–62.9s, all 1080x1920 9:16, total 146.3s / **9
eye-verified cuts** / 3 graphics / 193 caption cues.
**Method:** per-reel granular traces — fingerprint index + scdet re-detect +
ORB zoom traces + caption-band census + EBU audio passes + spectrograms, every
cut and graphic event verified by eye on 1fps/8fps/12fps/native-fps sheets
(evidence: scratchpad `restrained_trace/`, studies at
`_references/restrained/<id>.study/`). **Fresh-pixel spot-check 2026-07-09:** six
rules re-verified against new frame extractions before this doc shipped — see
§10.

This is the **restraint pole** of the measured corpus — the third grammar
beside `scripts/producer/docs/findings/PUNCH_STYLE.md` (locked-tripod
punch-cut shorts) and `docs/studies/MEASURED_EDIT_GRAMMAR.md` (pro long-form). What
PUNCH does with cuts + a shout layer, RESTRAINED does with captions alone.

**Confidence policy:** every rule carries its sighting count and cites
reel + timestamp. A rule seen **<2 times** is flagged **LOW-CONFIDENCE** —
treat as hypothesis, re-verify before templating. 3/3 reels = HIGH; 2 reels =
MEDIUM.

Reel IDs (short form used below):
**DaeF** = DaeF86Ivott (46.84s @23.976 — two-person podcast clip, "Every piece
of content should pass this test"),
**DaN** = DaNyk2exmcC (62.93s @29.97 — handheld car-selfie, "Why Experts Fail
At Content"),
**DWA** = DWASWqDkqEU (36.54s @29.97 — locked studio wide at the mic, "BUILD A
BRAND THAT STANDS OUT").

---

## 0. Corpus numbers (eye-verified)

| Reel | Dur s | Cuts | Cuts/min | Cut kind | Zooms | Graphics | Caption cues | Cues/min | LUFS int | TP dBTP | Crest | Music |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DaeF | 46.84 | 8 | 10.25 | 4 reaction-cutaway PAIRS (0.25–0.87s inserts) | 0 (ORB 0.999–1.000) | 1 (thesis card 7.37s) | 64 | 82 | −14.6 | — | 6.95 | **NO** (verified) |
| DaN | 62.93 | 1 | 0.95 | mid-clause jump cut (eraser) | 0 | 1 (title badge, full reel) | 76 | 72.5 | −14.2 | 0.0 | 7.1 | **NO** (verified) |
| DWA | 36.54 | 0 | 0.0 | — | 0 (bg patch RMS 0.5–2.5) | 1 (title lockup, full reel) | 53 | 87 | −14.1 | −1.0 | 5.84 | **NO** (spectral) |

**The invariant that survives from the other two grammars:** the on-screen
text/state layer churns at ~**72.5–87 cues/min** (3/3) — squarely inside
punch's 51–89 states/min band — and every cue is **word-locked to speech**.
The knob that changes per grammar is WHICH layer carries the churn: pro
long-form = graphics, punch = cuts + lockups, **restrained = captions only**.

**Instrument warnings (3/3):**
- The fingerprint "music: likely" heuristic voted wrong on ALL THREE reels —
  compressed podcast/cab mastering (crest 5.8–7.1) lights the crest/floor
  votes. Spectral-verify speech gaps before trusting the music vote (DaeF
  8.04–8.53s gap measures −52.8dB dark across the spectrogram; DWA's
  21.3–21.9s gap shows room tone but zero harmonic/rhythmic structure).
- 2fps pHash state counts mis-read caption-only reels both ways: DaN
  overcounts true text cadence ~25% on handheld footage (90.5 vs 72.5/min);
  DWA undercounts 5x (11 states vs 53 cues — a 3.6%H caption band doesn't
  move global pHash). Use a caption-band census.
- DWA `face_present=false` is a false negative — the face is ~7%H in the
  full-body wide, under the detector floor. Face-anchored planners silently
  no-op on this framing.

---

## 1. Hook anatomy

**H1 — The thesis graphic IS the hook, pinned from frame 0. [3/3 — HIGH]**
DWA: "BUILD A BRAND / THAT STANDS OUT" two-line maroon lockup fully present at
frame 1 (0.033s) → last frame, zero animation. DaN: red two-chip title badge
"Why Experts Fail / At Content" at frame 0 → final frame, pixel-static
(spot-checked: bbox y 0.672–0.766 identical at 0.03/15/30.5/45/62.8s). DaeF:
black thesis card "Every piece of content should pass this test" on frame 0,
held 7.37s while he talks PAST it (curiosity object, not transcription), then
instant pop-out (verified present 7.334s → gone 7.417s, ≤2 frames). There is
no cold-open build: the promise is the wallpaper.

**H2 — Cold open mid-thought, zero production. [3/3 — HIGH]**
DWA opens mid-sentence ("every bro online…") with caption + title already on
at frame 1; DaN opens on a question ("You know what's really funny?") with 0
cuts in the first 10s; DaeF's card + captions are on at frame 0 over an
unbroken take. Cuts in the first 10s across the corpus: {0, 0, ~2}. The edit
pretends it was always running.

**H3 — The cadence is FLAT: the hook is only ~8% denser. [measured 3/3]**
DaN: 13 cues in the first 10s (78/min) vs 72.5/min overall = 1.08x. DWA: no
front-load at all (cue cadence near-constant across 36.5s). This is the
opposite of punch H2 (graphics-carried front-load) and the longform 2.35x
envelope — encoded as `pacing_restrained.hook_front_load = 1.0`.

---

## 2. Cut grammar — the cut is an ERASER or a REACTION, never an energy beat

**C1 — Cut rate floor is ZERO. [3/3 — HIGH]**
0 cuts / 36.54s (DWA, one take, verified by scdet@10 + scdet@0.015 + bg-patch
RMS 0.5–2.5 vs frame0), 1 cut / 62.93s (DaN), 8 cuts / 46.84s (DaeF — and all
8 are 4 cutaway pairs over ONE unbroken speaker take; the speaker holds 94.6%
of screen time, longest hold 16.2s). Encoded as
`pacing_restrained.min_changes_per_min = 0.0`.

**C2 — The utility jump cut: an eraser, hidden under a cue swap. [1x —
LOW-CONFIDENCE]**
DaN ~29.82s (spot-check corrected from the trace's 29.77s; hard jump between
frames 29.800→29.834): a mid-clause splice ("…what you have achieved | would
get…") removing a breath/flub in the same setup. The caption cue swaps ON the
cut instant, which conceals the seam. This is the OPPOSITE of punch C4
(pivot-word energy cuts): here a cut is subtraction, not punctuation.

**C3 — Reaction-cutaway pairs: 0.25–0.87s B-cam inserts of a listening human,
video-only over continuous speech. [4 pairs, 1 reel — LOW-CONFIDENCE]**
DaeF: all 8 cuts are 4 flash cutaways to the listener's reaction shot over one
unbroken take — B-roll-of-a-human punctuation, not punch-in energy. 3 of 4
cutaway OUTs land within ±1–2 frames of a new clause's caption-cue start
("Are they going", "So I can say", "And the"), twice with the caption LEADING
the cut by ~1 frame; returns are looser (2 of 4 mid-cue). Audio is untouched
(no J/L work, one breath gap kept).

**C4 — The camera may hold the ENTIRE reel. [3/3 — HIGH]**
Longest zero-cut, zero-graphic-entrance stretch: DWA 36.5s (the whole reel),
DaN 33.1s, DaeF 16.2s. The hold is legal ONLY because the caption layer never
stops (§4) — encoded as `pacing_restrained.max_still_gap_s = 40.0` (above the
36.5s measured max; effectively OFF).

**C5 — Cuts snap to caption-cue starts to hide seams. [2 reels — MEDIUM]**
DaN's one cut swaps its cue on the cut instant (verified); DaeF's cutaway OUTs
ride clause-start cues (C3). Executable: when a restrained plan cuts at all, snap
the cut instant to a cue boundary.

---

## 3. Zoom grammar

**Z1 — ZERO. No punch-ins, no creep, no ramps. [3/3 — HIGH]**
DaeF: ORB similarity scale 0.999–1.000 across every insert boundary and every
long hold (227–967 inliers) — the "punch-in" the eye sees is the subject
leaning into the mic. DWA: pixel-stable tripod 36.5s. DaN: handheld phone in a
moving truck — motion is ambient, not editorial. Aliveness comes from the
speaker's own physicality (DaeF hand-whip at 36.1s trips scdet; DWA mime beats
at 16.0/20.5/22.0/24.4s; DaN near-constant gestures, face area swinging
0.07–0.20 organically). Executable: `punchIns` track EMPTY, no creep lane.

---

## 4. Caption system — the retention engine

The ONLY moving layer (3/3). Word-locked verbatim transcript in 1–5 word
bites; a Deepgram/Whisper word-timing pass grouped into 1–5 word cues at
0.25–1.4s each reproduces it exactly (DWA verified 14/14 scdet caption events
land on cue starts).

**CAP1 — Cue shape + cadence. [3/3 — HIGH]**

| Property | Value | Evidence |
|---|---|---|
| Cues/min | 72.5–87 | DaeF 82 · DaN 72.5 · DWA 87 |
| Cue length | 0.25–1.4s (DWA median 0.625s, p25 0.5 / p75 1.0; DaeF mean 0.73s) | DWA cue table · DaeF |
| Words per cue | 1–5, median ~3, always one line | DWA ≤0.69W · DaN 1–4 · DaeF 1–5 |
| Throughput | ~226 wpm verbatim | DaeF |
| Coverage | ~98% of runtime | DWA 35.8/36.5s |

**CAP2 — Face + treatment: whisper layer, NOTHING promoted. [3/3 — HIGH]**
White #FFFFFF grotesque (DWA medium weight, DaeF/DaN heavy), sentence case,
verbatim punctuation kept (DaeF), soft dark drop shadow, NO box, NO outline
weight, NO karaoke, NO word-highlight, NO color/bold emphasis, NO emoji.
Profanity ships uncensored (DWA "full of shit" @7.6s, "fucking fake plant"
@4.9s). Unlike punch there is NO shout layer to promote into — emphasis is
carried by the speaker's delivery, full stop.

**CAP3 — Geometry: center-x, one line, pinned y per reel. [3/3 — HIGH,
per-reel y]**
- DWA: y-center **0.458H** (chest/mic band; spot-checked 0.457, glyph top
  y=846–851px across 9–24.8s), cap 2.5%H (48px; measured 2.66–3.2%H with
  ascenders/descenders).
- DaeF: TOP-anchored **y=0.588H** (spot-checked 0.5875), ~3.3%H heavy.
- DaN: top edge LOCKED **y=0.6151H** (spot-checked 0.6146–0.6177 across five
  samples), cap 2.9%H.
The band is y 0.46–0.65 depending on framing; the anchor is PINNED for the
whole reel, never floats.

**CAP4 — Animation: instant both ways; fade-out ONLY into silence. [2 reels
measured — MEDIUM]**
DWA frame-verified at 29.97fps: cue→cue = hard replace ≤1 frame
(12.917→12.950); re-entry after silence = instant pop (21.984→22.017); exit
INTO a speech pause = the reel's only soft event, a ~0.30s/9-frame linear
fade-out (20.984→21.284), used once. DaN: replace ≤83ms, zero entrance
animation anywhere. DaeF: instant replace both ways.

**CAP5 — The caption GAP is a move: negative churn as emphasis. [1x —
LOW-CONFIDENCE]**
DWA 21.28–22.00s (0.72s): captions vanish exactly while he silently mimes the
polar-bear beat, then pop back on the next word (spot-checked: absent at
21.5/21.8s, back at 22.1s). The edit gets out of the way of the physical joke.

**CAP6 — Verbatim-over-groomed (anti-rule). [2 reels — MEDIUM]**
DaeF ships a live typo ("than it's" for "then it's" @14.7s) and keeps his
stutter ("which is is it"); DaN keeps 13 breath gaps of 0.27–0.49s. Hand-
authored fast, zero smoothing — same T10/E14 speed-over-polish family as
punch. Do NOT replicate the typo; DO replicate verbatim-over-groomed.

**CAP7 — Footnote/asterisk aside. [1x — LOW-CONFIDENCE]**
DaeF: "And then Trevor\*" + "\*my content director" at 1.4%H below the cue,
entering/exiting with it — an editorial aside as a mini-caption.

---

## 5. Graphics vocabulary — the graphics budget is ONE

Each reel carries exactly ONE graphic (3/3). Zero entrance animation, zero
exit animation (one instant pop-out), zero motion during hold.

**G1 — Persistent title chip / lockup (full-reel hold). [2 reels — MEDIUM]**
- DaN: two stacked rounded chips, core **#c3292f** (spot-check median
  #c4292f), white extra-bold text, block y **0.672–0.766H** / x 0.198–0.795,
  pixel-static frame 0 → final frame (bbox identical at five samples spanning
  the reel).
- DWA: two-line all-caps lockup, heavy chunky grotesque, deep maroon
  **#3D1A20–#4A2326** (spot-check glyph mean #492326) on the studio wall
  (#B0B5B4–#BDC3C2 depending on lighting gradient), block bbox
  [0.119, 0.101, 0.876, 0.182], line1 cap 3.75%H / line2 3.3%H, zero
  animation for 36.5s (title-patch RMS ~1.7–5 vs frame0).
The thesis stays pinned the ENTIRE ride — no comp in our catalog holds 60s+
(gap CG1).

**G2 — Cold-open thesis card (~7.4s hold, instant out). [1x —
LOW-CONFIDENCE]**
DaeF: black card ≈0.76W x 0.18H, LOWER-MID zone (below the caption line, y
≈0.66–0.84), white heavy text, on frame 0, held 7.37s while he talks past it,
pop-out ≤2 frames (verified 7.334→7.417s). States the promise as a curiosity
object.

**G3 — Real-asset restraint: no receipts, no pills, no diagrams, no PIP, no
b-roll. [3/3 — HIGH]** The DaeF edit adds exactly TWO things to raw footage:
burned captions and 4 reaction inserts + 1 card. That is the entire kit.

---

## 6. Audio doctrine

**M1 — NO music bed. [3/3 — HIGH as "no bed"; the DWA case is spectral-only]**
All three fingerprints voted "music likely" and all three are false positives:
DaeF's 8.04–8.53s speech gap goes dark across the whole spectrogram
(−52.8dB mean); DaN's spectrogram shows speech + compressed cab rumble only,
13 sub-−35dB gaps; DWA's 21.3–21.9s gap stays lit with broadband room tone but
shows no harmonic/rhythmic structure (crest 5.8 on pure dialogue = brutal
compression lighting the floor — ear-check before hard-coding). Encoded as
`pacing_restrained.music = False`.

**M2 — Master numbers. [3/3 — HIGH]**
Integrated −14.1…−14.6 LUFS — same family as the punch 6/6 pin and
compatible with our `AUDIO.lufs_target = -14.0`. Crest 5.8–7.1 =
mastered-density compression on raw speech. True peak: DaN hits 0.0 dBTP,
EXCEEDING the −1.5 delivery ceiling — same anti-rule as punch M2, keep our
TP ceiling.

**M3 — Breath gaps are LEFT IN; audio is a single untouched take. [2 reels —
MEDIUM]** DaN keeps 13 gaps of 0.27–0.49s; DaeF keeps a breath gap and runs
continuous speech under all cutaways (video-only inserts). DWA: silence ratio
0.000 but zero cuts to have trimmed. Dead-air surgery is NOT part of this
grammar the way it is for punch (255–260wpm stripped) — tighten only true
flubs (C2).

**M4 — Zero SFX, zero J/L work. [3/3 — HIGH]** Nothing to mark; no whooshes,
no transition sound, no audio edits at the one cut/inserts.

---

## 7. RESTRAINT — what restrained does NOT do (vs PUNCH_STYLE)

The NOT-list is the style. Verified by eye across all three reels (209 frames
DaN, 292 caption-band frames DWA, full grids DaeF):

| Device | PUNCH (6-reel measured) | RESTRAINED (3-reel measured) |
|---|---|---|
| Visible cuts | 17.2/min median, tight↔wide punch pairs ±12–45% | **0–1 utility cuts** (+ DaeF's 4 reaction cutaways); no punch grammar at all |
| Zoom | eased pushes +3–19%/s into payoffs, panel self-drift | **ZERO** (ORB 0.999–1.000) |
| Transitions | 6 softened joins/623s inside insert material | **ZERO** |
| Shout/keyword layer | yellow serif lockups, word-append builds, climax words | **NONE** — no keyword promotion, no yellow, no builds |
| Caption emphasis | tier-A amber keywords from first frame | **NONE** — plain white, zero color |
| Karaoke | zero (shared) | zero (shared) |
| Receipts/pills/grids | view-pill rows, tilted screenshot cards, 2x2 grids | **NONE** |
| Takeovers/b-roll/PIP | blur+desat takeovers, UI takeovers, PIP cards | **NONE** (reaction cutaway is a HUMAN, not an asset) |
| B/W grade operator | 6 instances / 4 reels | **NONE** |
| Music bed | 6/6, ~3 LU under dialogue | **NONE, 3/3** (verified false positives) |
| SFX | optional pops/thumps (2 reels) | **NONE** |
| Entrance animation | pop ≤2f, springs 0.15–0.35s, staggers | **NONE** — graphics simply EXIST at frame 0/1 |
| Outro | clean-down hold ≤12s, save-CTA bookmarks | **hard end mid-hold, no CTA, no endcard** (DWA ends on a held cue; DaN hard-ends; DaeF adds nothing) |
| Dead-air stripping | full (no gap >0.35s) | breath gaps KEPT (13x DaN) |
| Graphics budget | ~30 events/reel | **exactly 1** |

What carries retention instead (3/3): caption churn at 72.5–87 cues/min + the
pinned thesis graphic + the speaker's physical performance + (DaeF) 4 reaction
cutaways. Restraint is not a cheaper punch — it is a different instrument.

---

## 8. LOW-CONFIDENCE register (seen <2 times — re-verify before templating)

| Rule | Seen | Where |
|---|---|---|
| C2 utility jump cut hidden under a cue swap | 1x | DaN ~29.82s |
| C3 reaction-cutaway pairs, cue-start snapped | 1 reel (4 pairs) | DaeF |
| CAP5 deliberate caption blackout on a performance beat | 1x | DWA 21.28–22.0s |
| CAP7 footnote/asterisk mini-caption | 1x | DaeF ("Trevor\*") |
| G2 cold-open thesis card ~7.4s, instant out | 1x | DaeF 0–7.37s |
| CAP4b 0.30s fade-out into silence (vs instant) | 1x | DWA 20.984–21.284 |
| DaeF caption top-anchor y=0.588 (vs DaN 0.615 / DWA 0.458) | 1 reel each | per-reel pins |

Per-event rules from single reels follow the PUNCH_STYLE policy: hypotheses
until a second sighting. The three-reel invariants (§0, C1, C4, Z1, CAP1–CAP3,
G3, M1–M2, §7) are the doctrine.

---

## 9. The executable profile (wired)

`producer_config.MODES["short"]["pacing_restrained"]`, selected by
`target.pace == "restrained"` (resolver `plan_lint_motion._pacing_profile` maps
`target.pace` → `pacing_<pace>` generically — no new wiring needed).

| Key | Value | Source |
|---|---|---|
| `min_changes_per_min` | 0.0 | §2 C1 — measured floor IS zero cuts (0/1/8 per reel) |
| `max_still_gap_s` | 40.0 | §2 C4 — longest zero-change hold 36.5s (an entire reel) |
| `hook_front_load` | 1.0 | §1 H3 — cadence flat (hook ~8% denser); the t=0 thesis graphic clears the ratio |
| `state_changes_per_min` (advisory) | 80.0 | §4 CAP1 — caption cues 72.5–87/min (3/3); the brain paces the CAPTION layer to this, the lint does not read it |
| `music` (advisory) | False | §6 M1 — 3/3 spectral-verified no bed |

**Plan-authoring checklist (brain-side, from §§1–7):**
one thesis graphic at t=0 — full-reel title chip OR ~7.4s cold-open card,
zero animation (H1/G1/G2) · `transitions` track EMPTY · `punchIns` track
EMPTY, no creep (Z1) · music OFF (M1) · cuts ONLY to remove flubs/dead-air or
as reaction cutaways, snapped to caption-cue starts (C2/C3/C5) · keep breath
gaps (M3) · whisper captions: verbatim 1–5 word cues at 0.25–1.4s, white, no
karaoke/color/box, center-x, pinned y in the 0.46–0.65 band, instant replace,
fade-out only into silence (§4) · hard end, no CTA, no endcard (§7) ·
−14 LUFS master, keep the −1.5 dBTP ceiling (M2).

---

## 10. Spot-check record (2026-07-09, fresh frame extractions)

Six rules adversarially re-verified against new ffmpeg extractions + PIL pixel
measurement before this doc shipped:

1. **DWA title persistence/geometry/color** — patch RMS ~5 vs frame0 at
   0.03/9/18/27/36.4s; glyph mean #492326. CONFIRMED (wall bg measured up to
   #BDC3C2 at the frame top — lighting gradient, recorded in G1).
2. **DWA caption geometry** — glyph top y 846–851px, cap 2.66–3.2%H, y-center
   0.457, centered, no box. CONFIRMED.
3. **DWA caption gap** — absent at 21.5/21.8s, back at 22.1s. CONFIRMED.
4. **DaN badge + caption lock** — badge bbox y 0.672–0.766 pixel-identical at
   five samples across 62.9s, core #c4292f; caption top edge 0.6146–0.6177.
   CONFIRMED.
5. **DaN single jump cut** — hard jump between frames 29.800/29.834s
   (mean-diff 33.6 vs ~5 motion noise), caption swap ON the cut. CONFIRMED;
   **timestamp corrected 29.77 → ~29.82s** in C2.
6. **DaeF thesis card** — present frame 0 → 7.334s, gone by 7.417s (pop ≤2f);
   caption top edge 0.5875H. CONFIRMED (card zone recorded as LOWER-MID,
   ≈0.76W x 0.18H, in G2).

---

## 11. Which style calibrates the LIGHT-short preset — recommendation

**RESTRAINED calibrates `light`; PUNCH stays the calibration for `produced`.**

The `edit_scope` ladder's `light` scope (base cut + captions + subtle motion,
graphics/transitions OFF) is, to within one comp, exactly the measured restrained
kit — and restrained is the only measured grammar that is ON-STYLE with the
engaging lanes dark. Concretely, a light short should default to:

- `target.pace = "restrained"` → `pacing_restrained` floors (a 0-cut 40s hold is
  on-style; today's default floor of 12 changes/min would FAIL every reel in
  this corpus, including one with 8.7M-view-class craft).
- Captions: the restrained whisper-verbatim variant (§4), NOT karaoke — karaoke is
  off-style in BOTH measured shorts grammars (punch CAP1, restrained CAP2); the
  Light preset is where that correction bites first.
- Motion: `punchIns` EMPTY — restrained measures ZERO creep, so `light`'s "subtle
  motion" lane should default to none under this pace (the lane stays
  available for operator asks).
- Music: OFF by default (M1).
- The ONE graphic (H1) is the deliberate exception to "graphics OFF": a
  static thesis title chip is part of the restrained base kit. Until CG1 ships,
  a `light` plan approximates it with a hook card — but note the hold-time
  gap below.

Punch, by contrast, is a heavy produced grammar (17.2 cuts/min, ~30
graphic events/reel, music bed) — it calibrates `produced`/`full` shorts, not
`light`.

### Catalog gaps (specific, minimal — do NOT build in this change)

- **CG1 · persistent-title-chip comp.** Static two-line stacked rounded chips
  (measured #c3292f family / maroon lockup variant), zero animation, held
  frame 0 → final frame. Closest existing: hook-card, but
  `HOOK_CARD.hold_max_s = 6.0` — nothing can hold 60s+. (2 reels, MEDIUM.)
- **CG2 · cold-open thesis-card variant.** Dark card ≈0.76W x 0.18H, LOWER-MID
  zone, ~7.4s hold, instant pop-out. `HOOK_CARD` is white, upper-third, house
  animation — needs a dark/lower/instant-out variant. (1x, LOW-CONFIDENCE —
  spec only.)
- **CG3 · whisper-caption top-pinned variant.** Extends PUNCH_STYLE gap G2
  (which covers this layer almost exactly): `CAPTIONS["MINIMAL"]` minus gold
  accents/karaoke, plus a top-anchored pin (y 0.588–0.615 measured), verbatim
  punctuation + curly-quote typesetting, cap 2.5–3.3%H, and the
  0.30s fade-out-into-silence exit. (3/3 for the layer; the top-pin is
  2 reels.)
- **CG4 · reaction-cutaway lane.** 0.25–0.9s SECOND-SPEAKER (B-cam) video
  inserts, video-only over continuous audio, snapped to clause-start caption
  cues. Our broll/insert lane is full-frame FOOTAGE without cue-start
  snapping or a B-cam pairing concept. (1 reel, LOW-CONFIDENCE — park unless
  podcast-clip sources land.)
- **CG5 · footnote mini-caption.** The "Trevor\*" asterisk aside (CAP7).
  (1x, LOW-CONFIDENCE — spec only, park.)

Pipeline (non-catalog) notes already encoded: pacing credit for caption-state
churn is handled by the `pacing_restrained` floors; the music-vote false-positive
and pHash caption-band instrument warnings live in §0 for the next STUDY pass.
