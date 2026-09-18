# REFERENCE STYLE STUDY — Sniper's numbered style rules (R1 … R31)

Status: Sniper-authored design doctrine, rewritten for rc4 (2026-09-18). Pinned into
every Auto Edit doctrine snapshot. The numbered rules below are identifiers: planners,
lint messages, templates, tests and `producer_config.py` cite them as "R<n>". The
`producer-study` skill appends new rules to this file (see "How rules are added").

How to read this document:

- Each rule has the heading format `### R<n> — title`, a statement, a rationale and an
  **Encoded as** line naming where the product carries it.
- Every number is a **Sniper design parameter** (configurable, with a stated reason).
  Rules R1-R20 and R25-R31 are original Sniper rules written from first principles and
  Sniper's own templates and renders; they do not describe or measure anyone else's
  video. Rules R21-R24 restate what Sniper's earlier study of the **owner's own**
  long-form footage (the C0679 raw and edited pair, "pair 2") established; that study
  is historical and was not re-measured for rc4.
- Colour and type are named by role (accent, accent face, ink); values belong to the
  design tokens in `templates/motion/tokens.css`.

---

## Captions and type

### R1 — Minimal word-at-a-time captions anchored at chest height

The `minimal` caption style shows **one word per event**, or a phrase of up to three
words when adjacent words nearly touch (gap under 0.12 s). Emphasis words always stand
alone. Size ≈ 80 px on a 1080 × 1920 canvas (about 4 % of frame height; allowed
64-96 px). The event's vertical centre sits in the **chest band** under the chin — y
1050-1150 on the 1920-px canvas, or 8 % of frame height below the measured face box
when one is known. Type treatment is a thin outline and a soft shadow, **no box**. Each
word shows for at least 0.18 s and never hangs more than 0.4 s past the end of its
speech. Rationale: one word at a time at chest height keeps the reading point next to
the face, so the viewer reads and watches the speaker with one fixation region; a box
would turn a caption into a graphic.

**Encoded as** `CAPTIONS["MINIMAL"]`; `captions/captions_minimal.py`.

### R2 — Two-tone accent

Emphasis words, keywords and numbers render in the **accent colour and the accent face**
(a secondary display face used only for emphasis); everything else uses the primary
text style. Rationale: two tones give the viewer a second channel — "this word matters"
— without adding another element to read.

**Encoded as** `CAPTIONS["MINIMAL"]["accent"]`, `["accent_font"]`; `tokens.css` accent
roles; `section-marker` title tier.

---

## Placement

### R3 — The headroom is the graphics canvas

In a vertical talking-head frame, the space **above the head** is the natural home for
persistent graphics: it is usually empty, and a graphic there never covers the face or
the caption band. Placement measures the real top of the hair (median-background
subtraction; a 40 %-of-face-height fallback when it cannot be measured) and uses a
top inset of 60 px, smaller than the safe box's 250-px top because the top edge of a
Short carries only a small platform tab.

**Encoded as** `MOTION["anchors"]` (`headroom`), `FREE_SPACE`
(`headroom_top_inset`, `face_expand_up`); `planner/free_space.py`,
`planner/graphics_anchors.py`.

### R4 — Chest and beside-face anchors

Floating assets may sit **below the chin** (the chest band, falling back to the
lower-third band) or **beside the face** on the emptier side at face height. These
anchors are legal only where a face exists and require a measured face box
(`faceBBoxNorm`); without one, lint fails the entry.

**Encoded as** `MOTION["face_anchors"]`; `plan_lint_motion` face-anchor checks.

### R5 — Focus-shift over screen-share

Over screen-share footage the screen is the subject. The only legal graphics there are
an opaque own-screen cutaway or a **focus-shift** graphic: an alpha graphic over a
blurred copy of the base, so the screen recedes rather than being covered.

**Encoded as** `MOTION["anchors"]` (`focus-shift`), visual-state anchor legality in
`plan_lint_motion`.

### R6 — Persistent parametric widgets

A value that the speaker develops over a stretch (a progress figure, a set of options,
a milestone climb) is shown as a **persistent widget** that stays on screen and updates
in place, rather than as a sequence of cards. Widgets live in the headroom (R3) and
enter in stages (R9).

**Encoded as** `widget-gauge`, `widget-pills`; `planner/graphics_planner_gauge.py`.

### R7 — Numbered section markers

A section of a Short or long-form discussion may be marked by a small overlay in the
headroom: an **eyebrow** (the section number or label), a **title** in the accent tier
(R2) and an optional qualifier, on the side opposite the subject (R10), for about
2.5 s. It is a small alpha overlay over the live presenter, distinct from a full-frame
chapter card.

**Encoded as** `section-marker` (`num` / `line1` / `line2` / `side`).

### R8 — Safe-box discipline

All text and graphics sit inside the universal safe box — top 250, bottom 520, left
60, right 150 px on the 1080 × 1920 canvas — so no platform's interface covers them.
The bottom margin is the binding one (the caption and call-to-action stack of the
platforms); the visual centre sits at x 495, left of 540, because right-hand icon rails
are asymmetric.

**Encoded as** `SAFE_BOX`, `VISUAL_CENTER_X`; placement clamps in `free_space`.

---

## Motion and build

### R9 — Progressive disclosure

Graphics build in stages and enter from something **visible**: a quick 100-170 ms rise
or wipe, or a scale-in from a visible starting scale (about 0.7-0.92), never a pop from
nothing. Multi-part graphics build in reading order — eyebrow first, then title, then
qualifier or items. Rationale: an element that grows from a visible state gives the eye
a point to track; one that appears from nothing is noticed only after it is complete.

**Encoded as** entrance timing in the composition templates; section-marker and
schedule-stack builds; `MODULE_STUDY.md` ranks 2-4 for long-form cards.

### R10 — The placement law: slide to the emptier side

Text and panels anchor on the **emptier side of the frame, opposite the measured
subject**; wipe direction follows the anchored side. When the subject moves between
reframes, the graphic's side follows.

**Encoded as** `side` / `align` variables chosen from `free_space` measurements.

### R11 — Copy is condensed speech

Graphic copy is the speaker's words, condensed: it may shorten, never add. No number,
promise, price or claim appears that was not spoken in the kept cut.

**Encoded as** `claims_contract.py` (numeric tokens and phrase grounding); LESSON-001,
LESSON-009; `MODULE_STUDY.md` §5.6.

### R12 — Entity legality

When the speaker names something, decide whether it earns a graphic:

- **Rule 1** — a **generic category** ("AI", "software", "the internet", calendar words)
  earns **no** entity graphic; a mark for a category adds nothing and often borrows a
  brand that was not meant.
- **Rule 2** — a **specific** product with a recognisable mark gets the **bare mark**
  (`icon-badge`); the mark alone beats a chip plus label.
- **Rule 3** — a specific product **without** a known mark gets a **text chip**
  (`chip-row`); the text is then the information.

**One mark once:** the same mark may not reappear within 8 s. Marks are real marks
only — never emoji substitutes.

**Encoded as** `MOTION["generic_entity_blocklist"]`,
`MOTION["planner"]["one_mark_window_s"] = 8.0`; `planner/graphics_planner_rules.py`,
`planner/graphics_planner_density.py`.

### R13 — Zoom changes role between formats

**Long-form zoom is semantic**: a sparse second track under the cuts that lands on
meaning.

- **Rule 1** — punch **in** on the stressed beat of a claim;
- **Rule 2** — pull **out** to wide on a section reset;
- **Rule 3** — an in → out **bracket** for the biggest lines only (at most 3 per video);
- **Rule 4** — a slow **ramp** (0.3-1.8 % per second) under an uncut, graphic-free
  story stretch;
- **Rule 5** — every zoom departs from the wide baseline (scale 1.0) and resolves back
  to it.

Long-form defaults: median push 1.21, bracket ceiling 1.51, cadence at most 6 per
minute in the first 60 s and 5 per minute in the body (the body budget also admits the
continuous aliveness creep).

**Shorts zoom is rhythmic**: the zoom *is* the cut — most cuts land tighter or wider
than the shot before, alternating so the video does not creep in. Median reframe 1.18,
at most 10 per minute, one reframe every 6-10 s; ramps and brackets are occasional
texture, not proposed automatically.

Rationale: in long-form a zoom that happens often stops meaning anything, so it is
saved for meaning; in a Short the cut rate is high and a reframe on the cut hides the
jump while adding energy.

**Encoded as** `MOTION["zoom"]` (`magnitude`, `bracket_max_per_video`, `baseline_scale`,
`by_mode`); `planner/graphics_planner_zoom.py`; `plan_lint_motion` cadence checks.

### R14 — Talking-head long-form: protect the face

In the `cutaway-only` long-form grammar **no panel floats over the talking head**. The
single exception is one lower-band card (`glass-lower-third`) off the face. Structure
earns **full-frame cutaways**: three or more listed items earn a whiteboard, a process
earns a list cutaway, a thesis earns a burned kinetic quote (R18), a named artifact
earns a receipt (R17). **One attention move per moment**: a receipt and a cutaway never
compete for the same beat. Cutaways are expensive; they are budgeted and kept out of
the first 3 s and last 5 s. R14 is a per-video style choice, not a universal law — see
"R14 contradiction (callout)" below.

**Encoded as** `planner/graphics_planner_longform.py`,
`planner/graphics_planner_items.py`, `planner/graphics_planner_sequences.py`.

### R15 — Seam covers between worlds

A change of world — presenter to full-frame graphic and back — may carry a seam cover
so the change reads as deliberate: a **white flash** of about 3 frames, or a **light
leak** of about 0.375 s, each with a whoosh peaking around −15 dBFS. Covers are markers,
not decoration: at most 2 per minute, at least 1 s apart. Stock NLE transitions are not
covers (LL-014).

**Encoded as** `MOTION["transitions"]`; `motion/transitions.py`; `plan_lint_motion`
transition checks.

### R16 — The baseline look

Even a static talking head is edited: a tight **chest-up recrop** of the source frame
(default 1.28×, centred slightly above the middle at 0.44 of height; editorial band
1.0-1.5×) and a **subtle warm grade** that never changes between events. Zoom pushes
translate toward the face rather than scaling about the frame centre.

**Encoded as** `motion/baseline_look.py` (`WARM_GRADE`), `plan.baselineLook` lint
bands; face-relative push translation in `motion/punch_in.py`.

### R17 — Receipts beat rendered graphics

When the speaker names a **showable artifact** — their channel, their site, their
product, a document — cut to the real artifact. A receipt holds about 2.5 s (1-4 s),
replaces frames only (the voice continues underneath), and the same artifact is not
re-shown within 30 s. A rendered card for something that could simply be shown is
weaker evidence. Exception: when the beat's structure (several items, a comparison) is
more than any single artifact can show, the structural graphic wins.

**Encoded as** `BROLL["receipt_hold_s"]`, `BROLL["receipt_dedup_s"]`;
`planner/graphics_planner_receipts.py`, `broll/broll_insert.py`, `broll/broll_pool.py`.

### R18 — Kinetic burns for theses

The sentence a section exists for is burned as a **kinetic quote** that builds word by
word (about 130 ms between words) with one to three payoff words in the accent tier
(R2).

**Encoded as** `kinetic-quote-wide`; the R18 emphasis heuristic in
`planner/graphics_planner_longform.py`.

### R19 — Full-frame text is its own world

A full-frame text takeover is opaque: captions are suppressed under it, and entering
or leaving it is a seam (R15).

**Encoded as** own-screen anchor semantics (`MOTION["anchors"]`); caption suppression
windows in `graphics_base_effects.py`.

### R20 — Front-load the hook

A produced long-form's opening minute carries about **2.35×** the device density of the
body (cuts, zooms, graphics), then eases to a repeatable cruise. Rationale: the first
minute is where viewers decide to stay; the body must be sustainable for the remaining
runtime.

**Encoded as** `MODES.longform.hook_density_multiplier = 2.35`; region-aware still-gap
ceilings (`hook_still_gap_s`, `max_still_gap_s`); zoom cadence split (R13).

---

## Pair 2 — the owner's long-form footage (R21-R24)

These rules restate what Sniper's earlier study of the owner's own C0679 raw and edited
long-form established. They are kept because the product relies on them; the study
itself is historical.

### R21 — Re-delivered blocks and the retake winner

The owner's raw recording showed that a whole segment can be **re-delivered after an
interruption**, roughly a minute after the failed attempt — far outside a
few-utterances retake window. Sniper therefore also searches ahead **by time** (up to
120 s) under stricter guards, and always flags such long-range finds for the operator.
By default the **later take wins**; when an earlier take is better, the scanner flags it
(`needsOperator`) and never flips the winner on its own.

**Encoded as** `MODES.longform.retake_default = "later"`,
`MODES.longform.retake_lookback_s = 120.0`; `retake_scan.py`; `tests/test_edit.py`.

### R22 — Declare the graphics style per video

The owner's own long-form edits use more than one legitimate graphic grammar
(`cutaway-only`, `overlay-rich`, and the module `face-bridge`). A produced/full
long-form therefore declares its style once (`target.graphicsStyle`) with a rationale,
and the planner never guesses it. Styles do not mix within one video.

**Encoded as** `graphics_planner_longform.resolve_style`, `STYLES`; `MODULE_STUDY.md`
§4.

### R23 — Two-tier burned text

In the `overlay-rich` style, a thesis burns over the live presenter as **two tiers**: a
small verbatim fragment of the setup, then a large accent payoff building word by word
beneath it at speech cadence, slid to the emptier side (R10). The accent is a per-video
brand token, never hardcoded. The full-frame kinetic quote (R18) is reserved for the
single strongest thesis in each two-minute stretch; the others burn.

**Encoded as** `fragment-payoff`; `planner/graphics_planner_style.py`.

### R24 — Overlay-rich extras

The `overlay-rich` style adds four devices:

- **Concept stock**, a tier below receipts (R17): when speech is abstract and names no
  showable artifact, a 1.5-3.5 s concept insert (default 2.5 s), at most once per 60 s,
  body only, and always yielding to a receipt or cutaway on the same beat.
- **Enumeration with the presenter kept present**: five or more listed items may use a
  full-frame list with the presenter in an inset (`canvas-pip-list`) once that renderer
  is wired; until then a full-frame whiteboard list.
- **Chapter takeovers with a drifting ghost numeral**: the chapter ordinal settles as a
  large soft numeral, the title lands second (`section-takeover`).
- **A one-beat emphasis hit** of 300-500 ms, hard in and hard out (`glitch-hit`), placed
  only by the brain or operator — no transcript signal says "hit here".

**Encoded as** `BROLL["concept_hold_s"]`, `BROLL["concept_every_s"]`;
`planner/graphics_planner_receipts.py` (concept lane),
`planner/graphics_planner_items.py` (`PIP_MIN_ITEMS`), `section-takeover`, `glitch-hit`.

---

## R14 contradiction (callout)

R14 (protect the face; structure goes full-frame) and R23-R24 (burn text and stack
icons over the live presenter) contradict each other, and both are legitimate. Sniper
resolves the contradiction **per video**, not by averaging: the graphics style is an
axis (`cutaway-only` | `overlay-rich` | `face-bridge`) declared in the plan (R22). The
`cutaway-only` planner is the R14 grammar; `overlay-rich` is the R23-R24 grammar;
`face-bridge` is the module chassis grammar of `MODULE_STUDY.md` §4. Contradictions
found in future studies get a callout like this one; they are never silently resolved.

---

## Additional rules (R25-R31)

### R25 — Contrast follows the true background

Text drawn outside a card or field has the footage as its background. Any such text
carries its own backing (a pill, scrim or plate); contrast obligations are computed
against the text's real background, never against a card it does not sit on.

**Encoded as** `MOTION["contrast"]` (including `text_plate_sources`); LL-004, LL-033,
LESSON-006, LESSON-046.

### R26 — Graphics never cover the face

A graphic whose placement would overlap the measured face is moved to a legal region
or replaced with an anatomy that fits; if no legal region exists, placement must not
fall back to covering the face.

**Encoded as** `FREE_SPACE`, `verify_placement`; LL-034 (hardening open), LESSON-047.

### R27 — Physical fit before binding

A form is compatible only if its template's **measured** canvas and content box fit the
delivery: aspect mismatch is a hard no; a hold-to-cut template must end on a cut seam or
under a transition.

**Encoded as** `templates/motion/comp_capabilities.json`,
`graphics/comp_capabilities.is_aspect_legal_kind`; LL-036, LL-037.

### R28 — Hold long enough to read twice

A text graphic holds at least as long as its words take to read at a comfortable pace
(5 words per second is the fast end) plus a margin to re-read; hook cards hold 2.5-3 s
for up to 8 words.

**Encoded as** `HOOK_CARD` (`max_words`, `hold_s`), `MOTION["hold_min_s"]`.

### R29 — Every entrance has a cause

A graphic appears by moving in, by popping with a sound, or by being present from
frame 0 — never by a silent unexplained pop mid-video.

**Encoded as** `MOTION["entrance_causality"]`; `EDITCRAFT_LESSONS.md` §7.2; LESSON-016.

### R30 — Numbers on screen are spoken numbers

Every number painted on a graphic is spoken in that graphic's window.

**Encoded as** `claims_contract.py`; `MODULE_STUDY.md` §5.6.

### R31 — Study mechanics, never content

When a reference is studied, only its **mechanics** — timing, geometry, build order,
grammar — may become rules or templates. Its words, branding, assets, music, colours and
identity never enter Sniper, and a rule is written in Sniper's own terms with Sniper's
own rationale.

**Encoded as** this document's "How rules are added"; the `producer-study` and
`reference-editor` skills.

---

## Template corrections queued

Template changes that follow from these rules. Items keep their numbers.

1. **`section-marker`** — rebuilt to anchor on the emptier side (R10) and build
   eyebrow-first with a wipe-in title (R9, R7). Status: rebuilt. Open: its default
   sample copy must be neutral, original placeholder text (owned by the design stream;
   any change regenerates `comp_capabilities.json` and the reviewed
   `MOTION["contrast"]["text_plate_sources"]` hash).
2. **`schedule-stack`** — a stack of role-coloured rounded cards (title plus time)
   on the side opposite the speaker, with a staggered wipe-in (R9, R10), for routine,
   schedule or phased-plan beats. Status: built.

---

## How rules are added

The `producer-study` skill appends rules here after studying references:

- Use the next free number (currently **R32**) and the heading format `### R<n> — title`.
- State the rule in Sniper's own words, with a rationale and an **Encoded as** line
  (config key, template, lint rule or "doctrine only").
- Evidence records mechanics only: timings, geometry, counts. Do not quote the
  reference's words, name its creator or channel, or copy its titles, branding or colours
  (R31). Do not record a measurement that was not actually made.
- A contradiction with an existing rule gets an operator-visible callout (like the R14
  callout), never a silent overwrite.
