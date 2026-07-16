# Reference Style Study #1 — operator-supplied IG shorts (2026-07-05)

Three reference verticals studied (720×1280, ~24fps; 110s / 82s / 30s), via
pHash unique-state extraction (86 / 74 / 25 states) + frame review. These are
the operator's "good short" exemplars: **study spacing, what items look like,
how graphics relate to the human.** Contact sheets + frames:
session scratchpad `reference-shorts/`.

## The extracted grammar (rules of the road)

### R1 — Captions: minimal, word-at-a-time, chest-anchored
Single word or 2–3-word phrase on screen at once ("didn't", "break",
"situation.", "hard.", "sauce"). SMALL — ~4–5% of frame height (≈75–95px on
1080×1920). White sans, subtle shadow, no heavy outline box. Position:
**chest/neck center** — directly under the chin, moving slightly with
framing. NOT a lower-third block, NOT 2-line karaoke.
→ Implementation: new caption style `minimal` (word-at-a-time events, chest
band anchored relative to face bbox). Our karaoke band remains a second style.

### R2 — Two-tone accent typography
Keywords/numbers in YELLOW (serif-italic in ref-1 for elegance; bold in
refs-2/3), base text white. e.g. "1 *Familiarity* Rule", "**2x** Month",
"*Pictures* in Visions". Our gold #FFD400 matches; add serif-italic accent
option to tokens.

### R3 — The headroom is the graphics canvas
Framing deliberately leaves generous headroom + side space; ALL persistent
graphics live there: numbered section markers ("1 Familiarity Rule"), stat
pairs ("2x Month 1x Week"), the parametric gauge widget. **The face is never
covered — ever** (confirms operator doctrine on real exemplars).

### R4 — Floating chest-level assets
Images/screenshots float SMALL (~35% width) at chest height, face fully
clear, while the speaker keeps talking (ref-1's document image). Assets don't
take over the frame unless…

### R5 — Focus-shift blur (NEW tactic)
…the data deserves the whole frame: then the SPEAKER BLURS OUT and a sharp
full-frame table/graphic renders over them (ref-2's Keyword|Traits table,
yellow serif headers). Distinct from `blur-tease` (withholding): this is
**focus transfer** — human recedes, data stars, human returns.
→ Tactic `focus-shift-blur`: blur base video + overlay sharp graphic;
trivially achievable (boxblur + our alpha overlays).

### R6 — Persistent parametric widgets (NEW template class)
Ref-3 runs a difficulty gauge (green→red bar + moving arrow) + follower pills
(10k → 50k→100k → 200k) pinned in the headroom that UPDATE with the
narrative. A graphic with STATE that tracks the story, not a one-shot pop.
→ Template class `widget-*` with keyframed variable updates (hyperframes
seek-safe keyframes support this natively).

### R7 — Numbered section markers
Big numeral + small 2-word label, headroom-center. Our `stinger-wipe`/section
pattern maps; style per R2.

### R8 — Pacing (from state counts)
86 states / 110s (ref-1) ≈ a visual change every ~1.3s at peak — but mostly
from caption word-flips, NOT hard cuts. The BASE shot is calm (single locked
camera); the energy is typographic. Lesson: minimal captions at speech pace
supply the visual cadence; hard cuts stay sparse. This inverts our current
assumption (cut-driven cadence) for this style.

## Fingerprints (study_video.py, deterministic — quantifying R8)
| ref | cuts | cuts/min | longest static | unique states | music |
|---|---|---|---|---|---|
| ref-1 (110s) | 8 | 4.35 | **48.0s** | 115 | likely |
| ref-2 (82s) | 10 | 7.33 | 23.0s | 109 | likely |
| ref-3 (30s) | 2 | 4.05 | 20.9s | 38 | likely |

R8 confirmed with numbers: ~4-7 hard cuts/min (SLOW — long-form territory) while
states run 10-25x the cut count. The cadence is typographic, not cut-driven.
And a CORRECTION from the machinery: all three refs run a music bed ("likely",
loudness-floor + crest evidence) — my frame review called them speech-led. The
style pack includes a LOW bed; music remains opt-in per operator doctrine, but
when they ask for IG-minimal, recommend the bed.

## Style pack: "IG-minimal" (to sit beside "Kallaway-kinetic")
caption=minimal chest-anchored · accents=yellow two-tone · graphics=headroom
widgets + chest assets · takeovers=focus-shift-blur · base cuts sparse
(4-7 cuts/min measured) · LOW music bed (measured present in all refs;
still opt-in per music doctrine — recommend, never auto-add).

## DEEP PASS (2026-07-05, operator-demanded full-state review — 147+36 state frames)

The first pass SAMPLED (18 frames); this pass reviewed every unique state of
refs 2/3 + ref-1's mid-section. New findings the sample missed:

### R9 — Progressive disclosure: EVERYTHING builds in stages
No graphic appears fully-formed. Observed build orders, state by state:
- **Milestone widget (ref-3)**: lone "0 Followers" pill → arrow fades in →
  gauge marker appears → right pill enters (label DIMMED vs left = target-vs-
  current hierarchy) → **value hand-off** (right value becomes next left) →
  marker TRAVELS the gauge with the narrative (animated tween, mid-positions
  captured). Widget hugs the very top: y≈130–230.
- **Focus-shift table (ref-2)**: speaker blurs AND dims → "Keyword" header +
  divider draw FIRST → "Traits" header → left column populates → right column
  → long hold (5-8s) → sharp release back to speaker.
- **Section markers (refs 1&2)**: small white eyebrow ("System No.2") appears
  first → yellow-serif title WIPES IN below (mid-wipe states captured ≈
  100-170ms entrances) → extends ("& Creative Direction" adds a line).
  **TOP-LEFT anchored** (or the emptier side) — NOT centered. Structure:
  numeral/eyebrow + yellow-serif name + white-sans qualifier.
- **Schedule-stack (ref-2, NEW pattern)**: color-SEMANTIC rounded cards
  (green "Ideation 8-10am" / blue "Filming 10-2pm" / coral "Distribution
  2-3pm"), serif bold titles + small time sublabels, stacked on the side
  OPPOSITE the speaker, staggered wipe-in entrances.

### R10 — Placement law, observed everywhere
Graphics ALWAYS occupy the emptier region, opposite the subject; the same
marker moves sides between shots as the framing changes. (Exactly what
placement-v2/free_space is building — now reference-evidenced.)

### R11 — Real icons (operator-attested)
The operator confirms real app icons appear in these reels; my reviewed
sheets haven't captured the exact frames yet (likely ref-1 late states /
hook regions). Icon library built regardless (#27); when the frames surface,
match their icon sizing/treatment exactly.

### Template corrections queued from the deep pass
1. section-marker.html → top-left/emptier-side anchor, eyebrow-first
   progressive build (current version is centered numeral-led — wrong).
2. NEW template: schedule-stack.html (color-semantic cards, staggered).
3. widget-gauge/pills → staged entrance vars (pill-first, arrow, marker) +
   value hand-off support (current version shows all elements from frame 1).
4. Entrance timing standard: ~100-170ms wipes/fades, never pops-from-nothing.

## Build queue derived from this study (MG-3.5)
1. Caption style `minimal` (word-at-a-time + face-relative chest anchor)
2. `focus-shift-blur` compositing mode in graphics_stage (blur base under own-screen)
3. Widget template class (parametric gauge / counter pills) — hyperframes keyframes
4. Serif-italic accent tokens + headroom section-marker template
5. Face-relative graphic anchoring (anchor: "headroom" | "chest" | "beside-face"
   computed from faceBBoxNorm) — extends the anchor vocabulary beyond free-band/own-screen

### R12 — Icon doctrine (operator verdict, 2026-07-05)
Icons ALONE carry entity graphics — a recognizable mark in a small square
container beats icon+pill+label (the chip text is redundant with the mark and
with the spoken word). And GENERIC words earn no graphic at all: an "AI" chip
while the speaker says "AI" adds zero information (worse when it borrows a
brand's mark — two OpenAI knots for one sentence). Rules: (1) entity graphic
only when the entity is SPECIFIC (Codex yes, "AI" no); (2) prefer icon-badge
(square container, bare mark) over chip when the mark is recognizable;
(3) chips reserved for entities with NO known mark (text is then the info).

---

## ZOOM ADDENDUM (2026-07-06) — the shorts' zoom grammar

Ran the long-form zoom pipeline (`zoom_scale.py` whole-frame ORB similarity-scale
+ `zoom_detect.py`) on the three reference shorts, to give the IG-minimal style
pack the same zoom grammar the long-form study now has
(see `docs/studies/LONGFORM_VISUAL_STUDY.md`). Artifacts:
`scratchpad/reference-shorts/zoom/ref-{1,2,3}/data/zoom_map.json` +
`zoom/validate_shorts.jpg` (visual proof pairs).

**Noise floor — honest, because the shorts have no raw baseline.** I measured it
directly instead: ORB similarity-scale on within-shot frame pairs (which have no
real zoom). ORB survives the compression fine (inliers p50 326–718, ok-rate
80–91%), and the faces are 2–4× bigger than the long-form (area p50 0.043–0.080 vs
0.019), so the signal is actually *cleaner* than the long-form baseline — except
ref-2:
- **ref-1, ref-3 (locked, ~1–2 Mbps):** |scale-1| noise p90 ≈ 1.1–1.2% per 0.2 s,
  static-second median ≈ 0.02–0.04%. Punches (15–22%) clear it by 15×. Ramps
  ≥3% trustworthy; **sub-5% ramps are detectable but marginal** (one ref-1 −4.1%
  8.8 s creep is flagged low-confidence).
- **ref-2 (0.87 Mbps, a standing + slightly handheld shot):** noisier — 0.2 s p90
  ≈ 2.9%, static-second median ≈ 1.5%. **Sub-~4% ramps are NOT reliable here**, so
  I raised the ramp gate to 3% for all three and report ref-2 ramps with a caveat
  (its +37% "ramp" also contains the subject walking toward camera, so that
  magnitude is a combined subject+scale change, not a pure lens zoom). All punch
  cuts on all three are well above every floor and are visually confirmed.

**The numbers**

| | ref-1 (110 s) | ref-2 (82 s) | ref-3 (30 s) | long-form (ref) |
|---|---|---|---|---|
| Zoom events | 19 | 8 | 2 | 35 |
| **Events/min** | **10.3** | **5.9** | **4.1** | **2.15** |
| Punch : ramp | 17 : 2 | 6 : 2 | 2 : 0 | 21 : 14 |
| **Punch on a cut** | **17/18 = 94%** | 6/12 = 50% | 2/2 = 100% | ~⅓ of cuts |
| in : out | 9 : 10 | 4 : 4 | 1 : 1 | 20 : 15 |
| in:out ratio | 0.9 | 1.0 | 1.0 | **1.33** |
| Median magnitude | 17.7% | 18.6% | 18.2% | 20.8% |
| in→out brackets | 3 | 0 | 0 | (the signature move) |

### R13 — Zoom is RHYTHMIC in shorts, SEMANTIC in long-form

The single biggest difference between the two formats' zoom use:

- **The short fuses the cut track and the zoom track — nearly every cut is also a
  re-frame.** ref-1 punches on 94% of its cuts, ref-3 on 100%. So the editor almost
  never cuts to the *same* framing; each cut lands tighter or wider than the last.
- **~2–5× the long-form's zoom cadence** (4–10 events/min vs 2.15) — but the **same
  per-punch magnitude** (~18% linear). What scales up in a short is the *frequency*,
  not the size, of the push.
- **Direction is balanced (in:out ≈ 1.0)**, not the long-form's lean-in (1.33). The
  shorts *alternate* tighter/wider to manufacture a constant push-pull energy;
  they are not "pushing in on the point."
- **The in→out bracket exists (ref-1 × 3) but is demoted from signature to texture.**
  In the long-form the bracket is reserved for the biggest lines (hook payoff,
  product reveal, closing callback); in the short it's just one of the alternating
  moves that keep the frame kinetic, not a semantic marker.
- **Ramps are rare in shorts (4 total across 3 videos).** Shot lengths are too short
  to host a slow creep, and the hard-punch rhythm already supplies the motion; the
  long-form's subtle 0.3–1.8%/s ramps under narration have no equivalent here.

**Style-pack rule:** for `IG-minimal`, treat the zoom track as **part of the cut** —
default every hard cut to a scale change of ~15–20% linear, alternating direction to
avoid drifting monotonically tighter, at a cadence of one reframe every ~6–10 s
(ref-1's 10/min ceiling reads as high-energy; ref-3's 4/min as calmer). Reserve
gradual ramps for the long-form pack, not this one. This is the inverse of the
long-form doctrine ("cuts carry rhythm, zooms carry meaning"): in a short, **the
zoom IS the cut**.

### R14 — Talking-head longform: graphics are CUTAWAYS, never overlays (2026-07-06)
Direct machine-vs-pro comparison on identical footage (intro test): at the
agenda enumeration the pro shows NOTHING (delivery carries it); when content
earns a graphic he CUTS AWAY to a full-frame clean white whiteboard canvas
(hand-drawn connector, tiny nodes, massive whitespace). He never places a
translucent panel over the subject. Rules: (1) dense graphics on talking-head
longform = full-frame cutaway on the whiteboard-sketch canvas (whiteboard-*
family — the OPERATOR's language; liquid-glass is the sibling brand's, keep
for screen-share); (2) enumeration alone does not earn a graphic — story
beats do; (3) the frame belongs to the subject or to the canvas, never both.
Build queue: whiteboard-list, whiteboard-board siblings; MG-4 mapping:
talking-head longform enum/list → whiteboard cutaway (needsOperator), not rail overlay.

### R15 — Transitions are a language, and they are audiovisual (2026-07-05)
From the machine-vs-pro intro audit (docs/audits/INTRO_MACHINE_VS_PRO_AUDIT.md), measured
at native fps: every world-change in the pro cut is covered by a **white flash
(~3 frames / ~125ms: wash → full white → new shot)**, a **light-leak wash
(150–400ms, orange/pink)**, or a **hard cut into a dark graphic world** — and the
flash/wash moments carry **whoosh SFX** (−11 to −15 dB peaks in speech gaps vs a
−40 dB true-pause floor). Burned text exits INSIDE the flash. Nothing pops in
place; there are zero naked butt joints between visual worlds. SFX ≠ music — the
no-music-by-default rule stands; whooshes ride transitions only.

### R16 — Baseline look + reframe-on-seam; ramps recompose toward the face (2026-07-05)
The pro's "static" talking head is already an edit: a **tight chest-up crop of the
4K frame + warm grade**, and the framing changes at essentially every seam and
cutaway-return (70 boundaries/299s = 14/min incl. in-cutaway cuts). Between events
the frame is LOCKED (ORB median |dx| 0.08px/0.4s — no idle Ken Burns). Long ramps
carry a deliberate **translation vector** (−413/−286px @1080p across a +43.8%/24.9s
push): the zoom recomposes toward the face, never scales about a fixed center.
Machine gap measured: 0 reframes, raw wide framing, no grade → reads amateur
before any graphics question arises.

### R17 — Receipts beat rendered graphics (2026-07-05)
When speech references a showable artifact, the pro CUTS TO THE ARTIFACT: his
real YouTube channel page, his actual cartoons (3 clips × ~1.1s micro-montage),
his product sites (slow push + page scroll), his own studio. ~16% of intro
runtime is off the face, and most of it is receipts, not decoration. Planner
trigger: speech names a thing that exists on disk/URL → propose receipt cutaway
(1–4s; micro-montage for lists). Requires the operator's asset pool
(assess-pool-FIRST doctrine now has ground truth).

### R18 — Burned kinetic text for hook/thesis/quote lines (2026-07-05)
The pro burns styled kinetic type for the hook ("write this sentence down"),
the I-help sentence, key quotes, and selective caption fragments — building
**word-by-word at 100–150ms per word, synced to speech**, with a yellow/red
emphasis color on payoff words, and layout re-centering as words land. He does
NOT burn full captions on longform. The word timings needed are already in our
timeline map.

### R19 — Seam-cover law (2026-07-05)
Every retake/topic seam in the pro cut is covered by a reframe, a flash, or a
cutaway — his own retake seam at ~4:39 is masked by a B&W quote cutaway with
word-by-word text build. The machine's plan seams are naked butt joints on
identical framing. Lint rule queued: a cut seam with same-framing continuation
and no covering treatment = WARN.

### R20 — Retention front-load: the first ~2 minutes run ~2.5x treatment density (2026-07-06)
Operator doctrine, stated directly: "the intro has far more animations/edits than
the rest of the video — typically the first 2 minutes or so is to increase
retention; that's important for our editor brain to know for long form." The
measured pro cut agrees: **10 cutaways in the first 126s (~5/min) + 5 zoom events
in the first 60s (~5/min), settling to ~2/min for the body** — every treatment
family (cutaways, takeovers, kinetic text, zooms, transitions) is stacked in the
hook window, then eased to a repeatable cruise. Encoded: MODES["longform"]
["hook_density_multiplier"] (2.35), mode-keyed hold/takeover ceilings
(MOTION hold_max_s / takeover_max_s: longform 11.0/10.5s vs short 6.0/2.5s —
a longform cutaway that BUILDS needs the full enumeration span), and the MG-4
planner's 120s hook window (denser own-screen spacing in the hook, 1-per-45s
body). Plan authors: put the thesis takeover, the first whiteboard build, and
the receipt hits INSIDE the first two minutes; the body earns graphics only at
chapter-scale beats.

## Study pair 2 — "angle generator" (C0679 raw → edited, 2026-07-06)

Second raw↔edited pair (654s edit / 834s raw). Full-state vision sweep (712
states, 60 sheets, every sheet reviewed) + word-level edit diff + zoom map.
Fingerprint: 102 cuts (9.35/min), 22 zoom events (2.02/min — R13's longform
semantic cadence CONFIRMED as a stable prior), −28.1 LUFS quiet dynamic master
(second data point). Full catalogs in the session study; key deltas below.

### ⚠️ R14 CONTRADICTION — operator-visible callout (never silently resolved)
Pair 1's editor NEVER overlaid graphics on the talking head (R14). THIS edit
overlays constantly: icon stacks in headroom, two-tier burned text at chest,
prompt chips beside the face — and reserves full takeovers for section/canvas
moments. R14 is therefore NOT a universal law; it is a PER-VIDEO STYLE AXIS
(`graphics_style: cutaway-only | overlay-rich`). Both are the operator's own
videos. Default stays cutaway-only (conservative, pair-1-proven) until the
operator picks; the planner should carry the axis, not assume it.

### R21 — Edit-decision policy is footage-dependent, not fixed (87.1% vs 94.7%)
Pair 2 kept 87.1% of raw words (pair 1: 94.7%): tangents/weak-alternates
54.4s across 11 events + trims 31.9s — this edit CUTS CONTENT, not just
retakes+pauses. Retakes: 7 events, 6 later-wins + **1 earlier-wins**
(first counter-example — flag-don't-flip policy validated), and one
long-range retake pair 95s apart (loser@10.6 → winner@105.8), far beyond
retake_scan's 10-utt lookback. Brain: pause-tightening-first stays the FLOOR;
tangent-cutting is a judgment tier above it.

### R22 — Zoom grammar, second accent: ramps carry the demo body
Same 2/min semantic cadence, but punch:ramp = 11:11 (pair 1: 21:14) with
LONG ramps (+30%/33s, +33%/24s) under explanations, punch-OUTs at section
resets, and an opening 14.7s punch-OUT ramp as the hook move (depart tight →
resolve wide). Magnitudes median 22.9%. The zoom engine already renders all
of this; the PROPOSER should offer long smooth ramps under demo/story zones,
not only 1.6s thesis punches.

### R23 — Burned text grammar: fragment+payoff two-tier, accent = per-video token
The highest-frequency treatment (5+ instances both halves): small white
verbatim fragment line + LARGE bold accent payoff line building word-by-word
beneath (green for beliefs/warnings, yellow for numbers, azure canvas titles;
red handwritten accent on the hook). Accent color is a per-video BRAND TOKEN
SET, never hardcoded gold. Burned text slides to the emptier side on reframes
(R10 applies) and — ordering law — is committed BEFORE ramps in this style so
it scales with the push (burn-before-ramp; our pipeline runs graphics after
punch = the pair-1 ordering; this is part of the same style axis as R14).

### R24 — Demo-by-design: canvas graphics replace screen recordings
This "tool demo" video contains ZERO literal app screen recordings. The demo
is DESIGNED: prompt-chip overlays with a yellow variable slot, node-map
canvases with real brand icons (desaturate→color pop on land), value-handoff
(a spoken sentence built center-frame SHRINKS into the canvas title, then
connectors draw BEFORE their nodes), section takeovers with drifting ghost
numerals, and one canvas-PiP list (speaker demoted to a ~27%-width rounded
inset card while an 8-item list staggers in — long enumerations may keep the
speaker present INSIDE the cutaway). Concept-stock b-roll (AI/robot/office,
1.5–3.5s) is the tier below receipts; every b-roll boundary is covered by a
brand-accent wash or white flash (extends R15: wash color follows the brand;
plain white-flash-cut is a legal seam cover). The outro (~last 60s) is
treatment-free — stop spending graphics after the last content beat.

## Study pair 3 — GPT-5.6 Sol AI segment (Nate Herk, 2026-07-15)

Exact reference: `J_jswzXhYJA`, AI-produced section 0:00–3:07. The full card
catalog and frame evidence live in `NATEHERK_CARDS.md`; the direct C0679
comparison lives in `GPT56_SOL_C0679_GAP_STUDY.md`. A new 5fps sweep, every-state
contact-sheet review, zoom map, and 12fps entrance bursts reconfirm the earlier
study. The reusable rules below close the earlier documentation gap: this
reference had been studied in detail, but its laws had not reached this canonical
planner-facing file.

### R25 — Face-bridge is a macro-layout preset, not an overlay synonym

The AI segment uses two stable editorial chassis after 13.5s: a cream left rail
with full-height footage on the right, and a dark full-frame canvas with the
presenter continuously carried into a tall rounded right-side PIP. The chassis
alternate about eight times through 187s. The face is never covered, removed, or
reintroduced as an unrelated clip. `graphicsStyle: overlay-rich` is therefore
insufficient: it permits floating widgets over an unchanged camera frame, which
is not this grammar. Planner/render target: an explicit `face-bridge` treatment
whose rail and dark-PIP geometry are stable across the entire chapter. This is
the operator-visible adjudication of R14's contradiction, not a replacement for
the separate `cutaway-only` preset.

### R26 — Tokens repeat; information anatomy does not

In the AI section, 20 graphic windows use 19 distinct information forms; across
the full reference, 23 windows use 20 forms. The consistent system comes from
palette, typography, eyebrow, connectors, PIP geometry, and build rhythm—not
from repeating one card. Ledger, fan-out, timeline, bars, scoreboard, checklist,
UI diff, diagram, scanner, loop, pipeline, and statement are chosen by semantic
shape. A per-video allocator must drain compatible unused forms before reuse.
Reference prior: roughly 0.87 distinct forms/window. Repository floors may be
lower for feasibility, but a plan below its configured floor is not exportable.

### R27 — A card is a live evidence surface, not a narration subtitle

The reference's factual beats show typed evidence: status values, dates,
comparisons, deltas, thresholds, pass/fail chips, UI captures, provenance, or an
honest limit. C0679 frequently replaced those with a heading plus a numbered
sentence that paraphrased the speaker. For config, chronology, comparison,
measurement, QA, vendor, and mechanism beats, the payload contract must require
the matching evidence fields. A title-only fallback is a semantic failure even
if it is legible and animated. Claims source and limitation modules land last.

### R28 — Progressive build order follows cognition

Every dense reference card begins with orientation, exposes a visual skeleton,
then lands modules in narration order. The recurring order is eyebrow/headline
→ container/axis/connectors → current evidence → comparison/result → receipt or
caveat. Ghost-resolve keeps text in place; bars carry their labels at the moving
tip; chip rows sweep at about 80–120ms/item; the card may continue evolving for
several seconds. The first meaningful module lands within about 0.6s of entry.
One generic fade/slide applied to the fully assembled card does not satisfy this
rule.

### R29 — Spend motion on information before camera punch-ins

The benchmark AI section measured 5 zoom events (1.6/min), median magnitude
6.5%, maximum 13.9%. C0679 measured 31 events (2.78/min), median 11.9%, maximum
31%, with 28 punch cuts and only 3 ramps. The reference obtains rhythm from
chassis changes, progressive module lands, fills, scanner motion, and in-place
statement swaps. When a semantic graphic can evolve, do not insert a punch pair
to fill the same attention gap. Camera motion supports the information hierarchy;
it is not a substitute for one.

### R30 — Decision-to-render parity is a release invariant

For every graphic decision, the rendered timeline must contain exactly one row
with the same `graphicId`, `semanticBeatId`, and `kind`. C0679's Palmier build
changed 12 planned kinds; 8 were bound intro decisions whose ledger still named
the richer original forms. It also inserted three unplanned body graphics. The
existing plan lint correctly rejects this state. Any path that can export while
that lint is failing is an authority defect, not a stylistic exception. Palmier
mutation must be candidate-scoped, plan-hash-bound, gate-bound, and read back
after each authorized batch.

### R31 — Review the exact full candidate, not a short surrogate

C0679's available deterministic audit covered a 47.3s render and failed black,
eye-trace, and composite-reference checks; the delivered master is 670s. A short
render can validate machinery, but it cannot approve the full edit. Completion
requires an export of the exact candidate fingerprint plus full-duration
deterministic QC and separate composition/editorial reviews bound to that export
hash. Reviews must explicitly check graphic variety, semantic relevance,
presenter geometry, progressive builds, and long-gap pacing.
