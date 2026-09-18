# EDITCRAFT LESSONS — longform + b-roll doctrine (baked 2026-07-11)

Two studies of the same editing teacher's craft, folded into the PRODUCER's
deterministic pipelines:

- **EC1** — a ~35-min produced education longform, MEASURED shot-by-shot
  (158 shot/state changes traced; 5 word-timed trigger→insert
  confirmations) plus the creator's own TAUGHT curriculum on the same
  footage.
- **EC2** — a second taught video (editcraft2, 872s) with the rules
  demonstrated live on real artifacts; measured 677 visual-state events /
  101 cuts (46.6 states/min vs 6.95 cuts/min).

Every rule below carries its evidence stamp and, where it touches code, the
exact config key / lint / LESSON-id it is encoded as. Conflicts with our
already-measured grammars (MODULE / punch / restrained / slideware / the
production envelope) are adjudicated in §10 — **the meta-rule R12 (§9)
governs every adjudication**.

Encoding map: `scripts/producer/producer_config.py` (`BROLL`, `MODES`,
`MOTION`, `AUDIO` additions), `scripts/producer/docs/findings/
FAILURE_LEDGER.md` LESSON-012..026. Additive only; no default changed.

**CROSS-CHECKED (2026-07-11):** two machine cross-checks (journals
wf_5035c1e1-82e + wf_bde3eba0-7fa) re-verified the numeric citations
against the deep-study events + VTT word timings; corrections are stamped
inline below (see FAILURE_LEDGER LL-012/LL-013 + LESSON-027 — word-timed
citations come from the wordLock pass, never hand-copied).

---

## 1. The LANE SPLIT — presenter vs screen-share are different grammars

**Measured (EC1, 158 shot/state changes):** presenter footage runs **15.6
shot/state CHANGES per minute with a 39% cutaway share** — that 15.6 is
state-change CADENCE (every visual-state/shot change counted), NOT detector
hard cuts, which measure **≈5.8/min on the presenter lane** (machine
cross-check 2026-07-11); screen-share footage runs **0.6 cuts/min** with
retention carried by cursor motion + a persistent PIP + demo audio. Never
apply one lane's pacing lint to the other.

**Camera-hold legality (Restrained C4 reconfirmed at longform scale):** a 157s
zero-cut hold is legal ONLY while another layer churns (cursor, PIP, demo
audio, pills). A bare hold that long is never legal on presenter footage.

**State-churn invariant (EC2 R7, CONFIRMED 4/4 grammars):** produced content
churns *some* visual layer at ~45–90 events/min while hard cuts stay
0–17/min (editcraft2: 46.6 states/min vs 6.95 cuts/min). Never force cut
density to hit an energy number — pick WHICH layer churns per style.

**Encoded:** `MODES["longform"]["pacing_lanes"]` (presenter/screen-share
lane data the brain + future lane-aware pacing lint read);
`MODES["longform"]["pacing"]["state_churn_per_min"]` advisory band;
LESSON-014. Roadmap: teach `plan_lint_motion`'s pacing pass to switch lane
by the plan's visual-state map (the `visual_state` module already
classifies talking-head / screen-share zones).

## 2. B-roll doctrine (the b-roll lane's law)

### 2.1 Trigger → insert latency (MEASURED, word-timed)
Land every b-roll/graphic within **0–1.5s of its trigger**. The anchor is
the **REFERENCE-PHRASE START** (the first word of the naming phrase), so an
insert may LEAD the phrase's head noun by up to ~1.5s while still trailing
the trigger — the band stays (0, 1.5). Five word-timed confirmations:
MKBHD 757s→760s, Trahan ~766s→766s, "keyboard shortcuts" 489–495s→492s,
"regret" 56–62s→57s, "14-day filmmaker" word "14-day" **1768.48s → zoom
1769.39s (+0.91s) / graphic 1769.65s (+1.16s)** (machine-verified from the
VTT word timing + deep-study events; an earlier hand-copied "~798s→796s"
pair put the insert ~2s BEFORE its trigger and contradicted the very band
it was cited to confirm — LL-013, LESSON-027).
**Encoded:** `BROLL["trigger_latency_s"] = (0.0, 1.5)`; the receipts lane
already lands `outStart` exactly ON the trigger word (latency 0, inside the
band); LESSON-025.

### 2.2 Literal-first matching
If the speech names a person/tool/product/site, show THAT thing (creator
clips, phone mockup, web UI, site scroll, camera sensor). Reserve
conceptual b-roll for emotional beats only (regret / boredom / diligence)
and stage it as cinematic SELF-footage, never stock.
**Corroborates** REFERENCE_STYLE_STUDY R17 ("receipts beat rendered
graphics") and the word-locking in MEASURED_EDIT_GRAMMAR.
**Encoded:** `BROLL["literal_first"]` + `BROLL["conceptual_only_for"]`;
LESSON-012. Conflict with the R24 concept-stock lane adjudicated in §10.1.

### 2.3 B-roll priority ladder (EC2 R10, CONFIRMED 3rd source)
**Motion graphics > purpose-shot b-roll > stock** ("lazy version", 3:54) —
choose by explanatory density; animation wins where footage is too slow or
confusing (Dude Perfect beat 4:02–4:37). Direct external confirmation of
HyperFrames-PRIMARY ordering.
**NEW sub-rule (education content): SELF-DEMONSTRATING B-ROLL** — apply the
taught technique to a real on-screen artifact (the hue lesson literally
turns the screenshot red @8:02; the cut lesson uses THIS video's timeline
@9:31). Demo-on-real-artifact outranks metaphor illustration;
receipts-over-claims (real tweets/analytics) now 3/3 creators.
**Encoded:** `BROLL["priority"]`; LESSON-012.

### 2.4 Hold bands (MEASURED)
| insert kind | hold |
|---|---|
| referenced-creator clips | 1.5–2.5s |
| literal object/system shots | 2–4s |
| montage-burst shots | 0.6–0.7s |
| side-by-side comparison cards | 9–10.5s |
| list cards | 8–12s |
| step/title cards | 2–3s |
| diagram cards | 2.5–8.5s |

**Encoded:** `BROLL["hold_bands_s"]` (the brain picks the band by kind;
the existing `MODES[*]["broll_insert_max_s"]` footage ceilings are
unchanged — see §10.4 for the card-hold adjudication).

### 2.5 VO continuity law
A-roll speech never stops under any insert — all b-roll is **video-only**;
mute borrowed-clip audio; demo/native audio is allowed only when the demo
IS the lesson (playthrough moments).
**Already true in code:** `broll/broll_insert.py` composites video-only
("receipts ride on top, never touch audio"). **Encoded:**
`BROLL["vo_continuity"]` + `BROLL["demo_audio_exception"]`; LESSON-013.

### 2.6 Credit label law
Borrowed third-party footage carries a lower-left **`CREDIT: <NAME>`**
label for the insert's full duration (observed on 100% of MKBHD/Trahan
shots). **Encoded:** `BROLL["credit_label"]`; LESSON-013. Roadmap: a
`credit` field on brollTrack entries rendered as a chip comp.

### 2.7 Enter/exit grammar
Hard cut in/out for ~90% of inserts; **zoom pull-in/pull-out ONLY at
a-roll↔b-roll seams; glare/flash or whip-blur ONLY at graphic↔a-roll
seams**. Transitions are seam markers (~10–12 events in 35 min ≈ 0.3/min),
never intra-lane decoration.
**Corroborates** MOTION["transitions"]["max_per_min"]=2.0 sitting far above
the measured rate (a ceiling, not a target) and plan_lint_smooth's WARN on
flash/leak in longform. **Encoded:** `MOTION["transitions"]["seam_roles"]`
+ `["longform_events_per_min"]` advisory.

### 2.8 Insert polish law
Every b-roll insert gets the same LUT/grade as A-roll (type-180 rotate if
rigged overhead) and stabilization when handheld — inserts must be
indistinguishable in polish from A-cam.
**Encoded:** `BROLL["insert_polish"]`; LESSON-013.

### 2.9 B-roll acquisition loop (TAUGHT)
Freeze editing at rough-cut → watch it → write the FULL b-roll shot list →
shoot ALL of it in one outing → resume. Plan-then-batch, never
shoot-per-gap. **Encoded:** LESSON-025 (operator workflow; matches our
propose-review-fill loop where the planner emits `assetId: null` slots).

## 3. Card grammars (full-frame graphics)

### 3.1 Full-frame cutaway law (RECONFIRMED)
Every card, list, diagram, and comparison is a full-frame takeover; never
panel a graphic over the face; around-face elements are limited to small
pills stacked in measured free space.
**Already law:** `feedback_pro_graphics_are_cutaways` + the own-screen
anchor + free-space placement. Third corroboration — no change.

### 3.2 Step-card template
Every section boundary gets a full-frame dark card — viewfinder chrome
(AUTO/RECORD corners), eyebrow "STEP #N", glitch/typewriter title build,
**2–3s hold**, hard cut out, **riser+hit under it, new music track for the
new chapter**. **Encoded:** hold band in `BROLL["hold_bands_s"]
["step-card"]`; audio in §6; LESSON-026. Comp roadmap: a `step-card`
template in `templates/motion/compositions/`.

### 3.3 List-card grammar
Dark grid bg, title with exactly ONE red keyword, items build **one per
spoken beat** (~2–3s apart, 3 items typical); the decision variant builds
all options then COLLAPSES to the chosen answer + red arrow + typed
one-line reason.
**Corroborates LL-011 progressive point reveal** (per-item word-locked
lands are already an ERROR-gated law on longform: `MOTION["row_lands"]` +
`plan_lint_visual.check_row_lands`). The ONE-red-keyword rule matches the
payload-economy doctrine (LESSON-023).

### 3.4 Comparison-card grammar
Before/after claims get side-by-side LIVE video panels with white labels
(ORIGINAL/ENHANCED, BEFORE/AFTER), **9–10.5s hold — long enough to actually
hear/see the difference twice**. **Encoded:** `BROLL["hold_bands_s"]
["comparison-card"]`; §10.4 for the ceiling adjudication.

### 3.5 Signature card recurs
The brand concept card (10-step number line) appears at the hook (t11) and
AGAIN on re-mention (t48) — encode signature cards as reusable comps keyed
to a concept, replayed on re-mention. **Encoded:** LESSON-026 (brain
judgment: which concept is signature); comps are already content-hash
cached so a replay is free.

### 3.6 Section recap card
Close a long teaching section with a 2–3s card — circular face bubble
centered on dotted black + pill title of what was just taught ("HOW TO ADD
TEXT") — before the next step card. **Encoded:** LESSON-026.

### 3.7 Topic-chip overture
The intro may stack topic pills around the presenter in free space (6
chips, ~4s) as a contents preview — free-space-placed, face never
occluded. **Compatible** with the free-space placement engine
(`planner/free_space.py`) as-is; a chip-row comp already exists.

## 4. Screen-share teaching lane

### 4.1 Persistent tutorial PIP (new lane; extends pending pip_takeover #39)
During screen-share teaching, composite a circular webcam PIP **~11% frame
width, bottom-right, over the timeline zone (never over the content being
taught)**; introduce it when depth increases (his: step 5 onward), omit it
during quick cruise-through demos.
**Encoded:** `MODES["longform"]["tutorial_pip"]` (data for the future lane;
the ANIMATED pip_takeover remains unwired — task #39).

### 4.2 Screen-rec punch-in
Never show a full 1080 desktop — punch into the active UI region;
split-composite two zoomed panels when comparing controls; add keycap
callout graphics (white keycap + action label, e.g. "Q — DELETE LEFT")
when a shortcut is spoken. **Encoded:** LESSON-014 (punch-into-UI);
keycap-callout comp is roadmap.

## 5. Captions on longform — keyword pills, not streams

**EC1:** long-form emphasis layer = sparse white caption pills echoing the
key phrase (**~8 per 35 min**: LINK IN THE DESCRIPTION, QUALITY ASSURANCE,
CHECK FOR TYPOS…), never verbatim caption streams.
**EC2 R11 (CONFIRMED format split):** long-form: NO continuous caption
track; sparse short center-screen emphasis captions (≤3 words TYPICAL, not
a hard cap — a 7-word emphasis card is observed on-style) only where the
exact words matter (7:03–7:24 practice+sermon); shorts: continuous 1–5 word
cues.
Karaoke remains off-style in every measured grammar.
**Encoded:** `MODES["longform"]["emphasis_pills"]` advisory
(`captions_burn: False` + SRT sidecar already the longform default —
compatible: the sidecar is closed captions, not a burned stream). Roadmap:
a small `emphasis-caption` pill comp for the longform lane.

## 6. Music + SFX doctrine

**EC1 (his words, his practice):** riser+hit marks every new section;
whoosh/pop under every graphic entrance; **trim SFX to the animation's
entrance duration only and add a fade-in handle** to soften attack; music
bed **~−20 dB under voice**, adjusted by ear; **new song per chapter**;
"audio is half of the viewing experience."

**EC2 R3 — emotional SFX classes (11:16–12:01):** extend the sfx vocabulary
beyond whoosh/click/pop with **riser** (pre-payoff tension; HONESTY GATE:
only when a real payoff follows), **hit** (payoff/emphasis; riser→hit chain
legal), **drone** (dark/suspense mood). Map to beat types at plan time;
keep whoosh-on-motion + highlight-sound-on-highlight as the mechanical
layer.

**EC2 R4 — music as segment architecture (12:33–14:22, practiced in his own
master):** longform plans split by subject change and assign a music mood
per segment; music-STOP at a major pivot = jolt (his 2:30 hits −56 LUFS on
the pillar transition); slow fade-out = segment-closing signal; drop/quiet
the bed under the pitch/CTA (his 4:50–5:33 runs −21..−27 LUFS); sync a
music hit to the problem→solution pivot; prefer stems when available.
**LONGFORM ONLY** — punch shorts keep a constant bed (6/6 zero-gap),
restrained has none (§10.9).

**Encoded:** `AUDIO["sfx_classes"]` + `["sfx_trim_to_entrance"]` +
`["sfx_fade_in_handle"]`; `MODES["longform"]["music_segments"]`;
`AUDIO["music_duck_db"]` (18–20) already brackets the taught ~−20 dB —
corroboration, unchanged; LESSON-018, LESSON-019, LESSON-026. Roadmap:
synthesize riser/hit/drone into `audio/sfx_library` (the pack build is
seeded/deterministic).

## 7. Motion rules on graphics + stills

### 7.1 Eye-trace continuity (EC2 R1, NEW — taught 9:26–9:57 w/ self-demo)
At every hard cut and every full-frame graphic insertion, the incoming
frame's focal point (face, key text, highlighted element) must land near
the outgoing frame's gaze point; violations allowed only as deliberate
flagged jolts (his 10:08 anti-rule). Graphics placement should read the
PREVIOUS shot's focus, not just free space.
**Encoded:** `MOTION["eye_trace"]` (advisory + the planned wiring named:
previous-shot focal xy as a `resolve_offset_v2` input + Audit B WARN);
LESSON-015.

### 7.2 Entrance causality (EC2 R5, GENERALIZED — adjudicates 9:02–9:24 vs
punch instant-pop vs restrained frame-0 pins)
Every graphic entrance needs a cause the viewer can perceive: (a) animated
move-in, (b) instant pop PAIRED with an SFX (shutter/pop) or a hot bed, or
(c) present from frame 0. **A silent unexplained mid-video pop is the only
illegal state.** Lint spec: graphics with inDur=0 must carry an sfx slot or
start at t=0 (longform produced lane).
**Encoded:** `MOTION["entrance_causality"]` (the legal-cause catalog +
lint spec); LESSON-016. Roadmap: the inDur=0 check in `plan_lint_motion`.

### 7.3 Stills vs frozen cards (EC2 R6, SPLIT RULE — adjudicates taught
6:12–6:25 vs MODULE pixel-frozen holds)
Photos/screenshots inserted as b-roll get slow scale/position drift (pro
hold band **0.5–1%/s**) or perspective moves; DESIGNED cards/dioramas stay
**pixel-frozen** and get aliveness from build cadence instead. Never
reintroduce drift on cards.
**Encoded:** `BROLL["still_drift_pct_per_s"]`; LESSON-017. (The aliveness
creep engine already exists for footage; cards stay frozen — unchanged.)

### 7.4 Image-focus operators (EC2 R2, NEW — all six demoed on a real
screenshot, 7:40–8:18)
A still-image b-roll operator set as comp variants: **animate-key-text,
highlight-scribble, darken/blur-surround, hue-shift (SIGNED color
semantics: red=negative, green/yellow=positive), circle/arrow/underline,
subject-glow**. Use on screenshots/photos, not on designed cards.
**Encoded:** `MOTION["image_focus_ops"]` + `MOTION["hue_shift_semantics"]`
(the comp-variant vocabulary); LESSON-017. Comp templates are roadmap.

## 8. Structure + envelope refinements

### 8.1 Bursts attach to montage BEATS, not positions
Example/proof/sell beats carry the cut bursts — intro log-montage **16
state changes/10s**, course-pitch **42 state changes/30s** (the video's
peak). These magnitudes are visual-state/shot-change counts, NOT detector
hard cuts — the deterministic cut detector peaks at **11/10s and 19/30s**
on the same windows (machine cross-check 2026-07-11); any future burst
lint must count STATE EVENTS. Each pitch-montage shot gets a white benefit
label; a stat card ("OVER 101,446 STUDENTS") anchors the proof.
**Refines** PRODUCTION_ENVELOPE_STUDY (front-loaded envelope): the peak is
beat-attached, not position-attached. **Encoded:**
`BROLL["burst"]["longform"]`; LESSON-025. The intro envelope's
`receipt_montage_state_s` (0.8–1.5) is a DIFFERENT device (receipt
montage) and stays unchanged — §10.2.

### 8.2 A-roll islands economy (EC2 R9, CONFIRMED)
Face prominent only **30% of runtime**; 41 a-roll bursts, median 4.5s /
p75 6s; the two longest (12s @4:53, 22s @5:11) carry the CTA/pitch — spend
a-roll on important, confident statements and on the ask; carry
explanation on graphics. Matches his own taught rule (3:31) and our
envelope doctrine. **Encoded:** LESSON-020.

### 8.3 Blur-teased roadmap (EC2 R8, promoted LOW → MEDIUM)
2nd independent sighting (punch H1 + editcraft2 0:10.5: four blurred
pillar labels, revealed one per chapter with column recalls at 0:25.5,
2:29, 8:31, 10:27): open with the video's full roadmap as a curiosity
object with payload labels blurred/withheld, reveal progressively. Pattern
family now MEDIUM cross-creator; his variant stretches the reveal across
the whole video. **Encoded:** doc-only (a comp + brain move; no
deterministic surface yet).

### 8.4 Edit-order curriculum (TAUGHT)
import/organize → chronological story assembly (bottom track = sacred
A-roll) → color+audio enhancement BEFORE any cutting → fluff cut
(pauses/retakes/boring, split+delete-left/right) → b-roll+graphics+effects
in one pass → music+SFX → QA watch-through (recolor b-roll, typo check) →
export.
**Maps onto the pipeline:** enhance-before-cut = our `audioEnhance` runs on
the dialogue bus pre-transitions; fluff cut = `edit/apply_pauses.py
--retakes`; QA watch-through = Audit B + FRAME.IO REVIEW (typo check).
No change needed — corroboration of the stage order.

## 9. THE META-RULE — audience-experience selector (EC2 R12, taught 0:41–2:17)

Editing grammar must match what the audience came for; **disruption of the
expected experience is the #1 retention killer**. The Sam pole (0.65
cuts/min, pauses kept, zero graphics) and the MrBeast pole (~2s cuts) BOTH
win. This is the doctrine behind `target.pace` / `target.treatment`: "use
b-roll as much as possible" and "strip all pauses" apply only to the
stimulation lane; restrained-lane restraint is not under-editing. **Any future
taught-rule conflict gets adjudicated through this selector first.**
**Encoded:** LESSON-021 (contractually binds the authoring brain); it is
the adjudicator used throughout §10.

## 10. Conflicts with our grammar — adjudicated

| # | conflict | adjudication |
|---|---|---|
| 10.1 | EC1 literal-first "conceptual = cinematic self-footage, **never stock**" + R10 "stock = the lazy version" vs the R24 **concept-stock lane** (`graphics_planner_receipts.concept_lane`) | Via R12: the concept-stock lane is a *style-gated* (overlay-rich only), lowest-tier, 1/60s-capped lane — the editcraft/cinematic-education grammar simply never activates it. `BROLL["priority"]` now records the ladder (motion-graphics > purpose-shot > stock) so the brain prefers a HyperFrames comp or graded self-footage before any stock fill. Lane kept, caps unchanged. |
| 10.2 | EC1 montage-burst hold **0.6–0.7s** vs intro envelope `receipt_montage_state_s` **(0.8, 1.5)** | Different devices measured on different corpora: the envelope band is per-receipt holds in the hook's receipt montage; the 0.6–0.7s band is pitch/proof burst shots. Default unchanged; the burst band lives separately in `BROLL["burst"]["longform"]["hold_s"]`. |
| 10.3 | EC1 body is HEAVILY edited (cards ~1/min, b-roll, montage bursts) vs `MODES["longform"]["broll_min_spacing_s"]` comment "front-loaded in the opening only" | Already corrected by the 2026-07-07 whole-video envelope measure (memory: production_envelope). The comment is stale doctrine, the NUMBER (10s spacing) is compatible with ~1 card/min bodies. Number unchanged; doctrine recorded here. |
| 10.4 | EC1 **list cards 8–12s** / comparison cards 9–10.5s vs `MOTION["hold_max_s"]["longform"]`=11.0 / `takeover_max_s`=10.5 | Ceilings KEPT (pinned to the MODULE-measured reference + `tests/test_module_longform.py`). A comparison card (10.5s) fits exactly; a 12s list card is legal in the editcraft grammar only with per-item progressive lands (LL-011) and requires a conscious knob raise — the band is recorded in `BROLL["hold_bands_s"]` so the brain knows the pro range. Not a measured-error correction: two references disagree, the tighter gate stands until an operator style pack asks for the looser one. |
| 10.5 | EC2 R4 music segment architecture vs punch constant bed (6/6 zero-gap) / restrained no bed (3/3) | Mode+pace-scoped: encoded LONGFORM-ONLY (`MODES["longform"]["music_segments"]`); shorts style packs keep their `music` flags. Exactly R12. |
| 10.6 | EC2 R1 eye-trace placement vs current free-space-only placement (`planner/free_space.py` places into the emptiest legal region with no memory of the previous shot) | Additive: advisory `MOTION["eye_trace"]` + LESSON-015 bind the brain now; wiring previous-shot focal xy into `resolve_offset_v2` + an Audit B WARN is the named roadmap. No behavior changed. |
| 10.7 | EC2 R5 entrance causality vs punch instant-pop (≤83ms) and restrained frame-0 pins | Not a conflict — R5 was GENERALIZED to adjudicate them: pop+SFX/hot-bed and frame-0 are both legal causes. Only the silent mid-video pop is illegal (longform produced lane lint spec recorded). |
| 10.8 | EC2 R6 drift-on-stills vs MODULE pixel-frozen holds | SPLIT RULE as given: stills/screenshots drift 0.5–1%/s; designed cards stay pixel-frozen. `BROLL["still_drift_pct_per_s"]` applies to photo b-roll only — the card grammar is untouched. |
| 10.9 | EC1 seam vocabulary (zoom pulls at a-roll↔b-roll seams, flash at graphic seams, ~0.3/min) vs `plan_lint_smooth` WARNing on flash/leak in longform | Compatible: the lint already treats flashes as a WARN-worthy rarity; the measured 0.3/min sits far under `max_per_min` 2.0. `seam_roles` records WHICH seam type each cover is legal at (advisory); lint stays as-is. |
| 10.10 | EC1 tutorial PIP (persistent webcam bubble over screen-share) vs shorts PIP ban (operator-adjudicated 2026-07-10: static face-in-PIP takeover = longform only) | Aligned: the tutorial PIP is a LONGFORM screen-share device, encoded under `MODES["longform"]` only. The shorts ban stands. |

## 11. Encoded-where map

| rule | encoding |
|---|---|
| lane split + camera-hold + churn invariant | `MODES["longform"]["pacing_lanes"]`, `pacing.state_churn_per_min`, LESSON-014 |
| trigger latency, hold bands, burst bands, credit, VO continuity, priority, literal-first, polish, still-drift | `producer_config.BROLL` (+ receipts/illustration lanes now read their hold/gap constants from it), LESSON-012/013/017/025 |
| step/list/comparison/signature/recap cards | `BROLL["hold_bands_s"]`, LL-011 row-lands law (already ERROR-gated), LESSON-023/026 |
| tutorial PIP, screen-rec punch-in | `MODES["longform"]["tutorial_pip"]`, LESSON-014 |
| keyword pills / caption format split | `MODES["longform"]["emphasis_pills"]` (R11) |
| SFX classes + honesty gate, music segments | `AUDIO["sfx_classes"]`, `MODES["longform"]["music_segments"]`, LESSON-018/019 |
| eye-trace, entrance causality, image-focus ops | `MOTION["eye_trace"]`, `MOTION["entrance_causality"]`, `MOTION["image_focus_ops"]`, LESSON-015/016 |
| a-roll islands, edit order, acquisition loop | LESSON-020/025 (+ pipeline stage order already matches) |
| R12 meta-rule | LESSON-021 — the standing conflict adjudicator |
