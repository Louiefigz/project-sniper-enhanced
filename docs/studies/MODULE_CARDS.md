# MODULE CARDS — Sniper's long-form card catalog, form selection and variety doctrine

Status: Sniper-authored design doctrine, rewritten for rc4 (2026-09-18). Pinned into
every Auto Edit doctrine snapshot. Companion to `MODULE_STUDY.md` (transition
grammar T-A … T-G, build ranks 1-11, adoption items §5.1-§5.10).

How to read this document:

- Section numbers and form numbers (**#1 … #20**) are identifiers cited by
  templates, `producer_config.py`, lint rules and tests. Keep them stable; a form that
  is retired keeps its number.
- Every number is a **Sniper design parameter** with a stated reason and a home in
  code. None is a measurement of a third-party video.
- Colour and type are named by **role** (light field, dark canvas, ink, result
  accent, process accent, warning accent). Values belong to the design tokens.

---

## §1 The card system

### §1.1 Two chassis

Every long-form module card is built on one of two chassis. Using only two is itself
a rule: the viewer learns both in the first minute and afterwards reads *content*,
not layout (`MOTION["layout_families"]`, `MOTION["longform_smooth"]["max_layout_families"]`
= 3 — the two chassis plus one lower-band card).

**Light chassis — the split rail beside the face.** A light field occupies the
anchored side of the frame while the presenter, re-centred by the footage recompose
(`MODULE_STUDY.md` T-B), keeps the rest. Design parameters: 33-40 % of frame width —
0.3302 for `glass-rail` and `module-rail` (634 of 1920 px), 0.375 for
`module-bullet-bars` (720 px), in `MOTION["recompose"]["geometry"]`. Rationale: one
third is the narrowest field that still carries a two-line headline plus four or five
short rows at a size readable on a phone held vertically playing a landscape video;
going past about 40 % pushes the presenter's face towards the frame edge, where the
recompose zoom needed to re-centre it would exceed the tasteful band
(`MOTION["recompose"]["zoom_cap"]`).

**Dark chassis — the own-screen takeover.** The whole frame becomes a dark canvas.
It may carry the presenter in a rounded card on the right (`MODULE_STUDY.md` rank 11,
§5.9) or not at all. Rationale: some information (a scoreboard, a multi-column
ledger, a pipeline) needs the full width; the dark canvas makes the switch
unmistakable and gives accents maximum contrast.

### §1.2 Numbered form catalog

A **form** is an information anatomy, not a template file; one template may render
several forms and one form may have several templates.

| # | Form | Chassis | Template(s) | Build notes |
|---|---|---|---|---|
| #1 | Chapter opener: ordinal + chapter title | dark | `section-takeover` | ordinal settles first, title lands second |
| #2 | Agenda / roadmap: numbered rows of what is coming | dark | `agenda-slide` | rows land as each item is named |
| #3 | Receipt line: a source, date or quoted artifact as evidence | either | `slideware-receipt-cell`, ledger receipt rows | lands last in its card (MODULE rank 9) |
| #4 | Status / queue cards: label plus live status | light | `module-rail` (`contentMode: status`) | one card per spoken item, connector drawn between |
| #5 | Key-value ledger rows, then a numbered chip fan-out | dark | `module-ledger-dark` (`grid: chips`) | rows stagger ≈ 0.25 s, then chips sweep (rank 8) |
| #6 | Dated vertical timeline | light | `module-rail` (`contentMode: timeline`) | dates land in order; the current point uses the process accent |
| #7 | Ledger with one big value bar and parallel columns | dark | `module-ledger-dark` (`grid: columns`) | bar value first, columns fan out |
| #8 | Numbered steps with a dot rail | light | `module-rail` (`contentMode: steps`), `list-build` | one step per spoken step |
| #9 | Boxed callout: one hero value against its baseline | either | `module-takeover`, `stat-card` | hero value, then the baseline it beats |
| #10 | Checklist with confirmation badges | light | `module-rail` (`contentMode: checklist`) | each row confirms when the speaker confirms it |
| #11 | Scoreboard: hero number, supporting tiles, optional limit | dark | `module-scoreboard` | hero → tiles → chip sweep → limit |
| #12 | Bullet-bar chart with a threshold tick and a verdict footnote | light | `module-bullet-bars` | bars fill with values (rank 7); verdict footnote last |
| #13 | Tool identity and authorisation: the real mark of a named tool | either | `logo-card`, `icon-badge`, `icon-badge-wide` | real marks only, no emoji (`REFERENCE_STYLE_STUDY.md` R12) |
| #14 | Before / after split | either | `versus-split` | left settles before right |
| #15 | Trend over time | either | `chart-story` | only when the window speaks a number (LL-040) |
| #16 | Single metric instrument: gauge or counter | either | `widget-gauge`, `count-up` | counts to a spoken value |
| #17 | Vertical steps rail on glass | light | `glass-rail` | per-row lands required (LL-011) |
| #18 | Horizontal node pipeline with a "you are here" node | dark | `module-pipeline` | nodes land left to right; active node in the process accent |
| #19 | Thesis statement: one sentence, the point in the result accent | dark | `statement-card`, `kinetic-quote-wide`, `fragment-payoff` | a kicker may replace the statement in place on the same chassis (`MODULE_STUDY.md` T-E) |
| #20 | Screen-share frame with presenter PIP | screen | footage + PIP (see §3) | the screen is the card |

### §1.3 Build envelope

A card is fully built **about 1.2-2 s after its first pixel** when its modules do not
wait for narration, and its modules finish no later than the narration that
introduces the last one when they do (§5.4 lands). Build order is always: shell and
hairlines (rank 2) → eyebrow (rank 3) → headline (rank 5) → modules on their lands
(rank 1) → evidence ribbon (rank 9). Rationale: 1.2-2 s is long enough to show the
build order (the viewer sees what kind of card this is before its content) and short
enough that the card is complete while the sentence that called for it is still
being spoken. The first content must land within 0.6 s of an own-screen card's
entrance and 0.9 s of a panel's (`MOTION["first_land"]`, LL-002, LESSON-003): an
empty shell held longer reads as a stall.

### §1.4 Content type → form family

The brain classifies each beat's **information shape**; the form family follows.
This table is the prose form of `producer_config.MOTION["card_form_map"]` (the data
catalog lint reads); the two must always agree.

| Information shape | Form family (comp kinds, in catalog order) | Forms |
|---|---|---|
| `comparison` — numbers against a baseline, hero versus alternatives | `module-bullet-bars`, `module-scoreboard`, `module-takeover`, `versus-split`, `chart-story` | #9, #11, #12, #14, #15 |
| `trend` — change over time | `chart-story` | #15 |
| `process` — ordered or parallel steps | `module-pipeline`, `module-rail`, `glass-rail`, `agenda-slide`, `whiteboard-map`, `list-build` | #8, #17, #18 |
| `evidence` — receipts, ledgers, tool identity and authorisation | `slideware-receipt-cell`, `module-ledger-dark`, `whiteboard-connector`, `logo-card`, `icon-badge`, `icon-badge-wide` | #3, #5, #13 |
| `credibility` — the speaker's earned authority | `avatar-bio-card`, `module-ledger-dark`, `whiteboard-connector`, `logo-card` | #5, #13 |
| `chapter` — a new chapter or a promised roadmap | `section-takeover`, `agenda-slide`, `whiteboard-map`, `module-pipeline` | #1, #2, #18 |
| `limit` — measurements against a limit | `module-bullet-bars`, `module-scoreboard` | #11, #12 (threshold tick and footnote in the warning accent) |
| `scale` — one hero metric | `module-scoreboard`, `stat-card`, `widget-gauge`, `count-up` | #9, #11, #16 |
| `list` — multi-point lists and checklists | `glass-rail`, `module-rail`, `whiteboard-list`, `canvas-pip-list`, `agenda-slide`, `list-build` | #8, #10, #17 |
| `thesis` — one sentence, no data | `statement-card`, `fragment-payoff`, `kinetic-quote`, `kinetic-quote-wide`, `line-swap` | #19 |

Rules that go with the table:

1. **Shape decides, not preference.** Numbers compared against each other on a plain
   statement card are a defect: the viewer has to do the comparison in their head.
   `plan_lint_visual.check_form_shape` flags a card with ≥ 2 numeric tokens whose
   window speaks a comparative marker ("versus", "vs", "than", "compared") but whose
   kind is outside the comparison family (`MOTION["form_shape"]`; ERROR for
   produced/full long-form, WARN elsewhere). LL-015, LESSON-029.
2. **Every required beat resolves.** A `decisionRequired` produced/full beat resolves
   to a compatible bound graphic or matching b-roll; omission never discharges it;
   with b-roll off the beat must be a graphic (LL-032).
3. **Physical fit before binding.** A compatible form must also fit a legal region on
   the measured framing and canvas (LL-034, LL-036, LESSON-047).
4. **Number-painting forms need a spoken number.** `chart-story` and `count-up` are
   compatible only when the beat's window speaks a value (LL-040).

---

## §2 Variety doctrine

**Variety lives in structure, not palette.** Brand tokens (colours, type, motion
timing) stay constant for the whole video; card **anatomy** varies. Rationale: a
constant palette is what makes a video feel like one production; a repeated anatomy
is what makes a viewer stop reading, because it looks like something already read.

Rules, all encoded in `MOTION["variety"]` and enforced by the hard
`graphics.variety_contract` gate for produced/full long-form with automatic graphics
(and by `plan_lint_visual.check_variety` as WARN in lighter scopes):

1. **No information-bearing kind twice in a row.** Two consecutive windows of the
   same kind read as one card that flickered.
2. **The first minute.** Once the output reaches 40 s, the first 60 s carries at least
   **four** information-bearing windows in at least **four** forms; below 40 s, a plan
   that already has four windows still owes four forms (LL-030 — a duration threshold
   decides when density is owed, never whether variety is).
3. **The first three minutes.** Over the first min(output, 180 s) the floor grows from
   **5 windows / 4 forms at 60 s to 8 windows / 6 forms at 180 s** (one more window per
   25 s, one more form per 30 s, distinct ratio ≥ 0.67; `local_floors`).
4. **The whole plan.** At least 6 windows, and at least ceil(0.5 × windows) distinct
   kinds (`min_windows`, `min_distinct_ratio`).
5. **Exemptions.** Caption layer kinds (`layer_kinds`) and a deliberate `statements[]`
   replacement chain on one statement card do not count as repeats.
6. **Variety never authorises a wrong form.** If only one compatible form fits a beat,
   the beat keeps it; repetition is legal only when the compatibility graph proves it
   unavoidable (`graphics.form_allocation`, LL-032, LESSON-045), and cross-project
   usage history is consulted before reusing a familiar form (LESSON-036).

Why these floors: four forms in the first minute is the smallest number at which a
viewer experiences "this video shows me different kinds of things" rather than "this
video has a card"; the three-minute ramp keeps the intro — the densest region of a
produced long-form — from settling into a two-card loop, while the proportional
whole-plan floor leaves the body free to breathe. All floors are deliberately
permissive: a well-planned video clears them without trying.

---

## §3 Screen-share grammar

When the footage is a screen recording, the **screen is the card**. Cards do not sit
over it; the screen itself is framed, focused and narrated.

- **Framing.** Never show a full bare desktop at delivery size: crop or punch in to
  the active region the speaker is talking about. A desktop at 1920 px wide renders
  interface text too small to read on a phone.
- **Presenter PIP.** During a screen walkthrough the presenter may continue as a small
  circular PIP in the bottom-right corner, ≈ 11 % of frame width, placed over the
  least important region and never over the content being discussed; introduce it when
  the explanation deepens, omit it for quick fly-throughs (`MODES.longform.tutorial_pip`,
  `EDITCRAFT_LESSONS.md` §4.1). Long-form only.
- **Cursor.** The cursor is the pointer the viewer follows. Keep it visible; do not
  cut while it travels to its target.
- **Motion events.** Zoom or pan toward the region the narration names; an image-focus
  operator (`EDITCRAFT_LESSONS.md` §7.4) may isolate a region of a still screenshot.
- **The screen leads narration.** Show the action as, or just before, it is described,
  never after: a viewer who hears "click Export" should already be looking at Export.
- **Entrances over screen-share.** Only an own-screen cutaway or a focus-shift graphic
  (the base blurs back) is legal over a screen-share zone (`MOTION["anchors"]`,
  `REFERENCE_STYLE_STUDY.md` R5). Face-relative anchors need a face and are illegal
  there.
- **Pacing.** Screen-share is a different grammar from presenter footage: a long hold
  is legal while cursor, PIP, demo audio or keyword pills keep changing
  (`MODES.longform.pacing_lanes`, `EDITCRAFT_LESSONS.md` §1, LESSON-014).

---

## §4 Ranked gap list

What the catalog cannot yet express, ranked by how often a long-form explanation
needs it. Roadmap forms join their families in `card_form_map` only once a template
is built and measured (`templates/motion/comp_capabilities.json`).

| Rank | Gap | Family it would join | Status |
|---|---|---|---|
| 1 | Dated horizontal timeline for chronology across months or years | `trend` / a future `chronology` | not built; #6 covers short vertical timelines |
| 2 | Interface diff: before/after of one screen with the changed region marked | `evidence` (`ui-diff`) | not built |
| 3 | Parallel scanner lanes for question-and-answer or QA flows | a future `qa` family (`scanner-lanes`) | not built |
| 4 | Animated shrink of live footage into the presenter card | chassis transition | not wired (`MODULE_STUDY.md` §5.10) |
| 5 | Screen-share PIP composite as a first-class plan field | §3 | advisory (`tutorial_pip`) only |
| 6 | Automatic fill for left-column full-frame cards held beyond 5 s | layout balance | WARN only (LL-005) |
