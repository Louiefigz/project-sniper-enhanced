# Motion Grammar Study — the durable rules of movement (2026-07-06)

**Purpose.** Not "copy the pro's timeline" — *extract the grammar*: **WHEN** a move is
warranted, **HOW** it should behave, and **HOW SMOOTH** it must be, as rules that
generalize to any new video. "Every video is different, but it should feel consistent
and engaging." So this doc is **triggers → behavior ranges → a smoothness bar**, plus an
explicit split of what is **INVARIANT** across two different pro editors (the brand/motion
doctrine the template enforces) vs what **VARIES** with content (what the brain decides
per video). It answers the operator's complaint that the machine reads *stale and
mechanical*.

**Clips measured (first 300s each, 23.976fps):**
| tag | file | role |
|---|---|---|
| **PRO #1** | `Replaced 5 Content Tools…mp4` | reference edit A (creator X) |
| **PRO #2** | `angle generator.mp4` | reference edit B (creator Y, the C0679 edit) |
| **RAW** | `C0679.MP4` (4K) | PRO #2's **unedited source** — the locked-camera **noise floor** |
| **MACHINE** | `C0666 FULL 16min (machine edit).mp4` | the failure sample |

**Method.** 12fps grayscale analysis frames → per-sample **ORB whole-frame similarity
transform** (scale + translation) anchored to each shot's first frame (drift-free; the
RAW clip validates the floor at 0 framing change over 300s — so every framing move in an
edit is an editor DECISION). Easing = RMSE of each zoom's normalized-progress curve vs
linear / ease-in-out / ease-in / ease-out + a **step-fraction** (share of the change in one
sample). Native-fps `signalstats` for transitions + grade; YuNet for crop tightness (PRO #2
vs its own RAW = a clean same-footage read). Tools in scratchpad `motion/`; evidence on
Desktop `MOTION STUDY - pro vs machine/`.

---

## 1. The 4-way scoreboard (evidence, not a transcript)

| Motion signal | RAW (floor) | MACHINE (bad) | PRO #1 | PRO #2 | invariant band (both pros) |
|---|---|---|---|---|---|
| Framing **MOVING** (% frames) | 2% | 19% | 51% | 41% | **≥ ~40%** |
| **Motion p90 ÷ raw floor** | 1.0× | **3.7×** | 23.5× | 14.1× | **≥ ~10×** |
| Longest **FROZEN** hold | 300s | **39.1s** | 18.2s | 23.8s | **≤ ~24s** |
| Total frozen | 100% | 67% | 42% | 49% | ~40–50% |
| Within-shot zooms **eased** | – | 2 of 9 | 17 of 17 | 9 of 11 | **~80–100%** |
| Zoom **step-fraction** (median) | – | **0.83** | 0.11 | 0.10 | **< ~0.25** |
| Zoom velocity-peak τ (median) | – | **1.00** | 0.31 | 0.38 | **0.2–0.8** |
| Zoom **recompose** transl. (median px@1080) | – | 59 | 287 | 318 | **≥ ~250** (≥150 floor) |
| Zoom magnitude (median) | 0 | 15% | 26% | 33% | **~20–40%** perceptible |
| Ramp duration (median / max) | – | 2.9 / 23.7s | 3.8 / 22.8s | 5.7 / 20.3s | **2–6s** typ., up to ~22s |
| Framing-change cadence | 0/min | 8.4/min | 6.2/min | 5.8/min | ~6/min |
| Transitions (flash / warm-wash) | 0 / 0 | 4 / 2 | 16 / 27 | 10 / 0 | **flash ~10–16**; wash varies |
| Home framing (face height) | 23% | 28% | 22% | 24% | **~22–24%** (moderate) |

**The single most damning number:** the machine's motion p90 is **3.7× the raw
locked-camera floor** — it barely moves more than an *unedited* camera. Both pro edits run
**14–24×** the floor. The machine is closer to a dead camera than to a pro edit.
(`plots/04_four_way_summary.png`.)

---

## 2. INVARIANTS — the motion grammar (true across BOTH pro editors)

These held on two different creators and two content types (a personal-story video and a
tool-demo video). **This is the doctrine the template/renderer should guarantee on every
longform video, regardless of content.**

- **G1 — The frame is never still.** ≥40% of frames carry framing motion; motion p90 ≥10× a
  locked camera. A second motion layer always runs under the talking head.
- **G2 — Never freeze longer than ~20s.** Both pros cap at 18–24s; something (a creep, a
  reframe, a cutaway) always moves before then. (`strips/11_MACHINE_frozen_hold…` = the
  machine's 39s dead hold, the violation.)
- **G3 — Every animated zoom is EASED, never linear, never a mid-shot snap.** step_frac
  < 0.25, velocity peaks *inside* the ramp (τ 0.2–0.8): accelerate then settle. Both pros
  sit at 0.10–0.11. (`plots/05_easing_two_pros_vs_machine.png` — both pros ride the S-curve;
  the machine is flat-then-jump or straight-linear.)
- **G4 — Every push RECOMPOSES toward the face.** A ≥15% push carries a translation vector
  (both pros median ~290–320px@1080); it does not scale about a fixed center — that reads
  mechanical (R16). (Machine's one ramp: 0px, the tell.)
- **G5 — Perceptible magnitude.** Emphasis pushes are 20–40% linear (both pros median
  26–33%); subliminal creeps 3–8%. The machine's 15% median is undersized.
- **G6 — Hard steps are legal ONLY on a cut.** Both pros use instant scale steps, but they
  land on cuts (punch-on-cut), where the cut hides the step. A hard step *without* a cut
  reads as a glitch. (The machine's snaps also sit on cuts, so they're legal — the machine's
  failure is G1/G2/G3, not the punch-on-cut.)
- **G7 — No naked seam.** Every hard content jump / world-change is transition-covered (a
  white flash 83–125ms is the shared primitive). Zero butt-joints on identical framing.
- **G8 — Home framing is MODERATE; tightness is EARNED by zooms.** Both pros sit at ~22–24%
  face height — PRO #2 is only ~1pt tighter than its own 4K RAW (24% vs 23%) with **no
  measurable grade shift** (warmth/sat ≈ raw). The pros do **not** rely on a baked tight-crop
  or warm grade; they hold a moderate frame and create tightness *dynamically* via eased
  zooms. (`baseline/01_angle_edit_vs_raw.jpg`.)
- **G9 — Front-load the hook.** Treatment density ~2.35× in the first ~2 min, then eased to a
  cruise (R20).

> **Correction to prior doctrine:** the "baselineLook = tight chest-up crop + warm grade"
> emphasis (INTRO_MACHINE_VS_PRO_AUDIT queue #1) is **not** a durable invariant — neither pro
> edit leans on it (PRO #2's edit ≈ its raw in crop and grade). Keep the stage for genuinely-
> wide raws, but the engagement lever is **motion (G1–G7)**, not the static look.

---

## 3. VARIANTS — the adaptive layer (the brain decides per video)

Differed between the two pro edits → **content-driven choices, not doctrine.** Expose these
as knobs; don't hardcode them.

- **V1 — Graphics style axis.** PRO #1 = **cutaway-only** (never overlays the head; cuts to a
  whiteboard world). PRO #2 = **overlay-rich** (icon stacks, chest burns, chips beside the
  face). Already tracked as `graphics_style: cutaway-only | overlay-rich` (R14 contradiction).
- **V2 — Zoom size + ramp length track content type.** PRO #2 (a *demo*) runs bigger, longer
  ramps (median 33% / 5.7s, up to +33%/20s) under explanation; PRO #1 (a *story*) runs
  smaller, shorter pushes (26% / 3.8s). Demo bodies earn long slow ramps; story beats earn
  quicker punches (R22).
- **V3 — Transition palette.** PRO #1 = flashes **+ warm orange/pink light-leak washes**
  (16+27). PRO #2 = **flashes only** (10; no warm washes — its washes, if any, follow a
  different brand color, R24). Flash is the shared primitive; wash color/usage is a per-video
  brand token.
- **V4 — Cut rhythm.** PRO #1 = steady ~14/min (median shot 1.1s). PRO #2 = ~11.6/min but
  **bimodal** (bursts of sub-0.1s micro-cuts + longer 20–35s holds). Both keep the frame
  alive; the cut cadence itself is a style choice.
- **V5 — Direction bias.** PRO #1 leans **push-IN** (lean-in on claims, in:out ~1.33 over the
  full video); PRO #2 is **ramp-balanced** (punch:ramp ~11:11, opens on a punch-OUT). The mix
  of in/out/ramp is content-driven.

---

## 4. TRIGGERS — the WHEN (decision rules)

What in the content/audio/structure warrants which move. Each rule generalizes and cites its
evidence (this study + the semantic zoom/transition maps in LONGFORM_VISUAL_STUDY and
INTRO_MACHINE_VS_PRO_AUDIT). These are conditions the editor brain evaluates per beat.

| # | WHEN (trigger) | DO | Evidence |
|---|---|---|---|
| T1 | A **new claim / stressed assertion** lands | cut+reframe **punch-IN** (on a cut) or eased **push-IN** (mid-shot) | Rule 1; both edits push on emphasis |
| T2 | **Section reset / topic hand-off / new beat** | **punch-OUT** to wide (release tension) | Rule 2; PRO #2 opens on a punch-out |
| T3 | **Long continuous speech** — a story or demo/explanation stretch | slow **eased RAMP** underneath (the aliveness layer): subtle 3–8% for story, larger 20–35% over 15–22s for a demo body | Rule 4 / R22; G1 |
| T4 | The **single biggest line** (hook payoff, product reveal, closing callback) | **in→out BRACKET** (push-in held ~1.5–2s → release to wide); **≤3 per video** | Rule 3 (signature move) |
| T5 | A **hard content jump / retake seam / cut to a new visual world** | **transition cover** — white flash across the jump (wash for a softer world-entrance); never a naked seam | R15/R19; G7 |
| T6 | Speech **names a showable artifact** (a site, an old clip, a screen) | **cut to the artifact** (receipt cutaway, 1–4s; micro-montage for a list) | R17 |
| T7 | A **dense concept needs a second modality** | **cut to a graphic world** (cutaway) OR overlay — per the V1 style axis | R14/R24 |
| T8 | The frame has **held still ~15–20s** with nothing structural happening | force a subtle **eased creep / micro-reframe** *before* the ~24s ceiling | G2 (pros never exceed ~24s) |
| T9 | **First ~2 min** (the hook) | stack all of the above at **~2.35×** the body density | R20 / G9 |
| T10 | **Last ~60s** (outro, after the final content beat) | **stop** spending treatments | R24 |

**Anti-trigger (when to HOLD STILL):** a bare enumeration/agenda with no story weight earns
**nothing** — delivery + the existing motion layer carries it (both audits: the pro shows
nothing at the agenda list). Motion is spent on *meaning*, not on a metronome.

---

## 5. BEHAVIOR — the HOW (motion spec, as RANGES so it adapts)

Per move, the parameters the renderer draws from (ranges, not fixed values):

| Move | Magnitude (linear) | Attack→settle | Easing | Recompose | Notes |
|---|---|---|---|---|---|
| **Punch-in (on cut)** | 15–40% (≈+20–25% typ.) | instant (it's a cut) | n/a (cut hides it) | center on face | G6: cut-only |
| **Eased push-in (mid-shot emphasis)** | 15–40% | **1.5–6s** | **ease-out / ease-in-out**, step_frac<0.25 | **≥150px, typ. 250–400px** toward face | the "perceptible zoom" |
| **Creep ramp (story/demo body)** | 3–8% subtle · 20–35% demo | **8–22s** | smooth (smoothstep) | toward face | the aliveness layer (T3) |
| **Punch-out (section reset)** | to wide (baseline 1.0) | 0.8–4.7s | eased out | resolve to home | T2 |
| **Bracket (biggest line)** | up to ~50% in | hold ~1.5–2s → release | eased | toward face on the in-punch | ≤3/video |
| **White flash** | — | **2–3 frames (83–125ms)** | wash→white→cut | — | hard jumps; text exits inside |
| **Light-leak / brand wash** | — | **4–9 frames (167–375ms)** | fast-rise/slow-decay | — | softer entrance; color = brand token (V3) |

Home baseline (G8): face **~22–24%** of frame height; grade **subtle-to-none** (don't
over-crop or over-warm — the pros don't).

---

## 6. SMOOTHNESS BAR — the quality gate (frame-by-frame QC checklist)

Pass/fail thresholds a reviewer or `plan_lint_motion` applies to ANY longform cut. Derived
from the two-pro invariants; the machine fails 1–5.

1. **No frozen framing > 20s.** (Machine 39s — FAIL. Both pros ≤24s — PASS.)
2. **≥40% of frames carry framing motion** (motion p90 ≥ ~8× a locked-camera floor). A
   continuous creep must run under talking stretches. (Machine 19% / 3.7× — FAIL.)
3. **Every animated push is EASED:** step_frac < 0.25 **and** velocity peak at 0.2 < τ < 0.8.
   **Never linear, never a mid-shot snap.** (Machine 0.83 / τ=1.0 — FAIL.)
4. **Every push ≥15% RECOMPOSES toward the face:** ≥150px@1080 translation. **Never a
   fixed-center scale.** (Machine 0–59px — FAIL.)
5. **Perceptible cadence:** ~2–3 eased pushes/min (≥15% each) in the body, ~2.35× in the
   first 2 min. (Machine <1/min eased — FAIL.)
6. **No naked seam:** every hard content jump / world-change is flash/wash-covered; a
   same-framing butt joint is illegal.
7. **Moderate home framing (~22–24% face), tightness earned by zooms** — not a baked crop.

---

## 7. TEMPLATE USAGE RULES — when to reach for which, and how it must animate

- **`punch_in` static punch** → **only on a cut** (its instant snap is correct there;
  mechanical anywhere else). Magnitude 15–40%, center on the face.
- **`punch_in` ramp** → all mid-shot motion (emphasis pushes T1 **and** the T3/T8 aliveness
  creep). **MUST** set `ease:"smooth"` **and** `centerX/centerY` (face target). This is the
  single most-violated rule today (§8).
- **`punch_in` bracket** → biggest lines only (T4), ≤3/video.
- **`transitions` white-flash** → hard content jumps / retake seams (T5); **light-leak** →
  softer world-entrances, color following the brand (V3).
- **Cutaway / graphic world** → dense concept (T7) or named artifact (T6). Full-frame cutaway
  (PRO #1) vs overlay (PRO #2) is the **V1 style axis** the brain picks per video — not a default.
- **`baseline_look`** → optional; keep the home frame moderate (G8). Don't over-crop/grade.

---

## 8. PARAMETER / CODE CHANGE LIST

Two-pro-validated; unchanged in substance from the first pass. **The render primitives are
ready; the gap is the PLAN not using them.**

### PLAN-side (highest leverage)

1. **Emit `ease:"smooth"` on every ramp/bracket** — `graphics_planner_zoom.py`
   `_bracket_cand:123`, `_boundary_candidates:141`, `_stretch_ramps:164`. None set `ease`
   today → `punch_in.py` renders `ease="linear"` (`:138`) = the mechanical ramp measured.
   (Render support: `punch_in.py:259` `_eased`.) **Enforces G3.**
2. **Emit `centerX`/`centerY` (face target) on every ramp/bracket/push** — same sites +
   `_punch_cand:112`. Pull from `faceBBoxNorm`. (Render support: `punch_in.py:317`
   `_ramp_crop_exprs`.) **Enforces G4.**
3. **Lower the stretch-ramp floor + drop the "graphic-free" gate** —
   `producer_config.py:421` `ramp_min_stretch_s` is `30.0`; both pros creep under much
   shorter stretches and continuously. Drop to ~8–12s and let `_stretch_ramps` fire under
   shots that already carry a graphic. **Enforces G1/G2 (kills the 39s freeze).**
4. **Raise body zoom cadence + honor content type** — `producer_config.py:405`
   `by_mode.longform.cadence.body_per_min` is `2`; measured pro body ≈ 5.8–6.2 framing
   changes/min. Lift toward 4–6; let demo/explanation zones draw longer ramps (V2:
   `ramp_rate` band `0.3–1.8%/s`, magnitudes to ~35%). **Enforces G5.**
5. **Seam-cover every world-change; lint the smoothness bar** — extend `plan_lint_motion.py`
   (`:360` transitions, `:214` punchIns, `:402` baselineLook already present) to WARN on:
   frozen>20s, a mid-shot linear/snap ramp (no `ease`), a ≥15% push with no `centerX/centerY`,
   an uncovered same-framing seam. This makes §6 executable.

### RENDER-side — READY, not the bottleneck

`punch_in.py` already renders `ease="smooth"` smoothstep + per-frame face-recompose crop;
`transitions.py` renders frame-exact flash/wash+whoosh; `baseline_look.py` crops+grades. No
new primitive is needed for G1–G8. *(Optional nicety: add an `"ease":"out"` option beside
`"smooth"` in `punch_in._eased:259` — both pros favor ease-**out** on fast punches — low
priority; `smooth` already beats `linear` decisively.)*

### TEMPLATE-side — graphic design

Burned kinetic-text lane (word-by-word, 100–150ms/word eased) — machine burns 0; a
design/comp task, already queued (audit item 5). Lower priority for the "mechanical"
complaint than G1–G5.

---

## 9. Top 5 movement deltas (ranked by impact) + the one fix

1. **Frozen framing — no continuous eased-motion layer** (G1/G2): machine 3.7× the raw
   floor, one 39s dead hold; pros 14–24×, ≤24s. *The "stale" root.*
2. **Zooms don't ease or recompose** (G3/G4): machine snaps 7/9 (step_frac 0.83) / one
   linear-0px ramp; both pros ease ~80–100% and recompose ~290–320px. *"Not smooth."*
3. **Zoom cadence + magnitude too low** (G5): 9 pushes @15% vs 11–17 @26–33%.
4. **Seams uncovered** (G7): 4 flashes vs 10–16. *"Cuts don't read."*
5. **Fewer world-changes / longer holds:** overlaps the cutaway-lane gap (V1).

**Single highest-leverage fix:** make `graphics_planner_zoom.py` emit **eased
(`ease:"smooth"`), face-recomposing (`centerX/centerY`) ramps, densely, under the talking
stretches** (lower `ramp_min_stretch_s`, allow non-graphic-free). One change installs the
living second-layer both pros share and kills deltas 1–3 at once. **PLAN-side** — the
renderer already supports every knob.

---

## 10. Evidence index (Desktop `MOTION STUDY - pro vs machine/`)

- `plots/04_four_way_summary.png` — raw/machine/pro#1/pro#2 across the 4 core signals.
- `plots/05_easing_two_pros_vs_machine.png` — both pros ride the S-curve; machine snaps/linear.
- `plots/01_aliveness_trace.png`, `02_within_shot_scale.png`, `03_easing_shape_proof.png` — pair-1 detail.
- `strips/10…` pro#1 eased ramp · `20…` pro#2 eased ramp+recompose · `11…` machine 39s frozen hold ·
  `12…` pro white-flash · `13…` machine hard snap.
- `baseline/01_angle_edit_vs_raw.jpg` (edit ≈ raw crop/grade) · `00_baseline_side_by_side.jpg`.
- `README.txt` — operator summary.

**Honest limits:** N=2 pro editors (invariants are priors to re-confirm on a 3rd pair). The
warm-wash detector is warm-keyed → PRO #2's brand-colored washes may be undercounted (V3).
Cross-video grade is confounded by cutaway content; the same-footage PRO #2-vs-RAW numbers
are the clean read. "Frozen" counts static graphic cards, so talking-head motion is
understated — the pro-vs-machine gap is if anything larger.
