# PUNCH_STYLE.md — the Punch short-form style specification

**Style ID** `punch` · **pace ID** `punch` · **intent preset** `punch-produced`
(`src/lib/producer/intent-presets.ts`) · **lint profile** `MODES["short"]["pacing_punch"]`
(`scripts/producer/producer_config.py`) · **caption preset** `CAPTIONS["WHISPER"]`.

**Status.** Sniper design specification, written for Project Sniper (rc4, 2026-09-18). It
replaces the earlier document at this path in full. This is the only copy: the former duplicate
under `docs/studies/` has been removed and its links point here.

**Who reads this.** The Auto Edit authoring brain reads this file before it authors any track
when `target.style` is `"punch"`; `src/lib/server/auto-edit-doctrine.ts` pins it into the
per-run doctrine snapshot. Maintainers read it before changing `pacing_punch`,
`CAPTIONS["WHISPER"]`, the pop/exit motion tokens or the `punch-shout-lockup` composition.

**How to read it.** Section numbers and rule IDs (H2, C5, CAP3, E4, G17, …) are stable
identifiers cited by code comments, config comments, templates and the intent-card preset text;
keep them when editing. Each rule gives the rule, the design reason, and how it is enforced:
**ERROR** (a gate fails the plan), **WARN** (a lint reports it), or **advisory** (the authoring
brain follows it; no code checks it).

The one-sentence idea: *one steady camera, and the edit supplies the energy — hard cuts between
framings on the words that matter, with two layers of text doing the emphasis.*

---

## 0. Evidence and scope

- **Evidence.** Sniper design specification; parameters verified against `producer_config.py`
  and the lint/tests named in §11. The rationale for each rule is first-principles reasoning
  about cutting a single locked-off talking-head take for a vertical feed, stated with the rule.
  This document does not report measurements of any third-party video and makes no
  audience-retention claims.
- **Numbers.** Every numeric value here is a **Sniper design parameter**. Where code reads it,
  §9 names the reader.
- **Format.** 9:16 shorts only; the preset is short-only.
- **Choose Punch when** the footage is one steady single-speaker take, the script has clear
  stressed words or pivots, and the goal is a fast, energetic short.
- **Do not choose it when** the delivery should breathe and the words alone should lead (use
  Restrained), or when the message depends on showing evidence full-frame (use Slideware).

## 1. Hook

**H1 — The first frame is designed.** Frame zero already contains the speaker and a text
element (the hook card, or a keyword lockup from §5.4 E1). When text sits over busy footage in
the opening, the footage under that graphic may use the blurred, desaturated base (§5.4 E4).
*Why:* the first frame doubles as the cover and the loop point, so it should read as a finished
composition, not as an empty frame waiting for the edit to start.
*Enforced:* the produced scope owns the graphics lane, so a short needs a `style: "hook"` title
card starting at 0.0 s (**ERROR**, `plan_lint_overlays.check_title_cards`). The lockup/base choice
is advisory.

**H2 — The hook is carried by a graphic from frame zero, not by a burst of cuts.**
⇒ `hook_front_load = 1.3`.
*Why:* Punch is already dense for its whole length. Requiring the first 3 s
(`MODES["short"]["hook_window_s"]`) to be 1.5× denser than an already fast body (the generic
short default) would force a cluster of cuts before the viewer has heard a full sentence. The
opening is carried instead by text present from t = 0 (H1, §4 T1), and the ratio only has to
show a moderately denser opening.
*Enforced:* **WARN** in `plan_lint_motion._warn_pacing`.

## 2. Cut engine

**C1 — Visible cuts drive the tempo.** ⇒ `min_changes_per_min = 14.0`.
*Why:* the edit is the energy source, so the floor sits above the generic short floor (12.0).
14 per minute is about one discrete visual change every 4.3 s. Graphic entrances and staged lands
also count as changes (`planner/pacing.py` `visual_change_times`), so a plan meets the floor
with cuts and word-locked text together.
*Enforced:* **WARN** in `_warn_pacing`.

**C2 — Cut on the words that matter.** Place cuts at kept-word boundaries at pivots: the start of
a stressed word, a contrast ("but", "instead"), or the start of a new claim.
*Why:* a change of framing that coincides with a stressed word reads as emphasis. The same
change in the middle of an unstressed phrase reads as an interruption.
*Enforced:* advisory. Cut boundaries are kept-word boundaries by construction (the edit brain
cuts between words).

**C3 — Strip dead air hard.** Tighten pauses more than in Restrained; keep a pause only when it
is a deliberate beat before a payoff line.
*Why:* in a fast edit an unmotivated pause reads as a mistake rather than as breathing room.
*Enforced:* advisory (the author drives `edit/pause_scan.py` / `edit/apply_pauses.py`).

**C4 — Alternate framings at every cut.** With one camera, the second "angle" is a tighter crop
of the same frame. Adjacent segments must differ in scale: wide then tight, or tight then wide.
Two adjacent segments at the same scale are never allowed.
*Why:* a cut between two near-identical frames is a jump cut that looks like an error. Changing
scale at the seam turns the same cut into an intentional one; this is the general film-editing
principle that a cut should change the shot enough to read as a new shot.
*Enforced:* advisory.

**C5 — Punch-step band.** A tight framing is a static `punchIns` window whose `zoom` is between
`MOTION["punch_in"]["zoom_min"]` (1.05) and 1.45. ⇒ `punch_zoom_max = 1.45`.
*Why:* the step has to be large enough to read as a new shot (C4), so Punch allows more than the
generic ceiling of 1.25. A tight shot at 1.45× uses about 69 % of the reframed width (1 / 1.45),
so the picture is upscaled by that factor; the quality cost grows with the factor, and 1.45 is
Sniper's design limit, kept below the renderer's hard ceiling (`motion/punch_in.py`
`ZOOM_MAX_HARD` = 1.55).
*Enforced:* **ERROR** in `plan_lint_motion._check_punch_window` through `_punch_zoom_max`, which
reads `punch_zoom_max` only when `target.pace == "punch"`; every other pace keeps 1.25. Tests:
`PunchCeilingTests` in `scripts/producer/tests/test_punch_gaps.py`.

**C6 — Hard cuts only.** Every seam is a straight cut; see §7.
*Why:* the scale step is the transition. A dissolve, flash or wipe would soften exactly the
discontinuity the style depends on.
*Enforced:* **ERROR** through the preset's `lanes.transitions: "off"` (§7).

**C7 — Removals first, framing second.** Build the cutTrack from the edit brain's removals
(pauses, retakes) first, then assign wide and tight framings to the resulting segments.
*Why:* framing choices made before the removals are known get broken by the removals.
*Enforced:* advisory.

**C8 — Longest no-change stretch.** A stretch with no discrete visual change may last up to
12 s. ⇒ `max_still_gap_s = 12.0`.
*Why:* Punch never lets the frame sit for long, but a closing line delivered without
interruption is legitimate. 12 s admits one held closing statement and flags anything longer.
It sits above the generic short ceiling (8 s) because in this style the text layers (§4) keep
changing during a held shot, and the lint does not count caption changes.
*Enforced:* **WARN** (`pacing_report` → `_warn_pacing`).

## 3. Within-shot zoom

**Z1 — Scale changes happen on cuts, not inside a segment.** A punch-in is a static window that
starts on a cut seam and holds its zoom for the segment. No eased pushes and no zoom ramps inside
a spoken segment.
*Why:* the style's motion language is the discontinuous step. Mixing smooth zooms with steps
weakens both, and a ramp makes the next cut's scale difference unpredictable.
*Enforced:* advisory for shorts (the smooth-longform seam rule in `plan_lint_smooth.py` applies to
long-form only).

**Z2 — No aliveness creep.** Do not author `role: "aliveness"` punch-ins.
*Why:* a continuous creep makes consecutive segments differ in scale by a changing amount, which
blurs the wide/tight distinction C4 relies on. The frame is meant to be locked between cuts.
*Enforced:* advisory. The produced scope leaves the motion lane on (for C5 steps), so the zoom
planner may still propose aliveness windows; the author drops them.

## 4. Two text layers

Punch uses two text layers with separate jobs. Emphasis lives in the layers, never in a caption
animation.

**T1 — The keyword lockup layer.** A few keywords per clip are promoted into a large lockup in
the headroom above the face (§5.4 E1). This layer carries the hook (H2) and the payoff words.

**T2 — The verbatim caption layer.** Every spoken word appears in small replace-per-cue
captions below the face (CAP2).

**CAP1 — No karaoke sweep.** Captions replace whole cues; words are never highlighted one by
one as they are spoken.
*Why:* a sweep keeps the eye moving across a line; replace-per-cue keeps it in one place while
the picture is cutting.
*Enforced:* the whisper renderer emits no karaoke events (`captions/captions_whisper.py`).

**CAP2 — Small verbatim captions.** ⇒ `CAPTIONS["WHISPER"]`, selected with
`captions.style: "whisper"`.
*Why:* small type below the face leaves the headroom free for T1, and short replace-per-cue cues
(one to three words) stay readable during fast cutting. The treatment is a soft shadow with no
outline box, so the captions do not become a second graphic.
*Enforced:* by the renderer and config values listed in §9.2. Tests: `WhisperCaptionTests`
(`test_punch_gaps.py`).

**CAP3 — Inline accent emphasis.** A word listed in `captions.emphasisWords` takes the caption
accent colour from its cue's first frame; it is never swept or animated in.
*Why:* colour that is present from the first frame is read as part of the word. Colour that
animates in draws attention to the animation instead.
*Enforced:* `captions_whisper._render_cue` applies an inline colour override for the whole cue.
Tests: `test_inline_amber_from_first_frame`.

**CAP4 — Word-append timing band.** When a lockup builds word by word, each word lands between
0.08 s and 0.42 s after the previous one.
*Why:* below about 0.08 s (between two and three frames at 30 fps) words land effectively
together, and the build is indistinguishable from a pop. Above about 0.42 s the build falls
behind speech: at 150 spoken words per minute a word lasts 0.4 s, so a slower append could not
stay locked to the words.
*Enforced:* the `punch-shout-lockup` composition clamps its `appendS` variable to 0.08–0.42.

## 5. Visual system

### 5.1 Tokens

Exactly two identity tokens:

- **one display face** — the display-face token `--font-serif-display`, used only for T1 lockups;
- **one accent colour** — the single accent token `--lemon`, used only for payload words in T1.

The caption layer's inline accent (CAP3) is a separate config value,
`CAPTIONS["WHISPER"]["accent"]`. Everything else is white on footage.
*Why:* one face and one colour make the lockups recognisable as a system; a second accent would
make emphasis ambiguous.
*Enforced:* the tokens live in `templates/motion/tokens.css`. This specification fixes the token
roles only; the actual face and colour values are chosen by the design system and may change
without changing this document.

### 5.2 Placement grid

Three zones on the 1080×1920 canvas:

1. **Headroom** — T1 lockups, between 0.115 and 0.27 of frame height (the lockup's block
   centre `slotY`, default 0.19).
2. **Face** — never covered by text.
3. **Caption band** — T2, centred horizontally, between 0.60 and 0.64 of frame height.

*Why:* fixed zones let the viewer learn where each kind of text appears within the first seconds.
*Enforced:* the caption band is config (§9.2); `punch-shout-lockup` clamps `slotY` to the
headroom band. Keeping every other graphic off the face is advisory for this style.

### 5.3 Animation law

- **Pop in within two frames.** `templates/motion/motion-tokens.js` `POP_IN_S` = 2 / FPS; CSS
  `--pop-in-dur: 0.066s`.
- **Never animate out.** A graphic ends either exactly on the next cut (`"exitOnCut": true` on
  the `graphicsTrack` entry clamps its `outEnd` to the next cutTrack seam) or with an instant
  hard-off at a sentence boundary.

*Why:* a two-frame entrance reads as a cut-like event and matches the cut engine. Exit animations
add motion just when attention should move to the next line; ending on a cut hides the exit
inside the picture change.
*Enforced:* `graphics/exit_on_cut.py` clamps before render and composite, and is shared by lint,
`render.py` and `assemble.py`. Lint warns when a clamp collapses a hold. Tests: `ExitOnCutTests`.

### 5.4 Element catalog

- **E1 — Keyword lockup** ⇒ `punch-shout-lockup` (kicker / payload / co-word / second kicker;
  `build` is `pop` or word `append` per CAP4). The payload uses the display face and accent.
- **E2 — Caption layer** ⇒ the whisper captions (T2, CAP2, CAP3).
- **E3 — Word-locked builds** ⇒ list or diagram cards whose items land on spoken words (staged
  `atN` lands), used only where a beat genuinely lists or sequences something.
- **E4 — Footage takeover base** ⇒ `"takeoverBase": "blur-desat"` on a graphic entry
  (`TAKEOVER_BASES`): the footage under the graphic's window is blurred and desaturated, applied
  and restored on single frames. Legal only under an alpha overlay; illegal with `own-screen`
  (which covers the frame) or `focus-shift` (which already blurs).
  *Why:* text over busy, saturated footage loses contrast. Blurring and desaturating the
  speaker's own footage keeps the scene continuous while giving the text a quiet ground.
- **E5 — Icon draw-on badge** ⇒ `stroke-draw-badge`, for a save or follow call to action; it
  follows the 5.3 pop law.

## 6. Music

**M1 — A bed is recommended.** ⇒ advisory `music = True`. The preset still sets `music: false`;
the operator opts in.
*Why:* with frequent cuts, a continuous bed carries continuity across the seams. Music remains
the operator's explicit choice because presets never enable it.
*Enforced:* the operator-intent contract fails a plan whose `music.enabled` differs from the
stored intent (**ERROR**). A bundled starter bed is registered at ingest
(`ingest_scan.scan_builtin_music`), so ticking Music works without a project music folder.

**M2 — Standard bed mix.** Use the standard duck: the bed sits under dialogue with sidechain
ducking (`AUDIO["music_duck_db"]`, `AUDIO["music_gap_db"]`), and the program masters to −14 LUFS
with the −1.5 dBTP true-peak ceiling.
*Why:* the voice is the content; the bed should never compete with it.
*Enforced:* `audio/audio_mix.py` / `audio/music_stage.py`; `plan_lint_audio.py` requires
`gapDb` to keep the voice at least 3 dB above the bed.

**M3 — Never cut to the beat.** Speech is the timing authority. Cuts follow words (C2), never
music bars.
*Why:* beat-matched cuts would move cut points away from word boundaries.
*Enforced:* advisory.

## 7. Transition budget

None. Every seam is a hard cut (C6). The preset sets `lanes.transitions: "off"`.
*Enforced:* **ERROR**. The operator-intent contract fails a plan that authors `transitions`
while the stored intent has that lane `"off"`.

## 8. Low-confidence register

Design judgements that have not been validated with viewers or with a Sniper-rendered
side-by-side comparison:

- **L1** — the floor of 14 changes per minute (C1) and the 12 s hold (C8) are design choices,
  not measurements.
- **L2** — the advisory state rate of 70 per minute (§9) is arithmetic from an assumed speaking
  pace.
- **L3** — the 1.45 ceiling (C5) trades sharpness for step size; the right value depends on the
  source resolution, which varies by project.
- **L4** — whether Z2 should forbid every aliveness window, or allow one under a held closing
  line, is open.
- **L5** — M1 recommends a bed without a Sniper study of when a bed helps a punch edit.

## 9. Executable profile

### 9.1 Pacing profile

`MODES["short"]["pacing_punch"]`, selected when `target.pace == "punch"`
(`plan_lint_motion._pacing_profile`).

| Key | Value | Rule | Read by |
|---|---|---|---|
| `min_changes_per_min` | 14.0 | §2 C1 | `plan_lint_motion._warn_pacing` (WARN) |
| `max_still_gap_s` | 12.0 | §2 C8 | `planner/pacing.py` `pacing_report` → `_warn_pacing` (WARN) |
| `hook_front_load` | 1.3 | §1 H2 | `_warn_pacing` (WARN) |
| `state_changes_per_min` | 70.0 | §4 | advisory; no code reads it |
| `music` | `True` | §6 M1 | advisory; the preset stores `music: false` until the operator opts in |
| `punch_zoom_max` | 1.45 | §2 C5, §10 G17 | `plan_lint_motion._punch_zoom_max` → `_check_punch_window` (ERROR) |

`state_changes_per_min` counts T1 and T2 text changes plus cuts. For example, 150 spoken words
per minute grouped about 2.5 words per cue gives 60 caption changes, and the C1 floor adds at
least 14 more.

### 9.2 Caption preset

`CAPTIONS["WHISPER"]`, rendered by `captions/captions_whisper.py`.

| Key | Value | Rule |
|---|---|---|
| `font_size` / `font_size_range` | 42 / (40, 44) px | §4 CAP2 (about 2.2 % of a 1920 px frame height) |
| `phrase_max_words` | 3 | §4 CAP2 |
| `phrase_gap_s` | 0.35 | §4 CAP2 (a breath starts a new cue) |
| `min_hold_s` / `hang_s` | 0.25 / 0.35 | §4 CAP2 (readable minimum; no lingering into dead air) |
| `band_y_frac` / `center_x` | (0.60, 0.64) / 540 | §5.2 |
| `outline_px` / `shadow_px` | 0 / 2 | §4 CAP2 (no box, soft shadow) |
| `fill` / `sentence_case` | white / true | §4 CAP2 |
| `accent` | config value | §4 CAP3, §5.1 |

The caption font is a config value (`font`) and is not fixed by this specification.

### 9.3 Preset

`punch-produced`: mode `short`; scope `produced`; `lanes: {transitions: "off"}` (§7); pace and
style `punch`; `music: false` (M1 opt-in); `audioEnhance: {preset: "voice-rnn"}` (a steady voice
under fast cutting).

## 10. Implementation items (gap IDs)

Items this style needed beyond the generic pipeline. All listed items are built.

| ID | Item | Where | Tests |
|---|---|---|---|
| **G1** | display-face token | `--font-serif-display` in `templates/motion/tokens.css`; face file in `assets/fonts/` | `ShoutLockupTemplateTests.test_tokens_css_carries_lemon_and_serif_display` |
| **G2** | caption preset | `CAPTIONS["WHISPER"]`, `captions/captions_whisper.py` | `WhisperCaptionTests` |
| **G3** | keyword lockup composition | `templates/motion/compositions/punch-shout-lockup.html` | `ShoutLockupTemplateTests.test_comp_exists_with_house_conventions` (contract only; the render is exercised outside the unit suite) |
| **G4** | exit law and motion tokens | `graphics/exit_on_cut.py`, `templates/motion/motion-tokens.js`, pop tokens in `tokens.css` | `ExitOnCutTests`, `ShoutLockupTemplateTests.test_motion_tokens_helper` |
| **G5** | takeover base | `TAKEOVER_BASES` in `graphics/exit_on_cut.py`; rendered by `graphics/graphics_stage.py` | `TakeoverBaseTests` |
| **G17** | style-aware punch ceiling | `pacing_punch["punch_zoom_max"]`, `plan_lint_motion._punch_zoom_max` | `PunchCeilingTests` |

Identifiers G6–G16 are not used by this specification; they are reserved so that G17 keeps its
existing meaning in code. The bundled starter bed (M1) is covered by `BuiltinMusicTests`.

## 11. Verification record

What was checked when this specification was written (2026-09-18, rc4 working tree):

1. **Profile values equal the config.** Each value in the §9.1 and §9.2 tables was compared with
   `producer_config.MODES["short"]["pacing_punch"]` and `producer_config.CAPTIONS["WHISPER"]` by
   importing the module; all listed values matched.
2. **The ceiling is style-aware.** Probing `plan_lint_motion.check_punch_ins`: a static
   punch-in at zoom 1.45 with `pace: "punch"` passed; 1.5 with `pace: "punch"` failed
   ("zoom must be a number in [1.05,1.45]"); 1.3 under the default pace and under
   `pace: "slideware"` failed against [1.05,1.25].
3. **Lane waivers and music.** With the preset's stored intent, a plan that authors
   `transitions` or enables music fails the operator-intent contract (probe).
4. **Unit tests.** `scripts/producer/tests/test_punch_gaps.py` and `test_pacing.py` were run
   against this revision; results are in the rc4 evidence log for this change.

Not checked: the visual result of this style has not been rendered and reviewed for this
revision of the document, and no claim is made about how viewers respond to it.
