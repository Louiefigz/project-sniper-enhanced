# MODULE STUDY — Sniper's long-form graphic doctrine

Status: Sniper-authored design doctrine, rewritten for rc4 (2026-09-18). It is
pinned into every Auto Edit doctrine snapshot (`src/lib/server/auto-edit-doctrine.ts`)
and cited by code comments, lint messages and tests. Companion: `MODULE_CARDS.md`
(the card form catalog, form-selection table and variety floors).

How to read this document:

- Section numbers, transition IDs (**T-A … T-G**), technique ranks (**rank 1 … 11**)
  and adoption items (**§5.1 … §5.10**, also written "§5 item N") are identifiers.
  Code cites them; keep them stable.
- Every number here is a **Sniper design parameter**. Each one is stated with the
  reason Sniper uses it and the place it is encoded. None of them is a measurement
  of anyone else's video. Where a value was checked against Sniper's own renders or
  tests, the check is named; otherwise it is a design choice made from first
  principles and is deliberately configurable.
- Visual design (palette, typefaces) is owned by the design tokens in
  `templates/motion/tokens.css` and `motion-tokens.js`. This document names colour
  and type **by role** ("result accent", "ink", "light field") and never by value.

---

## §0 What "module" means and why long-form needs a doctrine of its own

A **module** is one self-contained unit of on-screen information inside a card: a
labelled row, a bar with its value, a node in a pipeline, a chip, a receipt line.
A **card** is a composition that builds a small number of modules (usually 3-6)
while the presenter talks about them.

Long-form differs from a Short in three ways that drive every rule below:

1. **The viewer has time to read, so the card must be worth reading.** A card that
   restates the sentence verbatim adds nothing (LESSON-009). A card earns its
   window by giving the ear structure it holds poorly: numbers, comparisons,
   sequences, lists, named evidence.
2. **The presenter is the continuity.** Over ten or more minutes the viewer's
   relationship is with the person. Graphics either sit beside the face or take the
   frame over briefly and hand it back; they do not bury the presenter.
3. **Build order is comprehension order.** A card that appears fully formed asks the
   viewer to read everything at once while the voice talks about one thing. A card
   that builds module by module, on the words that introduce each module, lets eye
   and ear stay on the same item.

---

## §1 Pipeline position and quality control

### §1.1 Where long-form graphics sit

The brain authors `edit_plan.json` (cut, graphics windows, specs, lands). The
deterministic gates run before any render (`plan_lint*`, `hook_contract`,
`claims_contract`, `variety_contract`, `template_usage_contract`, the optional
reference gate). Only a plan that passes renders; then Audit B and two visual
critics review the candidate. Every rule in this document therefore has two
homes: an authoring rule the brain follows, and, where the rule is mechanical, a
gate that catches the brain when it forgets.

### §1.2 Verdict table — what Sniper's long-form graphic system must do

Numbered items are identifiers (e.g. "#11" below is cited as "§1.2 #11").

| # | Capability | Sniper verdict | Where it lives |
|---|---|---|---|
| #1 | Graphics enter on the word that introduces them | Required | trigger lanes + `planner/word_lock.py` |
| #2 | Two chassis: a light rail beside the face and a dark full-frame takeover | Required | `MODULE_CARDS.md` §1.1, `module-*` comps |
| #3 | Containers land before their text (skeleton-first) | Required | §3 rank 2, motion tokens |
| #4 | Modules land when the speaker reaches them | Required | §5.4, `spec.moduleLands`, lint |
| #5 | Exits happen on the graphics layer only, with runway | Required | §2 T-D, `graphics/exit_on_cut.py` |
| #6 | A statement can be replaced in place, with a readable gap | Required | §2 T-E, `statement-card` `statements[]` |
| #7 | Seams sit on word boundaries | Required (WARN) | §2 T-G, §5.5 |
| #8 | The light rail pushes in while the footage recomposes | Long-form only | §2 T-B, §5.8 |
| #9 | Presenter kept visible inside a full-frame card | Long-form only | §3 rank 11, §5.9 |
| #10 | Animated shrink of the footage into a PIP card | Not wired | §5.10 |
| #11 | **Pre-render truth check**: every number painted on a card is spoken in its window | Required, hard gate | §5.6, `claims_contract.py` |
| #12 | Post-render visual QC of the assembled candidate | Required | Audit B + composition and editorial critics |

Why **#11** is placed before render rather than after: a wrong number on a card is
the most damaging error a graphic can make (it puts a false claim in the
presenter's mouth), and it is also the cheapest one to catch — it is visible in the
plan as text next to a transcript window. Checking it after render would spend a
full render to find a defect that string arithmetic on the plan finds in
milliseconds. Post-render review (#12) remains, because it catches what plan text
cannot show: legibility, occlusion, timing feel.

---

## §2 Transition grammar (T-A … T-G)

A long-form edit has two layers that can change: the **footage** (cuts, scale,
position) and the **graphics layer** (cards, rails, overlays). The transitions below
are the only sanctioned ways to move between presenter, rail and takeover. They were
chosen so that each change has one visible cause and never smears the presenter.
Stock NLE transitions (wipes, slides, dissolves, cross-fades) are not part of this
grammar and are rejected by lint in every mode (FAILURE_LEDGER LL-014, LESSON-028).

### T-A — Hard cut into a full-frame card

The default way into an own-screen card: a hard cut on a word boundary, the card
complete in its frame from its first frame except for the modules that build on
narration. Rationale: a full-frame change of world is already a strong event; adding
motion on top only delays the moment the viewer can start reading.

### T-B — Rail push-in with footage recompose

The light rail grows from its anchored edge to about one third of the frame width
while the footage re-centres the presenter in the remaining space. Design
parameters: rail field ≈ 33 % of a 1920-px frame (634 px,
`MOTION["recompose"]["geometry"]`), growth over ≈ 0.33 s with a power-out ease; the
footage glide starts ≈ 0.12 s before the rail is visible and runs ≈ 0.40 s
(`MOTION["recompose"]` `lead_s` / `move_s`). Inside the rail, each row's container
lands first and its text follows; successive rows arrive about 0.25 s apart (the
"row cadence" used by `module-ledger-dark`, `module-rail`, `statement-card`).
Rationale: starting the footage move slightly before the rail makes the rail look
like the cause of the move rather than an obstacle the presenter dodges; a power-out
ease front-loads the motion so the field is effectively settled before its first
text lands.

### T-C — Rail out to a presenter PIP card

When the content outgrows a one-third rail, the rail hands off to the dark takeover
and the presenter continues inside a rounded PIP card on the takeover (§3 rank 11,
§5.9). Layer order during the build: canvas, then the presenter card, then module
containers, then text ("layer 4" = containers before text, the same skeleton-first
rule as rank 2). Rationale: the viewer never loses the face at the moment the
information gets denser, which is exactly when a full cutaway would feel like the
presenter left the room.

### T-D — Blur-recede exit on the graphics layer only

A card may leave by blurring, fading and receding slightly over ≈ 0.15 s
(`EXIT_BLUR_S` in `motion-tokens.js`, `--exit-blur-dur` in `tokens.css`,
`graphics/exit_on_cut.EXIT_BLUR_S`). Only the graphics layer blurs; the footage is
never blurred by an exit. 0.15 s is about four frames at 30 fps: long enough to read
as a deliberate exit, short enough not to compete with the next word. The exit needs
runway: a blur-recede that would still be running at a cut seam is a lint ERROR
unless `exitOnCut` clears the card on the cut (LL-001, LESSON-002).

### T-E — Statement swap with an empty beat

A statement card may replace its statement in place (`statement-card`
`spec.statements[]`): the outgoing line blur-dims over ≈ 0.15 s, **two frames stay
deliberately empty**, then the incoming line ramps in over ≈ 0.3 s. Rationale: the
empty beat tells the eye "new sentence" the way a paragraph break does; without it
the incoming words read as a correction of the outgoing ones. A deliberate
`statements[]` chain is exempt from the variety repeat rule (`MODULE_CARDS.md` §2).

### T-F — Takeover return on a cut

Leaving a full-frame card returns to the presenter on a hard cut at the presenter's
baseline framing (or the next planned framing). A takeover is never dissolved into
the face. Any discontinuous change of footage scale must land on a cut seam; eased
pushes run at least 0.25 s (`MOTION["longform_smooth"]`, `plan_lint_smooth`).
Rationale: a cut is the one place where a change of scale reads as intentional; a
visible pop in continuous footage reads as a glitch.

### T-G — Seams locked to word boundaries

Every transition `outTime` and every graphics window edge sits on a boundary between
kept words, in output time. The planner snaps them (`planner/word_lock.py`
`snap_to_word_boundary` / `snap_plan_seams`); `plan_lint_motion.check_word_lock`
WARNs when a seam sits more than **150 ms** from the nearest kept-word boundary
(`MOTION["word_lock"]["warn_off_boundary_s"] = 0.15`). Rationale: a seam between
words reads as the speaker's own punctuation; a seam inside a word clips a sound and
reads as a mistake. 150 ms is chosen to be shorter than a typical stressed syllable
at conversational pace, so a seam inside that tolerance cannot fall in the middle of
a word the viewer hears as whole. It is a WARN, not an ERROR, because the brain may
have a reason (a deliberate hit on a stressed syllable) and must say so.

---

## §3 Ranked build techniques (rank 1 … 11)

Ranked by how much each technique contributes to comprehension of a long-form card.
The first four are universal (every card kind); the rest apply where the card's
anatomy has the parts they describe. Token values live in `motion-tokens.js` and
`tokens.css` and are pinned by `tests/test_module_pack.py`.

### rank 1 — Modules land when the speaker reaches them

A card's modules land on the spoken words that introduce them, not on a fixed
stagger. The brain picks one kept word per module; code converts the picks into
comp-relative times (`graphics_copy.fill_module_lands` → `spec.moduleLands`). Lint
requires lands to be increasing, at least **0.25 s** apart and inside the card's
hold (`MOTION["module_lands"]["min_spacing_s"]`). Guidance band between lands:
0.6-1.4 s (`MOTION["module_lands"]["band_s"]`) — about one short spoken phrase; it
is guidance for the brain's word picks, not a wall. Rationale: 0.25 s is the
shortest interval at which two separate arrivals still read as two events rather
than one; lands closer than that stack.

### rank 2 — Skeleton first

The card's containers, hairlines and panels land first; their text follows
**0.35 s** later (`SKELETON_GAP_S`, `--skeleton-gap`). Rationale: when the layout
arrives before the words, the eye learns where things will appear and can move there
as soon as they do, instead of scanning a card that is still assembling.

### rank 3 — The eyebrow leads the headline

A small all-caps label (the eyebrow), led by a role-coloured dot, appears
**0.25 s** before its headline (`EYEBROW_LEAD_S`, `--eyebrow-lead`; allowed band
0.08-0.5 s). Rationale: the eyebrow names the category of what is coming ("COST",
"STEP 2", "RESULT") so the headline is read in context.

### rank 4 — Text resolves in place

Text appears with an in-place opacity ramp of **0.2 s** (`TEXT_RAMP_S`,
`--text-ramp-dur`; band 0.12-0.25 s) and never travels more than a few pixels.
Rationale: moving text must be tracked before it can be read; text that resolves
where it will stay can be read during its own entrance.

### rank 5 — Two-line accent headline

Card headlines use two lines: line 1 in ink states the subject, line 2 in the
**result accent** states the point. Rationale: the split tells the viewer which half
of the sentence is the claim without extra graphics.

### rank 6 — Semantic accent roles

Accent colour carries meaning, consistently across every card in a video:

| Role token | Meaning |
|---|---|
| result accent | outcomes, hero numbers, "what you get" |
| process accent | steps, the active node, "where we are" |
| neutral / ink | comparisons, baselines, labels |
| warning accent | limits, thresholds, failures — **only** |

Rationale: if a colour means one thing everywhere, the viewer reads the colour
before the words. The warning accent is reserved so that it keeps its alarm value.
Contrast of every accent against its actual background is a lint obligation
(LL-004, LL-033, `MOTION["contrast"]`).

### rank 7 — Bars fill with their value

Bars fill over ≈ 0.75 s with a power-out ease and each bar's value label lands with
the bar tip, not before. Rationale: a number shown before its bar has finished
growing contradicts the bar.

### rank 8 — Chip sweep

A row of chips lands as a quick sequential sweep, ≈ 85 ms per chip. Rationale: the
sweep reads as "one group of several" in a way a simultaneous pop does not, while
staying fast enough that no single chip becomes an event of its own.

### rank 9 — The evidence ribbon lands last

A source-and-date receipt line (small monospaced type) lands last in the build.
Rationale: evidence answers "says who?" — the question a viewer asks only after
reading the claim. It is exempt from the numeric claims gate because it cites a
source rather than the narration (`claims_contract.py`), but the brain verifies
that the cited source really is the claim's source (LESSON-005).

### rank 10 — A settled hold before any exit

After its last land a card holds fully built long enough to be re-read before any
exit starts: at least the long-form hold floor, 1.5 s
(`MOTION["hold_min_s"]["longform"]`). Rationale: the moment a card is complete is
the first moment it can be read as a whole; exiting then wastes the build.

### rank 11 — The dark takeover with a presenter card

For dense content the frame becomes a dark canvas and the presenter continues in a
rounded card on the right. Design parameters: the presenter card occupies
x 1344-1878, y 60-1020 of the 1920×1080 delivery canvas (≈ 28 % of width, ≈ 89 % of
height) with a 24-px corner radius (`graphics/pip_hole.HOLE_BY_KIND`, pinned by
`tests/test_module_longform.py`). Rationale: the right-hand band keeps the face at a
comfortable size for lip-reading while leaving the left two thirds as a single
reading area; the fixed geometry means every hole-comp and the renderer agree to the
pixel. Long-form only.

---

## §4 Cutaway or face-bridge: choosing the long-form graphics style

Produced/full long-form must declare one graphics style per video in
`target.graphicsStyle`, with a rationale (`graphics_planner_longform.resolve_style`;
lighter scopes keep the legacy default). The three styles are:

| Style | What carries information | Choose it when |
|---|---|---|
| `cutaway-only` | Full-frame cutaways (whiteboards, kinetic quotes, receipts); nothing floats over the talking head except one lower-band card | The talk is conversational, structure is occasional, and the face is the product |
| `overlay-rich` | Two-tier burned text, headroom icon stacks and chips over the live presenter; full takeovers reserved for section moments | Energetic delivery where cutting away would break momentum (see `REFERENCE_STYLE_STUDY.md` R22-R24) |
| `face-bridge` | The two module chassis: the light rail beside the face, then the dark takeover with the presenter card | Explanations dense enough to need the full frame, where the presenter should never disappear |

Adjudication rules:

1. **Pick by the audience's reason for watching** (`EDITCRAFT_LESSONS.md` §9). If
   they came for the person, protect the face; if they came for the method, protect
   the reading area.
2. **Do not mix styles inside one video.** A viewer learns the video's grammar in
   the first minute; switching grammar later reads as a different editor.
3. **Face-bridge is not "more graphics".** It is the same information budget
   delivered without cutaways. The variety floors and claims rules apply unchanged.
4. **Shorts never enter this axis.** The PIP card, rail push and face-bridge are
   long-form grammar and are banned for shorts by `plan_lint_module`.

---

## §5 Adoption items (§5.1 … §5.10)

Each item is a capability Sniper adopted from this doctrine, with its status.

### §5.1 — Item 1: the module motion-token pack

`TEXT_RAMP_S` 0.2, `EYEBROW_LEAD_S` 0.25, `SKELETON_GAP_S` 0.35, `EXIT_BLUR_S` 0.15
in `motion-tokens.js`, with CSS twins in `tokens.css`. One source of timing for every
module comp, so two cards built from different templates still feel like one system.
Status: shipped; `tests/test_module_pack.py` pins both twins.

### §5.2 — Item 2: the exit vocabulary

`spec.exit` ∈ {`hold`, `fade`, `blur-recede`} (`graphics/exit_on_cut.EXITS`). The
renderers clamp an exit to the next cut seam before rendering so a blur ends exactly
on the seam; lint fails windows too short for the blur to complete (T-D, LL-001).
Status: shipped.

### §5.3 — Item 3: the statement replace grammar

`statement-card` `spec.statements[]` with the T-E empty beat. Status: shipped.

### §5.4 — Item 4: narration-paced module lands

The brain picks which kept words each module lands on;
`graphics_copy.fill_module_lands` converts them to comp-relative `spec.moduleLands`;
the comp schedules each module's build at its land; `plan_lint_motion` validates
the lands (increasing, ≥ 0.25 s apart, inside the hold). This is rank 1 made
executable. Status: shipped; `tests/test_module_lands.py`.

### §5.5 — Item 5: word-locked seams

`planner/word_lock.py` snaps transitions and graphics windows onto kept-word
boundaries at plan time; `plan_lint_motion.check_word_lock` WARNs beyond 150 ms
(T-G). Status: shipped; `tests/test_word_lock.py`.

### §5.6 — Item 6: the claims contract

Before render, every **numeric** token in card copy (`graphicsTrack[].spec` strings,
numeric affix slots, `titleCards[].text`) must be **spoken in the card's window**.
Matching is arithmetic, not semantic: digits, currency/percent/multiplier edges,
K/M/B scales and spelled cardinals composed by lookup. Multi-word phrases on a card
must also be spoken in the window or be declared structural labels (LL-003). Evidence
and icon slots are exempt. Whether a paraphrase is faithful is the brain's call in
SKILL step 4b; the gate only guarantees that no number appears that the presenter
did not say. Status: shipped, hard gate; `claims_contract.py`,
`tests/test_claims_contract.py`. This is the executable form of §1.2 #11.

### §5.7 — Item 7: semantic accent tokens

The rank 6 roles exist as named tokens (result, process, warning, ink) so templates
cannot drift into ad-hoc colours. Values are chosen by the design tokens, not here.
Status: shipped as tokens; values owned by the design system.

### §5.8 — Item 8: rail-push entrance and light skin

`glass-rail` `spec.entrance: "rail-push"` and `spec.theme: "light"` implement T-B.
Long-form only (`plan_lint_module`). Status: shipped; `tests/test_module_longform.py`.

### §5.9 — Item 9: the static presenter-in-PIP takeover

Hole-comps (`graphics/pip_hole.py` registry: `module-takeover` always; the
scoreboard, pipeline and dark ledger when `presenterFrame` opts in) render the frame
around a transparent rounded hole, and the compositor scales the live footage into
the hole beneath the comp. Adjudicated legal for long-form by the operator on
2026-07-10; banned for shorts, where the frame is too small for a second face-sized
region. Status: shipped.

### §5.10 — Item 10: animated shrink-to-PIP

An eased move that shrinks the live footage into the PIP card (`graphics/pip_takeover.py`).
Status: **not wired** — `render.py` never calls it and `plan_lint_motion` rejects
`needsPip` / `canvas-pip-list` entries that would need it. Do not describe it as
available.

---

## §6 Limits of this doctrine

- It governs long-form graphics. Short-form grammar lives in the style documents
  and `SHORTFORM_LESSONS.md`.
- It does not choose card forms; `MODULE_CARDS.md` §1.4 does.
- It does not make a card legible on arbitrary footage; contrast and occlusion are
  separate gates (LL-004, LL-033, LL-034).
- Timing values are parameters. When a value changes, change the token twins and
  their tests together, and update this document in the same change.
