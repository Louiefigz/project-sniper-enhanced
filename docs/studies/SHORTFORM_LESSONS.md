# SHORTFORM LESSONS — shorts curriculum + breakdown reasoning (baked 2026-07-11)

Two shorts studies folded into the PRODUCER's deterministic pipelines:

- **SF1** — a Resolve shorts-editing tutorial where every taught rule was
  also MEASURED in the editor's own demo timeline (hook stack, caption
  spec, J-cuts, track architecture).
- **SF2** — a produced outdoor client-reel/commercial breakdown (30.5s
  reel, frame-verified), taught with the editor's reasoning per decision.

Every rule carries its evidence stamp (timestamps / frame refs from the
source reports) and its encoding. Conflicts with our measured shorts
grammars (jadenly / caleb / angela / talking-head) are adjudicated in §9 —
the EC2 R12 audience-experience selector (see `EDITCRAFT_LESSONS.md` §9)
governs all of them. **SF2 is a THIRD PACE POLE** and is encoded as its own
pacing profile; its motion budget never bleeds into desk talking-head
presets.

Encoding map: `producer_config.MODES["short"]` (`hook_stack`,
`pacing_client_reel`), `BROLL["burst"]["short"]`,
`AUDIO["riser_bridge_s"]`, FAILURE_LEDGER LESSON-022/023/024. Additive
only; no default changed.

---

## 1. The hook zone (0 → ~2.5–3s)

### 1.1 Hook stack (SF1, TAUGHT + MEASURED-IN-DEMO)
A shorts hook zone is a **5-element simultaneous stack**: zoom-OUT reveal
at t=0, 2-line mixed-typography text lockup, blur/treatment layer BEHIND
the text, ~1.2s riser SFX resolving exactly at body start, and **NO
captions** (delete auto-caption cues under the hook). CORROBORATED for the
text-owns-the-hook part (Jaden H2/T1, Caleb H1); zoom-out + riser are
**promo-pole additions**.

### 1.2 Hook typography (SF1, MEASURED)
The lockup is two-tier — plain white bold line + payload word in accent
style (bold-italic + glow; blue here, yellow in Jaden — **accent color is
a skin choice, the two-tier structure is the invariant**). ~5–7%H per
line, chest band, never covering the face. CORROBORATED (Jaden T1).

### 1.3 Hook = one continuous shot (SF2, cross-creator HIGH)
ZERO cuts in the hook; all hook energy lives in staged text + one zoom
move. Frame-verified 0 cuts in reel 0–4.4s with ~6 text events. Agrees
Jaden H2 (6/6), Caleb H2 (3/3). Plan the hook camera move at the SHOOT
(pan-up/reveal) so the edit can stage word-group reveals over it
(SF2 1:01–1:17).

### 1.4 Hook zoom-out reveal + frame-zero legality (SF2, 8:24–10:13)
Adjustment layer above all text, scale **~1.3x→1.0 over ~60 frames**, ease
out-cubic hand-shaped to an S-curve. **HARD RULE: frame zero must not be
visibly over-zoomed** — a 2.08x start was rejected on sight; shipped ~1.34
(Fusion readout Size 1.339874).

### 1.5 Hook word staging (SF2, timeline-verified t=443)
Each word-group (This / VOLUSIA COUNTY / Mansion / EMBARRASSING / until we
showed up) is its own text clip with staggered starts, **landing every
~0.5s**, word-locked to the VO. TEXT-BEHIND-SUBJECT (magic-mask sandwich)
is legal ONLY in wide outdoor scenes with subject <~30% of frame and real
scene depth (SF2 4:27–5:47) — in tight talking-head the cutaway/zone
doctrine stands (adjudicated vs `feedback_pro_graphics_are_cutaways`).

### 1.6 Riser bridge (SF1, new device)
~1.2s riser under the hook, ending exactly where the body starts; level
pulled well down. No coverage in measured corpora — adopted as an
**optional produced-treatment SFX slot**.

**Encoded:** `MODES["short"]["hook_stack"]` (zone, captions-off,
zoom-out scale band + frame-zero cap, lockup invariant, riser),
`AUDIO["riser_bridge_s"]`, LESSON-022/024. The existing `hook_window_s`
3.0 and HOOK_CARD comp defaults are unchanged.

## 2. Captions

### 2.1 Caption spec (SF1, MEASURED — exact numbers)
Auto-captions at max 10 chars/line, single line, 0-frame gap → 1–3 word
cues; styled once at TRACK level: serif-adjacent font, white, ~3.3%H,
stroke 1, center-x, MID-FRAME (~0.55–0.60H), plain preset (no karaoke).
**CONFIRMS the Jaden/Caleb mid-frame whisper band as the 3rd independent
source** — karaoke remains off-style in every measured shorts grammar.
Our `CAPTIONS["WHISPER"]` (2.2%H, band 0.60–0.64) is a sibling SKIN of the
same family — defaults unchanged (§9.5).

### 2.2 Captions start post-hook (SF1) + caption-vs-graphic law (SF2)
Captions run from ~3s (first body word) to end; the hook zone shows the
designed lockup INSTEAD. Never double styled hook text and captions in the
same window. SF2 generalizes it: **captions are generated LAST, then cues
are DELETED wherever a designed text moment exists** — captions live only
in open space/time (frame-verified: no frame shows captions + shout text
simultaneously). Gate-encodable: never render a caption cue overlapping a
shout window. **Encoded:** `hook_stack["captions_in_hook"] = False` +
LESSON-022; gate roadmap: a caption/graphic overlap check in the captions
stage (shorts already suppress burned captions under own-screen takeovers
in the monolithic path).

### 2.3 Whisper caption spec (SF2)
White mixed-case (italic here), 1–3 word groups, replace every ~0.5–1.0s,
floated into per-shot open space near chest/shoulder — total on-screen
churn measured **92.9 states/min** (top of Jaden 51–89 / Caleb 72.5–87
bands). No karaoke, no box (3rd corroboration). **Encoded:**
`pacing_client_reel["state_changes_per_min"]`.

### 2.4 Emphasis is EARNED per word (SF2, 7:50–14:22)
Only words the script wants remembered get a styled treatment — stop-motion
preset on action phrases, partial-blur zoom on outcome phrases,
delay-up-slide on secondary hook lines; everything else stays whisper
captions. **YELLOW = PAYLOAD WORD ONLY: exactly 3 accent words in 30s**
(the location, the outcome, the CTA verb) via character-level styling.
Cross-creator HIGH (Jaden T1 yellow lockups; whisper tier-A amber).
**Encoded:** `pacing_client_reel["accent_words_per_30s"] = 3`; LESSON-023.

## 3. Cut grammar

### 3.1 Silence-chop density ≠ punch-cut density (SF1, MEASURED)
A raw talking take chopped to zero dead air yields **~26 seam cuts/min**
(7 segments/14s from a 2:16 take, ~8–9x compression) — but these seams are
MASKED (J-cuts, b-roll, punch-ins), unlike Jaden's felt punch-cuts. **Do
not conflate masked-seam density with punch-cut density when linting
pace.** The pacing lint counts DISCRETE VISIBLE changes — a masked seam
under b-roll is one change, not two. Doc + LESSON-024 context.

### 3.2 J-cut rule (SF1, TAUGHT — 3–4 frames; AXIS, not law)
On every retained seam, the next clip's audio starts 3–4 frames early on a
second audio track; start the early audio on a phrase start read from the
waveform — never mid-sentence. Apply ONLY in clean/invisible-seam
treatments; **OFF for punch-cut grammar** (Jaden — cuts ARE the energy)
and **restraint grammar** (Caleb keeps breath gaps, zero J/L).
**Encoded:** doc + adjudication §9.3 (the cut engine renders butt joins
with a 15ms audio crossfade today; J-cut leads are a named roadmap for the
clean-seam treatment).

### 3.3 Punch-in on clip change (SF1, TAUGHT)
A small punch/zoom-in when moving to the next clip; the closing clip may
take a slow zoom-out. CORROBORATED: this IS our shorts rhythmic-zoom
grammar (`MOTION["zoom"]["by_mode"]["short"]` — zoom IS the cut). No
change.

## 4. B-roll micro-rules (SF1 + SF2)

1. **Word-matched**: b-roll is matched to the exact spoken phrase
   (trigger→content) — corroborates `BROLL["trigger_latency_s"]` and the
   receipts lane word-locking.
2. **Action frame**: the cutaway starts ON the action frame, not before it
   (brain picks `assetStart`; LESSON-025's shorts corollary).
3. **Full-frame V2 over CONTINUOUS A-roll audio** — already how
   `broll/broll_insert.py` composites (video-only riders).
4. **Audio hygiene**: strip ALL b-roll audio in one bulk operation at
   import — `BROLL["vo_continuity"]`.
5. **Burst density datum**: 3 cutaways in ~4s (~1.3s each) mid-reel —
   encoded `BROLL["burst"]["short"]` (§9.2 for the spacing adjudication).
6. **B-roll inherits the grade AND the motion language** (SF2): copy the
   A-roll grade onto every b-roll clip and reuse the same zoom-out
   animation — one motion vocabulary per short
   (`BROLL["insert_polish"]`).
7. **AI-reframe b-roll subject-centered** for 9:16 instead of static crops
   (SF2) — our face-aware reframe already does this for sources; pool
   b-roll reframing is roadmap.
8. **B-roll is the PROOF layer** (SF2): cover spoken process claims with a
   4–5 clip montage (~6s window), each entry word-locked; punch-in on the
   proof/testimonial beat when the credibility payoff lands.

## 5. Energy + emphasis budget (the client-reel pole)

- **ONE ENERGY PEAK PER SHORT** (SF2): a single light-leak/CRT overlay
  burst (composite Add) + riser SFX, placed EXACTLY on the hook's promise
  resolution ("until we showed up", reel ~3.1–4.5s) — **not on every
  cut**. Agrees MEASURED_EDIT_GRAMMAR "flash covers energy beats"; never
  import into jaden/caleb paces (their measured transition count is zero).
- Motion budget: **2 zoom-outs + 1 punch-in + 1 overlay per 30s** — this
  is the whole per-reel allowance.
- **CTA grammar** (SF2 17:08): end the client reel with the client's offer
  + strategy-call link + subject POINTING DOWN + accent action word
  ("Click the link!"); no channel outro inside the reel.
- **Hand-drawn accent layer**: yellow arrow/scribble pointing at the
  referenced object during the hook; arrows layer BELOW all text effects.

**Encoded:** `MODES["short"]["pacing_client_reel"]` (floors + advisory
budget keys); LESSON-024.

## 6. Treatment-gated devices (promo pole ONLY)

- **Text-entrance recipe** (SF1, TAUGHT): keyframe rise over 20 frames
  (~0.67s @30fps), ease-out cubic, ~4-frame smoothing handle, optional
  glow. **CONFLICT with measured top-tier grammars** (Jaden pop ≤83ms,
  nateherk in-place opacity 120–250ms, Caleb zero animation) — legal only
  under a flashy/promo treatment; calibrated presets keep pop/opacity
  tokens (§9.4).
- **Light-leak/film-burn seam cover** (SF1, TAUGHT): Add-composite overlay
  into the next clip. Matches the LONG-FORM cut-cover family; OFF-style
  for jadenly (C2: 21/21 hard cuts) and caleb shorts. Only in
  produced/flashy shorts treatment.
- **Music at platform** (SF1, operational): for IG distribution, prefer
  trending audio added in-app at post time (or a free-copyright track)
  over a baked bed — a DISTRIBUTION choice that coexists with the −14 LUFS
  baked-bed doctrine for other styles. Encoded:
  `pacing_client_reel["music"] = False` (bed added at the platform).

## 7. Process curriculum (speed system)

- **Hook text only** (SF2): script exactly one line — the hook; the body
  is spitballed by the subject. Hook formula: named location +
  status/number signal + negative state + "until we" transformation.
- **Target length ~30s** for client-reel shorts (timeline-verified 30.5s).
- **Color grade FIRST, one restrained LUT** — grade before any cutting
  (matches EC1's enhance-before-cut order); reject over-saturating looks.
- **Speed doctrine** (SF1): the whole reel edit is ~10 minutes because
  everything reusable is pre-built (asset pack: text animations, overlays,
  SFX) and the cut loop uses exactly 2 bindings. System analog: comp
  templates + brand tokens; never hand-author per video — exactly our
  comps + `tokens.css` model.
- **Template everything reusable** (SF2): saved template timeline with
  hook text stacks + comment-card comps, copy-paste per client reel —
  agrees our comp+parameterize doctrine.
- **Track architecture** (SF1, MEASURED): subtitle track on top /
  hook-title layer / effect-backdrop + b-roll / A-roll video / A-roll
  audio / J-cut leads / SFX-riser — graphics and captions live ABOVE
  footage as independent layers, matching our output-space overlay
  compositing model. Corroboration; no change.
- **Vertical setup** (SF1): 1080x1920 timeline before any editing —
  matches `CANVAS`.
- **Iterate taste in the edit loop** (SF2): author→look→revise convergence
  (presets rejected on sight, layout re-staged 3x) — matches SKILL step-4
  multi-round convergence.
- **ANTI-RULE (3rd cross-creator sighting):** speed-over-polish ships
  typos ("Houeses" on screen, reel 7–8.5s). Do NOT replicate typos — run
  FRAME.IO REVIEW on every render; DO replicate fast hand-set text over
  over-designed cards.

## 8. The third pace pole — `pacing_client_reel`

SF2's SCOPE GUARD verbatim: "this is a THIRD PACE POLE (produced outdoor
client-reel/commercial) — 2 zoom-outs + 1 punch-in + 1 overlay per 30s
CONFLICTS with measured jaden (zero transitions) and caleb (zero zoom);
keep it as its own pacing profile, do not bleed its motion budget into
desk talking-head presets."

Encoded as `MODES["short"]["pacing_client_reel"]`, selected by
`target.pace == "client-reel"` (the `_pacing_profile` lookup maps dashes
to underscores). Floors sit below the measured values as with every pack;
the budget keys are advisory doctrine the brain/skill reads.

## 9. Conflicts with our shorts grammars — adjudicated

| # | conflict | adjudication |
|---|---|---|
| 9.1 | SF2 client-reel motion budget (2 zoom-outs + 1 punch + 1 overlay + 1 energy peak / 30s) vs jadenly (zero transitions, punch-cut energy) and caleb (zero zooms) | New third pace pole `pacing_client_reel`; budgets scoped to it, selected only by `target.pace`. R12: different audience expectation (commercial/promo vs desk talking-head). Nothing bleeds. |
| 9.2 | SF1 b-roll burst (3 cutaways in ~4s) vs `MODES["short"]["broll_min_spacing_s"]` = 8.0 | Spacing default KEPT for lone purposeful inserts (it was never lint-enforced — advisory cadence). Bursts are a beat-attached exception (EC1: bursts attach to montage/proof beats, not positions), recorded in `BROLL["burst"]["short"]`. |
| 9.3 | SF1 J-cut law ("on every retained seam") vs jaden punch-cut grammar and caleb breath-gap grammar | AXIS, not law (as the study itself flags): clean/invisible-seam treatments only; OFF elsewhere. Cut engine unchanged (15ms equal-power crossfade stays); J-cut audio leads = named roadmap for the clean-seam treatment. |
| 9.4 | SF1 text-entrance 20-frame rise (taught) vs measured pop ≤83ms / 120–250ms opacity / caleb zero animation | Treatment-gated: legal only under flashy/promo treatment; calibrated comp presets keep their pop/opacity tokens. Not added to any default. |
| 9.5 | SF1 caption spec (~3.3%H, band 0.55–0.60H, serif-adjacent) vs `CAPTIONS["WHISPER"]` (2.2%H, band 0.60–0.64, Inter) | Skin variance inside one family; third independent corroboration of the mid-frame whisper band + no-karaoke. WHISPER defaults unchanged; a future "SF1 skin" may override per-plan. |
| 9.6 | Karaoke off-style in every measured grammar (SF1/SF2/R11) vs `MODES["short"]["captions_style"]` default `"karaoke"` | Default KEPT: it is the operator's base/brand default with its own evidence line (TikTok official pacing); every measured style pack overrides to whisper/minimal via `captions.style`. Flagged so the operator can flip the default deliberately — not silently by a bake. |
| 9.7 | SF1 hook riser + zoom-out (5-element stack) vs jaden/caleb hooks (text-owns-the-hook, no riser/zoom) | The lockup/text part is the cross-style INVARIANT (corroborated); zoom-out + riser are promo-pole additions gated behind produced/flashy treatment (`hook_stack` records both tiers). |
| 9.8 | SF2 text-behind-subject (magic-mask sandwich) vs `feedback_pro_graphics_are_cutaways` (never panels over face) | Condition-scoped as the study itself adjudicates: legal only in wide OUTDOOR scenes, subject <~30% of frame, real depth; tight talking-head keeps the cutaway/zone doctrine. |
| 9.9 | SF1 hook captions OFF vs shorts `captions_burn: True` | Compatible: captions still burn for the body; the hook zone's cues are deleted (designed lockup instead). `hook_stack["captions_in_hook"] = False` + LESSON-022; renderer wiring for cue deletion under designed-text windows is the named gate roadmap. |

## 10. Encoded-where map

| rule | encoding |
|---|---|
| hook stack, zoom-out scale + frame-zero cap, riser, captions-off-in-hook | `MODES["short"]["hook_stack"]`, `AUDIO["riser_bridge_s"]`, LESSON-022/024 |
| client-reel pole floors + motion/emphasis budget | `MODES["short"]["pacing_client_reel"]` (selected by `target.pace`) |
| b-roll bursts, audio hygiene, grade/motion inheritance | `BROLL["burst"]["short"]`, `BROLL["vo_continuity"]`, `BROLL["insert_polish"]` |
| caption/designed-text separation, payload emphasis economy | LESSON-022, LESSON-023 |
| one-energy-peak + hook one-shot legality | LESSON-024 |
| typo anti-rule | FRAME.IO REVIEW QC pass (already a standing tool) |
| J-cut axis, text-entrance recipe, light-leak | doc-only, treatment-gated (§9.3/§9.4) |
