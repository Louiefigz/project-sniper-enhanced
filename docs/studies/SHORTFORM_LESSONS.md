# SHORTFORM LESSONS — Sniper's produced-Short doctrine (hook, captions, bursts, the client-reel pace)

Status: Sniper-authored design doctrine, rewritten for rc4 (2026-09-18). Pinned into
every Auto Edit doctrine snapshot. It is the rationale for `MODES.short.hook_stack`,
`MODES.short.pacing_client_reel`, `BROLL["burst"]["short"]` and
`AUDIO["riser_bridge_s"]` in `scripts/producer/producer_config.py`, for the pace ID
`client-reel` (`src/lib/producer/intent-presets.ts`), and for Brain lessons
LESSON-022 … LESSON-024.

How to read this document:

- Section numbers are identifiers; code and ledger lessons cite them.
- Every number is a **Sniper design parameter** with a stated reason; none is a
  measurement of a third-party video.
- The three style documents (restrained, punch, slideware) own their own grammars.
  This document holds what is common to produced Shorts plus the **client-reel** pace,
  and it says explicitly where a rule is scoped to one pace. When rules conflict, the
  audience-experience rule in `EDITCRAFT_LESSONS.md` §9 decides first.

---

## §1 The hook zone

The first ~3 seconds of a Short decide whether the rest is watched. Everything in the
hook zone serves one job: **state the promise so it can be read and heard at once**.

### §1.1 The hook stack

The hook zone is `0 … 3.0 s` (`hook_stack.zone_s`, equal to the Short's
`hook_window_s`). It stacks, in order of importance:

1. a **designed text lockup** carrying the promise (§1.2) — the invariant across every
   produced style;
2. the spoken hook in **one continuous shot** (§1.3);
3. optionally, for the client-reel pole only, a **zoom-out reveal** (§1.4) and a
   **riser bridge** (§1.6).

Auto-captions are **removed under the hook**; the lockup shows instead, and captions
start at the first body word (§2.2).

**Encoded as** `MODES.short.hook_stack` (advisory; the brain reads it when authoring a
produced Short's hook).

### §1.2 The two-tier lockup

The lockup is **two tiers**: a plain line in the primary text style plus the payload
word or phrase in the accent style. Each line is **5-7 % of frame height** (roughly
96-134 px on a 1920-px canvas), placed in the chest band, **never covering the face**.
The accent colour is a skin choice made by the style; the two-tier structure is the
rule. Rationale: at 5-7 % of height a line is readable at phone size in the fraction of
a second a scrolling viewer gives it; the tier split tells the viewer which word is the
promise.

**Encoded as** `hook_stack.lockup = "two-tier"`,
`hook_stack.lockup_line_h_frac = (0.05, 0.07)`.

### §1.3 The hook is one shot

Do not cut inside the hook. The hook's energy comes from the promise and the staged
text (§1.5), not from cut density. Rationale: a cut in the first seconds forces the
viewer to re-find the speaker's face at the moment they are deciding whether to stay.

**Encoded as** `pacing_client_reel.hook_cuts = 0` (client-reel); style documents own
their own hook rules.

### §1.4 The zoom-out reveal (client-reel only)

The client-reel pole may open on a slight zoom that eases **out** to the full frame:
from **1.34×** (never above **1.5×**) over **60 frames** with an out-cubic ease. **Frame
zero must never look visibly over-zoomed**: a first frame that is obviously cropped
into softness reads as a mistake before the reveal can read as a reveal. The zoom is
applied to the whole composed frame (a layer above footage and text), so the lockup
rides the reveal with the picture instead of sliding against it.

**Encoded as** `hook_stack.zoom_out = {"scale_from": 1.34, "scale_from_max": 1.5,
"dur_frames": 60, "ease": "out-cubic"}`; LESSON-024.

### §1.5 Word staging

Hook text arrives in **word groups at speech cadence**: each group appears as the
speaker says it. Rationale: staged text reads with the voice instead of ahead of it,
so the viewer hears and sees the same word.

### §1.6 The riser bridge

An optional riser of about **1.2 s** plays under the end of the hook and **ends exactly
where the body starts**, with its level pulled well below the voice. Rationale: it
signals "the promise is about to be paid" and makes the hook-to-body boundary feel
intentional. It is subject to the riser honesty gate (`EDITCRAFT_LESSONS.md` §6.1): only
when a real payoff follows.

**Encoded as** `AUDIO["riser_bridge_s"] = 1.2`, `hook_stack.riser_s = 1.2`.

---

## §2 Captions

### §2.1 Captions come from kept words

Burned captions are derived from the **kept transcript words** and their timings; the
brain never writes caption text. Corrections fix transcription errors only
(`captions.corrections`, `CAPTION_AUTO_CORRECTIONS`) and never change what was said.

**Encoded as** `CAPTIONS`, `captions/caption_corrections.py`.

### §2.2 No captions under designed text

Captions are generated **last**, and every cue that overlaps a designed text moment is
removed: the hook zone shows the lockup instead of captions, and no frame ever shows
captions together with a shout lockup or card text. Rationale: two text layers saying
the same thing at once halve the reading time for both.

**Encoded as** `hook_stack.captions_in_hook = False`; LESSON-022.

### §2.3 Placement

Captions sit in the lower band inside the universal safe box (`SAFE_BOX`,
`CAPTIONS["y_band"]`), dropping lower when the mid-frame is occupied by the body
(`FREE_SPACE["caption_low_band"]`).

### §2.4 Earned emphasis

Accent colour or a styled treatment is **earned per word**. Only payload words the
viewer should remember get it — typically the place or subject, the outcome and the
call-to-action verb — about **three accent words per 30 s**, and at most **one accent
keyword per list-card title**. Everything else stays in the base caption style.
Rationale: emphasis works by contrast; a caption track in which every third word is
coloured has no emphasis.

**Encoded as** `pacing_client_reel.accent_words_per_30s = 3`; LESSON-023.

### §2.5 Caption pace

At most 10 words per second on screen (`CAPTIONS["words_per_sec_max"]`), with blocks
held long enough to read (`CAPTIONS["block_s"]`).

### §2.6 Case and punctuation

Captions keep the speaker's words; casing follows the chosen style (sentence case for
the whisper layer). Brand and product casing is fixed by the correction map.

### §2.7 Line breaks

Break captions at phrase boundaries (`CAPTIONS["gap_split_s"]`), never inside a name or
a number.

### §2.8 One reading target per moment

At any frame the viewer has one primary thing to read: the lockup, a card, or the
caption. When a card is up, captions yield (§2.2).

### §2.9 Caption style follows the pace

`karaoke` is the default produced-Short style; `whisper` is the punch pace's small
verbatim layer; `minimal` is the word-at-a-time style (`REFERENCE_STYLE_STUDY.md` R1-R2).
The client-reel pace uses a quiet verbatim layer so that the three accent words (§2.4)
stand out.

**Encoded as** `CAPTION_STYLES`, `MODES.short.captions_style`.

---

## §3 Cut grammar in Shorts

- A cut is either an **eraser** (removes a flub, a pause, a false start) or an **energy
  beat** (a reframe on emphasis). Know which one each cut is.
- In Shorts, a reframe usually rides the cut (`REFERENCE_STYLE_STUDY.md` R13: zoom is the
  cut), balanced between tighter and wider so the video does not creep in.
- The hook is one shot (§1.3); cutaways land on their trigger words
  (`EDITCRAFT_LESSONS.md` §2.1).

---

## §4 B-roll in Shorts: lone inserts and bursts

A lone insert lasts 1-2 s (at most 5 s) and lone inserts are spaced at least 8 s apart.
A **burst** — up to **three inserts within 4 s**, each held **0.6-1.3 s** — is the
exception, and it belongs to a beat whose content is a group (examples, proof, a
process shown in steps). Rationale: three quick shots read as "look how much"; the same
shots spread out read as filler.

**Encoded as** `MODES.short.broll_min_spacing_s = 8.0`, `broll_insert_s = (1.0, 2.0)`,
`broll_insert_max_s = 5.0`, `BROLL["burst"]["short"] = {"max_inserts": 3,
"window_s": 4.0, "hold_s": (0.6, 1.3)}`.

---

## §5 One energy peak per Short

A produced Short has **one** energy peak: a single overlay burst plus a riser, landing
**exactly on the resolution of the hook's promise** — the moment the viewer gets what
they were promised. Never put an energy device on every cut. Rationale: a peak is
defined by contrast with what surrounds it; several peaks are a plateau.

**Encoded as** `pacing_client_reel.energy_peaks_max = 1`,
`overlay_bursts_per_30s = 1`; LESSON-024.

---

## §6 Audio hygiene

- The voice never stops under an insert (`EDITCRAFT_LESSONS.md` §2.5).
- Masters target −14 LUFS integrated with a −1.5 dBTP ceiling (`AUDIO`).
- In the client-reel pace, music is **not baked into the master**: the bed is chosen at
  posting time on the platform, so the master carries voice and designed sound effects
  only.

**Encoded as** `pacing_client_reel.music = False`.

---

## §7 Endings

A produced Short ends so that it can loop: the last line resolves the hook and the
call to action lives in the caption text, not in a closing card (`MODES.short.ending_loop`).

---

## §8 The third pace: `client-reel`

Sniper's Short paces span a restraint pole (`restrained`: almost no cuts, captions carry
the tempo) and a stimulation pole (`punch`: frequent visible cuts and lockups). The
`client-reel` pace is a third, **promotional** pole for produced reels about a service or
result: one continuous hook shot, a proof montage in the body, and a small, fixed
motion budget spent deliberately. Each key of its profile:

| Key | Value | Rationale |
|---|---|---|
| `min_changes_per_min` | 8.0 | the body's proof montage carries the change rate; the floor sits below it so a quieter body is a WARN, not a wall |
| `max_still_gap_s` | 10.0 | the hook may hold one shot for several seconds under text; the body never rests longer than the montage spacing |
| `hook_front_load` | 1.3 | hook density lives in the staged text (§1.5), not in cuts |
| `state_changes_per_min` | 90.0 (advisory) | a quiet verbatim caption layer churns about every 0.7 s even when the picture holds |
| `music` | False | the bed is chosen at posting time (§6) |
| `target_duration_s` | 30.0 | a reel of about 30 s, usually shorter |
| `hook_cuts` | 0 | the hook is one shot (§1.3) |
| `energy_peaks_max` | 1 | one peak on the promise's resolution (§5) |
| `zoom_outs_per_30s` | 2 | the hook reveal (§1.4) and one closing move |
| `punch_ins_per_30s` | 1 | reserved for the proof or testimonial beat |
| `overlay_bursts_per_30s` | 1 | the single energy peak |
| `accent_words_per_30s` | 3 | earned emphasis (§2.4) |

The first three keys are read by the pacing lint; the rest are advisory budget the
brain spends exactly, never per cut.

**Encoded as** `MODES.short.pacing_client_reel`; selected by
`target.pace == "client-reel"`; LESSON-024.

### §8.1 Scope guard

The client-reel budget **never bleeds into other paces**. It conflicts with punch
(which uses no transitions) and with restrained (which uses no zooms), so it lives in
its own profile and is never applied to desk talking-head presets. A promotional motion
budget applied to a conversational clip reads as an advertisement for a video that is
not one.

### §8.2 The talking-head pace, for contrast

The `talking-head` pace is the slow end of produced Shorts: one continuous speaker, few
cuts, and pace carried by **a few sustained content graphics** rather than a change
every few seconds. Long stretches of presenter plus captions are on-style. A run of
climbing quantities in the speech (a milestone sequence) earns **one sustained gauge**
that updates as the numbers are spoken, instead of one card per number. Profile:
`min_changes_per_min` 4.0, `max_still_gap_s` 16.0, `hook_front_load` 1.3
(`MODES.short.pacing_talking_head`). Pace is not treatment: a talking-head Short is
still produced (it has graphics), just slow.

---

## §9 Conflicts

### §9.1 Client-reel versus the other paces

Resolved by the scope guard (§8.1): the operator's selected pace decides which budget
applies; budgets never mix.

### §9.2 The burst exception

`broll_min_spacing_s` (8 s in Shorts) is the cadence for **lone** inserts. A burst
(§4) is a beat-attached exception to that cadence, not a violation of it, and is bounded
by its own window and count. The long-form intro receipt montage is a different device
again (`EDITCRAFT_LESSONS.md` §10.2).

---

## §10 Encoded-where map

| Rule | Config / code | Lesson |
|---|---|---|
| §1.1-§1.2 hook stack, lockup | `MODES.short.hook_stack` | LESSON-022 |
| §1.4 zoom-out reveal | `hook_stack.zoom_out` | LESSON-024 |
| §1.6 riser bridge | `AUDIO["riser_bridge_s"]`, `hook_stack.riser_s` | — |
| §2.2 no captions under designed text | `hook_stack.captions_in_hook` | LESSON-022 |
| §2.4 earned emphasis | `pacing_client_reel.accent_words_per_30s` | LESSON-023 |
| §4 bursts | `BROLL["burst"]["short"]`, `MODES.short.broll_*` | — |
| §5 one peak | `pacing_client_reel.energy_peaks_max`, `overlay_bursts_per_30s` | LESSON-024 |
| §8 client-reel | `MODES.short.pacing_client_reel`, pace ID `client-reel` | LESSON-024 |
| §8.2 talking-head | `MODES.short.pacing_talking_head`, `planner/graphics_planner_gauge.py` | — |
| §9.2 burst exception | `BROLL["burst"]`, `broll_min_spacing_s` | — |
