# SLIDEWARE_STYLE.md — THE SLIDEWARE STYLE grammar (4-reel granular synthesis)

**Creator:** slideware (IG **a reference account**, social-media-marketing educator).
**Corpus:** 4 reels, 35.97–46.74s, all 1080x1920 9:16 @30fps, total **164.7s /
28 hard cuts / ~150 graphic+text events**. Sets: locked-tripod desk (Daix,
Dadm) and handheld outdoor deck (DaiA, DagN) — same grammar in both.
**Method:** per-reel granular traces — fingerprint index + scdet re-runs
(0.3/0.12 thresholds) + 1fps whole-reel contact grids + 8fps hook grids
(0–10s) + 12fps bursts ±0.6s around every cut AND graphic event + 24fps
micro-bursts on the complex enters + full-res 1080x1920 frame reads + PIL
3x3-median pixel sampling for hex tokens + cross-reel state-grid recurrence.
Study indexes: `~/ProjectSniper/_references/slideware/<id>.study/fingerprint.json`.

**Confidence policy** (same standard as
`scripts/producer/docs/findings/PUNCH_STYLE.md`): every rule carries its
sighting count. A rule seen **<3 times** is flagged **LOW-CONFIDENCE** — treat
as hypothesis, re-verify before templating. Counts cite reel + timestamp.

Reel IDs (short form used below): **Daix** = Daix1yuJAP3 (40.87s, indoor desk,
"3 THINGS To Do After Posting"), **DaiA** = DaiA1H9hd0i (41.1s, outdoor,
split-ledger verdict machine), **DagN** = DagN2gkOV8j (46.74s, outdoor,
"5 main types of content"), **Dadm** = DadmBrVjnIA (35.97s, indoor desk,
"How to Tell a STORY in Under 1 Minute").

Wired into the pipeline: `producer_config.MODES["short"]["pacing_slideware"]`
(selected by `target.pace == "slideware"`, generic resolver
`plan_lint_motion._pacing_profile`). Ranked template build list in §11.

---

## 0. Corpus numbers (eye-verified traces)

| Reel | Dur s | Hard cuts | Cuts/min | Takeover share | States | States/min | Int LUFS | TP dBTP | Crest | Bed floor vs speech | Music bed |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Daix | 40.87 | 4 (9.433 / 22.133 / 26.267 / 30.267) | 5.87 | 2 deck sections (~43%) | 25 (fp; ~87 state-events/min true) | ~87 | −14.3 | −0.4 | 7.0 | ~3 LU under p50 | likely |
| DaiA | 41.10 | **0** (one continuous shot) | 0.0 | 0% (ledger instead) | 46 | 67 | −14.6 | −0.3 | 6.7 | ~3 LU (floor −16.0 vs p50 −12.9) | likely |
| DagN | 46.74 | 13 | 16.7 | ~60% (6 lime chapters) | 42 | 54 | −14.3 | +0.1 | 7.2 | ~4 LU (floor −16.7 vs p50 −12.5) | likely |
| Dadm | 35.97 | 11 | 18.35 | 39% (4 takeovers) | 36 | 60 | −14.4 | +0.5 | — | floor −18.3 | likely |

**Medians:** hard cuts/min **11.3** (range 0–18.35 — see §3: cut rate is
format-derived, NOT a tempo) · state-events **54–87/min** (4/4) · plan-level
discrete changes (cuts + graphic entrances, what the pacing lint counts)
**~23–53/min**, leanest Daix ~23/min · integrated **−14.3…−14.6 LUFS** ·
silence ratio **0.000, 4/4**.

**Instrument warning [4/4]:** scdet misses this style in the OPPOSITE way it
misses Punch's: Slideware's camera cuts are big (takeover boundaries, all found)
but her GRAPHIC swaps are invisible to it (Daix soft events at 2.233/8.1/38.8
were graphic swaps, not cuts; DagN's in-slide replace-chains register nothing).
Any pacing audit of an slideware-style cut MUST count state events, not cuts.

---

## 1. The one-token brand system

**B1 — ONE lime does everything. [4/4 — HIGH]**
The same lime is the payload-text color on footage, the full-canvas takeover
background, the transition wash, the CTA outline, the chart fills, and the
ledger titles — pixel-verified identical (±1 hex step) within each reel:
Daix **#C8F800** (glyph = canvas), DaiA **#CDFF00**, DagN **#C9FB00**,
Dadm **#CEFF0A**. One `--lime` token per rebuild; everything else is
black/white/charcoal plus micro-accents. This is the opposite of Punch's
gold-accent-on-dark model — brand cohesion via a single hex.

**Style tokens [4/4 unless noted]:**

| Token | Value | Evidence |
|---|---|---|
| Brand lime | #C8F800–#CEFF0A family, one per reel | pixel-sampled, 4/4 |
| White | #F8F8F8–#FFFFFF (captions, kickers, cards, rules) | 4/4 |
| Canvas-caption charcoal | #303030 (Daix) / #474E4B (Dadm) / #343436–#525053 (DagN) | 3/4 |
| Card white | #FBFBFB–#FDFBFD; slides square-corner (r0–8px), UI mocks rounded (r14px) | 4/4 |
| Dark chip/pill | #0A0A0A–#30373D (view chips ~75–90% alpha) | 4/4 |
| Red fill-in token | #C81018 `(insert …)` template text | DagN + Dadm — 2 reels |
| IG blue | #2078F8–#2A8DFD (mock-UI buttons only) | Daix + DagN — 2 reels |
| Payload font | ExtraBold extended geometric grotesque, ALL CAPS (Archivo Black / Montserrat 900 / Poppins 800 class) — **NOT serif** (vs Punch's Cooper) | 4/4 |
| Kicker/caption font | Poppins/Montserrat-class rounded sans, medium+bold mix, sentence case | 4/4 |
| Shadow | soft black on all text over footage; subtle on thumbs | 4/4 |

---

## 2. Hook anatomy

**AH1 — Frame 0 is FULLY DRESSED; zero entrance animation. [4/4 — HIGH]**
Daix: title lockup ("3 THINGS" lime ~5.5%H + white sub) AND both receipt-row
labels on at frame 0. DaiA: the entire ledger header (two lime column titles +
10 eye-count stat chips + white T-rule) on at frame 0. DagN: promise lockup
"5 MAIN TYPES / Of Content" + chest caption at frame 0. Dadm: 4-thumb proof
wall + 3-tier staircase promise at frame 0. Executable: the hook graphic is
baked into frame 0, no enter animation, cleared by swap or ON the first cut.

**AH2 — Receipts-first transformation promise. [4/4 — HIGH]**
The promise is shown as REAL analytics/thumbnails inside the first second,
never claimed in copy: Daix 10 cropped stat chips ("to go from this" 558/826/…
→ "to this" 2.4M/5.1M/…) pop in alternating rows every ~0.08–0.12s (each ≤42ms)
synced to her finger-counting, 0–0.46s; DaiA 273-vs-5.7M chip contrast readable
before a word lands; Dadm 4 live-playing thumbs with view pills (2.7M/24.9M/
5.6M/2.1M) + a LIVE iOS timer counting 01:00→00:57 making "1 minute" literal;
DagN 5-thumb receipts strip at 0.85s.

**AH3 — The hook is graphics-carried; cut density is LOWEST in the hook.
[4/4 — HIGH]**
Cuts in the first 10s: Daix 0 (first cut 9.433), DaiA 0, DagN 1 (2.167),
Dadm 2. DagN's cuts/10s curve is 1/4/2/4/2 — density RISES in the body.
Meanwhile the graphic/text layer churns ~1 event/s (Daix ~13 state events
0–10s; DagN 8; DaiA teaches its whole format machine by 5s). Executable: never
force cuts into the hook window; demand a dressed frame 0 + ≥1 graphic/text
event per second instead.

**AH4 — First structural payoff lands at ~1.8–2.4s. [4/4 — HIGH]**
Daix lockup→App-Store card swap @2.20; DagN first takeover cut @2.167; DaiA
first verdict cycle opens @2.35; Dadm proof cutaway @1.767. The format is
visible before 2.5s.

---

## 3. Cut engine — takeover alternation

**AC1 — Cuts are SECTION punctuation, not energy. [4/4 — HIGH]**
Every hard cut in the corpus sits on a structure boundary: Daix 4/4 cuts are
lime-deck in/out (9.433/22.133/26.267/30.267); DagN 13/13 are talking-head ↔
slide-chapter seams; Dadm 11 cuts alternate footage ↔ takeover (+1 blooper
beat, +1 proof cutaway); DaiA needs no sections → ZERO cuts in 41.1s. There
are no same-framing punch cuts anywhere.

**AC2 — Cut rate is format-derived: 0–18.4/min. [4/4 — HIGH]**
The rate is a FUNCTION of takeover count, not a tempo to target. Author the
section structure; the cuts fall out.

**AC3 — Two mutually exclusive graphic economies. [4/4 — HIGH]**
(a) **VOLT TAKEOVER deck** [3/4 — Daix, DagN (60% of runtime), Dadm (39%)]:
full-frame lime canvas replaces footage entirely, cleared by the next hard
cut. (b) **PERSISTENT LEDGER** [1/4 — DaiA]: a headroom scoreboard accumulates
every evidence graphic via fly-docks; no takeovers, no cuts. A reel commits to
ONE economy; never both.

**AC4 — Talking-head inserts shrink to breaths between takeovers.
[2/4 — LOW-CONFIDENCE]**
DagN TH inserts run 0.67–1.7s between slide chapters (the SERIES insert is
0.67s); Dadm step-lockup TH beats 1.4–2.6s. The face becomes the punctuation.

**AC5 — Overlay-carried tail: the last cut lands ~10s before the end.
[2/4 — LOW-CONFIDENCE]**
Dadm: zero cuts 25.47→35.97 (10.5s) while three overlay set-pieces churn
(pipeline strip → page riffle + EASIER → comment CTA). Daix: last cut 30.267,
then 10.6s of caption shouts, receipt PIPs, and the notification CTA. DagN's
tail is only 1.9s — not universal.

---

## 4. Camera grammar — the anti-Punch

**AZ1 — ZERO punch-ins, zero zoom steps, zero creep. [4/4 — HIGH]**
Face area constant all reel: Daix ~2.5% on one locked framing for 40.87s; DaiA
face 3–4% with handheld micro-sway only (bbox drift 0.22–0.27W, no digital
move); DagN/Dadm no reframe at any cut. This directly violates the shorts
tight↔wide doctrine (PUNCH_STYLE §2 C5): an slideware plan runs `punchIns` EMPTY
— all motion energy is takeover alternation + graphic churn.

**AZ2 — Transitions ≈ zero: one lime-wash in 164.7s. [4/4 — HIGH; the wash
itself 1x — LOW-CONFIDENCE]**
27 of 28 cuts are 1-frame hard. The single exception: Dadm @4.233, a lime
#CEFF0A wash fades in ~3f to ~95%, hides the cut at peak, exits as a L→R
soft-edge wipe ~4f (0.25s total) — used ONCE, at the hook→steps seam.
Executable: `transitions` track EMPTY; the wash is an opt-in seam token.

**AZ3 — One deliberate framing change: the blooper alt-take.
[1x — LOW-CONFIDENCE]**
Dadm 15.667–16.333: tighter alt take (face +58%) for the self-roast "Loser"
beat, with hand-drawn arrow. A performance beat, not an edit-energy device.

---

## 5. Caption system spec

**ACAP1 — Karaoke sweep rate: ZERO. Color-in-captions: ZERO. [4/4 — HIGH]**
No per-word highlight, no color emphasis anywhere in 164.7s. Our shorts
default (`captions_style: "karaoke"`) is off-style; inline BOLD on a key word
is the only in-line emphasis (DaiA "post fluffy", "takes long").

**ACAP2 — Dual-mode skin, switched by background. [3/4 — HIGH]**

| Mode | Spec | Evidence |
|---|---|---|
| Footage ("whisper") | white #F8F8F8–#FFF semibold, ~1.9–2.4%H, sentence case, soft shadow, NO box; chest band x0.5 y0.58–0.66; 1–4 words, replace-per-cue 0.3–1.2s | Daix y0.58–0.66 · DaiA y≈0.60 0.7–1.3s · DagN chest · Dadm y0.40–0.63 |
| Lime canvas (pill) | white #F8F8F8–#FCFAFB SQUARE-corner rect (r4–8px), charcoal #303030–#474E4B bold ~1.7–1.9%H text, center x0.5; slot y0.75–0.82 (Daix/DagN) or fixed mid-card y0.51–0.59 (Dadm); 2–5 words, replace-per-cue 0.4–1.2s, ON at the cut frame | Daix "here are the metrics" on at 9.433 · DagN 12 cues 35–44.8s · Dadm all 4 takeovers |

The pill exists because white text vanishes on lime — a rebuild MUST switch
caption skin per background (bake the pill into takeover comps).

**ACAP3 — Emphasis is promoted IN PLACE, not to headroom. [3/4 — HIGH]**
The payload word becomes its own cue as giant lime caps INSIDE the caption
band, sandwiched staircase-style by white whisper words: Daix "3 BARS" (6.8%H,
biggest type in the reel) @4.92, "SOLID" @31.0, "FLOPPED" @33.75 (~6.2%H,
hold ~1.5–2s); DaiA promotes payload nouns to the lime lockup layer 19x while
captions never carry them; Dadm "EASIER" (~6.5%H) fade-pops at full size
@31.05. Punch promotes to headroom; Slideware shouts in the caption slot. Shared
law: the whisper layer itself NEVER carries color.

**ACAP4 — Captions go silent when slides carry the words.
[1 reel — LOW-CONFIDENCE]**
DagN runs ZERO captions 12.2–33.6s — the slide content IS the VO text. Daix
instead keeps pill cues running through decks. Default: keep the pill lane on.

---

## 6. Text / graphics vocabulary

### 6.1 Position grid (normalized; measured)

| Zone | Geometry | Used by |
|---|---|---|
| Headroom band | y0.12–0.36 full width | DaiA ledger · Daix PIP slot x0.61–0.90 y0.115–0.445 · receipts strips y0.14–0.35 (Dadm y0.16–0.33, DagN y0.245–0.35) |
| Section-lockup headroom | kicker y≈0.135, headline y≈0.165 (DagN); headroom-left y0.05–0.13 (Dadm steps) | numbered step lockups |
| Chest band | y0.58–0.68 | whisper captions, action payloads ("3 BARS"), caption shouts, CTA lockups (Daix y0.60–0.68, DagN y0.615) |
| Canvas content zone | x0.08–0.92, y0.13–0.80 | all takeover slides (Daix table x0.075–0.925 y0.20–0.71; DagN table x0.14–0.87 y0.13–0.86) |
| Canvas caption-pill slot | x0.5, y0.75–0.82 (or mid-card 0.51–0.59) | §5 ACAP2 |
| Mock-UI bar slot | center x0.5, y0.23–0.31 | Daix notification y0.263–0.308 · DagN follow bar y≈0.23 · Dadm comment bar y≈0.26 |
| Evidence row (footage) | y_c ≈0.72–0.80, ≤0.78W centered | DaiA thumb rows y0.755 · calendar y0.744 |

Graphics never cover the face; the takeover REPLACES the face instead
(operator doctrine: pro graphics are full-frame cutaways, confirmed in a
second creator's grammar).

### 6.2 Animation grammar (frame timings @30fps unless noted)

| Move | Timing | Evidence |
|---|---|---|
| 0-frame pop (lockups, chips, badges, whole slides) | ≤1–2f (≤42–83ms), no scale ramp, no fade | 4/4 — Daix chips ≤42ms · DaiA lockups ≤1f@24 · DagN slides instant on cut · Dadm lockups instant — HIGH |
| Word-locked token stagger | per-token 0.3–0.9s, locked to the spoken word | 4/4 — HIGH |
| Whole-unit sheet fade + settle | ~0.2s (5f@24) opacity + ~2%W settle drift; even a 6-row sheet enters as ONE unit, never row-staggered | Daix table 9.52→9.75 + diagnostic 26.33→26.55 — 2x, 1 reel — **LOW-CONFIDENCE** |
| Fade-cascade (doc/card sets) | per-item opacity 0→1 in 0.17–0.2s, ~0.25s stagger, strict reading order, no motion | Dadm 9-card + 3-column cascades · DagN strip images resolve 3–5f — 2 reels — confirmed |
| Slide-carousel (deck paging) | exit-left + enter-from-right simultaneously ~0.45s (11f@24), settle at end | Daix @12.48 + @18.28 — 2x, 1 reel — **LOW-CONFIDENCE** |
| Phone-card enter | slide-from-right-edge ~0.2s OR scale-settle 80%→100% ~0.2s | Daix @4.79 + @24.07 — 2x, 1 reel — **LOW-CONFIDENCE** |
| Fly-dock (ledger absorb) | group shrink-translate scale 1→0.28 over 0.30s (7–8f), accel-in hard-stop, NO fade, docks to a named column slot | DaiA ×12 — HIGH in-reel, single-reel — verify cross-reel |
| Mock-UI container expand | width ~30%→100% over 0.17–0.25s ease-out, content pops +2f, scripted button state-flip at a beat | Daix + DagN + Dadm (fade 0.3s variant) — 3 reels — HIGH as a class |
| Typewriter | ~0.17s/char + send-press ring + heart morph | Dadm ×1 — **LOW-CONFIDENCE** |
| Page-riffle prop | doc pages flip-drop 0.15–0.5s cadence, curl + settle wobble | Dadm ×1 — **LOW-CONFIDENCE** |
| **EXIT — THE LAW** | **NEVER animated out.** Instant in-place replace, instant clear mid-hold, or cleared exactly ON the hard cut. Exceptions in 164.7s: ONE animated exit (Daix phone PIP slides right 0.17s @8.13) + the one lime-wash (§4 AZ2) | 4/4 — HIGH |

### 6.3 Element catalog

**E1 — Keyword staircase lockup (+ numbered step kickers). [4/4 — HIGH,
~40 sightings]** Kicker white semibold ~1.9–2.4%H sentence case (payload words
bold) / PAYLOAD lime ALL-CAPS ExtraBold extended grotesque 4.2–7.8%H (std 5.5,
hero 7.8 DaiA "DEFINED", verdict variant 3.6) / white co-word ~2%H offset
right-below landing 0.3–0.9s after. Numbered kickers: "#1/#2/#3" (Daix),
"Step #1…#5" (Dadm), "For X Posts" (DagN ×7). Soft dark shadow, no box. IN
0-frame pop word-locked; OUT instant replace (chain cadence 0.31–1.0s) or
clear — never fade. Verdict variant reuses the EXACT column-title string+color
(DaiA ×12).

**E2 — Lime takeover slide deck. [3/4 — HIGH, 12 deck sections]** Full-frame
lime canvas replacing footage ON a hard cut; white or charcoal all-caps header
3.2–4%H y0.18–0.21; content zone §6.1; caption pill riding it; slide 1 enters
whole-unit-fade (Daix) or instant-with-word-locked-cell-pops (DagN table
skeleton instant, 6 example clips pop ≤80ms one per spoken item, stagger
1.2–2.1s) or fade-cascade (Dadm); between slides = carousel (Daix) or
whole-slide instant replace-chain 0.6–1.9s/card (DagN ×5, Dadm); deck cleared
ON the cut back to footage. Optional darker gradient top #96CB07→lime by
y≈0.35 (Dadm).

**E3 — Receipt thumb-cell + eye/view-count chip. [4/4 — HIGH, 60+ chips in
DagN alone]** The signature proof stamp: EVERY receipt thumbnail carries a
dark pill (near-black #0A0A0A–#251F1C ~75–90% alpha, r4–10px, white eye glyph
+ bold count 1.2–1.7%H). Cells are PLAYING clips, never stills (DagN/Dadm
verified frame-to-frame). Layouts: hook strip 1×4–5, grids 2×3/2×4, series
walls 2×6, receipts wall 2×4 0.08W + @handle. Optional label chip above
(olive #697257 semi-opaque r6px). Build: per-cell pops 0.08–0.5s stagger
word-locked, or fully-built on cut.

**E4 — Doc-table card. [3/4 — HIGH]** White #FBFBFB card, square-ish corners
(r≈8px), 1px charcoal rules, bold sans header row (DagN charcoal #525053
header fill), document-sans body — reads as a real doc/table screenshot.
Daix metric-definitions + ratio chart; DagN 6-row type table; Dadm 9 real
Google-Doc screenshot cards (intentionally near-illegible — volume of proof
over readability).

**E5 — Fill-in template card w/ red tokens. [2/4 — LOW-CONFIDENCE]**
White square-corner card, black 900 caps headline ~3%H, bulleted body
~1.15%H with RED #C81018 "(insert …)" tokens, "Example:" + 1–2 playing
thumbs. DagN ×5 replace-chain; Dadm SCRIPT STRUCTURE cards.

**E6 — Phone-walkthrough card (real UI PIP). [2/4 — LOW-CONFIDENCE]**
Real dark app screenshot #0B0D13 ~0.29W pinned headroom corner; enter
slide-from-edge or scale-settle ~0.2s; content INSTANT-SWAPS between app
screens while holding (Daix ×3 swaps incl. her real Insights: 8,139,216
views); LIVE state changes (Dadm iOS timer counts real seconds); exit instant
(once: slide-right).

**E7 — Hand-drawn annotation glyphs. [3/4 — HIGH as a class]**
White or lime wobbly-stroke curved arrows with arrowheads pointing at specific
UI elements inside cards (Daix ×2 incl. the Insights nav icon; Dadm ×3 incl.
"Loser" + the timer); hand-drawn white curly braces under lockups (DagN ×3).
Cheap comp: SVG scribble path anchored to card coordinates.

**E8 — Mock-OS UI CTA. [3/4 — HIGH]** "Fake UI as CTA": Daix iOS follow
notification (white rounded banner x0.28–0.72, gradient-ring avatar, IG
wordmark, @handle, blue #2078F8 Follow) expanding pill→full width ~0.25s;
DagN IG follow bar (0.47W, expand 0.17–0.2s, Follow→Following flip ~2f at a
scripted beat +1.4s); Dadm ManyChat comment-gate bar (0.72W, lime outline,
typewriter "S-T-O-R-Y" ~0.17s/char, pink #EC1455 send → heart morph — the
typed word IS the reel's payload word). Always paired with a "FOLLOW FOR
MORE"-class lime lockup in the chest band + white subline replace-chain.

**E9 — Split-ledger scoreboard + fly-dock. [1/4 reel but ×12 in-reel —
HIGH in-reel, LOW-CONFIDENCE cross-reel]** DaiA's verdict machine: persistent
headroom scoreboard (two lime column titles + 5+5 eye-chips + white T-rules +
center spine x0.5 w4px that GROWS 0.19H→0.357H as rows dock); loop =
caption setup → lime payload lockup → evidence exhibit at chest → verdict
lockup reusing the column title → evidence shrink-flies 0.30s into that
column and STAYS. Chip variants: solid #141A19 / translucent #30373D /
lime-stroke 2px #E0FF59 = winner highlight. The reel ENDS on the completed
mosaic — the payoff is the accumulated frame. Supports build-once-recall
(docked thumbs re-enter fully built in a lime-stroke box @4.83) and live
cell-swap rows (@30.05).

**E10 — Comparison boards. [2/4 — LOW-CONFIDENCE]** DagN "OG | DOUBLE DOWNS"
(black 900 col headers, OG playing thumb 0.19W vs 2×3 mini-grid; thumb sets
RE-FILL instantly every ~1.0–1.2s in sync with the caption pill, 5 sets in
5.2s; 2×2 wall variant with four 0.30W clips playing through). DaiA's ledger
is the persistent cousin.

**E11 — Equation / formula build. [2/4 — LOW-CONFIDENCE]** Dadm
[STORY]+[STRUCTURE]+[FORMAT] builds L→R, 0.2s fades, 0.25s stagger, cream
label chips #F9FFE5, "=" + result doc; slot content swaps ~2s during hold.
Daix V2F formula slide: charcoal extra-bold headline ~3.4%H + 3px WHITE
stroke rect framing the fraction on lime.

**E12 — Typos ship (anti-rule). [2/4 — confirmed]** Daix "got board" /
"your need to study" in the diagnostic sheet; DaiA "stuffs". Same law as
Punch E14: replicate the plain hand-set SPEED, never the typos.

---

## 7. Music + mix doctrine

**AM1 — A bed runs under the entire reel; zero true silence. [4/4 — HIGH]**
Silence ratio 0.000 in all four; heuristic bed call "likely" 4/4. The bed sits
**~3–4 LU under the dialogue median** in gaps (floors −15.9/−16.0/−16.7/−18.3
vs speech p50 ≈ −12.5…−13.2) — the same hotter-than-our-default family as
Punch M3. Start at gapDb≈10 and mix toward the measured floor by ear.

**AM2 — Master numbers. [4/4 — HIGH]** Integrated −14.3…−14.6 LUFS
(compatible with our `AUDIO.lufs_target = -14.0`); crest 6.7–7.2 (mastered
density). True peak −0.4…+0.5 dBTP — TWO reels exceed the −1.5 delivery
ceiling (DagN +0.1, Dadm +0.5): do NOT copy; keep our TP ceiling.

**AM3 — Timing authority is speech, never the beat.** Cuts and graphic events
land word-locked throughout (§6.2); no beat-sync observed. Inherited
unchanged from the Punch doctrine.

---

## 8. LOW-CONFIDENCE register (seen <3 times — re-verify before templating)

| Rule | Seen | Where |
|---|---|---|
| AC4 TH inserts shrink to 0.67–1.7s breaths | 2 reels | DagN · Dadm |
| AC5 overlay-carried tail (~10s no cuts) | 2 reels | Dadm 25.47→end · Daix 30.267→end |
| AZ2b lime-wash transition token (0.25s in/out) | 1× | Dadm 4.233 |
| AZ3 blooper alt-take framing beat | 1× | Dadm 15.667 |
| ACAP4 captions absent while slides carry meaning | 1 reel | DagN 12.2–33.6 |
| Whole-unit sheet fade + settle (5f@24 + 2%W drift) | 2×, 1 reel | Daix 9.52 · 26.33 |
| Slide-carousel paging (0.45s conveyor) | 2×, 1 reel | Daix 12.48 · 18.28 |
| Phone-card slide/scale-settle enter | 2×, 1 reel | Daix 4.79 · 24.07 |
| E5 fill-in template card w/ red tokens | 2 reels | DagN ×5 · Dadm |
| E6 phone-walkthrough PIP w/ content swaps | 2 reels | Daix · Dadm |
| E9 split-ledger + fly-dock (cross-reel) | 1 reel (×12) | DaiA |
| E10 comparison boards | 2 reels | DagN S5/S6 · (DaiA cousin) |
| E11 equation/formula build | 2 reels | Dadm 22.4 · Daix 12.48 |
| Typewriter comment-gate (0.17s/char + heart) | 1× | Dadm 33.97 |
| Page-riffle prop | 1× | Dadm 30.07 |
| Live cell-swap rows / whole-kit variant swap | 1 reel | DaiA 30.05 · 35.6 |
| Calendar card (+ empty-calendar gag) | 1 reel (2×) | DaiA 9.55 · 37.05 |
| Brand-kit card w/ per-item font faces | 1 reel (2×) | DaiA 34.9 |
| Retention diagnostic-matcher sheet | 1× | Daix 26.267 |

Everything in §§0–2, AC1–AC3, AZ1–AZ2(law), §5 ACAP1–ACAP3, §6.2 pop/exit
laws, E1–E4, E7–E8, §7 is corroborated across ≥3 reels.

---

## 9. The executable profile (wired)

`producer_config.MODES["short"]["pacing_slideware"]`, selected by
`target.pace == "slideware"` (generic resolver `plan_lint_motion._pacing_profile`
maps `target.pace` → `pacing_<pace>`):

| Key | Value | Source |
|---|---|---|
| `min_changes_per_min` | 16.0 | §0 — floor below the leanest reel's plan-level (cuts + graphic entrances) rate ~23/min (Daix); the others run ~32–53/min |
| `max_still_gap_s` | 8.0 | §0/§6 — longest measured no-cut+no-graphic stretch ≈5.8s (Daix 12.48–18.28, a formula slide held under caption-pill churn); the 12.7s "static" stretches were camera holds carried by graphic churn |
| `hook_front_load` | 1.3 | §2 AH3 — hook density lives in the graphics layer; cut density is LOWEST in the hook, so demanding the default 1.5 misfires on on-style plans |
| `state_changes_per_min` (advisory) | 65.0 | §0 — 54–87 state-events/min (4/4); the brain paces caption+graphic churn to this, the lint does not read it |
| `music` (advisory) | True | §7 AM1 — 4/4 carry a bed, ~3–4 LU under speech |
| `punch_ins` (advisory) | False | §4 AZ1 — ZERO punch-ins 4/4; the track stays EMPTY |
| `transitions` (advisory) | False | §4 AZ2 — 27/28 cuts hard; the track stays EMPTY |

**Plan-authoring checklist (brain-side, from §§1–7):** one `--lime` token
everywhere (§1) · frame 0 fully dressed + receipts inside 1s (AH1–AH2) · first
structural payoff ≤2.4s (AH4) · pick ONE graphic economy: takeover deck or
persistent ledger (AC3) · cuts ONLY at section boundaries; `punchIns` EMPTY;
`transitions` EMPTY (AC1, AZ1–AZ2) · whisper captions dual-mode, pill on
canvas, zero karaoke (§5) · emphasis promoted IN PLACE as lime caption shouts
(ACAP3) · every enter 0-frame pop / whole-unit fade / word-locked stagger;
every exit instant or ON-cut (§6.2) · every receipt is a REAL pixel source
with an eye-count chip (E3) · mock-OS CTA at the end (E8) · music bed on,
−14 LUFS master, keep the −1.5 dBTP ceiling (§7).

---

## 10. Longform-intro treatment (operator-flagged)

**EXTRAPOLATION WARNING — the corpus is 4 SHORTS; zero longform evidence.
Everything here is a mapping of measured shorts grammar onto our measured
longform envelope (`docs/studies/PRODUCTION_ENVELOPE_STUDY.md`, `hook_contract.py`),
flagged LOW-CONFIDENCE by construction.**

What transfers to a longform intro (the first ~60s, where density runs
2.2–2.5× the body):

1. **Frame-0 dressed promise + receipts strip (AH1/AH2)** transfers directly:
   it satisfies the hook contract's captions + named-tool→graphic obligations,
   and the eye-chip receipts wall (E3) is a STRONGER credibility exhibit than
   a bare PIP for the credibility-claim obligation — receipts over claims.
2. **The lime takeover deck (E2)** maps onto the longform TAKEOVER rail (the
   glass-rail full-frame move in the render architecture): a full-frame
   cutaway that replaces footage, never a panel-on-face — the operator's
   cutaway doctrine confirmed in a second creator. Use it for the named-tool
   walkthrough beat; bake the caption pill INTO the takeover comp because
   longform does not burn captions (`MODES["longform"].captions_burn=False`).
3. **Numbered staircase lockups (E1)** drop into the section-marker lane
   (`graphics_planner_boundaries`) as the intro's chapter grammar.
4. **Density arithmetic:** her measured deck cadence (a slide/graphic event
   every 1–6s) clears the longform hook ceiling
   (`pacing.hook_still_gap_s = 4`) without adding a single cut — an
   slideware-treated intro passes the region-aware gate on graphics alone.

What does NOT transfer:

- **The zero-punch camera (AZ1).** Our longform envelope measures real
  punch/zoom usage in intros (cuts 2.2×, zoom events 2.5× in the first 60s),
  and the hook contract's strong-beat→push obligation stands. Do not strip
  pushes from a longform intro on Slideware's authority — her corpus cannot
  speak to longform. Resolution: Slideware supplies the GRAPHICS vocabulary
  (deck, lockups, receipts, pill); the camera layer keeps OUR longform
  grammar. Where a takeover hard-cut lands ON a strong beat, it is a bigger
  state change than a push — prefer it there rather than stacking both.
- **The mock-OS CTA (E8)** belongs at the video END, never in the intro.
- **The 60% face-absent takeover share (DagN)** would violate longform
  talking-head dominance; cap takeovers to the intro's walkthrough beats and
  section seams.

---

## 11. Ranked TEMPLATE BUILD LIST (reuse frequency × distinctiveness)

Full specs; geometry normalized to 1080x1920. Ranking = (sightings × reels) ×
how much of the grammar collapses without it.

**#1 — `slideware-takeover-deck` (lime slide-deck container + paging).**
3/4 reels, 12 deck sections, 39–60% of runtime where present — THE signature
structural move; nothing in the catalog renders it. Full-frame solid lime
`--lime` (#C8F800–#CEFF0A family; optional gradient top #96CB07→lime by
y0.35); header slot white or charcoal 900 caps 3.2–4%H center y0.18–0.21;
content zone x0.08–0.92 y0.13–0.80; caption-pill slot x0.5 y0.75–0.82.
IN: container + header + pill instant ON a hard cut (0f). Slide-1 content:
whole-unit fade 5f@24 + ~2%W settle drift, OR instant skeleton + word-locked
cell pops ≤80ms (stagger 1.2–2.1s), OR fade-cascade 0.17–0.2s/item @0.25s
stagger reading-order. Paging: carousel exit-left + enter-from-right
simultaneously ~0.45s (11f@24, settle at end) OR whole-slide instant
replace-chain 0.6–1.9s/card. OUT: cleared ON the hard cut back to footage —
never a comp fade.

**#2 — `slideware-staircase-lockup` (kicker / lime payload / co-word + in-place
caption shout).** 4/4 reels, ~40 sightings — extends the Punch G3 lockup with
a lime + extended-grotesque variant (NOT serif). Slots: kicker white semibold
1.9–2.4%H sentence case (payload words bold); PAYLOAD `--lime` ALL-CAPS
ExtraBold extended grotesque (Archivo Black/Montserrat 900 class) 4.2–7.8%H
(std 5.5 / hero 7.8 / verdict 3.6); co-word white ~2%H offset right-below,
lands 0.3–0.9s after. Placements: headroom-center w/ numbered kicker
("#N" / "Step #N:" / "For X Posts") for sections; chest band y0.58–0.68 for
action payloads + caption shouts (SOLID/FLOPPED/3 BARS, 6.2–6.8%H, hold
1.5–2s) + CTA. IN: 0-frame pop per token, word-locked. OUT: instant in-place
replace (chain 0.31–1.0s) or clear — never fade. Verdict variant reuses an
exact referenced string+color.

**#3 — `slideware-receipt-cell` (thumb cell + eye-count view chip; strips /
grids / walls).** 4/4 reels, 60+ chips in DagN alone — the proof stamp on
EVERY receipt. Cell stack: optional label chip (olive #697257 semi-opaque
r6px, white 1.1–1.3%H) ABOVE a 9:16 media slot (0.075–0.30W by layout;
square corners on canvas, r10px + shadow on footage) that PLAYS video (needs
video-in-cell, not stills) ABOVE/BELOW the view chip: near-black
#0A0A0A–#251F1C ~75–90% alpha pill r4–10px, white eye glyph + bold count
1.2–1.7%H. Layouts: hook strip 1×4–5 (headroom y0.14–0.35), 2×3 / 2×4 grids,
series walls 2×6 @0.075W, receipts wall 2×4 @0.08W + @handle. Build:
per-cell 0-frame pops, stagger 0.08–0.5s word-locked (hook chips alternate
rows every ~0.1s), or fully-built ON a cut; exits instant/ON-cut.

**#4 — `slideware-caption-dual-mode` (whisper preset + canvas pill skin).**
4/4 reels — every second of runtime renders through it. Footage mode: white
#F8F8F8 semibold 1.9–2.4%H sentence case, soft shadow, NO box, chest x0.5
y0.58–0.66, 1–4 words, replace-per-cue 0.3–1.2s, ZERO karaoke/color (inline
bold only). Canvas mode: white square-corner pill (r4–8px), charcoal
#303030–#474E4B bold 1.7–1.9%H, x0.5 y0.75–0.82 (or mid-card 0.51–0.59),
2–5 words, replace-per-cue 0.4–1.2s, ON at the cut frame. Skin switches per
background — pill baked into takeover comps. Emphasis externalized to #2's
in-place shout.

**#5 — `slideware-mock-os-cta` (fake-UI CTA bar).** 3/4 reels — high
distinctiveness, closes every reel. White rounded banner/bar r14px + soft
shadow, center x0.5 y0.23–0.31, 0.47–0.72W: avatar w/ gradient/lime ring, IG
wordmark or grey @handle ~1%H, action button system-blue #2078F8–#2A8DFD
r6px (variant: pink #EC1455 send circle, lime outline bar). IN: container
expands ~30%→100% width 0.17–0.25s ease-out, content pops +2f. Scripted
interaction beat: Follow→Following flip ~2f at +1.4s / typewriter payload
word ~0.17s/char + send-ring + heart morph (typed word = the reel's payload
word). Pairs with a chest-band lime lockup (~3–4.2%H) + white subline
replace-chain. Holds to end / fade-to-black.

**#6 — `slideware-split-ledger` (persistent scoreboard + fly-dock absorb).**
1/4 reels but ×12 in-reel repetitions and 41s persistence — HIGH in-reel,
**LOW-CONFIDENCE cross-reel: verify on a second comparison-format reel before
hard-coding**. Headroom y0.12–0.36 full width: two `--lime` column titles
2.2%H at x0.305/x0.705; 5 eye-chips per side h1.35%H r6px (solid #141A19 /
translucent #30373D / lime-stroke 2px #E0FF59 = winner highlight); 2px white
rule under each row; white center spine x0.5 w4px GROWS 0.19H→0.357H as rows
dock. Dock animation: evidence group shrink-translate scale 1→0.28 over
0.30s (7–8f), accel-in hard-stop, NO fade, into the named column slot; minis
0.048W keep labels/strokes; rows fill top-down and NEVER exit; the video ends
on the completed mosaic. Needs: named dock slots, spine growth, group-shrink
primitive, build-once-recall, live cell-swap rows.

---

## 12. Catalog gaps beyond the build list (spec only — do not build here)

- **G-A1 · Scribble annotation arrow.** SVG wobbly-stroke curved arrow
  (white/lime, ~3–4px, arrowhead) anchored to card coordinates; curly-brace
  variant (E7, 3/4). Near-miss: `whiteboard-connector`.
- **G-A2 · Fill-in template card.** White square card + red #C81018
  "(insert …)" tokens + example thumbs (E5, 2/4 — LOW-CONFIDENCE).
- **G-A3 · Phone-walkthrough card.** Real-UI PIP with instant content swaps
  between app screens + live state (E6, 2/4 — LOW-CONFIDENCE); near-miss:
  Punch G13 playing-video PIP.
- **G-A4 · Comparison board.** Column headers + re-filling thumb sets synced
  to the caption pill (E10, 2/4 — LOW-CONFIDENCE).
- **G-A5 · Equation build row.** Slots + white "+"/"=" glyphs + cream label
  chips, L→R 0.2s fades (E11, 2/4 — LOW-CONFIDENCE).
- **G-A6 · Lime-wash transition token.** 0.12s wash-in → cut at peak → 0.15s
  L→R soft wipe out (AZ2b, 1x — LOW-CONFIDENCE).
- **G-A7 · Page-riffle prop / pipeline strip / calendar card / brand-kit
  card / diagnostic-matcher sheet.** Single-reel set pieces (§8) — park until
  a second sighting.
- **G-A8 · Video-in-cell support (infra).** #3 and #6 require comps whose
  media slots PLAY clips; the graphics renderer currently composites stills.
  This is the biggest infra dependency of the build list.
