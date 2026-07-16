# INTRO TEST — MACHINE vs PRO, frame-by-frame delta audit (2026-07-05)

The machine's intro edit (`INTRO TEST (machine edit).mp4`, 307.2s) against the
pro's finished cut ("Replaced 5 Content Tools With 1 Production Workflow",
first 299.1s) — **the same raw footage, the same spoken words**, word-aligned
(2,679 anchor words, 94.7% match). This is the ground-truth answer to "why does
the machine edit read amateur," measured, not vibes.

Method: producer-study loop (fingerprints → aligned frame ladders → native-fps
animation bursts → ORB pan/zoom probes → gap/loudness audio probes). Evidence
sheets delivered to `~/Desktop/INTRO AUDIT - machine vs pro/` (16 images).
Working data: session scratchpad `audit/` (alignment.json, pacing, bursts).

## 1. The scoreboard (aligned window, same spoken content)

| Dimension | PRO (299.1s) | MACHINE (307.2s) |
|---|---|---|
| Runtime for identical words | 299.1s | 307.2s (**+8.1s looser**) |
| Visual cut boundaries | **70 (14.0/min)** — median shot 0.9s, mean 4.1s, max 27.6s | **0** (3 invisible plan seams; longest static stretch = the whole video) |
| Zoom/reframe events | **17** (punches + ramps to +44%) | 1 (1.21x, 1.6s) |
| Cutaway / b-roll segments | **~15 substantive** (~48s ≈ 16% of runtime off the face) | 0 |
| Graphic treatments | 10+ distinct families (see §2) | 2 glass overlays (1 broken) |
| Burned kinetic text | ≥5 moments | 0 |
| Transitions | white-flash ~125ms, light-leak washes 150–400ms, hard cuts into "graphic worlds", **whoosh SFX** | none — butt joints, silent |
| Baseline framing | tight chest-up crop, graded warm, constantly re-framed | raw wide 4K framing, flat color, never changes |
| Silence in window | 7.0% (max gap 1.04s) | 10.8% (4 gaps ≥0.8s) |
| Audio | −24.4 LUFS, LRA 4.8 (dynamic), low bed likely, SFX on transitions | −15.6 LUFS, LRA 2.7 (over-compressed), bone dry |

Visual state density (study fingerprints): pro ≈ 520 states/974s with 62
graphic instances in 4 families; machine = 76 states/307s that are almost all
compression noise on one static shot.

## 2. What the pro actually does (cutaway catalog, intro window)

Every substantive claim gets a **second modality**. Catalogued from frames, with
what is being SAID at that moment:

| # | Pro time | What it is | Trigger in speech |
|---|---|---|---|
| 1 | 0:04.6 | Kinetic red/white burned text of the hook + doodle arc-arrow w/ icon badges → **white flash** → reframe | "write this sentence down" |
| 2 | 0:11.3–0:19.0 | Full-screen **dark takeover cards** ×2, progressive hand-off | thesis restate ("that line alone… the other half is your system") |
| 3 | 0:26.9 | Light-leak wash → **ident card** (face in circle + kinetic "I'm…") | self-intro |
| 4 | 0:38.1–0:46.6 | **Whiteboard mind-map build**: graph paper, nodes land per enumeration item, connectors **draw on**, canvas drifts; exit white flash → punch-in +23.8% | "YouTube comedy channel… SEO company… AI agency" |
| 5 | 1:22.7–1:27.8 | Illustrated 3D **podium 1-2-3** scene w/ spotlight + in-graphic camera | "launched three different things" |
| 6 | 1:34.1–1:37.6 | **Screen-recording receipts**: his real YouTube channel page | "I started with YouTube" |
| 7 | 1:42.7–1:46.0 | 3 rapid clips of his actual cartoons (~1.1s each, micro-montage) | "they were animated sketches" |
| 8 | 1:52–1:58 | Punch-outs make headroom → ❌ checklist lands **beside the face** item-per-beat ("No Niche / No Offer / No Idea") → light-leak exit | "no niche, no offer, no idea" |
| 9 | 2:02.3–2:05.8 | Laptop b-roll: his AI-agency site, slow push + page scroll | "tried to build an SEO company" |
| 10 | 2:31.5 | Stock footage (business people), blown light-leak entrance | client-work era |
| 11 | 2:40.0–2:43.7 | SEO site **progressive scroll** receipts | "Engineering-first SEO" |
| 12 | 2:57.4–3:01.6 | Kinetic type takeover "I know AI" + robot image, staged mixed-typography build | "I know AI, I've been building with it" |
| 13 | 3:23.8→3:47 | Wash → **burned caption fragments** + 22.8s slow push-in under story | "I felt very confident…" |
| 14 | 3:47.6–3:53.8 | **Red pyramid "Principles" takeover** w/ in-graphic push + hand-drawn annotation of his exact sentence | "principle number one: don't scale delivery until…" |
| 15 | 4:17.9 | Kinetic "our video workflow is chaos" burn → white flash → reframe → **studio b-roll** (his real room) | "five different applications… video-first production workspace" |
| 16 | 4:38.9–4:45 | +44.3% ramp then −32.6% punch-out bracket | "when I actually needed a sharper…" |
| 17 | 4:39–4:41 (out ~283) | **B&W quote cutaway**, yellow text builds word-by-word — **covers the retake seam** | "thinking that I needed more tactics" |

B-roll sources: own archive (cartoons), own products (site screen-recordings),
own studio, stock, illustrated metaphor scenes, whiteboard canvas. Receipts >
decoration throughout.

And the control case: at the **agenda enumeration (0:55–1:10)** — where the
machine floated its glass rail — the pro shows **nothing at all**. Delivery +
reframe alternation carries it (R14 confirmed on second look).

## 3. Animation grammar (native-fps burst measurements)

- **White flash** = ~3 frames (~125ms): wash frame → full white → new shot.
  Burned text rides OUT inside the flash.
- **Light-leak wash** = 150–400ms orange/pink, used both as cutaway entrance
  and overlay exit.
- **Takeover entrance**: hard cut into dark world; card scales/fades ~400ms;
  internal elements (icon, bold words) continue brightening to ~1.2s. Staged,
  never pop-from-nothing (R9 re-confirmed at 24fps).
- **Whiteboard**: wash-in ~150ms → node fades ~250ms → connector **draws on**
  → canvas drifts laterally; un-built nodes visible as black boxes
  (progressive disclosure).
- **Word-by-word quote build**: 100–150ms per word, matching speech cadence;
  yellow emphasis on payoff words; layout re-centers as words land.
- **Checklist**: coordinated move — punch-OUT first to create headroom, then
  items pop (~100ms) on each spoken beat, placed beside the face.
- **In-graphic camera**: podium/pyramid scenes contain their own pushes and
  annotation draw-ons; a graphic is a scene, not a sticker.
- **Transitions are audiovisual**: flash/wash moments carry whoosh-level SFX
  (peaks −11 to −15 dB in speech gaps vs −40 dB true-pause floor).

## 4. Zoom + pan mechanics (ORB probe, 960×540 basis)

- Between events the pro is **locked** (median |dx| 0.08px/0.4s) — no idle
  Ken Burns drift. Motion is always deliberate.
- Ramps carry **translation**: the +43.8%/24.9s push accumulates −206px/−143px
  (≈ −413/−286 @1080p) — the zoom **recomposes toward the face**, it does not
  scale about a fixed center. `punch_in.py` currently scales around a static
  anchor → machine ramps will read mechanical. Needs a pan-to-target vector.
- Machine window: 1 zoom event vs pro's 17. Note the MG-4 zoom planner
  *proposed* more; brain review accepted only 1. Acceptance was tuned for
  overlay-averse caution, not zoom cadence (longform doctrine says 2.15/min ≈
  10–11 events for this window).

## 5. Audio

- Pro: −24.4 LUFS integrated (window), LRA 4.8, TP −5.2; "gaps stay lit" →
  low bed likely + transition SFX. NOT loudness-maxed. (Keep our −14 LUFS
  platform target — but the pro proves dynamics + layers matter more than
  level.)
- Machine: −15.6 LUFS (C16 known miss vs −14 target), LRA 2.7 — the
  compressor+speechnorm chain crushed dynamics, and there is no SFX/bed layer
  at all.

## 6. Why the machine edit reads amateur — five roots, ranked

1. **No cutaway/b-roll lane exists.** Pro spends ~16% of runtime off the face
   across ~15 cutaways in 6 families; machine has zero. This is the single
   biggest perceived-quality gap.
2. **No reframe/cut cadence.** 70 visible framing changes vs 0. The machine
   ships the raw wide framing, ungraded, and never moves. (The pro's baseline
   is ALREADY a punch-in: tight chest-up crop of the 4K frame + warm grade.)
3. **No transition language.** Every pro world-change is flash/wash/cut +
   whoosh; machine graphics fade in over the face, silent, and its plan seams
   are naked butt joints (pro covers its seam with a B&W quote cutaway).
4. **No burned text.** The pro burns the hook, the I-help line, key quotes,
   and selective caption fragments in styled kinetic type; machine burns
   nothing (captions.burn=false in this plan).
5. **Looser pauses + dry audio.** +8.1s dead air vs pro on identical words;
   over-compressed, quiet, no SFX.

Plus the two known render bugs, both confirmed on frames: **G21** (glass-rail
sample rows "Captions/Music/Export final.mp4" leak into unset rows) and **G22**
(rail centered over the face). The machine's one good graphic (lower-third
"Five apps to one board") is clean but static for 5.1s over a static frame.

## 7. Automation queue (in build order)

1. **baseline-look stage**: talking-head longform default = tight crop from 4K
   (the pro's chest-up framing) + simple warm grade LUT. Instant 50% of the
   "pro look" for near-zero effort.
2. **reframe-on-seam engine**: every cut/cutaway-return/plan-seam lands on an
   alternate framing (±15–20%, direction-alternating; R13/R16). Extend
   `punch_in.py` with a face-target pan vector so ramps recompose, not
   center-scale.
3. **transition primitives** in the renderer: `white-flash` (3f), `light-leak`
   (8–10f), `cut-to-world` — plus a tiny whoosh SFX library keyed to
   transitions (SFX ≠ music; the no-music-by-default rule stands).
4. **whiteboard cutaway family** (R14 build queue): whiteboard-map (nodes +
   draw-on connectors + canvas drift + progressive disclosure), whiteboard-list.
   Full-frame cutaways, not overlays. MG-4 mapping: talking-head-longform
   enum/story → whiteboard cutaway; thesis → takeover card (glass-takeover-bg
   exists) or burned kinetic quote.
5. **kinetic burn-ins**: hook/thesis/quote lines burned word-by-word at speech
   cadence with emphasis color (16:9 comp + burn stage; word times from the
   timeline map — we already own them).
6. **receipts b-roll lane**: ingest operator-provided artifacts (screen
   recordings, old clips, site captures) as sources; MG-4 trigger: speech
   references a showable artifact → propose receipt cutaway (1–4s, micro-
   montage for lists). Assess-pool-FIRST doctrine already says this — it now
   has ground truth.
7. **seam-cover law in lint**: every retake/topic seam must be covered by a
   reframe, flash, or cutaway — a naked butt joint on identical framing is a
   lint WARN (X-rule).
8. **pause tightening**: longform max residual gap ≤1.0s (pro's max was
   1.04s); current edit left 4 gaps ≥0.8s incl. 1.2s.
9. **C16 fix + LRA floor**: hit −14 LUFS without crushing LRA below ~4
   (machine 2.7 vs pro 4.8) — revisit the compressor chain, and stop
   pre-normalizing before the graphics/SFX mix exists.
10. **MG-4 zoom acceptance**: accept toward doctrine cadence (2–3/min
    longform), not 1-per-video; planner already proposes candidates.

## 8. v2 RETEST (2026-07-06) — same raw, rebuilt pipeline, re-measured

Queue items 1–3 + 7–10 built and shipped (baseline_look.py, pan-aware
punch_in, transitions.py w/ whoosh synth, channels/master fixes, lint +
selftests 132 green); v2 re-rendered from the TRUE 4K raw and re-measured with
the identical instruments that graded v1:

| Dimension | PRO | MACHINE v1 | MACHINE v2 |
|---|---|---|---|
| Cut boundaries (scdet 8) | 70 (14/min, incl. in-cutaway) | 0 | **22** |
| Zoom events | 17 | 1 (undetected) | **15 (2.94/min, 13 punch + 2 ramp, in:out 0.88, median 15.3%)** |
| Baseline framing | tight chest-up crop + warm grade | raw wide, flat | **chest-up 1.28 crop of 4K + warm grade, face-recomposed ramps** |
| Transitions | flash/wash + whoosh | none | **3 white-flash + 1 light-leak, frame-exact (wash→white on seam), whoosh −15 dBFS pre-master** |
| Max residual gap | 1.04s | 1.21s | **1.0s** |
| Audio | −24.4 LUFS, LRA 4.8 | −15.6 LUFS, LRA 2.7, one-eared | **−14.1 LUFS, LRA 4.3, TP −1.9, dual-mono repaired** |
| Graphics | 10+ families | glass rail w/ G21 leak over face + lower-third | **lower-third only (clean, no leak); rail dropped per R14** |
| Audit B | — | 17/0/0 (missed all of the above) | 20/0/0 |

The retest itself caught and fixed three shipping-grade bugs the build had
introduced or exposed (X20 integer-fps retiming slid seam flashes off their
frames; X21 whoosh-mixing defeated dead-channel detection → one-eared speech;
X22 every pre-existing animated ramp was silently anchored top-left).
Evidence: Desktop "INTRO AUDIT - machine vs pro/v2/" (v2 video + ladders +
verification strips).

REMAINING GAP vs pro, in order (unchanged from §6/§7): the cutaway/b-roll lane
(whiteboard family, receipts, takeover cards — queue items 4–6) and burned
kinetic text (item 5). The v2 ladder shows talking-head rows now at parity;
every remaining delta row is a missing cutaway.

### v3 (2026-07-06, same day) — the cutaway lane, built and re-measured

Queue items 4–6 shipped: whiteboard-map/whiteboard-list/kinetic-quote-wide
comps (16:9, empty-defaults, verified through graphics_render.py own-screen),
broll_insert.py receipts stage (frames replaced, audio bit-identical), MG-4
longform retarget (canvas filter, R14 gauntlet, receipts lane, 120s hook
window per operator retention doctrine — see R20), mode-keyed hold/takeover
ceilings, X23 dark-takeover audit handling.

| Dimension | PRO | v1 | v2 | v3 |
|---|---|---|---|---|
| Cut boundaries | 70 | 0 | 22 | **40** |
| Cutaway shots detected | ~71 full-video | 0 | 0 | **16** |
| Zoom events | 17 | 0 detected | 15 | 14 (2.74/min, in:out 1.0) |
| Graphic worlds | whiteboard/takeovers/receipts | 1 broken rail | lower-third only | **whiteboard-map build + 2 kinetic takeovers + 4 receipts + lower-third** |
| Audio | −24.4 LUFS, LRA 4.8 | −15.6, one-eared | −14.1 | **−14.0 exact** |
| Audit B | — | 17/0/0 (blind) | 20/0/0 | 19/1/0 (warn = legitimate graphic holds) |

Same-beat proof (Desktop `v3/00 SAME BEAT - v3 vs pro.jpg`): at the thesis,
enumeration, three receipt beats, and the retake seam, v3 makes the same
editorial move as the pro. MG-4 acceptance landmark: run cold on this footage
the planner independently proposed the whiteboard at the enumeration
(word-timed nodes), the thesis quote, receipts 3/3 — plus whiteboard beats at
112s/234s that match real pro graphic moments (checklist, pyramid).

Honest notes: receipt assets were lifted from the pro cut's own cutaways (the
operator's own artifacts) — the lane's ingest/propose/render machinery is what
was tested, not asset sourcing; the light-leak color and whoosh level remain
ear/eye calibration knobs; kinetic-quote-wide's mid-build re-centering has one
awkward two-line gap state worth a polish pass.

## 9. Honest limits

- Cutaway boundaries from 5fps frames (±0.2s); burst timings from native
  23.976fps (exact).
- N=1 pro editor; these are priors to recalibrate on the next pair (the
  transition/receipts grammar is consistent with the IG reference studies,
  which raises confidence).
- Pro LUFS measured on the downloaded file; YouTube's stream normalization
  may differ.
- scdet@8 "70 cuts" includes in-cutaway internal cuts; talking-head-only
  reframes are a subset (~⅓ by the zoom map's punch table).
- The −24.4 LUFS pro level is NOT a target to copy (platform spec −14 stands);
  the transferable facts are dynamics (LRA), the bed, and transition SFX.
- Tool caveat found during this audit: `study_zoom` reported 0 events on the
  machine edit, but the planned 1.21x punch-in DID render (frame-verified at
  53.6–55.2s). Short (~1.6s) ramps inside a single cut-free shot fall below its
  trajectory windowing — don't trust zoom-map zeros on uncut footage.
