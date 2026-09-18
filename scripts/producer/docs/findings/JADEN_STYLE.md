# JADEN_STYLE.md — THE JADEN STYLE grammar (6-reel granular synthesis)

**Creator:** iamjadenly (Jaden Young, content strategist, ~299K IG).
**Corpus:** 6 reels, 55.9–150.7s, all 1080x1920 9:16 locked-tripod talking-head,
total 623.1s / 166 eye-verified cuts / ~146 graphic+text events.
**Method:** per-reel granular traces — fingerprint index + scdet re-detect +
whisper word timestamps + ORB/face-bbox zoom traces + RMS/onset audio passes,
every cut and graphic event verified by eye on 1fps/8fps/12fps frame sheets.
Dense event logs: `~/ProjectSniper/_references/iamjadenly/<id>.study/granular.json`
(**on disk for DQr/DVg/Daf only** — the DZ2/DaG/DaV logs were session-local and
never persisted; their claims below were re-verified from fresh pixels).

**RE-AUDITED 2026-07-09 (comprehension audit):** every rule below re-verified
against FRESH frame extractions (contact sheets + 24/30fps bursts at every cited
timestamp) plus independent machine traces (frame-diff + scale-fit cut
classifiers, YuNet face-height zoom traces, ebur128/silencedetect, onset-flux).
Verified rules are marked implicitly by their surviving text; every number the
pixels contradicted is corrected in place and listed in §11. 50/53 named rules
confirmed; 2 partially (Z3, M4); §5.2 had two wrong coordinate rows (fixed).

**SUPERSEDES** `PROJECT_SNIPER/docs/JADEN_STYLE.md` (v1, fingerprint-level, one
deep-traced reel). Three v1 numbers are corrected here by the 6-reel traces:
scdet cut counts (undercount ~2x → §2 C1), "captions carry zero emphasis"
(false in 4/6 reels → §4), and the 20s still tolerance (true no-change max is
10.9s → §2 C8).

**Confidence policy:** every rule carries its sighting count. A rule seen
**<3 times** is flagged **LOW-CONFIDENCE** — treat as hypothesis, re-verify
before templating. Counts cite reel + timestamp.

Reel IDs (short form used below): **DQr** = DQrbyYRDZGh (140.9s@30),
**DVg** = DVgWXuXDXdN (150.7s@24), **DZ2** = DZ2u2o8qEjV (101.2s@30),
**DaG** = DaGwe1PCFWQ (88.1s@30), **DaV** = DaVNfI1iT1q (86.3s@30),
**Daf** = Dafb57RiAjt (55.9s@30).

---

## 0. Corpus numbers (eye-verified, not scdet)

| Reel | Dur s | Visible cuts | Cuts/min | scdet said | Graphic/text events | Base captions | Takeovers/bands |
|---|---|---|---|---|---|---|---|
| DQr | 140.9 | 44 (p50 shot 2.57s) | 18.7 | 44 (scdet8 re-detect) | 36 | **NONE** — keyword-pop only | 9 UI takeovers, 2 blur-takeovers |
| DVg | 150.7 | 26 (21 scdet + 5 sub-thr) | 10.4 | 21 | ~30 | whisper slot 2.2%H | 1 PIP |
| DZ2 | 101.2 | 31 | 18.4 | 17 | 13 graphics + ~19 caption-emphasis | phrase-pop 2.3%H | 4 notes inserts, 2 PIP demos, 3 cutaways |
| DaG | 88.1 | 23 | 15.7 | 23 (scdet8; ≥4 invisible at thr 10) | 27 | chunk-replace 2.3%H | 3 blur-takeovers, 2 meme bands |
| DaV | 86.3 | 23 (9 A-roll + 5 swaps + 5 takeover + 4 PIP) | 16.0 | 14 | ~30 | phrase-replace 2.2%H | 2 top-band PIPs, 2 card carousels, 1 grid |
| Daf | 55.9 | 19 | 20.4 | 9 | 20 | phrase chunks 1.6%H | 2 b-roll trips, 5-card stack |

**Medians:** visible cuts/min **17.2** (range 10.4–20.4) · on-screen state rate
**51–89 states/min** (fingerprint states@2fps, 6/6) · speech **255–260 wpm
effective** (DQr 610w/260wpm; DVg 641w/255wpm) · silence ratio **0.000, 6/6** ·
integrated **−14.5…−14.7 LUFS** (0.2 LU spread).

**Instrument warning [6/6]:** scene detection undercounts this style ~2x —
same-background punch cuts are sub-threshold (Daf 9→19, DZ2 17→31, DaV 14→23).
Any pacing audit of a locked-camera short MUST use a face/scale trace, not
scdet (confirmed independently in DQr, DZ2, DaG, DaV, Daf traces).

---

## 1. Hook anatomy

**H1 — A graphic owns frame 0. [5/6 — HIGH]**
DQr title pill 0→6.45s (white #FCFCFC full-round pill, center-x, y0.55–0.65,
pre-baked at frame 0, pop-out ≤1f); DaG stacked white pills y0.29–0.36,
0→2.96s, pop-off ≤2f exactly as speech starts (+🤫 emoji spring 0.375→0.75s,
11f, 30%→100% overshoot); DZ2 white pill y0.075 w0.46 baked frame 1, struck
exactly ON the first punch cut @3.03; Daf white pill card x0.15–0.85
y0.138–0.276, 0→2.96s static, pop-off ≤83ms; DVg the ENTIRE blueprint diagram
pre-placed at frame 0 (see H6). Exception: DaV opens captions-first + receipts
@0.625s. Executable: card present at t=0, **zero motion during hold** (4/5),
hold 2.96–6.45s, exit ≤2 frames on speech start or first cut.

**H2 — The hook is graphics-carried, NOT cut-carried. [6/6 — HIGH]**
Cuts in the first 10s: DQr 0 (one take to 12.17s), DVg 0 (first cut 14.58s),
Daf ≤1 (0 in the 0–10s bucket; burst starts 20.8s), DaG 1 (first cut 4.5s),
DZ2 4, DaV 7. Meanwhile the graphic/text layer changes every ~0.65–1.0s:
Daf a graphic event every ~0.65s from 5.8–10.9s; DQr title pill + 4 proof
chips (1.58/2.25/3.30/4.03) + 3 keyword ladders inside the zero-cut 0–12.17s;
DVg 8 graphic states in 0–10s. Executable: never force cut density into the
hook to "front-load" — demand a graphic on screen inside the first ~1.6s and a
graphic/text event cadence of ≥1 per second instead.

**H3 — Hook receipts: staggered view-count pills. [4/6 — HIGH]**
DaV 984/523/1223 @0.625/0.75/1.0s (y0.171–0.232, stagger 0.125–0.25s, all out
together @1.58); DaG 2.6M/2M/1M @8.375/8.75/8.875 (top row y≈0.06, right→left,
0.375s then 0.125s, off ON cut @10.033); Daf 3 dark pills, 0.08–0.17s stagger,
die ON the x1.92 punch-in @10.87; DQr 4 proof chips @1.58–4.03 (dark pill
#251F1C ~85% alpha, eye glyph, group fade @4.92). Spec: 3–4 pills, per-pill pop
≤2f, stagger 0.1–0.4s, hold 0.8–1.2s, exit as a group or ON a cut, word-locked
to "views / numbers like this".

**H4 — Save-CTA bookmark inside the hook (s 9–16). [4 instances, 3 reels — HIGH,
re-measured frame-accurate 2026-07-09]**
DZ2: outline stroke-draws 8.70→9.00 (~9f), FILLS @9.13–9.17 (2f) on the word
"save", off @~9.52 (0.82s total). DaG: yellow ~4px outline draws 16.00→16.30
(~9f), outline HOLDS ~0.4s, fill-flood @16.72 + ~1.15x pop, off ON cut @17.0.
DaV: draw 14.08→14.55 (~14f), white fill snap @14.85–14.88 (2f), out between
15.62 and 16.0 (hold ~1.7s) — SAME asset reused at the outro @~84 (visible
@84.0 in the 1fps trace). Spec: stroke-draw 9–14f → fill snap 2–3f (the fill
may wait ~0.4s after the outline completes), "save"-word amber in the caption,
total hold 0.8–1.9s.

**H5 — Promise/engine ignition at 12–17s. [4/6 — HIGH]**
DZ2 "4 main principles" @16.03 (3.4s hold — the ONLY faded-in caption in 6
reels); DaG biggest punch of reel x1.44 @17.0 on the promise; DaV list engine
#1 @17.37; DQr first cut @12.17 clears the keyword ladder into the body.
(DVg names its promise earlier: "10X" @9.5 + "In the next 30-90 Days" @10.3.)

**H6 — Blur-tease cold open. [1x — LOW-CONFIDENCE]**
DVg: the whole blueprint pre-placed gaussian-blurred above his head at frame 0,
racks blur→sharp in **~0.15s** exactly on "a video like THIS" @1.5s, scale-exits
@4.95 (~0.15s); its pieces are then rebuilt one-by-one across the whole reel.
(v1 doc's "1.6s rack" is superseded by the granular ~0.15s measurement.)

**H7 — B/W device inside the hook. [2x — LOW-CONFIDENCE]**
DaG threat-word full-frame drain @4.0–4.47 (1–2f drain, caption flips yellow,
color restored ON cut @4.50); DZ2 B&W self-skit gag @5.73–7.57.

---

## 2. Cut engine + beat timing

**C1 — Visible cut rate 17.2/min median (10.4–20.4), p50 shot ~2.6s. [6/6 — HIGH]**
Per-reel: 18.7 / 10.4 / 18.4 / 15.7 / 16.0 / 20.4. DQr p50 shot 2.57s.

**C2 — Cuts are SPEECH-timed, never music-timed. [6/6 — HIGH]**
DQr music autocorr strength 0.06 → all 44 cuts within ~80ms of a word boundary;
DVg median 35ms to a syllable attack; DZ2 median offset to the ~120BPM bass
grid 0.10s (statistically random for a 0.5s beat); DaG onset autocorr 0.029,
all 23 cuts in RMS dips −32..−54dB; DaV 8/9 A-roll cuts inside an RMS pause
−34..−57dB; Daf all 19 cuts in RMS dips −35..−48dB. The beat grid is speech.

**C3 — Two join classes; renderer target = pause-end −0.1s. [6/6 — HIGH]**
(a) **Pause-trim**: cut sits in the breath gap, next word attacks **+0.02–0.18s
AFTER** the cut, ~4.5dB hotter (DaG mean +4.5dB; DZ2 ~40% of cuts, pre-RMS
0.02–0.08 → post 0.13–0.23, attack 50–150ms; Daf 19/19; DaV +50–150ms).
(b) **Speech-through punch**: video-only reframe under continuous VO (DVg 16/21
cuts land MID-WORD — one unbroken vocal performance; DZ2 ~35%; DQr VO runs
under all 9 UI takeovers = J/L by construction). No deliberate J/L audio lead
>100ms anywhere (DaG 10ms-resolution check).

**C4 — Cuts land on pivot words. [3 reels, ≥10 verified locks — HIGH]**
DQr: ON the first word of a new thought (Come/So/For/Because/Now/Give) or
inside the final syllable of the prior sentence (owner./this./positive.);
DVg "So"@36.21, "These are all styles"@87.0, "So don't overcomplicate"@99.79;
DaV "Lastly"@74.27 on the #9→#10 boundary.

**C5 — Strict tight↔wide alternation; step magnitudes. [5/6 — HIGH]**
Every cut lands tighter or wider than the last. IN steps +12..+45% face-height
(DVg 21/21; max x1.44 DaG @17.0; outlier x1.92 Daf @10.87), OUT steps −13..−30%
(DVg −13..−25; DaG x0.69–0.93; Daf to x0.55). All steps are 1-frame hard;
zoom never eases ACROSS a cut.

**C6 — Punch magnitude scales with importance. [3 reels — confirmed]**
DVg largest punch (+45%) reserved for the imperative "So don't overcomplicate"
@99.79; DaG largest (x1.44) on the promise @17.0; DQr crash push +60% on
"Come close when I tell you this" @52.97.

**C7 — Punch-OUT is functional, not aesthetic. [≥6 instances, 4 reels — HIGH]**
Fires ~0.1s BEFORE a graphic lane opens (Daf 35.97 before the comment card,
44.6 before the 5-card stack; DaV 17.367 widens to the "list stage" making chip
headroom) or marks a voice/register change (DaG x0.69 audience-quote @12.87,
x0.72 "Listen" reset @60.4; DZ2 punch-out wide @94.53 = outro register).
Plan-order implication: graphics placement is decided BEFORE punch framing.

**C8 — Envelope: three shapes, one constant. [6/6 measured]**
Front-loaded (DaV 42 cuts/min in 0–10s → ZERO cuts in the last 34.3s; DZ2
12–24/min 0–40s → 6/min body), flat (DaG 13–16/min, 10s buckets 6–18), and
inverted-hook (DQr 0 cuts 0–12.17s → peak 6 cuts in 70–80s; Daf 0 cuts 0–10s →
burst 20.8–40s). The constant: an **outro clean-down** [4/6]: DZ2 10.9s
zero-graphics hold @83.7–94.5; DaG final 9.2s zero cuts AND zero graphics
(then a physical lean into lens — YuNet face trace 2026-07-09: ~x1.27 over the
final ~1.5s, 477→607px, not x1.36 in 0.5s); DaV last 34.3s
carried by captions/pills alone; Daf sparse outro under a −1.15%/s pull.
Counter-example: DQr ends on an accelerating +22% push into a salute.
**True no-change ceiling:** the longest stretch with NO cut and NO graphic
entrance measured anywhere is **10.9s** (DZ2 83.7–94.5). DaG 9.2s, DaV ~10.0s
(59→69s between pill swaps). The fingerprints' "20–34s static" stretches were
camera-holds carried by graphic/caption churn. (Re-verified 2026-07-09: frame-
diff events inside all three holds were checked with a YuNet face trace — all
are body sway / caption swaps, no cuts; the DZ2 hold ends in the punch-out
@94.53, face 541→363px = −33% in 0.3s. The 12.0s `max_still_gap_s` stands.)

---

## 3. Zoom grammar (within-shot)

**Z1 — Hold drift ≤1%/s; the tripod is locked. [5/6 — HIGH]**
DVg background patches pixel-identical (SSIM 1.000) across 6.6–8.5s holds;
measured drifts: DVg ±1%/s, DaG 0..+1.5%/s (body sway, not digital), Daf
0.3–0.8%/s, DaV +0.7%/s body, DZ2 ±2%/s. Aliveness comes from the text layer
and the creator's physical lean, NOT a digital creep lane.

**Z2 — Eased push builds INTO a payoff: +1.4..15%/s over 1–4s. [≥5 instances,
4 reels — HIGH; rates re-measured by face trace 2026-07-09]**
Daf +1.4%/s ×4s (31.9–36.0, "here is what to do" build; the original 2.84%/s
overstated) and +5.6%/s ×1.1s (44.6–46.0, under the comment stack); DaV +23%
over 1.5s = +15%/s (6.0–7.5s, building into the b-roll hit); DZ2 +6.1%/s
(31.2–35.5, under the stacked emphasis pair; original said 8.7). The DQr
77.7–80.1 citation was MISATTRIBUTED — the face trace shows +3% total there;
that window is a UI-takeover Ken Burns (Z5/E5), not a talking-head push.
DQr 131.3 +13.7% stands (part of the outro build). Note DVg and DaG have ZERO
eased pushes — the move is legal, not mandatory.

**Z3 — Slow pull-out as de-emphasis. [2 clean instances + 1 mixed, 2 reels —
demoted 2026-07-09]**
DQr 13.6–17.8 −21.8% over 4.2s = −5.2%/s (laptop reveal — face-trace verified).
Daf outro decompression −2.5%/s across the final 10s (includes 2 punch-out
steps; the pure-creep share is smaller). The DQr **34.8–46.9 "−24.7%" citation
is CONTRADICTED** — the face trace is FLAT (256→264px) across that window; the
widening was a step near ~34.3–35.0, and the icon row landed on an already-wide
frame. DQr 120.6–128.4 measures −56% but includes punch-out steps — a mixed
window, not a pure creep. Room-making pull as a distinct sub-rule:
**LOW-CONFIDENCE** (now 0 clean sightings).

**Z4 — Crash push-in. [1x — LOW-CONFIDENCE]**
DQr @52.97: cut wide, then ram +59%/s for 0.65s (+60% total) on "Come close
when I tell you this".

**Z5 — Held panels are never frozen: 1.5–4%/s self-motion. [4 reels — HIGH]**
DZ2 PIP mockup +3%/s self-creep (57.5–61.4) and grows 60→75%W (67.87–71.27);
DQr UI takeovers get +7.6%/5s Ken Burns; Daf receipt cards float-drift while
held; DaV example cards float gently, inset drifts. Any panel held >1.5s
carries its own drift.

**Z6 — Outro camera move. [2x, opposite directions — LOW-CONFIDENCE]**
Daf pulls out −1.15%/s over the final 10s; DQr pushes +22% accelerating (peak
+26%/s @139.9) into the salute. No stable rule — author per ending mood.

---

## 4. Caption system spec

**CAP1 — Karaoke sweep rate: ZERO. [6/6 — HIGH]**
No per-word color sweep exists anywhere in 623s. DQr goes further: NO base
captions at all (keyword-pop only — see CAP7). Our shorts default
(`captions_style: "karaoke"`, gold active word) is off-style for this grammar.

**CAP2 — Base "whisper" layer: 1–4 word chunk-replace. [5/6 — HIGH]**

| Property | Value | Evidence |
|---|---|---|
| Grouping | 1–4 words per chunk | DVg 1–3, DZ2 2–4, DaG 1–4, DaV 2–4, Daf phrase-chunked |
| Replace cadence | median hold 0.45–0.55s (range 0.25–1.2s) ≈ ~2 swaps/s | DZ2 0.45s median; DaG 0.55s; DaV 0.55s; DVg ~2 swaps/s @255wpm |
| Throughput | 185–280 wpm | DZ2 185; DaG 240–280; DVg 255 |
| Swap animation | hard replace, no fade/slide — ONE faded entrance in 6 reels (DZ2 @16.03, ~0.15s) | DZ2/DaG/DaV/Daf explicit |
| Face | white geometric sans semibold (SF-Pro/Proxima class), sentence case | DaG/DaV/DZ2/Daf |
| Treatment | soft shadow; NO box, NO stroke | DaV "no stroke"; DVg "no box"; DZ2 "no box" |
| Size | 1.6–2.5%H (≈31–48px @1920) | Daf 1.6; DVg 2.2; DaV 2.2–2.5; DaG 2.3; DZ2 2.3 |
| Position | center x0.5, y0.55–0.66 (under chin, above any mic) | DVg 0.55–0.62; DaG 0.56; DZ2 0.60; DaV 0.60; Daf 0.605–0.658 |

**CAP3 — Tier-A emphasis: inline keyword tint. [4/6 — HIGH]**
Payload word(s) render yellow/amber **from the chunk's first frame** (never
swept in): DZ2 ~#f0b03a ("attention"@0.4, "save this video"@9.1); DaG
~#F5C518 ("flops", "be banned", "buy in power"); DaV #F2D24B ("Save it",
"freemiums"); Daf yellow claim/CTA/list words, red-X on negations. Whole-phrase
amber for number/CTA payloads: DaV "2 takes per video"@47.38, "Save this
video"@83.7; DaG "like/comment/share/follow"@77.48.

**CAP4 — Tier-B emphasis: promotion to a display layer, word-append builds. [5/6 — HIGH]**
Concept names / punchlines / CTAs leave the base style: font-switch to the
chunky yellow serif at 1.4–1.7x, building **word-by-word (additive)**:
- DZ2: 0.08–0.2s/word, hold 0.9–1.5s, ~11 occurrences in 101s ("speaking on
  camera"@2.0, "That's a problem"@30.38 landing ON the punch cut, SPEAK 3x-size
  CTA @97.8 struck on cuts both sides).
- Daf: 0.10–0.42s/word measured (It's@2.87 / actually@2.97 / my@3.42 /
  fault@3.67 — burst-verified 2026-07-09; the first append is faster than the
  original 0.21 floor), serif 1.4x.
- DaG: cumulative word-builds on quote/CTA beats (~0.25s/word), serif swaps for
  concept words.
- DVg: keywords PROMOTED off the caption slot to a separate big yellow-serif
  layer (~4.5%H), chest-slot swaps ~0.9s.
- DQr: the promotion layer IS the whole system — payload nouns appended
  **+0.03–0.15s** of the spoken onset (CASH@7.17+COW@7.75; MONEY@8.75+
  MAKING@9.13+MACHINE@9.63), cleared at sentence end ±0.03s or by the next cut.
Climax-word variant (goes WHITE and 1.5–1.7x: MACHINE h0.07, numeral 10 h0.10):
DQr only — **LOW-CONFIDENCE**.

**CAP5 — Captions never fight a takeover. [5/6 — HIGH]**
SUPPRESSED during full-frame cutaways/b-roll/memes (DZ2 all 3 non-speech
cutaways; DaV b-roll + guru carousel; Daf both b-roll trips), or RELOCATED
under top bands (DZ2 y0.60→0.46 under the notes insert; DaG →y0.26–0.35 under
meme bands and →top y0.12 in the B/W audience-quote beats). Relocation
specifically: 2 reels — **LOW-CONFIDENCE** as an executable variant.

**CAP6 — Text survives cuts; changes ~0.07s AFTER them. [3 reels — confirmed]**
DaG captions persist across cuts and swap on the next word onset (~+0.07s);
DQr overlay text rides across jump cuts (HOOK persists across cut @108.97);
DVg the Top-3 stack stays pinned in screen space across the +20% punch @42.67.
Overlay/caption layers live in output space, independent of framing.

**CAP7 — Caption-less keyword-pop variant. [1/6 — LOW-CONFIDENCE]**
DQr runs zero base captions for 140.9s. Default the whisper layer ON; treat
keyword-pop-only as an opt-in variant.

**CAP8 — Persistent list-pill lane. [1 reel — LOW-CONFIDENCE]**
DaV "#N." amber slab-serif pill, ~2x caption size (cap ≈4.5%H), second line
y≈0.655, persistent 4–15s per item, swaps EXACTLY on item boundaries
(#1@17.37 … #10@74.3). Graphics are lifecycle-bound to the item (chip exits at
the #1→#2 boundary frame @20.32).

---

## 5. Text / graphic vocabulary

### 5.1 Style tokens [6/6 unless noted]

| Token | Value | Evidence |
|---|---|---|
| Signature yellow | one per reel in the **#F2D24B–#F5E960** lemon/amber family | DQr #F3EA2D · DVg #F5E960 · DZ2 #f0b03a–#f5c542 · DaG ~#F5C518 · DaV #F2D24B · Daf amber-gold |
| White | #FDFBFC–#FFFFFF | 6/6 |
| Dark chip/pill | #0B0203–#251F1C @ ~85% alpha | DQr #251F1C · DaG #1a1a1a · DaV #0B0203 · DZ2 #141416 |
| White pill/card | #FCFCFC–#f5f5f5, radius 14–20px | DQr, DaG, DZ2, Daf (4/6) |
| Display face | chunky rounded serif (Cooper/Recoleta/Chunk-Five class), heavy, black stroke or soft shadow | 6/6 |
| Two-tone pair law | yellow serif payload word + heavy WHITE grotesque partner, small white lead-in kicker ~1.8%H | DVg (Finance+Space, Content+Idea, 90+Days) · DaG (yellow initial cap + white serif rest) · DQr (lockups alternate yellow/white) — 3 reels |
| Red X | negation/"wrong" marker | DaV chip badge @17.85 + receipt card @23.6 · Daf red-X negation — 2 reels, **LOW-CONFIDENCE** |
| Real screenshots only | proof is a REAL asset (reel covers, IG UI, payment receipts), never a drawn stat | DVg T9 · DaV · Daf · DQr — 4 reels |

### 5.2 Position grid (normalized; measured)

| Zone | Geometry | Used by |
|---|---|---|
| Top band (inserts) | y 0→0.24..0.45, full width, hard edges | DaG meme bands 0.24–0.27H · DZ2 notes inserts 0.42–0.45H · DaV PIPs 0–0.28/0.35 |
| Keyword/text band | y0.115–0.27 — never over the face | DQr all text pops · DaG title slot y≈0.115 |
| Free-space title slot | top band, picked by where the face is NOT — measured "Metaphor" block x0.13–0.53, cap center y≈0.19 (CORRECTED 2026-07-09: the old "mid-left y0.40–0.55" row was wrong; the face sits low/RIGHT so the title went upper-LEFT) | DaG "Metaphor"@56.6 |
| Headroom chip | x≈0.10–0.31, y≈0.06–0.16 (CORRECTED 2026-07-09: old y0.27–0.39 was wrong — the chip rides the top band) | DaV ChatGPT chip @17.9 |
| Chip grid 2×3 | cols x0.197/0.534 w0.30, rows y0.276/0.371/0.457 h0.07 | DQr blur-takeover chips |
| View-pill row | y≈0.06 (DaG) / y0.171–0.232 (DaV) | receipts pills |
| Caption/formula band | y0.55–0.66; staircase formula y0.56–0.63 | DaV Hook/3 bullet points/CTA @42.05–43.23 |
| Bookmark | center x0.5, y0.64–0.79 (h≈0.09–0.155H) | DZ2 y0.70 · DaV y0.638–0.79 · DaG y0.64 |
| On-gesture | pinned to the pointing hand / raised hands | Daf comment cards at fingertip · DVg "2 Thing/1 Thing" @36.5 |

### 5.3 Animation frame timings (30fps unless noted)

| Move | Timing | Evidence |
|---|---|---|
| Text pop-in | ≤1–2f (≤83ms), NO fade, NO scale | DQr 1f · DVg ≤80–125ms (@24fps) · DaG ≤2f · Daf ≤2f — 4 reels HIGH |
| Word-lock | land ON or ≤0.3s EARLY of the spoken word; median abs offset ≤0.2s; never lag >0.3s | DVg median ±0.2s · DQr +0.03–0.15s · DaV/DaG/Daf word-locked — 5 reels HIGH |
| Card/chip spring | scale ~10–30%→overshoot→settle in 0.15–0.35s (5–10f), tilt ±3–6° settling, drop shadow | DaG 0.25–0.33s ±4° · DaV 0.15–0.2s · Daf 0.25–0.3s 2–8° · DVg inset 10–12f — 4 reels HIGH |
| Slide-in | 0.2–0.3s (6–9f) eased from edge + settle | DaV chip 7–8f · Daf proof card ~9f — 2 reels **LOW-CONFIDENCE** |
| Sibling stagger | pills 0.1–0.4s · cards 0.42–0.75s · icons ~0.45–0.5s · diagram nodes 0.9–1.1s word-locked | DaG 0.125–0.375s / DaV 0.125–0.25s / Daf 0.08–0.17s / DQr 0.15s pairs · DaV cards 0.42–0.75s · DQr+DaG icons ~0.45s · DVg nodes ~1.0s — HIGH |
| Draw-on | bookmark outline 8–13f → fill snap 2–3f | DZ2/DaG/DaV — 3 reels HIGH. Arrow stroke-draw 0.4s (DVg @9.0) — 1x **LOW-CONFIDENCE** |
| Live typing | ~10 cps + emoji drop | DZ2 4 notes inserts — 1 reel, 4x — **LOW-CONFIDENCE** (single reel) |
| Top-band on/off | ZERO entrance animation — placed in 1 frame, removed in 1 frame | DaV 2 PIPs · DaG bands · DZ2 notes hard cut-in — 3 reels HIGH |
| Blur+desat takeover base | live frame → gaussian σ≈20–30 + desat in 1–2f (DaG ×3, DQr rack-defocus 1–2f) up to ~0.3s (DaV @22.97); VO continues | 4 reels HIGH |
| **EXIT — THE LAW** | **NEVER animated out.** Hard-off ≤1–2f, either (a) exactly ON the next cut or (b) instant pop at the semantic boundary (sentence end ±0.03s / list-item boundary) | DaG **27/27** graphics hard-off ON cuts · DZ2 title@3.03 + CTA@97.77/98.65 struck on cuts · Daf pills die on punch@10.87 · DQr sentence-end clears (PHYSICAL exits 37.92 vs word end 37.90) · DaV item-boundary exits @20.32/74.27 — 6/6 HIGH. Exceptions in 623s: ONE motion-blur whip-exit (DVg @30.42, ~0.3s, synced to arm swipe, riding the cut) + one group fade (DQr 4 chips @4.92, 2–3f) |

### 5.4 Element catalog

**E1 — Keyword lockup / shout layer. [6/6 — HIGH]** Yellow serif payload
4.5–6%H + white grotesque co-word ~4%H + white kicker ~1.8%H; pop-in ≤2f
word-locked; replace-chain ~0.9s or cleared on cut. (Numerals ~8%H alternate
top corners: DVg 1@37.67-right, 2@48.58-left — 2x **LOW-CONFIDENCE**.)

**E2 — View-pill receipts row. [4/6 — HIGH]** See H3. Dark pill, eye glyph +
count, R→L stagger 0.1–0.4s, used as a CONTRAST device (DQr/DaG 2.6M/2M/1M vs
DaG 984/523/1223 vs DaG $5k/$10k payment cards @65.0 held only 0.8s).

**E3 — Tilted screenshot receipt cards / grids. [5/6 — HIGH]** Rounded r24–30px,
shadow, tilt ±3–6°, spring pop 0.15–0.35s, staggered 0.42–0.75s, float while
held; 2×2 grids (DaV @23.13–26.15 over B/W-blur bg; DaG @30.417–32.87), comment
cards at the fingertip (Daf, 0.25–0.3s scale-in + float, stacks 0.35–0.42s),
IG profile before/after at the CTA (DVg small@139.75 → 299K card exactly ON
cut@140.21; DQr profile FLASH 0.63s @97.47). Proof shows at RECOGNITION speed,
not reading speed: 0.63–3.5s holds (DQr 7 reel examples in 2.84s).

**E4 — Blur+desat takeover ("cutaway without leaving the take"). [8 instances, 4 reels — HIGH]**
Live frame blurs+desaturates in 1–2f MID-SHOT while speech continues; sharp
content (cards/chips/title) cascades in word-locked; a HARD cut restores
color/sharp and clears everything in 1f. DaG ×3 (receipts 2.5s, self-inset
1.38s, example cards 4.12s); DQr ×2 (option-chip menus 1.8s/1.68s, yellow title
stays sharp); DaV receipts grid 3.15s; DZ2 PIP demos over blurred GRAYSCALE
A-cam. Needs no second angle — matches "pro graphics are cutaways" doctrine.

**E5 — Full-frame UI/b-roll takeover, VO continuous, captions suppressed. [3 reels — HIGH]**
DQr ×9 (0.63–4.9s each, hard 1f in/out, +7.6%/5s Ken Burns so they never sit
dead); Daf ×2 trips (shots held 1.1–1.4s); DaV AI-brain b-roll 1.27s+0.37s
@8.33. Annotations pop whole ON the takeover (DQr red rounded-rect on SERP
@51.95, blue highlight on YT description).

**E6 — Top-band insert (chapter/reaction mechanism). [3 reels — HIGH]**
Full-width band 0.24–0.45H, 1-frame on/off, A-cam keeps punch-cutting
UNDERNEATH a persistent band (DZ2 punch under insert @80.85 — layers cut
independently), captions relocate below. Holds 1.8–7.3s.

**E7 — Notes-insert live typing. [4x, 1 reel — LOW-CONFIDENCE]**
DZ2: Apple-Notes dark #1b1b1d top 42–45%H, orange header, principle name typed
live ~10cps + emoji; holds 4.2/1.8/7.3/6.8s.

**E8 — Playing-video PIP card. [3 reels — confirmed]**
Rounded phone mockup PLAYING a clip: DZ2 ×2 demos (slide+scale 0.4–0.5s then
fade+scale 0.3s, over blurred grayscale A-cam, iOS Volume HUD acted: mute
@58.0, slider animates up 68.35→69.6 — the HUD story is 1 reel
**LOW-CONFIDENCE**); DaV example cards embedding playing mini-reels
(70.283–74.40); DaG self-inset with live mini caption (36.567–37.95).

**E9 — Bookmark save-CTA. [4x, 3 reels — HIGH]** See H4.

**E10 — B/W grade as a semantic operator. [6 instances, 4 reels — HIGH]**
Meanings: threat-word flash 0.47s (DaG @4.0), self-deprecating aside 3.1s
cut-locked both ends (DQr @101.90–105.03), audience-voice quote window 1.83s
with captions relocated to top and built cumulatively (DaG @12.85–14.68),
comedy skits (DZ2 ×2), pulse 0.9s ending AT a pull-out cut (Daf). Color restore
ALWAYS rides a cut (DaG, DQr, Daf).

**E11 — Progressive diagram build. [5 builds + 3 recalls, 1 reel — LOW-CONFIDENCE (single reel)]**
DVg: lockup pops → thin white 2–3px connector STUBS grow → satellite labels pop
at line-ends word-locked (Budgeting@25.30 vs spoken 25.30 = 0.00s), nodes
~0.9–1.1s apart; lists rotate in ONE slot ~0.9s instead of stacking; finished
diagrams RE-POP fully built as recap beats (map@30.3, pyramid@70.15 fused with
the cut on "boom, in that order", 6-thumb board 1.5s flash@93.2). Build
teaches, recall summarizes.

**E12 — Meme insert. [3 instances, 2 reels — LOW-CONFIDENCE]**
Rides as a top band (DaG ×2: 2.2s + 5.2s with a mid-band swap @42.7) or a
full-frame cutaway prefaced by the reel's only 0.4s desat+dim ramp (DZ2
@27.38–28.55, VO speech-through). Captions clear during memes.

**E13 — Gesture choreography. [≥7 instances, 3 reels — HIGH]**
Graphics are planned at PERFORMANCE time: labels anchor to raised hands (DVg
"2 Thing/1 Thing"@36.5), he points up at IDEA as it pops (DVg @115.97), bracket
draws synced to a two-hand split mime (DVg @117.13), cards materialize at the
pointing fingertip (Daf), hand-chops sync per appended word (DaG @34.06),
proof cards enter on an upward arm sweep (DVg @139.7). Requires hand-keypoint
anchoring we don't have (gap G8).

**E14 — Typos ship (anti-rule). [5 instances, 2 reels — confirmed]**
DQr "POSSITIVE" holds 0.55s @34.28; DVg "Narative"/"Comming"/"WORHT OF" in an
8.7M-view-class reel. Hand-set speed > copy QA. Do NOT replicate the typos; DO
replicate the implication: plain hand-set lockups beat over-designed cards.

---

## 6. Music + mix doctrine

**M1 — A bed runs under the ENTIRE reel; it is texture, never a timing
authority. [6/6 — HIGH]** Floors −15.3..−16.2 LUFS under −14.5..−14.7
integrated; autocorr strengths 0.06 (DQr) / 0.029 (DaG) / negligible (DaV);
DZ2 cut-to-beat offset median 0.10s (random); DVg cuts ignore the 93.8 BPM
felt grid. Sync target is always the voice.

**M2 — Master numbers. [6/6 — HIGH]** Integrated −14.5..−14.7 LUFS (0.2 LU
spread — compatible with our `AUDIO.lufs_target = -14.0`); crest 6.7–7.7dB
(mastered-music density); true peak −0.7..+0.4 dBTP — TWO reels exceed the
−1.5 delivery ceiling (DQr −0.0, Daf +0.4): do NOT copy, keep our TP ceiling.

**M3 — Zero true silence; the bed keeps gaps lit. [6/6 — HIGH]**
Silence ratio 0.000 in all six; the bed sits ~**3±1 LU under the dialogue
median** in speech gaps (floor p10 −15.3..−16.5 vs speech p50 −12.3..−12.9) —
far hotter than our default 10–12dB gap rise. Start at gapDb≈10 and mix toward
the measured floor by ear. Speech itself: 255–260 wpm effective, no gap >0.35s
(DVg 0 gaps in 150.7s) — dead air is fully stripped BEFORE pacing.

**M4 — SFX on graphics: reel-dependent, optional. [2 reels yes / 2 reels no]**
YES: DaV kick-band thumps within ~100–250ms of graphic entrances (b-roll@8.51,
chip@17.89, cards@72.72/73.53); DQr pop/whoosh on ~10 of 36 entries (2.29,
78.64, 86.85, 97.79, 102.06, 119.26…). NO: DZ2 zero alignment across all 13
entrances; DaG none detectable. Treat as optional garnish, never required.
(2026-07-09 caveat: a spectral-flux re-check finds onset peaks near entrances
in BOTH DaV and DZ2 — that instrument cannot separate SFX from coincident
speech attacks, so the per-reel yes/no split rests on the original ear pass
only — **MEDIUM**.)

**M5 — B-roll montage rides the music bar. [1 reel — LOW-CONFIDENCE]**
Daf: cutaway shots held 1.1–1.4s ≈ the 1.26s onset-autocorrelation period; the
only b-roll→b-roll cut is covered by a 0.42s orange→white light-leak + whoosh
(HF +20dB in a speech gap). Music grid applies ONLY inside insert montages.

---

## 7. Transition budget

**6 softened joins across 623.1s / 166 cuts (<4%); ZERO on talking-head↔talking-head. [6/6 — HIGH]**
DQr: 1 white-flash whip @80.83 (between two phone screenshots — burst-measured
2026-07-09: whiteout core ~5f + a blurred re-focus tail, ~0.2–0.3s total, not
3–4f) + 2 dim crossfades ~0.3s @70.7/71.27 (between YT scroll positions,
burst-verified). DVg: 1 motion-blur
swipe ~0.3s @30.42 (graphic exit riding a cut). DZ2: 1 desat+dim ramp 0.4s
@26.95 (pre-meme energy dip). Daf: 1 light-leak 0.42s + whoosh (broll→broll).
DaG + DaV: zero. **Rule:** the `transitions` track stays EMPTY for talking-head
joins; a flash/leak is legal only INSIDE insert material (screenshot→screenshot,
b-roll→b-roll). This is the opposite of the long-form light-leak grammar
(`docs/studies/MEASURED_EDIT_GRAMMAR.md` §3) — do not inherit it.

---

## 8. LOW-CONFIDENCE register (seen <3 times — re-verify before templating)

**3-reel band (holds on 3/6 reels — solid but not corpus-wide; keep the reel
count in mind when templating):** H4 bookmark (3 reels), C4 pivot-word locks
(3 reels), C6 importance-scaled punch (3 reels), CAP6 text-survives-cuts
(3 reels), E5 full-frame takeover (3 reels), E6 top-band insert (3 reels),
E8 playing-video PIP (3 reels), E13 gesture choreography (3 reels). Everything
else tagged HIGH holds on ≥4/6 reels or ≥6 instances across ≥4 reels.

| Rule | Seen | Where |
|---|---|---|
| H6 blur-tease cold open (rack ~0.15s) | 1× | DVg 0–1.6s |
| H7 B/W hook device | 2× | DaG 4.0 · DZ2 5.73 |
| Z3b room-making pull-out | 1× | DQr 34.8–46.9 |
| Z4 crash push-in +59%/s | 1× | DQr 52.97 |
| Z6 outro camera move (pull vs push conflict) | 2× | Daf −1.15%/s · DQr +22% |
| CAP4b climax word white +1.5–1.7x | 1 reel | DQr 9.63, 38.0 |
| CAP5b caption relocation under bands | 2 reels | DZ2 · DaG |
| CAP7 caption-less keyword-pop variant | 1 reel | DQr |
| CAP8 #N list-pill lane | 1 reel | DaV 17.37–74.3 |
| Red-X negation marker | 2 reels | DaV · Daf |
| Slide-in entrance (vs pop/spring) | 2 reels | DaV chip · Daf card |
| Arrow stroke-draw 0.4s | 1× | DVg 9.0 |
| E1b giant numeral 8–14%H, alternating corners | 2× | DVg 37.67, 48.58 |
| E7 live-typing notes insert (~10cps) | 1 reel (4×) | DZ2 |
| E8b acted OS HUD (iOS volume story) | 1 reel (2×) | DZ2 57.5, 68.35 |
| E11 progressive diagram build + recall | 1 reel (5+3×) | DVg |
| E12 meme insert | 2 reels (3×) | DaG · DZ2 |
| M5 b-roll rides music bar + light-leak seam | 1 reel | Daf |
| Whip-exit w/ motion blur | 1× | DVg 30.42 |

---

## 9. The executable profile (wired)

`producer_config.MODES["short"]["pacing_jadenly"]`, selected by
`target.pace == "jadenly"` (resolver `plan_lint_motion._pacing_profile`):

| Key | Value | Source |
|---|---|---|
| `min_changes_per_min` | 14.0 | §2 C1 — floor below the eye-verified 17.2/min visible-cut median (cuts alone; graphics add more; the lint counts both) |
| `max_still_gap_s` | 12.0 | §2 C8 — longest measured no-cut+no-graphic stretch 10.9s (DZ2 83.7–94.5); ceiling admits the legal outro hold |
| `hook_front_load` | 1.3 | §1 H2 — the front-load lives in the graphics layer; the lint counts graphic entrances, so a compliant plan clears 1.3 |
| `state_changes_per_min` (advisory) | 70.0 | §0 — 51–89 states/min (6/6); the brain paces caption+shout churn to this, the lint does not read it |
| `music` (advisory) | True | §6 M1 — 6/6 carry a bed; never beat-synced |

**Plan-authoring checklist (brain-side, from §§1–7):**
graphic on screen at frame 0, receipts pills in the hook (H1–H3) · bookmark
CTA at s 9–16 (H4) · transitions track EMPTY (§7) · every cut 1f hard,
speech-timed at pause-end −0.1s or speech-through (C2–C3), alternating
tight↔wide ±12–45% (C5), biggest step on the most important line (C6) ·
punch-out BEFORE opening a graphic lane (C7) · no aliveness creep — hold drift
≤1%/s; eased push only INTO a payoff at 3–19%/s (Z1–Z2) · whisper captions
1–4 words/0.45–0.55s, no karaoke, tier-A amber keywords, tier-B serif
promotions at 0.08–0.42s/word (§4) · graphics pop ≤2f word-locked ±0.2s,
staggered 0.1–0.75s, EXIT hard-off on cuts/boundaries (§5.3) · panels held
>1.5s carry 1.5–4%/s drift (Z5) · music bed on, ~3 LU under dialogue in gaps,
−14 LUFS master (§6) · end on a clean-down outro hold ≤12s (C8).

---

## 10. Catalog gaps — what the system cannot express yet (DO NOT build here)

Existing near-misses noted so the builder extends instead of clones.

> **Build status 2026-07-09 (RENDER/COMPS lane):** G1+G3 SHIPPED
> (`jaden-shout-lockup.html` + tokens.css `--font-serif-display` ChunkFive/OFL
> + `--lemon` #F5E960), G2 SHIPPED (`CAPTIONS["WHISPER"]` +
> `captions_whisper.py`, `captions.style: "whisper"`), G4 SHIPPED
> (`motion-tokens.js` pop-in ≤2f / instant-out + `graphics/exit_on_cut.py`
> ``"exitOnCut": true`` seam clamp), G5 SHIPPED (``"takeoverBase":
> "blur-desat"`` in graphics_stage), G17 SHIPPED
> (`pacing_jadenly.punch_zoom_max: 1.45`). The §11 music-bed blocker is closed
> by `assets/music/default-bed.mp3` + ingest builtin registration.

- **G1 · Display-serif shout font + signature-yellow token.** `templates/motion/
  tokens.css` has Inter + Georgia-italic and `--gold:#FFD400`. Need a chunky
  rounded display serif (`--font-serif-display`, Cooper/Recoleta/Chunk-Five
  class) + a lemon/amber token in the measured #F2D24B–#F5E960 family (6/6).
- **G2 · Whisper-caption preset.** `CAPTIONS["MINIMAL"]` is 80px (4.2%H) with
  gold serif-italic accents. §4 CAP2 needs: 1.6–2.5%H, 1–4 word chunk-replace
  at 0.45–0.55s median, y0.55–0.66, no karaoke, tier-A inline amber keyword
  colouring from the chunk's first frame.
- **G3 · Tier-B promotion layer / keyword-lockup comp.** `text-element.html` is
  one string, one colour, house fade/slide. Need: multi-token two-tone lockup
  (yellow serif payload 4.5–6%H + white grotesque co-word ~4%H + kicker
  ~1.8%H), word-append build at 0.08–0.42s/word, pop-in ≤2f, ZERO exit
  animation, replace-chain ~0.9s.
- **G4 · Exit-on-cut compositing rule.** House comps self-fade-out;
  `graphics_stage` honours window ends only. §5.3 law needs first-class
  support: kill any standing overlay exactly ON a cut instant (≤1f), plus
  `pop-in ≤2f` / `instant-out 0f` shared motion tokens replacing hand-rolled
  eases.
- **G5 · Blur+desat takeover base treatment.** 8 instances / 4 reels: live
  frame → gaussian σ≈20–30 + desat in 1–2f MID-SHOT (no cut), content cards
  spring in over it, hard restore ON the next cut. No lane exists
  (`pip_takeover` is unwired and a different move; `glass-takeover-bg` is a
  comp background, not a base-video treatment).
- **G6 · Top-band insert lane.** Full-width y 0–0.24..0.45 band, 1-frame
  on/off, A-cam keeps cutting underneath, captions RELOCATE below (render-time
  caption y-shift while a band is up). No comp + no caption-relocation wiring.
- **G7 · Tilted receipt-card / 2×2 grid comp.** Real-screenshot cards r24–30px,
  shadow, tilt ±3–6°, spring pop 0.15–0.35s, stagger 0.42–0.75s, float drift
  while held. `broll` lane is full-frame inserts; `stat-card`/`list-build` are
  flat card looks.
- **G8 · Gesture/fingertip anchor.** `MOTION["face_anchors"]` stops at
  faceBBoxNorm; E13 needs per-window hand keypoints + an `on-gesture` anchor
  (3 reels). Biggest infra lift.
- **G9 · View-pill row comp.** Eye-glyph + count pills, dark #251F1C@85% and
  light variants, 0.1–0.4s stagger, group exit. `widget-pills.html` is the
  nearest miss — verify before cloning.
- **G10 · Bookmark save-CTA comp.** Stroke-draw 8–13f → fill snap 2–3f; no
  draw-on animation primitive exists in the comp library.
- **G11 · B/W grade-pulse operator.** Windowed full-frame desaturate
  (0.47–3.1s) cut-locked at both ends; `baseline_look` grades whole-video warm
  only — no windowed grade track.
- **G12 · Panel self-drift.** Held panels need 1.5–4%/s scale/float (Z5, 4/6);
  comps render static holds today.
- **G13 · Playing-video PIP card.** Rounded phone mockup that PLAYS a clip
  over the blurred/grayscale base (3 reels); `canvas-pip-list` is an opaque
  takeover, b-roll is full-frame. The acted OS-HUD garnish is LOW-CONFIDENCE.
- **G14 · Live-typing notes insert (~10cps).** LOW-CONFIDENCE (1 reel) — spec
  only, park.
- **G15 · #N list-pill caption lane.** Persistent second caption line swapping
  on item boundaries, graphics lifecycle-bound to items. LOW-CONFIDENCE (1 reel).
- **G16 · SFX pop/thump layer on graphic entrances.** Optional (2v2 reels);
  `transitions` whoosh is the only SFX wire today. Low priority.

- **G17 · Punch-step ceiling.** `MOTION["punch_in"].zoom_max = 1.25` clamps the
  measured C5 step band (+12..45%, max x1.44 DaG; outlier x1.92 Daf). A jadenly
  plan's biggest legal punch is ~half the reference's biggest. Needs a
  pace-profile-aware step band (or a doctrine decision to keep the cap).

---

## 11. 2026-07-09 comprehension audit — fresh-pixel re-verify + reproduction test

**Re-verify:** all 53 named rules re-checked against FRESH extractions (6 hook
sheets, 10 body/outro sheets, 22 frame-accurate bursts at 24/30fps, YuNet
face-height zoom traces, scale-fit cut classification, ebur128/silencedetect/
flux audio passes). **50/53 confirmed** (Z3 partial — one DQr citation
contradicted; M4 instrument-ambiguous; §5.2 had two wrong coordinate rows).
Corrections were edited in place: H4 fill/exit times, C8 DaG lean magnitude,
Z2 rates + one misattribution, Z3 demotion, CAP4 Daf append floor, §5.2
Metaphor/chip rows, §7 white-flash duration. Independent instrument notes:
LUFS/TP/silence reproduced EXACTLY (−14.5..−14.7 / −0.7..+0.4 / 0 gaps, 6/6);
cut-rate medians bracket the eye counts (conservative frame-diff 8.4–12.8/min,
scale-fit 12.5–23.0/min vs eye 10.4–20.4/min) — reconfirming the §0 warning
that no single automatic counter reproduces the eye count; cuts sit at RMS
floors −34..−45dB with the post-cut word hotter in 78–93% of joins (C2/C3).

**Reproduction test** (scratch copy of `c0679-intro`, 36.67s jadenly short:
frame-0 hook card + staggered pill row + word-locked keyword pops + icon badge
+ 2.2s takeover + 4 alternating punch steps on cut joins, transitions EMPTY,
captions minimal; plan_lint clean, render+audit 22/22 pass). Deltas vs the
closest Jaden moments, same instruments both sides:

| Axis | Ours | Jaden | Delta |
|---|---|---|---|
| Visible cuts/min (scale-fit) | 13.1 | 12.5–23.0 (med ~17.4) | −25% vs median, in range |
| States/min (2fps diff) | 129 | 99–119 | +8% over max (captions bigger) |
| Punch step band | 1.08–1.22 (lint cap 1.25) | 1.12–1.44 (+1.92 outlier) | biggest step −50% (G17) |
| Hook card @frame 0 | yes, hold 3.0s, exit ~2f | yes 5/6, hold 3.0–6.5s, exit ≤2f | ≈0 (enable-window hard-off) |
| Keyword pop-in | 3–4f fade (0.12–0.17s) | ≤2f pop (≤0.083s) | ~2x slower + fades (G3/G4) |
| Keyword size / band | ~2.1%H @ y0.44 | 4.5–6%H serif @ y0.115–0.27 | ~2.4x small, wrong band (G1/G3) |
| Caption size (same instrument) | 2.6–3.3%H @ y0.57 | 2.1–2.3%H @ y0.60–0.64 | ~1.35x oversize (G2) |
| Karaoke sweep | none (minimal) | none 6/6 | ≡ |
| Integrated LUFS / TP | −14.2 / −1.9 | −14.5..−14.7 / −0.7..+0.4 | +0.3–0.5 LU; TP ceiling ours (keep) |
| Silence events | 0 | 0 (6/6) | ≡ |
| Speech-gap floor p10 | −47 dB (NO music bed) | −32..−36 dB (bed lights gaps) | gaps ~12–14 dB darker — M1/M3 unmet (no music asset in manifest; `music_stage` needs one) |
| Word-lock of graphics | on transcript onsets | ±0.2s median | ≈ (same mechanism) |
| Takeover | opaque statement-card 2.2s | blur+desat base + spring cards | structure ✓, base treatment missing (G5) |
| Panel self-drift | static hold | 1.5–4%/s drift (Z5) | missing (G12) |
| Bookmark CTA / B/W op / tilted receipts / gesture pins | absent | present | G10 / G11 / G7 / G8 confirmed real blockers |

**Verdict:** the executable profile (`pacing_jadenly` floors) and the plan
checklist survive contact with the renderer; what cannot be expressed is
exactly the §10 catalog-gap list (G1–G5, G7, G8, G10–G12 exercised and
confirmed by this attempt, G17 added). The reproduction is recognisably the
grammar at the structural level; it fails Jaden at the TYPOGRAPHY layer (serif
two-tone shout lockups), the ≤2f pop tokens, the blur+desat takeover base, and
the missing music bed.
