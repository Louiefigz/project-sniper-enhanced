# MODULE CARDS — card catalog, variety doctrine, screenshare grammar

Companion to `MODULE_STUDY.md` (pipeline/QC + transition grammar + adoption plan). This doc
owns the CARD layer: every graphic form in the reference, the design-system rule that governs
their variety, the screenshare chapter's grammar, and the ranked build list against our
catalog. Date: 2026-07-11. Source: `_references/module/J_jswzXhYJA.webm` (323.4s,
1920x1080@30, "GPT-5.6 Sol made this entire video").

Evidence base: 82 fingerprint states + 6 contact sheets covering all states + a 36-frame
0.5s-step pass over t=94.5–112.5 (which found one card the 2fps dedup hid) + 17 full-res
LOOKs + three 8fps build sheets (13–17s, 52–55s, 185.6–188.6s); screenshare chapter measured
by frame-diff over 272 half-second samples + cursor-position tracking + glyph-height
projection profiling. Timing ±1 frame (~40ms). N=1 video — priors, not laws.

Headline numbers: **7 hard cuts in 323s (1.3/min); graphics on screen ~93% of runtime after
t=13.5s; 20 distinct card forms across 23 graphic windows.** Variety comes from CARDS, not
cuts.

**Method note (for future studies):** the 2fps fingerprint dedup MISSED form #13 (vendor
proof cards, 104–110.5s) — it hid inside state 34's window and was found only by the
0.5s-step contact pass. When cataloging cards, run a fine-step contact pass over any long
"static-looking" window before declaring it one state.

---

## 1. Card catalog

### 1.1 The two chassis (every editorial card lives in one)

| Chassis | Mechanics | Palette / text | Semantic role |
|---|---|---|---|
| **CREAM SPLIT-PANEL** | cream panel wipes in from the LEFT edge (~0.3s, hard vertical edge), ~33–40% width; footage stays FULL-FRAME right | `#f0f0e6` panel, ink `#1a1a1a` text, cyan/green accents sparingly | input / plan / process narration (what was asked/done) |
| **DARK TAKEOVER** | near-black full-frame + faint grid; footage scales INTO a rounded (r≈24) 9:16 PIP right (~28%W × 89%H, drop shadow) in one continuous ~0.4s move; graphics column left ~62% | `#0a0d0e`, white text, lime `#b9f537` + cyan `#4fc3e8` accents | system / results / statements (power, scores, theses) |

Shared grammar on both: `• MONO-CAPS EYEBROW` (colored dot) → HEAVY-SANS THESIS-SENTENCE
headline ("The numbers moved.", "Words set the cut.") — 2 lines max, second line or key
phrase in accent, period always → 1–2 line gray explainer → content modules landing in
narration order. Amber is reserved: limits / failures / search targets only. The face is
NEVER covered (full-frame beside cream, PIP inside dark). Cream↔dark alternate 8 times
between 13.5–187s — the alternation IS the chapter rhythm (STUDY §3 rank 11).

### 1.2 The 23 graphic windows — 20 distinct forms

| # | Form (chassis) | Timestamps | Anatomy | Info-display pattern | Content type → why this form | Build animation | Uses |
|---|---|---|---|---|---|---|---|
| 1 | Terminal-prompt takeover (standalone) | 2.5–5.0s | full-screen charcoal rounded panel; ~28 lines white monospace of the actual `/goal` prompt + blinking cursor; footage dimmed, head/hands at edges | raw text block | claim/evidence — the input artifact shown verbatim | pops on as one block | 1 |
| 2 | HUD viewfinder (standalone) | 5.5–13.0s | white corner brackets ×4 + top-left chip `• SOURCE ANALYSIS 00:00:00` (green dot, dark bg, mono) | frame-the-footage meta chrome | meta/framing — footage "under analysis" | instant on; persists under #3 | 1 |
| 3 | Metadata lower-third (dark panel) | 7.0–13.0s | bottom-left panel: cyan mono eyebrow `PRODUCTION DISCLOSURE`; bold white 2-line `NATE DID NOT RECORD THIS`; divider; KV rows `ON SCREEN → NATE AVATAR V`, `WORKFLOW → AI GENERATED` (green) | headline + KV ledger | disclosure claim — facts as key→value receipts | eyebrow → headline → rows | 1 |
| 4 | Status/queue cards (cream) | 13.5–15.2s | `• INPUT / ONE PROMPT`; white sub-card `PROMPT_001 \| RECEIVED` (cyan left border + status), lime connector down to `PRODUCTION QUEUE \| 1 ITEM` | pipeline-intake ledger | process state — an item entering a system | panel wipe → card → connector → card | 1 |
| 5 | Session ledger (dark) | 15.5–25.5s | `• ACTIVE CODEX SESSION`; `GPT-5.6 SOL / ULTRA(lime)`; ledger rows `` model "gpt-5.6-sol" → VERIFIED(lime) ``, `` reasoning "ultra" → ACTIVE ``; thin cyan tree connectors branch to 4 numbered chips `01 WORDS • … 04 QA •` | KV ledger + fan-out chip row | config/spec facts — settings with live status tags | rows stagger, then chips fan out | 1 |
| 6 | Vertical timeline (cream) | 26.0–32.0s | `• OPENAI RELEASE / PREVIEW TO GA`; nodes JUN 26 (cyan ring) `LIMITED PREVIEW` → JUL 09 (lime ring) `GENERAL AVAILABILITY` on a cyan spine; outlined tag `• AVAILABLE BROADLY` | dated timeline | factual chronology — two dated events | node-by-node down the spine | 1 |
| 7 | Parallel agent grid (dark) | 32.5–45.5s | `• ULTRA ORCHESTRATION / ONE RUN. FOUR AGENTS.(lime)`; ledger bar `DEFAULT PARALLELISM 4 \| • COORDINATING`; connector drops to 4 equal columns AGENT 01–04, lime underlines; footnote chip `• OPENAI: FOUR AGENTS IN PARALLEL BY DEFAULT` | org-chart / fan-out grid + source footnote | parallel process — concurrency shown as columns, claim receipted | columns stagger 80–120ms after ~900ms narration wait (STUDY MG-2) | 1 |
| 8 | Numbered step list + rail (cream) | 46.0–52.0s | `• LONG-HORIZON WORK / One thread. Every handoff.` + sub; 5 white rows `01 Research→SOURCE … 05 Inspect→VERIFY` (cyan mono right-tags); cyan dot rail linking rows | step sequence w/ per-step status tag | linear process — ordered steps, each with an outcome tag | rows land in narration order | 1 |
| 9 | Benchmark comparison (dark) | 52.5–67.0s | `• OFFICIAL REPORTED SCORES / The numbers moved.`; card `TERMINAL-BENCH 2.1 \| SCORE (%)`: SOL ULTRA lime bar → 91.9 vs GPT-5.5 gray bar → 85.6; delta chip `+6.3 POINTS`; SECOND card slides in at 58s: `BROWSECOMP` + boxed cyan `92.2%` | comparison bars + delta chip + boxed metric callout | proof numbers vs baseline — hero vs comparison hierarchy | ghost headline → labels → tracks → lime fill ~0.75s (value lands WITH tip) → gray fill → delta chip only after both | 1 |
| 10 | Checklist build (cream) | 67.5–78.0s | `• PRODUCTION, NOT A PROMPT / Six obligations. One outcome.`; 6 rows land one-by-one `01 Research launch … 06 Check result`, each with lime `OK` badge; footer `• CHAIN RESOLVED`(lime) | checklist w/ pass badges + resolution footer | process→proof — obligations that resolve | rows one-by-one, badges with rows, footer last | 1 |
| 11 | Big-number scoreboard (dark) | 78.5–94.0s | `• SMALL LOCAL CHECK`; chip row ONE RUN / 13 TASKS / THIS MACHINE; giant lime `97%` + label; 3 outlined stat tiles 7 WINS / 5 TIES / 1 LOSS; 13-chip strip color-coded (01–07 lime win, 08–12 teal tie, 13 amber loss); footer `LIMIT(amber) \| Not proof it wins everything.` | hero metric + stat tiles + per-item color ledger + limitation footer | single number + distribution + honest caveat | hero → tiles → chip sweep (~1 per 85ms, STUDY MG-4) → limit footer; strip lands seconds after the 97% | 1 |
| 12 | Bullet-bar chart (cream) | 94.5–104s | `• VOICE CONSISTENCY / Four short generations.`; axis `0 … 60 SEC PRODUCTION CAP`; 4 lime-on-gray bullet bars 40.4/48.1/47.4/45.4 vs AMBER threshold tick at the cap; footnote `• 4 OF 4 UNDER 60 SEC`(lime); spectrum rail `BEGINNING —— VOICE HELD —— END` | measured bars vs limit line + verdict footnote | measurements vs a limit — every bar under the amber tick | bars fill, verdict footnote last | 1 |
| 13 | Vendor proof cards (cream) | 104–110.5s | `• AUTHORIZED PIPELINE / Voice becomes performance.`; white card `ELEVENLABS` + cyan waveform glyph + row `NATE VOICE CLONE \| AUTHORIZED`; second card `HEYGEN` + avatar glyph row | tool-identity rows w/ authorization status | tool/vendor claim — who did what, with permission | card-by-card (hidden from 2fps dedup; found by 0.5s pass) | 1 |
| 14 | UI-diff evidence (dark) | 111–122.5s | `• MOTION ENGINE CONTROL / API draft. Avatar V(lime) final.`; TWO embedded real-UI screenshots w/ header bars `API DRAFT \| AVATAR III(amber)` →(lime arrow)→ `EDITOR OUTPUT \| AVATAR V(lime)`; 4 step chips (04 lime-highlighted); ribbon `UI EVIDENCE HEYGEN STUDIO · PROJECT CAPTURE · JUL 09 2026` | before/after screenshots + step chips + receipt | mechanism proof — real captures, not illustrations | panels → arrow → chips → ribbon | 1 |
| 15 | Transcript-anchor diagram (cream) | 123–141.5s | `• PHRASE-TIMED EDIT / Words set the cut.`; card `TRANSCRIPT \| 117.02S` with word chips, `HYPERFRAMES` cyan-highlighted; cyan waveform bars; playhead line + diamond `• BEAT MARKER SNAPPED`; lime confirm `✓ AVATAR LAYER LOCKED`; legend chip `• WORD ONSET` | annotated domain diagram (word-level timeline) | mechanism — how words drive cuts, drawn as its own domain object | modules in narration order | 1 |
| 16 | Scanner lanes (dark) | 142–159.5s | `• INDEPENDENT ADVERSARIAL QA / Try to break the render.`; 4 lanes `LANE 01 Timing … LANE 04 Avatar presence`, each a thin track with a cyan dot that CREEPS + amber outlined tag `SEARCH FOR DRIFT / OVERFLOW / MISMATCH / GAPS` | parallel monitored lanes (animated scan) | QA process, ongoing — motion = searching | lanes land, then dots creep continuously through the hold | 1 |
| 17 | Loop process (cream) | 160–169s | `• DESIGN JUDGMENT TEST / Inspect. Fix. Render.`; 3 rows `01 Inspect → LOOK / 02 Fix → REVISE / 03 Render → REPEAT`; CURVED cyan arcs from row 3 back to row 1; receipt `CLAIM SOURCE: OPENAI · GPT-5.6 RELEASE · JUL 09 2026` | cyclical step list + receipt | mechanism, iterative — the visible loop-back arc says "repeats" | rows → loop arc → receipt | 1 |
| 18 | Horizontal node pipeline (dark) | 169.5–179.5s | `• ONE INSTRUCTION TO FINISHED VIDEO / The chain changed. The outcome held.(lime)`; 6 connected tiles `01 PROMPT → 02 ELEVENLABS VOICE → 03 HEYGEN AVATAR V → 04 HYPERFRAMES EDIT → 05 INDEPENDENT QA (active cyan dot) → 06 FINISHED VIDEO` | linear pipeline w/ active-node marker | process summary — the whole chain in one glance, "you are here" dot | tile-by-tile along the chain | 1 |
| 19 | Statement card + kicker (dark) | 180–185.5s; 186–187.3s | eyebrow `GPT-5.6 SOL · ULTRA`; display `Hold the outcome. / Adapt the chain.(cyan)`; gray subtext; CYAN→LIME gradient rule. Kicker variant: `THIS IS / DAY ONE.`(lime), no subtext, tiny mono pipeline footer | pure thesis | claim/thesis — no data, just the sentence | ghost-resolve; kicker swaps IN PLACE on the same chassis (ghost-out → ghost-in, PIP never moves) → HARD CUT to screenshare | **2** |
| 20 | Screenshare + PIP | 187.5–252s (VS Code); 252.5–291.5s (OpenRouter); 292–323s (VS Code) | full-bleed native capture + rounded PIP bottom-left (~8% frame area) + yellow cursor halo + in-text lime number highlights + live teal selection sweep + `Goal achieved (2h 32m)` status bar | primary-source capture with live highlighting — the "card" IS the evidence | evidence — cited numbers shown in their native app | hard cut in, PIP+cursor pre-placed; scroll is the cut (see §3) | **3** |

### 1.3 Build animation grammar (measured @8fps)

- **Ghost-resolve text**: headline enters as low-opacity gray ghost → resolves to final
  color in ~0.25s. Every card headline. (= STUDY §3 rank 4, opacity-first.)
- **Module stagger**: eyebrow+headline first, then modules land in NARRATION order
  0.4–0.9s apart — and cards keep EVOLVING mid-hold: 2nd sub-card at 58s inside the
  52.5–67s window; checklist grows 3→6 rows; the 13-chip strip appears seconds after the
  97%. A card is a live surface, not a static slide. (= STUDY §3 rank 1.)
- **Bar fills** 0.75–1.0s, value label lands WITH the tip; delta chip only AFTER both bars
  (= STUDY §3 rank 7 speed-hierarchy). Scanner dots creep continuously — motion during hold.
- **Scene transitions**: cream = left-edge wipe ~0.3s; dark = darkness takeover while the
  footage itself scales into the PIP (~0.4s — the footage IS the transition); same-chassis
  swap = in-place ghost swap; into screenshare = hard cut. Time to fully-built card
  ≈1.2–2s; holds 4.5–18.5s.
- **Provenance is a first-class module**: `UI EVIDENCE HEYGEN STUDIO · PROJECT CAPTURE ·
  JUL 09 2026` (#14), `CLAIM SOURCE: OPENAI · GPT-5.6 RELEASE` (#17), `• OPENAI: FOUR
  AGENTS IN PARALLEL BY DEFAULT` (#7), `LIMIT | Not proof it wins everything.` (#11).
  Receipts AND caveats land last in the build. (= STUDY §3 rank 9 + §5.6 claims contract.)

### 1.4 The mapping rule (content type → card form)

This is the planner-facing lookup. The brain classifies the beat's content; the form follows.

| Content type of the beat | Card form | Reference |
|---|---|---|
| Thesis / claim | statement card (dark, accent 2nd line, gradient rule); punch version = kicker | #19 |
| Config / spec fact | KV ledger rows + status tags (VERIFIED / ACTIVE) | #3, #5 |
| Linear process | numbered step list w/ per-step tags (cream) or horizontal node pipeline (dark, active dot) | #8, #18 |
| Parallel process | fan-out grid (columns) with connector tree | #7 |
| Number vs baseline | comparison bars + delta chip | #9 |
| Single proof metric | boxed metric callout or hero big-number + stat tiles | #9, #11 |
| Per-item outcomes | color-coded chip strip (win/tie/loss) | #11 |
| Measurements vs a limit | bullet bars + amber threshold tick + verdict footnote | #12 |
| Chronology | vertical dated timeline | #6 |
| QA / verification | scanner lanes (ongoing) or checklist w/ OK badges (resolved) | #16, #10 |
| Mechanism | annotated domain diagram, loop list, or UI-diff before/after | #15, #17, #14 |
| Tool / vendor claim | tool-identity card w/ authorization row | #13 |
| Cited external number | screenshare + cursor park (never a card — show the source) | #20, §3 |

---

## 2. VARIETY DOCTRINE — the design-system rule

**20 distinct card forms in 323s. Structural repeats: statement ×2, screenshare ×3 — every
other layout appears EXACTLY ONCE.** The viewer never sees the same information shape twice.
Reuse lives at the TOKEN level, never the LAYOUT level.

### Constant (the brand layer — reuse freely, always)

- Palette: cream `#f0f0e6` / ink `#1a1a1a` / near-black `#0a0d0e` / lime `#b9f537` /
  cyan `#4fc3e8`; amber = warnings/limits/losses ONLY.
- Mono-caps eyebrow with colored dot; heavy-sans thesis-sentence headline with accent
  2nd line and a period; gray explainer line.
- 1px-stroke rounded cards; tree/rail connectors; grid texture on dark.
- Provenance ribbons (UI EVIDENCE / CLAIM SOURCE / footnote chips) on every factual card.
- Face never covered: full-frame beside cream panels, PIP inside dark takeovers.
- The 2-chassis alternation (cream↔dark, 8 flips in 13.5–187s) as chapter rhythm.
- Build grammar (§1.3): ghost-resolve, narration-order stagger, payoff-last.

### Varies (the information layer — never repeat within a video)

- The internal STRUCTURE of the card: ledger vs bars vs grid vs lanes vs timeline vs
  diagram vs chip strip — chosen per beat by the mapping rule (§1.4).
- Accent emphasis alternates semantically: lime = result, cyan = process (STUDY §3 rank 6).
- Which module carries the payload (hero number vs delta chip vs verdict footnote).

### The rule, stated for our system

> **Tokens repeat; layouts don't.** Within one longform video, no information-bearing card
> layout should appear twice unless the content type genuinely recurs (theses may repeat as
> statement cards; evidence may recur as screenshare). The planner picks the FORM from the
> content type (§1.4); the brand system (palette, eyebrow, connectors, ribbons, build
> grammar) makes 20 different layouts read as one designer. Variety is carried by cards, not
> cuts — 7 hard cuts total; a new card form is this grammar's equivalent of a cut.

Implication for `comps-catalog.ts` / `graphics_planner_style.py`: a per-video used-form
ledger, so the planner drains distinct forms before repeating one — the inverse of our
current "pick the best-fitting comp independently per slot" behavior.

Deterministic enforcement is deliberately below the reference's 20/23 (~87%) diversity,
but it no longer activates only after a sparse plan has already escaped. For automatic
graphics on produced/full longform, a first minute of at least 40s must carry at least
four information-bearing graphic windows in four distinct forms. The early window then
grows from at least five windows/four forms just past 60s to eight windows/six forms at
180s; the whole-plan proportional floor remains. Each strong early transcript beat is
also surfaced as an `introSemanticBeats` row and must receive a persisted
`graphicsDecisions` result whose chosen kind belongs to that beat's `compatibleKinds`.

These are semantic floors, not permission to decorate. Section 1.4 remains prior: never
select a comparison, evidence, process, credibility, chapter, scale, list, or thesis form
merely to satisfy variety. If no compatible form earns the beat, persist the evidenced
omit/b-roll decision; satisfy density using other real transcript beats, never filler.

---

## 3. SCREENSHARE GRAMMAR — 187.4–323.4s (136s, 42% of runtime)

Three sub-chapters: **A** 187.4–252.5 (65.1s, VS Code + Codex chat — token/cost report) →
**B** 252.5–292.0 (39.5s, browser — OpenRouter compare page → pricing) → **C** 292.0–323.4
(31.4s, back to VS Code, static backdrop for the outro). Longest "static" stretch in the
video, and the inverse of the graphics-heavy first half: ZERO overlays, all aliveness
diegetic.

### 3.1 Framing — readability before recording, not in post

- Full-bleed, native 1:1 capture. Both apps fill 1920x1080 exactly — no letterbox, no
  window-on-wallpaper, no post punch-ins.
- Apps are PRE-ZOOMED: VS Code chat text measures 20–21px glyph height, 28.6px line pitch
  at 1080p (~1.5× default); browser similar (~22px rows). Every cited number is legible at
  1080p and survives 720p.
- Zero digital motion on the screen layer: frame-diff during holds is 0.3–1.3 (cursor+PIP
  noise only). No ken-burns, no crop-zooms, no drawn highlight boxes. The recording IS the
  graphic.

### 3.2 Presenter PIP — the aliveness anchor

- Rounded-corner portrait webcam pinned bottom-left: **x[11..369] y[612..1078] = 358×466px
  (18.6%W × 43.1%H, ~8% of frame area)**, ~11px left margin, flush to bottom.
- **Pixel-identical across all 136s and both apps** (measured t=197.0 / 233.5 / 271.5 /
  306.0 — same rect). Never moves, never resizes, never disappears.
- Head + shoulders + hands; continuous gesturing (points up at 194.2s, "I'll tag that right
  up here") — the ONLY human motion for 136s.
- Contrast: the AI segment's avatar uses a TALL RIGHT-SIDE card (~537×955px, form #14 /
  dark chassis). Two distinct PIP archetypes in one video: editorial-right (designed
  segments) vs corner-left (real capture).

### 3.3 Cursor grammar — the yellow halo is a laser pointer, not a fidget

- Solid yellow-green highlight disc ~35px dia (recorder feature, Cursorful/Screen-Studio
  style); detected in 85 of 272 sampled half-seconds (dims idle, brightens on move/click).
- Per-0.5s deltas: 64 still (<8px), 7 small (8–80px), 6 big hops (≥80px, max 168px/0.5s).
  **Median delta 0.0px.** Pattern: quick hop (≤0.5s) → long dwell (5–15s).
- Dwells sit ON the narrated payload: parked beside "3,143,246 tokens over 2h 33m" at 197s
  while "it used 3 million tokens" lands at 198.5; parked ON "$30 / M tokens" 255.5–257s
  while "basically half of Fable 5" lands 256–261s.

### 3.4 Motion events — all of them (frame-diff measured)

| t | Δ | event |
|---|---|---|
| 187.4 | 40.6 | hard cut INTO VS Code (chapter entrance) |
| 197.0 | 12.9 | wheel-scroll step → reveals "Goal usage: 3,143,246 tokens" |
| 214.5 | 11.6 | scroll step → agent-count answer ("spun up nine other agents" spoken 215.8) |
| 222.5 | 8.3 | scroll step → main-agent tokens ("86 million tokens" spoken 222.7) |
| 227.5–230.0 | 9.2–12.4 | 2.5s reading-pace scroll through the cost table |
| 233.5 | 14.9 | settles on Total **$318.23** exactly as "$300, a little over $300" lands (230.9–233.7) |
| 252.5 | 29.5 | app switch → browser (cursor visibly travels to top of screen first at 252.0) |
| 253.5–256.0 | 10.5→3.1 | decelerating momentum scroll to Pricing (natural trackpad ease-out) |
| 292.0 | 27.9 | app switch back → VS Code; Windows taskbar hover-previews on camera ~0.6s (291.5–291.9) — honest artifacts kept |

~8 motion events in 136s: one meaningful screen change every **9–16s in chapter A**, one per
chapter after. Holds of 19s / ~36s / 31.4s are legal because PIP + cursor supply continuous
micro-motion.

### 3.5 Narration sync — screen LEADS by ~0.5–1.5s

Pattern everywhere: **deictic phrase → scroll/hop → settle → number spoken while the cursor
parks on it.** "it says here" (196.9) → scroll 197.0 → "3 million tokens" 198.5. "if you look
at the actual API billing" (248.4) → app switch 252.5 → scroll 253.5 → "much cheaper" 256–258
with cursor on $30. The viewer's eye is already at the target when the claim lands. Chapter C
reverses it: words become general takeaway, the screen is demoted to backdrop — no new reads
demanded during the outro.

### 3.6 Entrances / exits / overlays

- Entrance: designed kicker card ("THIS IS DAY ONE.") → **hard cut** to full-bleed app with
  PIP and cursor already in place. No slide, wipe, or zoom-through. (= STUDY T-F family.)
- Chapter switches: raw cuts / real app switches, artifacts kept. New app = new claim domain
  (logs → billing → recap).
- Exit: the video ENDS on the static screenshare. No outro card.
- **Overlays on top of the screen: none.** No burned captions, lower-thirds, post-drawn
  boxes or arrows anywhere in 187–323s.

### 3.7 The grammar (8 rules)

1. **Full-bleed native capture; make the APP big before recording** (~1.5× zoom → ≥20px
   glyphs, ~29px line pitch at 1080p). Never fix readability in post.
2. **One persistent PIP, ~19%W × 43%H bottom-left, immortal** — same rect across apps and
   cuts for the whole chapter. (His own prompt demanded exactly this: "always keep the
   Avatar visible… vertical rounded crop with a drop shadow.")
3. **Cursor = laser pointer with a ~35px halo**: hop fast, park on the exact number being
   spoken, dwell 5–15s. No circling, no drift.
4. **Scroll is the cut**: inside an app, instant scroll steps and 2–3s eased momentum
   scrolls replace edit cuts; each reveals the next narrated payload and settles right
   before/as it's spoken.
5. **Screen leads the voice by ~0.5–1.5s** after a deictic trigger ("it says here", "if you
   look at", "we can see").
6. **App switch = chapter cut**, every ~30–65s, raw and honest. New app = new claim domain.
7. **Static holds up to ~35s are legal** only while PIP + cursor supply micro-motion; when
   the screen stops being read (outro), demote it to backdrop rather than removing it.
8. **No competing overlay layer** — no captions/graphics on top of a screenshare; the screen
   itself is the graphic.

---

## 4. RANKED CATALOG GAPS — what to build next (impact × effort)

Ground truth today (verified by read, not memory): comps live in
`templates/motion/compositions/` and are cataloged in `src/lib/producer/comps-catalog.ts`
(kinds: statement-card, kinetic-quote, glass-lower-third, icon-badge, whiteboard-list,
stat-card, chip-row, list-build, section-marker, versus-split, underline-circle,
widget-gauge, slideware-* pack, text/container elements). `module-takeover.html` EXISTS and
already covers the dark chassis + comparison bars + delta + evidence ribbon (STUDY §5.9)
well. Screenshare today: `producer_config.py:643–655` MOTION visual_states with
screen-share anchor doctrine; `plan_lint_motion.py:307–331` forbids face anchors + overlay
graphics over screen-share zones (own-screen / focus-shift only); StreamYard-style vstack
split exists for 9:16 shorts only (`REFRAME_LAYOUTS`, `producer_config.py:630–637`);
`graphics/pip_takeover.py` + `pip_hole.py` exist but are NOT wired into render.py (task
#39). **Nothing composites a longform screenshare chapter.**

Effort: S ≤ half day, M ≤ 2 days, L > 2 days. Order = impact ÷ effort, dependencies
respected. Prereq shared by all new comps: narration-paced `moduleLands` scheduling (STUDY
§5.4) — every form below builds in narration order.

| Rank | Gap | Kind | Impact | Effort | What to build (files) | Evidence |
|---|---|---|---|---|---|---|
| 1 | **Screenshare readability gate (ingest)** | screenshare | HIGH — cheapest failure point; a blurry capture poisons everything downstream | **S** | Measure glyph height on screen-share footage at ingest (projection-profile method used in this study); FAIL <~18px at 1080p → tell operator to re-record zoomed, or apply a STATIC region crop — never ken-burns. Hook into the producer ingest/audit path. | §3.1: 20–21px glyphs, 28.6px pitch; zero post punch-ins |
| 2 | **Cream split-panel chassis** | card | HIGH — carries **8 of his 20 forms** (#4,6,8,10,12,13,15,17); we have NO light chassis | **M** | `module-rail.html` sibling of `module-takeover.html`: cream `#f0f0e6` panel, left-edge wipe ~0.3s, ~33–40%W, footage untouched full-frame right, ink text, module slot system (eyebrow/headline/explainer/modules/footer). Same fill-spec seam as takeover. Overlaps STUDY §5.8 (glass-rail rail-push + light skin) — decide there whether it's a glass-rail theme or its own comp; the module SLOTS are the new part. | §1.1; 8 flips 13.5–187s |
| 3 | **Longform screenshare PIP compositor** | screenshare | HIGH — unlocks the entire 42%-of-runtime chapter format | **M–L** | ffmpeg overlay layer in render.py driven from edit_plan zones: full-bleed screen + camera track in a rounded PIP at a LOCKED rect (default bottom-left 18.6%W × 43%H, 11px margin), constant across the whole chapter; hard cut in/out with PIP pre-placed on frame one. Extend `graphics/pip_takeover.py`/`pip_hole.py` (nearest primitives, task #39). | §3.2: pixel-identical 358×466px across 136s |
| 4 | **KV ledger + status tags + fan-out chips module family** | card | HIGH-MED — the module vocabulary for forms #3,5,7; feeds both chassis | **M** | Shared module partials for both chassis: ledger row (`key "value" → TAG`), status tag (VERIFIED/ACTIVE lime/cyan), tree/rail connectors, numbered chip row, footnote/source chip. Add `kv-ledger` + fan-out build modes; wire specFields in `comps-catalog.ts`. | #5 (15.5–25.5s), #7 (32.5–45.5s) |
| 5 | **Bullet bars vs threshold tick** | card | MED-HIGH — the "measurements vs a limit" proof lane; distinct from versus-split/stat-card | **S** | Extend `stat-card.html` (or new `bullet-bars.html`): N horizontal lime-on-gray bullet bars + amber threshold tick + verdict footnote slot landing last. | #12 (94.5–104s): 4 bars vs 60s cap, `4 OF 4 UNDER` |
| 6 | **Node pipeline + dated timeline** | card | MED — process-summary and chronology lanes; cheap once module lands exist | **S each** | `node-pipeline.html`: 4–6 connected tiles, one active-dot marker. `dated-timeline.html`: 2–4 ringed nodes on a colored spine + outlined tag. Both chassis-agnostic. | #18 (169.5–179.5s), #6 (26.0–32.0s) |
| 7 | **Screenshare chapter/hold rules in planner + lint** | screenshare | MED — makes the format safe before the fancy layers | **S** | Planner: app-switch boundaries = the only hard cuts inside a screenshare zone; ban burned captions in longform screenshare zones (overlay graphics already banned, `plan_lint_motion.py:327–331`); cap no-motion holds at ~35s only when PIP+cursor layers present, else force a reveal or cutaway. | §3.4 hold table; §3.7 rules 6–8 |
| 8 | **Big-number scoreboard** | card | MED-HIGH — the hero-metric + honest-caveat payoff card | **M** | `scoreboard.html`: hero number (giant, lime) + outlined stat tiles + color-coded per-item chip strip (lime/teal/amber sweep ~85ms/chip) + amber LIMIT footer slot. Needs moduleLands (STUDY §5.4) for the staggered payoff. | #11 (78.5–94s): 97% + 7/5/1 + 13 chips |
| 9 | **Scroll-sync lint (Audit B extension)** | screenshare | MED — checkable version of the sync rule | **M** | Within screenshare zones: verify a screen-motion event lands 0–1.5s after each deictic/claim beat (frame-diff detector from this study) and the settle frame contains the referenced text/number (OCR spot-check). Extend the audit_render family. | §3.5: 4/4 sync cases measured |
| 10 | **Cursor-halo injection** | screenshare | MED — retrofits the laser-pointer onto raw captures | **M** | Track/detect the OS cursor; render ~35px 60%-alpha disc; enforce park-on-payload by snapping dwell to the claim's screen coordinates from the plan. Skip if the operator records with Cursorful/Screen Studio (rule 3 satisfied at capture). | §3.3: 35px disc, median 0px/0.5s, dwell 5–15s |
| 11 | **UI-diff evidence panels** | card | MED — mechanism-proof card; needs operator screenshot assets, so plan-time only | **M** | `ui-diff.html`: two embedded screenshot slots w/ header bars + arrow + step chips + evidence ribbon. Screenshots supplied via fill spec (operator/brain asset paths) — never generated. | #14 (111–122.5s) |
| 12 | **Scanner lanes** | card | LOW-MED — niche (QA-narration beats only), but the only "animated during hold" form | **S–M** | `scanner-lanes.html`: N thin tracks + creeping dots (continuous, eased) + amber search tags. Violates our pixel-frozen-hold doctrine (STUDY §5.12a) — scope as an explicit exception: motion is the MESSAGE here. | #16 (142–159.5s) |
| 13 | **Variety ledger in the planner** | system | MED — enforces §2's "layouts don't repeat" rule | **S** | Per-video used-form ledger in `graphics_planner_style.py`: drain distinct forms per content type before reusing one; statement/screenshare exempt. Cheap once ranks 2–8 give the planner enough forms to vary. | §2: 20 forms, repeats only statement ×2 + screenshare ×3 |

**Deliberately not building:** terminal-prompt takeover, HUD viewfinder, metadata
lower-third (#1–3 — one-off cold-open furniture, statement-card + text-element cover the
need); vendor proof cards (#13 — an icon-badge/receipt-cell variant, not a new form);
per-video fresh comp authoring (his approach; producer-study mints reusable comps instead,
STUDY §5 "deliberately not adopted").

Blocked/adjudication note: the dark chassis' shrink-to-PIP footage move and the face-bridge
lane remain gated on the STUDY §4 operator ruling (cutaway vs face-bridge). Nothing in ranks
1–13 above depends on it — the cream chassis keeps footage full-frame, and the longform
screenshare PIP is a locked composite, not a bridge transition.
