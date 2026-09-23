# SLIDEWARE_STYLE.md — the Slideware short-form style specification

**Style ID** `slideware` · **pace ID** `slideware` · **intent preset** `slideware-involved`
(`src/lib/producer/intent-presets.ts`) · **lint profile** `MODES["short"]["pacing_slideware"]`
(`scripts/producer/producer_config.py`) · **compositions** `slideware-takeover-deck`,
`slideware-receipt-cell`, `slideware-staircase-lockup`, `slideware-caption-dual-mode`.

**Status.** Sniper design specification, written for Project Sniper (rc4, 2026-09-18). It
replaces the earlier document at this path in full.

**Who reads this.** The Auto Edit authoring brain reads this file before it authors any track
when `target.style` is `"slideware"`; `src/lib/server/auto-edit-doctrine.ts` pins it into the
per-run doctrine snapshot. Maintainers read it before changing `pacing_slideware` or the four
`slideware-*` compositions.

**How to read it.** Section numbers and rule IDs (AH3, AC1, AZ2, ACAP1, E3, …) are stable
identifiers cited by code comments, config comments, tests and the intent-card preset text; keep
them when editing. Each rule gives the rule, the design reason, and how it is enforced:
**ERROR** (a gate fails the plan), **WARN** (a lint reports it), or **advisory** (the authoring
brain follows it; no code checks it).

The one-sentence idea: *an explainer in which designed slides do the showing, the speaker does
the telling, and the camera never moves.*

---

## 0. Evidence and scope

- **Evidence.** Sniper design specification; parameters verified against `producer_config.py`
  and the lint/tests named in §9 and §12. The rationale for each rule is first-principles
  reasoning about explaining one idea with on-screen material in a vertical short, stated with
  the rule. This document does not report measurements of any third-party video and makes no
  audience-retention claims.
- **Numbers.** Every numeric value here is a **Sniper design parameter**. Where code reads it,
  §9 names the reader.
- **Format.** 9:16 shorts. All four `slideware-*` compositions are 9:16; §10 covers what does and
  does not carry over to a long-form intro.
- **Choose Slideware when** the message is a method, a list, a comparison or a result that is
  clearer shown than said, and real evidence (screenshots, recordings, documents) exists for it.
- **Do not choose it when** there is nothing real to show (see E3) or the delivery should carry
  the clip alone (use Restrained).

## 1. Brand system

**B1 — One accent for the whole clip.** Every slideware element in a clip uses the same accent
colour, passed as the `accent` variable of each composition that takes one. There is no second
highlight colour. The deck canvas, the lockup payload and the caption pill all refer to that one
accent.
*Why:* when every slide, lockup and pill shares one colour, the viewer reads the clip as one
system, and a single change re-brands the whole clip.
*Enforced:* the accent value comes from the design system (`templates/motion/tokens.css`); this
specification fixes the role, not the value. `brand_lint.py <edit_plan.json>` rejects a
`graphicsTrack` spec colour that is not a `tokens.css` token, but it is a standalone gate and is
not invoked by the Auto Edit controller (§12). Keeping one accent across entries is advisory.

## 2. Hook

**AH1 — Frame zero is fully dressed.** At 0.0 s the frame already shows its first graphic (a deck
header, a lockup, or the hook card) and captions. Nothing builds up from an empty frame.
*Why:* the first frame doubles as the cover and the loop point; an explainer that opens on an
empty frame looks unfinished.
*Enforced:* the full scope owns graphics, so a short needs a `style: "hook"` title card starting
at 0.0 s (**ERROR**, `plan_lint_overlays.check_title_cards`). Additional frame-zero dressing is
advisory.

**AH2 — Real evidence early.** The first piece of real proof (a receipt cell with real media,
E3) appears inside the 3 s hook window (`MODES["short"]["hook_window_s"]`).
*Why:* the style's promise is "I will show you". Showing something real early earns the time the
slides will take.
*Enforced:* advisory.

**AH3 — The hook is carried by graphics, not by cuts.** ⇒ `hook_front_load = 1.3`.
*Why:* in this style, cuts are section punctuation (AC1) and are rare in the hook. Opening
density comes from graphic lands (deck header, cells, lockup words). The generic short ratio of
1.5 would push the author to add opening cuts, which conflicts with AC1; 1.3 still requires a
denser opening, counted on the graphic layer.
*Enforced:* **WARN** in `plan_lint_motion._warn_pacing`. Tests:
`test_slideware_pace_relaxes_the_front_load_only` in `scripts/producer/tests/test_pacing.py`.

**AH4 — No cut in the hook unless it opens a section.** The only legal cut in the first 3 s is
the cut into the first takeover section.
*Why:* it follows from AC1 and AH3; an unmotivated early cut spends the opening on a camera event
instead of on content.
*Enforced:* advisory.

## 3. Structure and cuts

**AC1 — Cuts only at section boundaries.** A cut happens only where the clip changes section:
talking head to takeover, takeover back to talking head, or one section to the next.
*Why:* the slides provide the change of view. Extra cuts inside a section would compete with
page turns and cell lands for the same attention.
*Enforced:* advisory.

**AC2 — One idea per section.** A takeover section carries one idea: one header and at most three
pages (`slide1`–`slide3` of the deck).
*Why:* a section is the unit a viewer can hold in mind while listening. The composition's
three-page limit matches that unit.
*Enforced:* the deck composition has three page slots; the one-idea rule is advisory.

**AC3 — Exactly one graphic economy per clip.** Choose one:

- **takeover deck** — full-frame deck sections that alternate with the talking head
  (`slideware-takeover-deck`); or
- **persistent ledger** — one list or tally that stays on screen beside the speaker and gains an
  item per beat (for example `list-build` or `module-ledger-dark` held across the section).

Never both in one clip.
*Why:* the two economies teach the viewer different reading habits (look at the whole frame, or
look at the running list). Mixing them makes every graphic a small puzzle about where to look.
*Enforced:* advisory.

**AC4 — Return to the speaker between sections.** Two takeover sections are never back to back;
the talking head comes back between them, even briefly.
*Why:* the speaker is the voice the viewer is following. Returning to the face marks the
section boundary and gives the eye a familiar anchor before the next section.
*Enforced:* advisory.

**AC5 — The voice never stops.** Takeover sections play over continuous narration; there are no
silent slides.
*Why:* a silent slide asks the viewer to read without guidance and stalls the clip's
momentum; the voice is what connects one slide to the next.
*Enforced:* advisory. Pause removal (`edit/pause_scan.py`) applies inside takeovers as elsewhere.

## 4. Camera

**AZ1 — No punch-ins.** The `punchIns` track stays empty. ⇒ advisory `punch_ins = False`; the
preset sets `lanes.motion: "off"`.
*Why:* the graphics already carry the motion. A scale change on the speaker would add a second
motion language, and the speaker frame is the calm constant between sections.
*Enforced:* **ERROR.** The operator-intent contract fails a plan that authors `punchIns` while
the stored intent has the motion lane `"off"`.

**AZ2 — Hard cuts only.** No seam transitions. ⇒ advisory `transitions = False`; the preset
sets `lanes.transitions: "off"`.
*Why:* the deck's page turns are the style's only "transition" and happen inside the graphic. A
seam effect on top would be a second transition vocabulary.
*Enforced:* **ERROR.** The operator-intent contract fails a plan that authors `transitions`
while the stored intent has that lane `"off"`.

**AZ3 — Motion lives inside the graphics.** Pages turn, cells pop, lockup words land; the frame
itself never moves.
*Enforced:* follows from AZ1 and AZ2.

## 5. Captions

**ACAP1 — No karaoke, no coloured captions.** Use whisper-style replace-per-cue captions (on
footage, `captions.style: "whisper"` with no `emphasisWords`) or the dual-mode caption element
(E4). Emphasis inside captions is weight only (`*bold*` in `slideware-caption-dual-mode`).
*Why:* the accent colour belongs to the slides (B1). Captions that also use colour would compete
with the one element that is supposed to carry it.
*Enforced:* advisory for the style choice; the dual-mode composition supports bold as its only
emphasis.

**ACAP2 — Two caption skins.** Captions change skin with the background: **footage mode** (white
text in the caption band over the speaker) and **canvas mode** (a pill behind the text, for
legibility over the accent canvas). ⇒ `slideware-caption-dual-mode` `mode: "footage" | "canvas"`.
*Why:* white text is legible over footage but can fail over a bright, flat accent canvas; a pill
restores contrast without changing the caption's position or rhythm.
*Enforced:* the composition implements both skins. Choosing the right skin per section is
advisory.

**ACAP3 — Captions never overlap designed text.** Keep the caption band clear of the deck header,
the lockup and cell labels.
*Why:* overlapping text is unreadable, and it makes the viewer choose between the spoken word and
the designed word.
*Enforced:* advisory.

**ACAP4 — A key phrase is shown once.** When a phrase becomes a staircase lockup (E2), it replaces
the caption in place instead of appearing twice.
*Why:* reading the same words twice on one frame spends attention for nothing.
*Enforced:* advisory. The staircase composition supports an in-place replace chain
(`payload2`, `payload3`, `replaceAt2`, `replaceAt3`).

## 6. Visual system

### 6.1 Grid

Three horizontal zones on the 1080×1920 canvas: a **header zone** at the top (deck header,
lockup kicker), a **content zone** in the middle (deck pages, receipt cells, lockup payload) and
a **caption zone** at the bottom (captions or pills). All text stays inside the canvas safe box.
*Why:* stable zones let the viewer learn where each kind of information appears.

### 6.2 Animation

- Lockup words and receipt cells **pop** in on a single frame at their word-locked times; they
  never fade.
- A deck's first page settles in as one unit with a very short entrance (about 0.2 s); later
  pages turn **carousel-style**: the old page exits left while the new page enters from the
  right.
- Nothing fades out; an element ends on a section cut or with an instant hard-off.

*Why:* pops and page turns are legible as discrete events that line up with speech. Slow fades
read as indecision in a style built on crisp slides.
*Enforced:* by the compositions' own timelines (the staircase lockup and receipt cells use
instant visibility sets; the deck does not fade itself out and leaves both seams to the
compositor).

### 6.3 Element catalog

- **E1 — Takeover deck** ⇒ `slideware-takeover-deck` (own-screen, full frame): header, up to
  three pages, up to three caption pills, page times `pageAt2` and `pageAt3`, `accent`.
- **E2 — Staircase lockup** ⇒ `slideware-staircase-lockup`: kicker, capitalised payload,
  co-word, word-locked pops and an in-place replace chain.
- **E3 — Evidence must be real pixels** ⇒ `slideware-receipt-cell`: each cell shows a label over
  a 9:16 media slot (`mediaN`) filled with a real screenshot, recording frame or document from
  this job's manifest. Never mock up evidence. A cell may carry a small count chip (`viewsN`)
  only when that number is spoken near the cell.
  *Why:* the style's credibility rests on the proof being real; a fabricated receipt would turn
  the whole clip into a claim the viewer cannot trust.
  *Enforced:* the numbers in `viewsN` and `labelN` are **ERROR**-checked by
  `claims_contract.py` (every numeric token in a `graphicsTrack` spec string must be spoken
  within 3 s of the card's window; only `evidence*` and `icon*` keys are exempt). That media is
  real is the author's responsibility and is checked at review, not by code.
- **E4 — Dual-mode captions** ⇒ `slideware-caption-dual-mode` (ACAP2). Registered as a caption
  *layer* kind (`MOTION["variety"]["layer_kinds"]`), so it does not count against the
  graphic-variety checks.
- **E5 — Persistent ledger** ⇒ an existing list or ledger card held across a section (AC3,
  ledger economy). There is no slideware-specific ledger composition.

## 7. Music and audio

**AM1 — A bed is recommended.** ⇒ advisory `music = True`. The preset sets `music: false`; the
operator opts in.
*Why:* a steady bed binds alternating slide and speaker sections into one piece.
*Enforced:* the operator-intent contract fails a plan whose `music.enabled` differs from the
stored intent (**ERROR**).

**AM2 — Standard master and duck.** The bed ducks under dialogue (`AUDIO["music_duck_db"]`,
`AUDIO["music_gap_db"]`), and the program masters to −14 LUFS with the −1.5 dBTP true-peak
ceiling (`AUDIO["lufs_target"]`, `AUDIO["true_peak_dbtp"]`).
*Enforced:* `audio/master.py`, the music stage and Audit B's loudness check.

**AM3 — The bed runs through.** No music stops, drops or stingers on page turns.
*Why:* page turns are already visual events; audio hits on every turn would double them and
become predictable.
*Enforced:* advisory.

## 8. Low-confidence register

Design judgements that have not been validated with viewers or with a Sniper-rendered
side-by-side comparison:

- **L1** — the rate floor of 16 per minute and the 8 s ceiling (§9) are design choices, not
  measurements.
- **L2** — the advisory state rate of 65 per minute is arithmetic (§9), not a measurement.
- **L3** — AC3's "never both" may be too strict for clips longer than a minute.
- **L4** — AH2's three-second target for the first real proof may be impractical when the proof
  needs setup.
- **L5** — whether the count chip (E3) helps comprehension or only adds clutter is open.

## 9. Executable profile and checklist

### 9.1 Pacing profile

`MODES["short"]["pacing_slideware"]`, selected when `target.pace == "slideware"`
(`plan_lint_motion._pacing_profile`).

| Key | Value | Rule | Read by |
|---|---|---|---|
| `min_changes_per_min` | 16.0 | §3 AC1–AC2, §6 | `plan_lint_motion._warn_pacing` (WARN) |
| `max_still_gap_s` | 8.0 | §6.2 | `planner/pacing.py` `pacing_report` → `_warn_pacing` (WARN) |
| `hook_front_load` | 1.3 | §2 AH3 | `_warn_pacing` (WARN) |
| `state_changes_per_min` | 65.0 | §5, §6 | advisory; no code reads it |
| `music` | `True` | §7 AM1 | advisory; the preset stores `music: false` until the operator opts in |
| `punch_ins` | `False` | §4 AZ1 | advisory key; the preset's `lanes.motion: "off"` is what is enforced |
| `transitions` | `False` | §4 AZ2 | advisory key; the preset's `lanes.transitions: "off"` is what is enforced |

*Why these values:* cuts are rare (AC1), so the rate floor is met by graphic events. Page turns,
cell lands (`atN`), lockup words and section cuts all count as discrete changes
(`planner/pacing.py` `visual_change_times`). 16 per minute, about one change every 3.75 s, is the
design floor for a slide-driven explainer. The 8 s ceiling equals the generic short ceiling
because the slides should never rest longer than a plain produced short would. The advisory
65 per minute adds caption and pill changes: for example, about 45 caption cues per minute plus
the 16-per-minute graphic floor and a few section cuts.

### 9.2 Preset

`slideware-involved`: mode `short`; scope `full`; `lanes: {motion: "off", transitions: "off"}`
(§4 AZ1, AZ2); pace and style `slideware`; `music: false` (AM1 opt-in); no `audioEnhance`.

### 9.3 Authoring checklist

1. One graphic economy chosen: deck or ledger (§3 AC3).
2. Frame zero fully dressed; hook card at 0.0 s (§2 AH1).
3. First real proof inside the first 3 s (§2 AH2).
4. Cuts only at section boundaries (§3 AC1); speaker between sections (§3 AC4).
5. `punchIns` empty and `transitions` empty (§4 AZ1, AZ2).
6. Captions: footage or canvas skin per section, bold as the only emphasis (§5).
7. One accent for every element (§1 B1).
8. Every receipt uses real media; every number shown is spoken (§6 E3).
9. Music only if the operator ticked it (§7 AM1).

## 10. Long-form intro

The slideware compositions are 9:16 only, and there is no long-form slideware profile. For a
16:9 intro, some ideas carry over as guidance through the ordinary long-form lanes: a dressed
first frame (AH1), early real proof (AH2), and one graphic economy (AC3). Nothing in §9 applies
to long-form, and `reference.targetStyle` is short-only.

## 11. Build list

The four compositions that implement this style
(`templates/motion/compositions/`, registered in `src/lib/producer/comps-catalog.ts` under
`section: "slideware"`):

| Element | Composition | Main variables | Notes |
|---|---|---|---|
| E1 deck | `slideware-takeover-deck` | `header`, `headerInk`, `slide1`–`slide3`, `pill1`–`pill3`, `pageAt2`, `pageAt3`, `gradientTop`, `accent` | own-screen; layout family `takeover` (`MOTION["layout_families"]`) |
| E3 receipt cells | `slideware-receipt-cell` | `layout` (strip / grid / showcase), `label1`–`label6`, `views1`–`views6`, `media1`–`media6`, `at1`–`at6`, `corner` | listed under the `evidence` form family in `MOTION["card_form_map"]` |
| E2 staircase lockup | `slideware-staircase-lockup` | `kicker`, `payload`, `coWord`, `payload2`, `payload3`, `band`, `payloadSize`, `kickerAt`, `payloadAt`, `coAt`, `replaceAt2`, `replaceAt3`, `accent` | word-locked pops; in-place replace chain (ACAP4) |
| E4 dual-mode captions | `slideware-caption-dual-mode` | `mode` (footage / canvas), `cue1`–`cue6`, `at1`–`at6` | caption layer kind (`MOTION["variety"]["layer_kinds"]`) |

The compositions' visual design (accent value, typefaces, default copy) belongs to the design
system and may change without changing this document.

## 12. Gaps and verification

**Gaps (not built):**

- no call-to-action endcard element specific to this style;
- no gate checks that one accent is used across all entries (B1) or that only one economy is
  used (AC3);
- `brand_lint.py` is not part of the Auto Edit gate bundle (a grep of `src/` on 2026-09-18 found
  no caller);
- nothing verifies automatically that receipt media is real (E3); review owns it.

**Verification record** (2026-09-18, rc4 working tree):

1. **Profile values equal the config.** Each value in the §9.1 table was compared with
   `producer_config.MODES["short"]["pacing_slideware"]` by importing the module; all seven keys
   matched.
2. **The lint uses the profile.** `test_pacing.py`
   `test_slideware_pace_relaxes_the_front_load_only` shows `pace: "slideware"` clears the hook
   front-load warning (1.3) while keeping the rate (16/min) and still-gap (8 s) floors.
3. **Lane waivers.** With the preset's stored intent, a plan that authors `punchIns` or
   `transitions` fails the operator-intent contract (probe).
4. **Punch ceiling unaffected.** Under `pace: "slideware"`, a static punch-in at 1.3 still fails
   the generic [1.05, 1.25] band (probe); this profile has no `punch_zoom_max`.
5. **Number claims.** `claims_contract.py` skips only keys beginning with `evidence` or `icon`
   (`_SKIP_PREFIXES`), so `viewsN` and `labelN` numbers are checked (read in code).

Not checked: the visual result of this style has not been rendered and reviewed for this
revision of the document, and no claim is made about how viewers respond to it.
