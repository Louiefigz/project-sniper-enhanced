# EDITCRAFT LESSONS — Sniper's long-form editing-craft doctrine

Status: Sniper-authored design doctrine, rewritten for rc4 (2026-09-18). Pinned into
every Auto Edit doctrine snapshot. It is the rationale for the long-form b-roll,
seam, audio and motion-continuity parameters in `scripts/producer/producer_config.py`
and for Brain lessons LESSON-012 … LESSON-026 in
`scripts/producer/docs/findings/FAILURE_LEDGER.md`. (The file keeps its historical
name; its content is Sniper's own.)

How to read this document:

- Section numbers (§1 … §11 and their subsections) are identifiers cited by code
  comments and ledger lessons. Keep them stable.
- Every number is a **Sniper design parameter**: a configurable default with a stated
  reason. None is a measurement of a third-party video. Where public standards inform
  a value (accessibility contrast, loudness, audio/video synchronisation), the
  standard is named.
- Each section ends with **Encoded as**, naming the config key, lint rule or lesson
  that carries the rule into the product.
- Four mechanisms that protect continuity across a seam or inside a still are grouped
  as the **continuity mechanisms CM-1 … CM-4** (zoom-pull seams, J-cut leads,
  image-focus operators, eye-trace). §11 maps them.

The single principle behind this document: **every edit decision should be explicable
from the viewer's side** — what they were looking at, what they were hearing, and what
they needed next. A rule that cannot be explained that way does not belong here.

---

## §1 Two footage lanes and the churn invariant

### §1.1 Presenter footage and screen-share footage are different grammars

On **presenter footage** the information is the person: face, voice, gesture. An
unchanging frame of a talking person is easy to stop watching, so some visual element
should change every few seconds — a cut, a punch, a card, a b-roll insert. Sniper's
advisory rhythm for the presenter lane is about **15.6 shot or state changes per
minute** (one every ~3.8 s), of which only about **5.8 per minute** are hard cuts; the
rest are graphics, inserts and scale changes, and about **39 %** of changes are
cutaways away from the presenter.

On **screen-share footage** the information is the moving interface. Every cut away
from the screen destroys the viewer's spatial model of where things are, so the lane
runs at about **0.6 cuts per minute** and keeps attention with other layers: the
cursor, a persistent presenter PIP, the application's own sound, and sparse keyword
pills. A long hold with **no cut at all** is legal on this lane — up to **157 s** —
but only while at least one of those layers keeps changing. The same hold on presenter
footage is never legal.

These values are advisory defaults the brain reads; the pacing lint does not yet
switch its ceilings by lane. The decimals are kept because consumers read them; they
express a design intent (presenter: a change every few seconds, mostly not cuts;
screen: almost no cuts), not a measurement.

**Encoded as** `MODES.longform.pacing_lanes`; LESSON-014.

### §1.2 The churn invariant: some layer always moves, cuts need not

Produced content keeps **some visual layer** changing at roughly **45-90 events per
minute** — captions, card builds, module lands, pills, cuts, inserts all count — while
hard cuts may stay far lower. Rationale: the eye needs something new about once a
second to stay engaged, but that novelty can live in any layer. Forcing the *cut*
count up to reach an energy target produces choppy edits; choosing *which* layer
churns is a style decision (captions in a restrained Short, card builds in long-form,
cursor and pills on screen-share).

Scope: the band describes presenter and produced zones. Screen-share-heavy videos
legitimately run below it; never flag them against it. A future lint that enforces the
band must scope it by visual-state zone.

**Encoded as** `MODES.longform.pacing.state_churn_per_min = (45.0, 90.0)` (advisory).

---

## §2 The b-roll lane

### §2.1 Trigger → insert latency

An insert that illustrates a phrase lands **0 to 1.5 s after the start of the phrase
that names it**. The anchor is the **first word of the naming phrase**, so an insert may
lead the phrase's head noun while still trailing the trigger. Before the phrase, the
image is a riddle; much later than 1.5 s, the viewer has moved on to the next idea and
no longer binds the image to the words. The receipts lane lands its inserts exactly on
the word (latency 0, inside the band).

Timing claims about any reference or render are **read from word timings**, never
recalled: a latency quoted in a document or comment comes from a word-lock pass or a
word-timed caption file (LL-013, LESSON-027).

**Encoded as** `BROLL["trigger_latency_s"] = (0.0, 1.5)`; LESSON-025.

### §2.2 Literal first

When the speech names a specific person, tool, product or site, show **that thing**:
the product's interface, the site scrolling, the object on the desk. Conceptual b-roll
(an image standing for an idea) is reserved for emotional beats — regret, boredom,
effort — and is staged as graded footage of the speaker's own world, not generic
stock. Rationale: a literal image confirms the words; a metaphor asks the viewer to
decode, and decoding competes with listening.

**Encoded as** `BROLL["literal_first"] = True`,
`BROLL["conceptual_only_for"] = ("emotional",)`; LESSON-012.

### §2.3 Priority ladder

Choose b-roll by **explanatory density**, in this order: Sniper motion graphics that
show structure; a purpose-shot insert of the real thing; stock footage last. When the
thing being explained can be demonstrated on a real on-screen artifact (the actual
document, dashboard or product), the demonstration outranks any illustration of it.

**Encoded as** `BROLL["priority"] = ("motion-graphics", "purpose-shot", "stock")`;
LESSON-012.

### §2.4 Hold bands by insert kind

The brain picks an insert's hold from its kind. Each band is set by how long the
viewer needs to *recognise* (a face or object) or *read* (a card) what is shown:

| Kind (config key) | Hold | Reason |
|---|---|---|
| `referenced-creator` — footage of a person the speaker names | 1.5-2.5 s | recognition of a face is fast; longer turns a reference into a segment about them |
| `literal-object` — the product, site or thing named | 2.0-4.0 s | recognise, then see one detail |
| `montage-burst` — one shot inside a burst | 0.6-0.7 s | a burst is read as a group, not shot by shot (§2.9) |
| `comparison-card` | 9.0-10.5 s | long enough to hear the comparison and see it twice |
| `list-card` | 8.0-12.0 s | one item per spoken item; bounded by the card ceiling (§10.4) |
| `step-card` — a section boundary card | 2.0-3.0 s | a signpost, not content (§3) |
| `diagram-card` | 2.5-8.5 s | scales with the number of parts |

The planner-lane constants that the receipts and illustration lanes read (receipt hold
2.5 s, same-artifact dedup 30 s, concept hold 2.5 s at most once per 60 s,
illustration hold 2.5 s at most once per 30 s) are documented with their rules in
`REFERENCE_STYLE_STUDY.md` R17 and R24.

**Encoded as** `BROLL["hold_bands_s"]`; card kinds also respect
`MOTION["hold_max_s"]`.

### §2.5 Voice continuity

The presenter's speech **never stops under an insert**. Every b-roll insert is
video-only; audio embedded in borrowed clips is muted. The single exception is a
demonstration whose own sound *is* the point (a product playing its audio), and then
only for the demonstration's length. Rationale: the voice is the thread the viewer
follows through the video; an insert that interrupts it turns an illustration into an
interruption.

**Encoded as** `BROLL["vo_continuity"] = True`,
`BROLL["demo_audio_exception"] = "playthrough"`; `broll/broll_insert.py` composites
video-only; LESSON-013.

### §2.6 Credit label for footage Sniper did not shoot

When an insert uses footage the operator did not shoot (and has the right to use), a
small credit label sits in the **lower-left corner for the insert's full duration**.
Rationale: attribution that appears only briefly is not attribution; the lower-left
corner is outside the caption band and the right-hand platform controls.

**Encoded as** `BROLL["credit_label"] = {"corner": "lower-left", "template":
"CREDIT: {name}", "full_duration": True}` (the comp and plan field are roadmap; the
lesson binds the brain now); LESSON-013.

### §2.7 Seam roles and zoom-pull seams (CM-1)

Most inserts enter and leave on a **plain hard cut**. A seam cover is a marker of a
change of *kind* of footage, not decoration, so each cover kind is legal only at its
seam type:

- **zoom-pull** at seams between presenter footage and b-roll (`aroll<->broll`);
- **flash / light-leak** at seams between a full-frame graphic and presenter footage
  (`graphic<->aroll`).

Covers are rare: the long-form advisory rate is about **0.34 per minute** (roughly one
every three minutes), always under the hard ceiling of `MOTION["transitions"]["max_per_min"]`.

**CM-1 — zoom-pull seams.** An eased digital zoom bridges or resolves an
a-roll/b-roll seam. Three variants, each with a default and an allowed band (all
Sniper design parameters, deliberately configurable):

| Variant | Shape | Defaults (band) |
|---|---|---|
| `punch-cut` | an eased punch-in on the outgoing shot that **completes before** the cut; the cut itself is covered by a light-leak or flash, sequentially | scale 1.205 (1.10-1.25), attack 0.33 s (0.25-0.42), completes 0.9 s before the cut (0.6-1.3), cover `light-leak` |
| `whip` | an accelerating zoom that spans the cut, blur-masked at its peak, then an eased settle on the incoming shot | peak 1.9 (1.5-2.0), ramp 1.0 s (0.7-1.4), settle to 1.195 (1.10-1.25) over 0.6 s (0.4-0.8), blur σ 12 within ±0.12 s of the seam |
| `settle` | the incoming shot eases out from a slight zoom just after the cut — a soft landing | from 1.08 (1.05-1.12) over 0.4 s (0.3-0.55), starting 0.1 s after the cut (≤ 0.55 s) |

Rationale: the punch-cut's zoom and cover are sequential because two simultaneous
events at one seam read as one confused event; the whip's blur hides the frame where
the scale is largest so the viewer never sees a soft upscale; the settle is small
(under 12 %) because it is a landing, not an emphasis. Only feature-tracked scale
evidence may propose a zoom-pull during study; a face-width change alone can be a
lean, not a zoom. Zoom-pulls are long-form only and count against the seam budget.

**Encoded as** `MOTION["transitions"]["seam_roles"]`,
`MOTION["transitions"]["longform_events_per_min"] = 0.34`,
`MOTION["transitions"]["zoom_pull"]`; executed by `motion/zoom_pull.py` through
`motion/transitions.py`; stock transitions banned (LL-014, LESSON-028).

### §2.8 Insert polish and grade inheritance

Every insert gets the presenter footage's grade and, when handheld, stabilisation, and
uses the video's one motion vocabulary. Rationale: an insert that looks like it came
from a different production reads as borrowed even when it is not; matching polish
makes the insert part of the argument.

**Encoded as** `BROLL["insert_polish"] = {"grade_matches_aroll": True,
"stabilize_handheld": True}`; LESSON-013.

### §2.9 Bursts attach to beats, not to positions

A **burst** — several short inserts in quick succession — belongs to a beat whose
content is itself a group: examples, proof, a list of results, the offer. Each shot in
an offer montage carries a short benefit label. Bursts are never scheduled by timeline
position ("something every N seconds"). Burst magnitudes are counted as **visual state
events** (cuts, graphics, inserts, panel changes), never as detector hard cuts alone.

| Mode | Burst parameters |
|---|---|
| short | at most 3 inserts in a 4 s window, holds 0.6-1.3 s |
| long-form | intro montage up to 16 state events per 10 s; offer / call-to-action montage up to 42 state events per 30 s; detector-cut ceilings 11 per 10 s and 19 per 30 s; holds 0.6-0.7 s |

Rationale: a group of examples shown as a group is understood as "there are many";
the same shots spread through the video are just more inserts. The ceilings bound how
fast a burst may run before individual shots stop registering at all.

**Encoded as** `BROLL["burst"]`; the lone-insert cadence
`MODES[*]["broll_min_spacing_s"]` still governs single inserts (§10.3,
`SHORTFORM_LESSONS.md` §9.2); LESSON-025.

---

## §3 Section architecture: step cards, signature cards, recaps

- **Every section boundary earns a step card**: a short card (2-3 s hold, §2.4) naming
  the new section, with a riser-to-hit sound (§6.1) and, in long-form with music, a new
  music segment (§6.2). Rationale: long-form viewers navigate by sections; a boundary
  that is not marked is a boundary the viewer misses.
- **Signature concept cards are reusable.** When a concept is central enough to be
  named more than once, build one card for it and **replay the same card** on each
  re-mention. Recognition is faster than reading, and repetition of the same visual
  ties the mentions together.
- **A long explanatory section may close with a recap card** (2-3 s): the presenter in
  a small bubble plus a pill title of what the section established, before the next
  step card. Rationale: a recap consolidates before the viewer is asked to hold a new
  topic.

**Encoded as** LESSON-026; step-card hold `BROLL["hold_bands_s"]["step-card"]`.

---

## §4 The screen-share lane

Screen-share grammar (§1.1) in practice:

- **Never show a full bare desktop** at delivery size — punch or crop into the active
  interface region the narration is about. Interface text at desktop scale is
  unreadable on a phone.
- The **cursor is the pointer**; keep it visible and do not cut while it travels.
- Keep the **application's own sound** when it demonstrates something; otherwise
  voice continuity (§2.5) applies.
- **Keyword pills** (§5) carry emphasis; captions remain the SRT sidecar.

**Encoded as** LESSON-014; `MODULE_CARDS.md` §3.

### §4.1 The walkthrough presenter PIP

During a screen walkthrough that goes into depth, composite a circular presenter PIP
of about **11 % of frame width** in the **bottom-right corner**, placed over the least
important region (typically timeline or status areas) and **never over the content
being discussed**. Introduce it when the explanation deepens; leave it out for quick
fly-throughs. Rationale: the face restores the human thread during long screen
stretches, and 11 % is large enough to read expression while small enough to cover
only chrome. Long-form only; the ban on presenter PIPs in shorts stands.

**Encoded as** `MODES.longform.tutorial_pip = {"width_frac": 0.11, "corner":
"bottom-right", "avoid": "content-zone", "introduce_on": "depth-increase"}` (the key
keeps its historical name).

---

## §5 Keyword pills, not captions

The long-form emphasis layer is **sparse**: a small centred pill echoing the exact key
phrase, typically up to **three words**, about **one every four minutes**
(0.25 per minute), and only where the precise words matter (a name to remember, a
term being defined, a number to write down). It is never a verbatim caption stream —
the SRT sidecar remains the caption track. "Three words" is typical, not a cap: a
longer phrase is legal when the exact wording is the point. Rationale: emphasis works
by contrast; frequent emphasis is no emphasis.

**Encoded as** `MODES.longform.emphasis_pills = {"per_min": 0.25, "words_typical": 3}`.

---

## §6 Audio craft

### §6.1 Sound effects: a mechanical layer and an emotional layer

Sound effects fall into two layers:

- **Mechanical** — `whoosh`, `click`, `pop`: the sound of something moving or
  appearing on screen (a whoosh under a motion, a click under a highlight).
- **Emotional** — `riser`, `hit`, `drone`, mapped to beat types at plan time: a
  **riser** builds tension before a payoff; a **hit** lands the payoff or a section
  arrival (every new section gets riser → hit); a **drone** carries a dark or
  suspenseful mood.

**The riser honesty gate:** a riser is legal **only when a real payoff follows**.
Tension without release teaches the viewer that the sound means nothing. A riser → hit
chain is legal.

Every effect is **trimmed to the entrance it accompanies** and given a short
**fade-in handle** so its attack is not a click. Rationale: an effect longer than its
motion is heard as a separate event.

**Encoded as** `AUDIO["sfx_classes"]`, `AUDIO["sfx_trim_to_entrance"]`,
`AUDIO["sfx_fade_in_handle"]`; `audio/sfx_library` ships the mechanical layer;
LESSON-018.

### §6.2 Music as segment architecture (long-form)

In long-form, music follows the structure: split by subject change, **one mood per
segment**, a **new track per chapter** entering on the section card's riser and hit. A
**music stop** is a deliberate jolt reserved for a major pivot; a **slow fade-out**
closes a segment; the bed **drops or ducks under the offer or call to action** so the
ask is heard clearly. The bed sits about **20 dB under the voice**, inside Sniper's duck
band of 18-20 dB. Rationale: at that level music is felt as atmosphere and does not
compete with speech intelligibility. Short-form style packs keep their own music rules
(a constant bed for punch, none for restrained).

**Encoded as** `MODES.longform.music_segments` (`bed_under_voice_db = 20.0`),
`AUDIO["music_duck_db"] = (18.0, 20.0)`, `AUDIO["music_gap_db"]`; `audio/audio_mix.py`
executes the bed; LESSON-019.

### §6.3 J-cut leads (CM-2)

The default seam is a **late-in-pause** cut: picture changes shortly before the next
word, with no audio lead (the edit brain picks those boundaries). About one seam in
five may carry a true **J-cut**: the incoming segment's audio starts **before** its
picture. Sniper's default lead is **80 ms**, with a preferred band of **65-95 ms** and a
hard maximum of **300 ms**; the outgoing part must keep at least **0.1 s** of its own
audio.

Rationale: a short audio lead makes a cut feel pulled forward by the speech rather
than imposed on it. The preferred band sits close to the audio-before-video
acceptability limit published in ITU-R BT.1359 (about 90 ms), so a lead in the band
reads as momentum rather than a sync error; beyond about 300 ms the lead is heard as
two sentences overlapping. Leads outside the band WARN; beyond the maximum they ERROR.
The lead is baked into the **outgoing** part's audio tail so every part keeps audio
length equal to video length and A/V sync is never shifted.

**Encoded as** `AUDIO["jcut"] = {"lead_default_ms": 80, "lead_band_ms": (65, 95),
"lead_max_ms": 300, "prev_min_residual_s": 0.1}`; `cutTrack[i].audioLeadMs`;
`compile_timeline.parse_audio_lead` (validator shared by lint and `cut_speed.py`).

---

## §7 Motion continuity

### §7.1 Eye-trace (CM-4)

At a hard cut or a full-frame graphic entrance, the viewer's eyes are still where the
previous shot put them. Land the incoming focal point — a face, the key text, the
highlighted element — **near the outgoing gaze point** when there is a free choice.
When placing a graphic, read the **previous** shot's focus, not only the free space. A
deliberate jolt is legal but must be flagged in the plan (`deliberateJolt`).

This is a **tie-breaker**, never a rule that overrides legibility or fit: designed
anchors, emptiness and safe margins win first. Sniper applies it as a small additive
bias on the placement score (**0.05**, against region scores that typically range
0.1-0.5) and as an **advisory** Audit B warning when a landed graphic's centre is more
than **0.45** normalised screen units from the gaze point.

**Encoded as** `MOTION["eye_trace"] = {"audit": "warn", "jolt_flag_key":
"deliberateJolt", "bias_weight": 0.05, "warn_dist_frac": 0.45}`;
`planner/eye_trace.py`, `planner/graphics_anchors.resolve_offset_v2`,
`audit/audit_motion.check_eye_trace`; LESSON-015.

### §7.2 Entrance causality

Every graphic entrance needs a **cause the viewer can perceive**: an animated move-in,
an instant pop **paired** with a sound effect or an energetic music bed, or presence
from frame 0. A silent, unexplained pop in the middle of a video is the only illegal
state — it reads as a rendering glitch. This one rule reconciles styles that look
opposite: restrained Shorts pin their graphic from frame 0, punch Shorts pop with sound,
long-form cards build in.

**Encoded as** `MOTION["entrance_causality"] = {"legal": ("move-in", "pop+sfx",
"frame0")}` (lint roadmap: `inDur = 0` needs an SFX slot or t = 0); LESSON-016.

### §7.3 Stills drift, cards do not

Movement is split by asset class. **Photos and screenshots** inserted as b-roll get a
slow scale or position drift of about **0.5-1 % per second**, or an image-focus operator
(§7.4). **Designed cards stay pixel-still**; their aliveness comes from their build
cadence (module lands), never from drift. Rationale: a still photo held without motion
reads as a frozen frame; a designed card that drifts makes its text harder to read and
looks like a mistake.

**Encoded as** `BROLL["still_drift_pct_per_s"] = (0.5, 1.0)`; LESSON-017.

### §7.4 Image-focus operators (CM-3)

A still screenshot or photo can direct attention to one region without a cut. The
operator vocabulary has six named operations — animate the key text, highlight
scribble, darken the surround, signed hue shift, circle / arrow / underline, subject
glow — of which four are executable today:

| Operator | What it does | Defaults (band) |
|---|---|---|
| `highlight` | a translucent marker-colour box wipes left to right over the region | alpha 0.4, wipe 0.4 s (0.3-0.7) |
| `darken-surround` | everything outside the region drops to 75 % luma, applied within one frame | hold 0.8-2.5 s |
| `blur-surround` | everything outside the region blurs (σ 8), no dimming | — |
| `hue-shift-signed` | a full-frame colour wash whose sign carries meaning | mix 0.65, ramp 0.233 s, hold 0.8-4.5 s |

**Signed colour semantics:** red for a negative reading, green (after a brief yellow
of about 1 s) for a positive one. Rationale: the colour lands the evaluation before the
viewer has parsed the numbers; the yellow step keeps a positive wash from reading as a
warning.

These operators apply to screenshots and photos only — never to designed cards (§7.3)
— and belong to the produced graphics stack: a treatment with its graphics lane off may
not carry them.

**Encoded as** `MOTION["image_focus_ops"]`, `MOTION["hue_shift_semantics"]`,
`MOTION["focus_ops"]`; executed by `broll/focus_ops.py` on `brollTrack[].focusOps`;
validated by the same parser in `plan_lint_broll.check_focus_ops`; LL-017; LESSON-017.

---

## §8 Production and presence

### §8.1 Plan the b-roll, then shoot it in one batch

Freeze the story at rough cut, write the **complete shot list** from the kept
transcript (every literal-first insert, every burst beat, every demonstration), and
capture it in one session. Then place each insert within the latency band (§2.1),
starting the cutaway on the action frame, and attach bursts to example, proof and offer
beats (§2.9). Rationale: b-roll captured before the cut is locked illustrates a story
that no longer exists; b-roll captured piecemeal does not match itself.

**Encoded as** LESSON-025.

### §8.2 A-roll islands

Spend presenter face time on **confident statements and the ask**; carry explanation
on graphics and inserts. Presenter islands between inserts are typically a few seconds
long, and the longest ones belong to the call to action. In a produced explanatory
long-form it is on-style for the presenter to be the dominant picture for only around a
third of the runtime. Rationale: the face persuades, the graphic explains; using the
face to explain a process wastes both.

**Encoded as** LESSON-020.

---

## §9 The audience-experience meta-rule

When two craft rules conflict, adjudicate **first** by what the audience came for. The
grammar must match the experience the viewer expects from this video; breaking that
expectation costs more attention than any single craft improvement gains.
Stimulation rules ("use b-roll as much as possible", "remove every pause") never bleed
into the restraint poles, and **restraint is not under-editing**: a restrained edit is
exactly as deliberate, just in fewer layers.

**Encoded as** `target.pace` / `target.treatment` selection; LESSON-021.

---

## §10 Conflict table

| ID | Conflict | Adjudication |
|---|---|---|
| §10.1 | Stimulation rules versus restraint poles | §9 decides: the operator's pace and treatment win; stimulation defaults never apply inside `restrained` or `clean-cut` |
| §10.2 | Burst (§2.9) versus the intro receipt montage | Different devices. The intro envelope's receipt montage holds each receipt 0.8-1.5 s (`MODES.longform.pacing.receipt_montage_state_s`) and is unchanged; a burst is a beat-attached group with its own ceilings |
| §10.3 | "B-roll only in the intro" versus b-roll in the body | The body carries b-roll too. Lone inserts keep the long-form cadence (`broll_min_spacing_s = 10.0`); bursts are the beat-attached exception |
| §10.4 | `list-card` hold band (up to 12 s) versus the long-form card hold ceiling (11 s) | **The ceiling stands.** Card kinds are capped by `MOTION["hold_max_s"]["longform"] = 11.0`; a list that needs longer is split or moved to a rail with per-row lands |

---

## §11 Encoded-where map

| Rule | Config / code | Lesson |
|---|---|---|
| §1.1 lane split | `MODES.longform.pacing_lanes` | LESSON-014 |
| §1.2 churn invariant | `MODES.longform.pacing.state_churn_per_min` | — |
| §2.1 latency | `BROLL["trigger_latency_s"]`; receipts lane | LESSON-025, LESSON-027 |
| §2.2-§2.3 literal first, priority | `BROLL["literal_first"]`, `["conceptual_only_for"]`, `["priority"]` | LESSON-012 |
| §2.4 holds | `BROLL["hold_bands_s"]`, `MOTION["hold_max_s"]` | — |
| §2.5-§2.6, §2.8 voice, credit, polish | `BROLL["vo_continuity"]`, `["credit_label"]`, `["insert_polish"]` | LESSON-013 |
| §2.7 seam roles | `MOTION["transitions"]["seam_roles"]`, `["longform_events_per_min"]` | LESSON-028 |
| §2.9 bursts | `BROLL["burst"]` | LESSON-025 |
| §3 sections | step-card hold band | LESSON-026 |
| §4.1 walkthrough PIP | `MODES.longform.tutorial_pip` | LESSON-014 |
| §5 pills | `MODES.longform.emphasis_pills` | — |
| §6.1 SFX | `AUDIO["sfx_classes"]`, `["sfx_trim_to_entrance"]`, `["sfx_fade_in_handle"]` | LESSON-018 |
| §6.2 music | `MODES.longform.music_segments`, `AUDIO["music_duck_db"]` | LESSON-019 |
| §7.1 eye-trace | `MOTION["eye_trace"]` | LESSON-015 |
| §7.2 entrances | `MOTION["entrance_causality"]` | LESSON-016 |
| §7.3 stills vs cards | `BROLL["still_drift_pct_per_s"]` | LESSON-017 |
| §7.4 focus operators | `MOTION["image_focus_ops"]`, `["hue_shift_semantics"]`, `["focus_ops"]` | LESSON-017 |
| §8.1 plan-then-batch | — | LESSON-025 |
| §8.2 A-roll islands | — | LESSON-020 |
| §9 meta-rule | `target.pace`, `target.treatment` | LESSON-021 |

### The continuity mechanisms

| ID | Mechanism | Section | Config | Executor | Tests |
|---|---|---|---|---|---|
| CM-1 | zoom-pull seams | §2.7 | `MOTION["transitions"]["zoom_pull"]` | `motion/zoom_pull.py` via `motion/transitions.py` | `tests/test_zoom_pull.py` |
| CM-2 | J-cut leads | §6.3 | `AUDIO["jcut"]` | `cut_speed.py`, `compile_timeline.parse_audio_lead` | `tests/test_jcut.py` |
| CM-3 | image-focus operators | §7.4 | `MOTION["focus_ops"]` | `broll/focus_ops.py` via `broll/broll_insert.py` | `tests/test_focus_ops.py` |
| CM-4 | eye-trace | §7.1 | `MOTION["eye_trace"]` | `planner/eye_trace.py`, `audit/audit_motion.py` | `tests/test_eye_trace.py` |
