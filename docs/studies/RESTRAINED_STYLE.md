# RESTRAINED_STYLE.md — the Restrained short-form style specification

**Style ID** `restrained` · **pace ID** `restrained` · **intent preset** `restrained-light`
(`src/lib/producer/intent-presets.ts`) · **lint profile** `MODES["short"]["pacing_restrained"]`
(`scripts/producer/producer_config.py`).

**Status.** Sniper design specification, written for Project Sniper (rc4, 2026-09-18). It
replaces the earlier document at this path in full.

**Who reads this.** The Auto Edit authoring brain reads this file before it authors any track
when `target.style` is `"restrained"`; `src/lib/server/auto-edit-doctrine.ts` pins it into the
per-run doctrine snapshot. Maintainers read it before changing `pacing_restrained`.

**How to read it.** Section numbers and rule IDs (H1, C4, CAP2, …) are stable identifiers cited
by code comments, config comments and the intent-card preset text; keep them when editing. Each
rule gives the rule, the design reason, and how it is enforced:

- **ERROR** — a gate fails the plan.
- **WARN** — a lint reports it; the author must act or justify.
- **advisory** — the authoring brain follows it; no code checks it.

The one-sentence idea: *a single speaker, one steady frame, and the words on screen carry the
pace.* Everything that could compete with what the speaker says is left out.

---

## 0. Evidence and scope

- **Evidence.** Sniper design specification; parameters verified against `producer_config.py`
  and the lint/tests named in §10. The rationale for each rule is first-principles reasoning
  about a single-speaker vertical clip, stated with the rule. This document does not report
  measurements of any third-party video and makes no audience-retention claims.
- **Numbers.** Every numeric value here is a **Sniper design parameter**. Where code reads it,
  §9 names the reader.
- **Format.** 9:16 shorts only. The preset is short-only, and the frame-one hook obligation (H1)
  never applies to long-form (`plan_lint_overlays._short_hook_required`).
- **Choose Restrained when** the delivery itself is strong, the point is an opinion, story or
  explanation that needs no on-screen proof, and the footage is a clean single take.
- **Do not choose it when** a claim needs visible evidence (use Slideware), when the delivery
  needs rhythm added by editing (use Punch), or when the take needs so many removals that the
  jump cuts would become the most noticeable thing in the clip (see C2).

## 1. Hook

**H1 — One thesis card from frame one.** The clip opens with exactly one `titleCards[]` entry
with `style: "hook"` and `outStart` 0.0 s. Its text states the clip's thesis in the speaker's
own terms, inside the `HOOK_CARD` limits: at most 8 words, 2 lines and 26 characters per line,
held 1.0–6.0 s.
*Why:* in a clip with no motion and few cuts, nothing else tells the viewer where the clip is
going. The first frame is also the cover and the loop point, so a written thesis there does
three jobs at once. One card, not a sequence, keeps the style's promise that nothing else will
interrupt the speaker.
*Enforced:* **ERROR.** `plan_lint_overlays._short_hook_required` keeps the hook obligation for
`target.style == "restrained"` even though the light scope does not own the graphics lane, and
`check_title_cards` requires a `style="hook"` card starting at 0.0. An explicit
`lanes.graphics: "off"` or a `trim` scope combined with this style is reported as an intent
conflict. Tests: `scripts/producer/tests/test_short_hook_intent.py`.

**H2 — The hook is the base shot.** The opening seconds use the same reframed composition as the
rest of the clip: no cold-open cutaway, no push-in, no special hook framing.
*Why:* a change of framing in the first seconds promises edited energy that a restrained clip
will not deliver. Keeping the frame constant makes the thesis card the single opening event.
*Enforced:* advisory. The preset waives the motion lane (Z1), so no push-in can be authored.

**H3 — Flat cadence.** The hook does not need to be denser in visual changes than the body.
⇒ `hook_front_load = 1.0`.
*Why:* the front-load ratio compares the change rate inside the short hook window
(`MODES["short"]["hook_window_s"]` = 3.0 s) with the rate in the rest of the clip. The generic
short profile asks for 1.5×, which would push the author to add opening events the style does
not want. At 1.0 the hook only has to be no sparser than the body, and the H1 card at 0.0 s
satisfies that whenever the body is at or below the hook's rate. An uncut body produces an
infinite ratio and passes.
*Enforced:* **WARN** in `plan_lint_motion._warn_pacing`, when the pacing check runs (§10).

## 2. Cuts

**C1 — Cuts are optional.** A single uncut take is a complete Restrained edit.
⇒ `min_changes_per_min = 0.0`.
*Why:* this style's tempo is carried by the caption layer (CAP1), which the pacing lint does not
count. Any change-rate floor above zero would pressure the author to add cuts only to satisfy a
number.
*Enforced:* **WARN** threshold in `_warn_pacing`; at 0.0 it can never fire.

**C2 — Cuts remove; they do not energise.** Every cut must remove something: a flub, a false
start, a retake, or dead air longer than a breath. Never cut only to create rhythm.
*Why:* on a locked single frame each jump cut is visible. It should buy a cleaner sentence. The
edit brain's proposers already work this way: `edit/pause_scan.py` tightens gaps down to a kept
breath and `edit/retake_scan.py` proposes retake removals, folded by `edit/apply_pauses.py`.
*Enforced:* advisory.

**C3 — Cover a removal with another angle only if the project already has one.** When the
manifest carries a second synchronized source, a removal seam may switch to it instead of
jumping inside the same framing. Never add new footage for this purpose; b-roll stays off.
*Why:* a change of angle hides a removal better than a jump within one framing, but bringing in
other footage would break the one-speaker premise.
*Enforced:* advisory. The b-roll lane is inactive under the light scope, and the operator-intent
contract fails a plan that authors `brollTrack` on an inactive lane.

**C4 — Longest legal hold.** A stretch with no discrete visual change may last up to 40 s before
the pacing lint warns. ⇒ `max_still_gap_s = 40.0`.
*Why:* the style deliberately allows a whole short on one shot. 40 s is long enough that a
complete short built from one continuous take of up to about 40 s never warns, and short enough
that a longer unbroken stretch is flagged for a deliberate decision: split it with a C2 removal,
or accept the hold knowingly. The same idea, that a long hold is legal only when another layer
keeps changing, is reused at long-form scale in `MODES["longform"]["pacing_lanes"]`.
*Enforced:* **WARN** (`planner/pacing.py` `pacing_report` → `_warn_pacing`). No separate hook
ceiling is set, so the hook uses the same 40 s ceiling.

**C5 — Snap cuts to caption changes.** When a cut is needed, put its output-time seam where a new
caption cue starts, so the text change and the picture change happen on the same frame.
*Why:* a cue change already draws the eye to the caption. A jump that lands on that frame reads
as one event instead of two, which makes the jump less noticeable. Cue boundaries fall at word
boundaries (`captions/captions_whisper.py` `_whisper_cues` breaks on a gap of at least
`phrase_gap_s`, on `phrase_max_words`, or at a sentence end), and cuts are made between kept
words, so the two can coincide.
*Enforced:* advisory.

## 3. Zoom and camera motion

**Z1 — No punch-ins, no zoom ramps, no aliveness creep.** The `punchIns` track stays empty. The
preset sets `lanes.motion = "off"`.
*Why:* in a still frame any scale change is the most visible edit on screen. It says "look here",
while this style promises that the speaker's delivery is the only emphasis. A slow creep also
moves the speaker relative to a fixed caption position.
*Enforced:* **ERROR.** `operator_intent_contract.py` fails a plan that authors `punchIns` while
the stored intent has the motion lane `"off"`. Upstream, `graphics_planner._apply_scope` empties
the proposed `punchIns` when the motion lane is not `"auto"`.

## 4. Captions

**CAP1 — Captions carry the tempo.** Burned, verbatim captions are on and change often.
Advisory target: `state_changes_per_min = 80`.
*Why:* with no motion and few cuts, the text is the only thing that moves. Short cues replaced
continuously give the eye a steady rhythm that is tied to the speech itself. 80 per minute is a
design target: for example, about 160 spoken words per minute grouped two words per cue gives
80 cue changes per minute. It is advisory because the real rate follows the speaker.
*Enforced:* advisory; the pacing lint does not read `state_changes_per_min` and does not count
caption cues. Caption presence is **ERROR**-checked: the light scope owns the captions lane, and
the operator-intent contract fails a short plan with no burned captions.

**CAP2 — Plain captions.** Use `captions.style: "whisper"` and leave `captions.emphasisWords`
empty: white sentence-case cues that replace each other, a soft shadow, no outline box, no
karaoke word sweep, no colour.
*Why:* colour and word sweeps are emphasis devices, and this style has one emphasis device, the
speaker. A box would add a second object to a frame whose graphic budget is one (§5). An empty
emphasis list keeps the whisper layer's inline accent from ever firing.
*Enforced:* advisory for choosing the style and leaving emphasis empty. The whisper renderer
enforces the treatment itself (`CAPTIONS["WHISPER"]`: `outline_px` 0, no karaoke events). Tests:
`WhisperCaptionTests` in `scripts/producer/tests/test_punch_gaps.py`.

## 5. Graphic budget

One graphic per clip: the H1 thesis card. No other title cards, no `graphicsTrack` entries, no
receipts, chips, PIP or b-roll.
*Why:* each extra object splits attention between reading the caption and reading the graphic.
The thesis card earns its place because it appears before the speaker has said anything.
*Enforced:* the light scope does not activate the graphics, b-roll, transitions or credibility
lanes, so the planners propose none of them, and the operator-intent contract fails a plan that
authors `graphicsTrack`, `brollTrack` or `transitions` on those inactive lanes (**ERROR**).
Extra `titleCards` are not blocked by code (the general limit is `LINT["max_title_cards"]`); a
second card is advisory-forbidden here. If the operator wants graphics, this is the wrong
style: choose Punch, Slideware or a generic preset.

## 6. Audio

**M1 — No music bed.** Preset `music: false`; profile advisory `music: False`.
*Why:* the content is the voice. A bed adds a second rhythm that the edit does not otherwise
have, and ducking movement is easiest to hear under a sparse edit. The operator can still tick
Music as an explicit choice.
*Enforced:* **ERROR** on drift: the operator-intent contract fails a plan whose
`music.enabled` differs from the stored intent. Presets can never enable music
(`src/lib/producer/__tests__/intent-presets.test.ts`).

**M2 — Standard master.** Deliver at Sniper's standard master: −14 LUFS integrated with the
−1.5 dBTP true-peak ceiling (`AUDIO["lufs_target"]`, `AUDIO["true_peak_dbtp"]`). No separate
loud master.
*Why:* consistent loudness with every other Sniper deliverable, and the true-peak ceiling
leaves headroom for platform transcoding. Loudness follows the ITU-R BS.1770 measurement used by
ffmpeg's loudnorm.
*Enforced:* the master stage (`audio/master.py`) targets it and Audit B checks integrated
loudness within `AUDIO["lufs_tolerance"]` (`audit/audit_checks.py` `check_loudness`).

**M3 — Keep the natural sound.** No `audioEnhance` preset. Pauses are tightened to a kept breath,
not cut to silence.
*Why:* noise reduction on a quiet single-microphone recording can make pauses sound processed,
and the breaths between phrases are part of a delivery that has no other rhythm.
*Enforced:* the preset carries no `audioEnhance` (asserted in `intent-presets.test.ts`), and
the operator-intent contract fails a plan whose `audioEnhance` differs from the stored intent
(**ERROR**). If a recording has obvious hum or noise, the operator should choose a cleanup
preset explicitly.

## 7. What Restrained does not do (compared with Punch)

| Dimension | Restrained | Punch (`scripts/producer/docs/findings/PUNCH_STYLE.md`) |
|---|---|---|
| Cuts | optional, remove-only (§2 C1, C2) | the main energy source, floor 14/min (§2 C1) |
| Zoom | none (§3 Z1) | hard scale steps on cuts, up to 1.45× (§2 C5) |
| Captions | plain whisper, no emphasis colour (§4 CAP2) | whisper plus inline accent and keyword lockups (§4) |
| Graphics | one thesis card (§5) | lockups, word-locked builds, takeover bases (§5.4) |
| Transitions | none | none (§7) |
| Music | none (§6 M1) | bed recommended, operator opt-in (§6 M1) |
| Dialogue cleanup | none (§6 M3) | `voice-rnn` in the preset |
| Hook | thesis card, flat cadence (§1 H1, H3) | graphic from frame zero, front-load 1.3 (§1 H2) |
| Longest hold | 40 s (§2 C4) | 12 s (§2 C8) |

## 8. Low-confidence register

Design judgements that have not been validated with viewers or with a Sniper-rendered
side-by-side comparison:

- **L1** — the advisory caption rate of 80 per minute (CAP1) is arithmetic from an assumed
  speaking pace, not a measurement.
- **L2** — the 40 s hold ceiling (C4) may be too permissive for clips well over a minute.
- **L3** — a thesis card held for the whole clip is not supported: title cards hold 1.0–6.0 s
  (`HOOK_CARD`). Whether a longer-held thesis would serve the style better is open.
- **L4** — the angle-switch cover (C3) has not been exercised in a Sniper render.
- **L5** — the no-cleanup rule (M3) assumes a reasonably clean recording.

## 9. Executable profile

`MODES["short"]["pacing_restrained"]`, selected when `target.pace == "restrained"`
(`plan_lint_motion._pacing_profile`).

| Key | Value | Rule | Read by |
|---|---|---|---|
| `min_changes_per_min` | 0.0 | §2 C1 | `plan_lint_motion._warn_pacing` (WARN) |
| `max_still_gap_s` | 40.0 | §2 C4 | `planner/pacing.py` `pacing_report` → `_warn_pacing` (WARN) |
| `hook_front_load` | 1.0 | §1 H3 | `_warn_pacing` (WARN) |
| `state_changes_per_min` | 80.0 | §4 CAP1 | advisory; no code reads it |
| `music` | `False` | §6 M1 | advisory; the preset's `music: false` is what is stored |

Preset `restrained-light`: mode `short`; scope `light`; `lanes: {motion: "off"}` (§3 Z1); pace
and style `restrained`; `music: false` (§6 M1); no `audioEnhance` (§6 M3).

## 10. Verification and enforcement record

What was checked when this specification was written (2026-09-18, rc4 working tree):

1. **Profile values equal the config.** Each value in the §9 table was compared with
   `producer_config.MODES["short"]["pacing_restrained"]` by importing the module; all five keys
   matched.
2. **The lint uses the profile.** Probing `plan_lint_motion.check_pacing` on a 60 s single-take
   short with a frame-one hook card, `pace: "restrained"` and a `produced` scope produced one
   WARN (a 57 s stretch over the 40 s ceiling) and no rate or front-load warning. The same take at
   38 s produced no warning. Under the default short profile the 38 s take warned for rate (below
   12/min) and for an 8 s still gap.
3. **Known enforcement gap.** `check_pacing` returns early unless at least one of the motion,
   graphics, transitions or b-roll lanes is `"auto"`. The `restrained-light` preset (light scope,
   motion off) activates none of them, so **for that preset the §9 pacing profile is never
   evaluated**; the probe returned no warnings for a 60 s uncut take. The profile applies when
   `pace: "restrained"` is combined with a scope that activates one of those lanes. Under the
   preset, the style is held by H1, Z1, §5, M1 and M3 instead.
4. **Hook obligation.** A light-scope plan with `style: "restrained"`, `lanes.motion: "off"` and
   no hook card fails `check_title_cards` (probe; also `test_short_hook_intent.py`).
5. **Lane waivers.** With the preset's stored intent, a plan that authors `punchIns` fails the
   operator-intent contract (probe; `test_operator_intent_contract.py` covers the general rule).

Not checked: the visual result of this style has not been rendered and reviewed for this
revision of the document, and no claim is made about how viewers respond to it.

## 11. Which preset this calibrates

This document calibrates the **`restrained-light`** preset: the light scope (clean cut plus
captions) with the motion lane waived and the named-style thesis hook kept. Compared with the
generic `light-short` preset it adds a required frame-one thesis card, removes the aliveness
creep, skips dialogue cleanup, and uses plain whisper captions rather than karaoke.
