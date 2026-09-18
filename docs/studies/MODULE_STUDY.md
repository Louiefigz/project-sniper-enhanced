# MODULE STUDY — J_jswzXhYJA ("How this video rendered itself")

Date: 2026-07-10. Source video: 323s, 1920x1080@30 (`_references/module/J_jswzXhYJA.webm`,
transcript `J_jswzXhYJA.en.vtt`; en-orig byte-identical, cmp-verified).
Evidence base: (a) transcript extraction of his self-narrated pipeline (0:00–3:07 is the AI
video narrating its own build; 3:07+ is Nate's cost/effort commentary), (b) frame-level visual
study — 7 contact sheets covering all 82 visual states + 21 burst grids at 12–24fps + phase-
correlation drift measurement on hold windows, preserved at
`_references/module/J_jswzXhYJA.study/` (working copies in the session scratchpad
`module-study/{sheets,bursts}/`). Timing uncertainty ±1 frame (~40ms). N=1 video — these are
priors, not laws.

His stack, for context: GPT-5.6 "Soul" in Codex at effort "Ultra" (4 concurrent agents, 9
subagents total), one vague prompt, zero human review. 2.5h wall clock; ~450M tokens total
(~86M main agent); ~$300+ at API prices, $0 on his subscription. His own verdict: Ultra
"overthinks, over-delegates" — effort "high" would have matched quality at ~half cost.
Division of labor, quoted: "ElevenLabs made the audio. HeyGen made the avatar. Hyperframes
rendered the edit. Soul planned and operated the chain."

---

## 1. His pipeline + QC vs ours

### 1.1 The two pipelines, side by side

```
HIS (agent-operated, all-QC-post-render)          OURS (brain plans, code renders, gates first)
────────────────────────────────────────          ─────────────────────────────────────────────
one vague prompt                                  operator footage + scope (edit_scope.py)
  │                                                 │
  ▼                                                 ▼
research → verified-claims-vs-hype gate           edit brain: pause_scan / retake_scan
  │                                                 → apply_pauses → cutTrack
  ▼                                                 │
mine his repos/videos for style ("inspiration")   calibration pipeline (producer-study):
  │                                               fingerprint → frame study → grammar doc
  ▼                                               with receipts → pacing profile → preset
script in his cadence → ElevenLabs (<60s chunks)    │
  → HeyGen avatar                                   ▼
  │                                               brain authors edit_plan.json
  ▼                                                 │
agent authors HyperFrames comp fresh              PRE-RENDER GATE FAMILY (his: none):
(visuals mapped to exact trigger phrase)          plan_lint + _motion/_audio/_reframe
  │                                               + hook_contract + SKILL step-4 convergence
  ▼                                               (author→audit→revise ON THE PLAN, multi-round)
FULL RENDER (HyperFrames)                           │
  │                                                 ▼
  ▼                                               deterministic render (render.py):
POST-RENDER adversarial pass, separate agents,    cut+speed → baseline → reframe → overlays
frames extracted from the render:                 → graphics (hyperframes comps + ffmpeg
  a. every entrance/exit                            composite) → punch-ins → enhance →
  b. text outside frame                             transitions → gain/master → captions
  c. presenter never disappears                   same plan → byte-identical MP4 (MD5-proved)
  d. factual claims vs release notes                │
  │                                                 ▼
  ▼                                               Audit B (audit_render → audit_motion /
ANY failed frame → fix → FULL re-render           _frames / _glitch / _probe) + FRAME.IO REVIEW
  → FULL re-review (cost: entire render/loop)       │
                                                    ▼
                                                  fail → fix plan → INCREMENTAL re-render:
                                                  graphics-only 19.9s, audio-only 11.7s,
                                                  base reused (~190s paid once)
```

### 1.2 Verdict table (SAME / WE LACK / OURS BETTER)

| # | His element | Verdict | Justification (evidence) |
|---|---|---|---|
| 1 | One prompt → agent plans + operates the whole chain | **SAME** | Our one-click Auto-edit: headless claude authors `edit_plan.json`, gates validate, render chains (578s raw→finished, verified e2e). |
| 2 | Agent-swarm render orchestration (4 concurrent, 9 subagents) | **OURS BETTER** | Our render is deterministic Python/ffmpeg/hyperframes executing a plan — same plan → byte-identical MP4. His own conclusion (Ultra over-delegated, ~2x cost, no quality gain) is evidence for our "brain owns WHAT, code owns WHERE" split. |
| 3 | Research + verified-claims-vs-hype gate before writing | **WE LACK (out of PRODUCER scope)** | PRODUCER edits operator-recorded footage — facts arrive spoken. Becomes relevant the moment brain-authored card copy carries claims → see §5 items 6–7. |
| 4 | Mining the creator's prior work for style | **OURS BETTER** | His is ad-hoc "took some inspiration". Ours is producer-study: yt-dlp → fingerprint → frame-by-frame study → grammar doc with receipts → executable pacing profile (Restrained 9 cuts/146s; Punch punch band 1.30–1.45, 50/53 rules frame-verified; Slideware comps). |
| 5 | HyperFrames as the edit renderer | **SAME** | Identical role: HTML comps rendered via hyperframes (`graphics/graphics_render.py`), composited over footage (`graphics/graphics_stage.py`), ffmpeg for footage stages. |
| 6 | Visuals mapped to the exact trigger phrase | **SAME idea, mechanism OURS BETTER** | His mapping is agent-asserted prose. Ours is deterministic: `planner/motion_triggers.py` shared vocabulary + `compile_timeline.py` source↔output map + `edit/plan_refit.py` — timing survives cut edits by arithmetic, never re-inference. |
| 7 | "Shift presenter instead of covering him; keep visible" | **SAME goal, different doctrine — OPERATOR ADJUDICATION NEEDED** | We solve occlusion preventively (`planner/free_space.py` + `graphics_anchors.resolve_offset_v2`, SAFE_BOX-clamped) and by cutting away. His reference reframes THROUGH the face. This contradicts stored doctrine — see §4, do not silently resolve. |
| 8 | QC: entrance/exit check on rendered frames | **SAME** | Audit B inspects rendered output; the EXIT LAW (`graphics/exit_on_cut.py`, shared by lint/render/assemble) makes exit correctness structural, not just detected. |
| 9 | QC: text outside frame | **OURS BETTER** | We prevent (SAFE_BOX clamping + `plan_lint` family before any render) AND detect (frame audits + FRAME.IO REVIEW). He only detects after paying for a full render. |
| 10 | QC: presenter never disappears | **SAME (his gate HARD, ours WARN)** | `audit_motion` presence check is WARN-only; face_track/reframe keeps the subject framed structurally. Harden when/if we composite a presenter into PIP slots (§5 item 10). |
| 11 | QC: factual claims vs source docs on the FINAL render | **WE LACK** | Nearest we have: FRAME.IO REVIEW (vision typo/grammar QC — mechanics, not truth) and `hook_contract.py` (presence of owed elements, not accuracy). No gate checks card copy is faithful to transcript/sources. §5 items 6–7. |
| 12 | Fail → fix → full re-render → full re-review | **OURS BETTER** | Same loop shape, radically cheaper: SKILL step-4 convergence catches most failures ON THE PLAN before any render; incremental assemble re-renders graphics-only in 19.9s / audio-only 11.7s vs his full re-render per failure. |
| 13 | All QC post-render (zero pre-render gates described) | **OURS BETTER** | Our pre-render family: `plan_lint`, `plan_lint_motion/audio/reframe`, `hook_contract`, `edit_scope`, thresholds centralized in `producer_config.py`. Detection-only QC pays render cost per bug. |
| 14 | Fresh per-video agent-designed cards | **OURS BETTER, honest caveat** | We template + parameterize (comps + brand tokens; brain writes copy through the `fill_*_spec` seam) — consistent, cacheable, gate-checkable. Caveat: his approach invents novel layouts per video; ours needs producer-study to mint a new comp. §2–3 below is exactly that minting. |
| 15 | Per-run token/cost telemetry | **WE LACK (small)** | He could report 450M tokens / $300 because the logs carried it. We have no per-run cost/wall-clock ledger. §5 item 11. |

**Net: two genuine gaps** — the factual-claims audit (11) and run telemetry (15) — plus one
doctrine question (7). Everything else is SAME or OURS BETTER. What the visual study adds is
a third category: comp-grammar techniques his video demonstrates that our comps don't have
yet (§3), which is where most of the adoption plan lives.

---

## 2. The transition grammar — technique by technique, with our implementation

Context from the fingerprint: 7 hard cuts in 323s (1.3 cuts/min) yet ~14 full-frame graphic
takeovers. The polish is NOT cut-carried and NOT drift-carried (phase correlation on holds:
dy=dx=0, peak 0.97 over 8–13s windows; 0 changed pixels >25 in the lanes region 150→158s).
It is **transition- + build- + live-face-carried**. Why the seams feel smooth, ranked:

1. The live face is the bridge element in EVERY transition — reframed, never cut.
2. Phases overlap by 1–3 frames each; total handoff 550–900ms but no single tween >350ms.
3. Directional continuity: rails exit the edge they entered; dark cards enter as washes,
   exit as blur-recede.
4. Per-layer exits: blur/fade applies only to the graphics layer; face stays sharp.
5. Skeleton-first: containers/hairlines land before text; text is always an in-place
   opacity ramp (never travels more than a few px).
6. Word-locking: every transition lands on a narration phrase boundary (verified vs VTT:
   25.7 "…about to see.", 67.2 "But benchmarks only explain part…", 186.0 "This is day
   one", 187.4 "So that was…").

Our renderer has THREE places a transition can live, and each technique below is assigned to
exactly one: (a) **comp-side** — the graphic animates its own entrance/exit inside the HTML
comp (zero renderer change; our graphics are already an alpha layer over footage, which is
precisely his "per-layer treatment"); (b) **ffmpeg transitions stage** —
`motion/transitions.py` seam covers (white-flash / light-leak), extended with new kinds;
(c) **footage-transform stage** — anything that moves the FOOTAGE itself (shrink-to-PIP),
which is a new/wired motion primitive, not a comp.

### T-A — Full-screen overlay in over live TH, exit via hard cut to punched-in crop
Measured: enters 1–2 frames (~40–80ms) at 2.23→2.43; exit ≤42ms at 5.58→5.62 directly to a
tighter TH crop.
**Verdict: ALREADY OURS.** `slideware-takeover-deck` arrives 0-frame on a hard cut;
"takeover exit lands on a punch-in reframe change" is a PLAN pattern (pair the graphic's
`outEnd` with a `punch_in` step at the same seam), not new code. Document in the SKILL as a
named move; no build.

### T-B — Rail push, light-in (13.35→13.72)
Measured: cream rail GROWS from the left edge 0→33% width in ~330ms, power-out (fastest
first 3 frames); live video never cut — face keeps playing full-frame right of the rail.
Headline fades in at ~65% of rail growth (ghost 13.48 → full ink 13.65, ~170–200ms,
opacity-only). Rows stagger +250ms/+400ms after headline, hairline container first, text
second.
**Implementation: comp-side, extend `glass-rail.html`.** The comp already exists with an
eyebrow slot (`#rail-eyebrow`) and staggered rows — but its rows slide in on x with
`back.out(1.6)` and the rail itself does not grow from the edge. Add an entrance mode
(`entrance: "rail-push"` composition variable): animate the rail container's clip/width
0→33% over 0.33s `power2.out`, headline opacity ramp starting at 65% of the grow, rows at
+0.25s/+0.40s container-before-text. Add a light skin (cream `#f0f0e6` field, ink text) as
a token theme — see §3.7. Because our graphics are output-space alpha overlays, "pushes over
live video without cutting it" is free. Effort: S–M.

### T-C — Rail-out → dark takeover with face shrinking into a PIP card (15.45→15.99)
Measured: 5 overlapping layers in ~550ms — (1) rail slides LEFT off (same edge it entered,
100–150ms); (2) clean full-frame face beat 1–2 frames; (3) dark canvas sweeps in WHILE the
face shrinks into a rounded PIP card right (~150–200ms, eased fast→settle); (4) skeleton row
containers arrive BEFORE their text; (5) cyan eyebrow → headline ramp 120–160ms. No element
waits for the previous one.
**Implementation: footage-transform stage — BLOCKED on §4 adjudication.** Layers 1, 4, 5 are
comp-side (directional exit + skeleton-first, both adopted below). Layer 3 moves the FOOTAGE
into a card — that is `graphics/pip_takeover.py` territory, which exists but is UNWIRED
(`plan_lint_motion` HARD-REJECTS `needsPip`/`canvas-pip-list` today because it would render
an empty face hole). If the operator approves the face-bridge treatment: wire pip_takeover
into `render.py`, add an eased shrink (full-frame → PIP rect over ~5 frames @30fps, ffmpeg
scale+overlay with an eased position/size expression — same technique family as
`punch_in.py`'s eased zooms), and flip the `audit_motion` presence check to HARD for plans
that use it. Effort: L. Until then, the credibility-beat fallback stands: full-frame
`statement-card`.

### T-D — Graphics-layer-only blur-out (67.12→67.28, ~150ms)
Measured: the graphics layer blurs + fades (slight recede) while the face PIP stays crisp —
proof of a layered comp. Then PIP expands to full-frame (~100–160ms), then rail-push per
T-B. Full dark→light handoff 66.9→67.66 ≈ 750ms, zero dead frames. Repeats at 122.5; lighter
gradient-wash variant at 159.45–159.70.
**Implementation: comp-side exit mode.** Our graphics are already the separate layer, so
this is purely in-comp: `exit: "blur-recede"` — GSAP to `filter: blur(Npx)` + opacity 0 +
scale ~0.98 over 0.15s (≈4 frames @30fps, ≈3–4 @24fps). Add `EXIT_BLUR_S = 0.15` to
`motion-tokens.js` and `--exit-blur-dur` to `tokens.css`; wire into `statement-card`,
`glass-rail`, takeover comps as an alternative to the current fade/instant-out. The EXIT LAW
(`exitOnCut`) still clamps `outEnd` to seams — blur-recede must complete BEFORE the clamp
point, so lint check: `outEnd - EXIT_BLUR_S >= holdEnd`. Effort: S.

### T-E — Statement swap with a deliberate empty beat (185.80→186.30)
Measured: statement exits via ~150ms blur/dim → **1–2 deliberately EMPTY dark frames** →
next statement opacity-ramps in ~300ms, word-locked to the narration ("This is day one",
VTT cue 186.0). The empty beat is the punch.
**Implementation: comp-side, `statement-card` v2 multi-statement.** A composition variable
`statements: [{text, accentLine}, …]` with an internal swap timeline: blur-dim out 0.15s →
gap of 2 frames (empty, field stays) → next ramps 0.3s. Swap times land on word boundaries:
`graphics_copy`'s fill spec computes each statement's land time from transcript word
timestamps (already available through the same pipeline `motion_triggers` reads) — the seam
where brain copy meets code timing, per house rules. Two separate plan entries with a
hand-tuned 2-frame gap also works but is fragile under refit; the in-comp version survives
`plan_refit` as one window. Effort: S (comp) + S (fill spec timing).

### T-F — Chapter hard cut with a persistent bridge element (187.37→187.42; 252.30→252.35)
Measured: graphics→screen-recording and IDE→browser are plain hard cuts (≤42ms); the face
PIP persists in an identical slot across the cut; the incoming screen immediately carries
motion (scroll + cursor halo).
**Verdict: consistent with our doctrine** (hard cuts between worlds). The persistent-PIP
bridge is part of the §4/T-C decision. The "incoming screen already moving" observation is a
SKILL note for screen-share sections: start screen segments mid-motion, not on a static
frame. No build.

### T-G — Word-locked seam timing (cross-cutting)
Every transition start in the reference lands on a narration phrase boundary (4/4 spot
checks vs VTT above). Our graphics entrances are mostly word-anchored already (triggers are
transcript-derived), but `motion/transitions.py` events and graphic out-times are not
snapped.
**Implementation: planner util.** `snap_to_word_boundary(t, words, max_shift_s)` in
`planner/` (arithmetic over the transcript word list through `compile_timeline` — code finds
WHERE, per house rules); apply to transitions-stage `outTime`s and to graphic `outStart`s at
plan time. `plan_lint_motion` WARN when a seam sits >150ms from the nearest word boundary.
Effort: S.

### Explicitly NOT adopted from the transition study
- **No ambient drift/Ken Burns on cards.** Measured: holds are pixel-frozen (dy=dx=0,
  peak 0.97). Motion is spent entirely at seams and builds. This VALIDATES our hold
  doctrine — reject any future "add subtle drift to make cards feel alive" impulse; the
  aliveness comes from the live face + build cadence.
- **No change to `white-flash`/`light-leak`.** His video has no flash/leak grammar; those
  stay for the reference styles that measured them (INTRO_MACHINE_VS_PRO_AUDIT §3). The
  module grammar is a new TREATMENT lane, not a replacement.

---

## 3. Motion-graphic techniques, ranked impact × effort

Reference layout system (both modes): eyebrow (mono caps + colored dot) → 2-line
heavy-grotesque headline, line 2 in accent → content modules with 1px hairline borders →
footnote chip / evidence ribbon (mono: "CLAIM SOURCE OPENAI GPT-5.6 RELEASE JUL 09 2026").
LIGHT = cream `#f0f0e6` rail ~33%W over live video, ink `#1a1a1a`. DARK = near-black
`#0c1014` canvas + faint grid, content column left ~58%, face PIP right (~28%W × 89%H,
r≈24px). Semantic dual accent: lime `#c6f542` = hero/results; cyan `#35b6d9` =
process/status; gray/white = comparison. All microtext/numerals monospace caps, wide
tracking.

Our token ground truth today: `tokens.css` has `--accent`, `--accent-ink`, `--accent-soft`,
`--ink`, `--lemon`, `--gold`, `--font-serif-display`, safe-zone vars, pop tokens
(`--pop-in-dur`, `--pop-scale-from`, `--instant-out-dur`); `motion-tokens.js` exports
`POP_IN_S` (≤2 frames), `POP_SCALE_FROM` (0.94). Punch pack law (pop ≤2f, never alpha fade)
is a DIFFERENT lane — none of the below touches it.

| Rank | Technique | Evidence | Impact | Effort | Implementation against our system |
|---|---|---|---|---|---|
| 1 | **Narration-paced progressive module builds** — a card lands 3–6 modules 600ms–1.4s apart, timed to spoken words, not a fixed stagger | MG-1 benchmark card builds over ~2s (52.4–59.5); MG-3 timeline nodes 1.2–1.4s apart = narration beats; MG-2 agent cards 80–120ms stagger AFTER a 900ms narration wait | HIGH — this is the core grammar; our slides land as one unit | **M** | Extend the `fill_*_spec` seam (`graphics_copy.py`): specs gain `moduleLands: [t0, t1, …]` (seconds relative to comp start), computed from transcript word timestamps through `compile_timeline`. Comps read a `moduleLands` composition variable and schedule each module's build at its land. Lint: lands strictly increasing, ≥0.25s apart, all inside the hold (`plan_lint_motion`). Brain never picks the numbers — it picks WHICH words, code converts to times. |
| 2 | **Skeleton-first builds** — containers/hairlines/empty tracks land BEFORE text/fills | MG-1: panel skeleton fades as one unit at 52.73, 600ms hold, THEN bars fill; T-C layer 4: row containers before text | HIGH — reads as designed, hides pop-in | **S** | Comp pattern + shared helper in `motion-tokens.js`: `skeletonFirst(tl, containerEl, contentEl, gapS)` (container opacity ramp, content ramp at +gap, default 0.35s). Apply to `list-build`, `stat-card`, `glass-rail` rows, takeover decks. |
| 3 | **Eyebrow-first rule** — mono-caps microtext + colored dot precedes every headline by 80–500ms | Every card; extreme case: eyebrow ALONE on empty canvas ~500ms at 141.5 | HIGH — cheap signature move | **S** | `glass-rail` already has `#rail-eyebrow`; add an eyebrow slot (text + dot, dot color from semantic accent) to `statement-card`, takeover comps, `stat-card`. Tokens: `--eyebrow-font` (mono), `--eyebrow-dot`, `EYEBROW_LEAD_S = 0.25` (band 0.08–0.5). Copy comes through the fill spec (brain-authored). |
| 4 | **Opacity-first text** — text NEVER travels more than a few px; in-place ramp 120–250ms | All headlines (e.g. 13.48→13.65 ghost→ink ~180ms; 15.87–15.99 ramp); phase-correlation confirms zero drift | HIGH — our statement-card reads busier than the reference | **S** | `statement-card.html` today: card `scale 0.94→1, y 18→0` over 0.5s + per-word `y: 22` rise stagger 55ms. Change to: card opacity ramp (keep ≤0.98→1 scale settle if any), text in-place opacity ramp 0.2s, per-line (not per-word) stagger. Token `TEXT_RAMP_S = 0.2`. Keep the old behavior available as a variant — Slideware/Restrained presets measured different grammar; this is the module skin, not a global rewrite. |
| 5 | **Two-line accent-shift headline** — line 2 in accent color | "ONE RUN. FOUR AGENTS." (32.65, line 2 lime); statement cards | MED-HIGH — signature statement form | **S** | Composition variable `headlineLines: [l1, l2]`; line 2 gets `color: var(--accent-result)` (or process). Pure comp + fill-spec change. |
| 6 | **Semantic dual accent** — lime = hero/results, cyan = process/status, gray = comparison | Benchmark hero bar lime vs comparison gray; cyan eyebrows on process cards; consistent across all 14 takeovers | MED-HIGH — system-level cohesion | **S–M** | `tokens.css`: add `--accent-result` / `--accent-process` / `--accent-compare` (theme maps them; module skin: `#c6f542` / `#35b6d9` / `#9aa0a6`). `planner/graphics_planner_style.py` assigns the semantic class per lane: gauge/receipts/payoff → result; boundaries/sequences/status → process. Deterministic mapping, no LLM. |
| 7 | **Hierarchy by animation speed** — hero bar fills 350–400ms power-out, comparison bar 700–900ms thinner/gray; value label lands WITH the bar tip; delta chip pops only after both | MG-1: hero 53.32–53.57 (15→92% in ~240ms of the 350ms fill), comparison ~2x slower, "+6.3 POINTS" chip at 58.12 | MED — in-card payoff moment | **M** | Extend `stat-card.html` / `widget-gauge.html`: bar-fill build with `heroDur=0.4s power2.out` / `compareDur=0.8s power1.out`, label position driven by the same tween progress, delta chip scheduled off `moduleLands` (rank 1). |
| 8 | **Chip-populate sweep / counter boxes** — N chips land ~1 per 80–90ms L→R | MG-4: 13 task chips over ~1.1s (78.5–84.5); MG-2 agent cards 80–120ms | MED | **S** (after rank 1) | `chip-row.html` gains a `sweep` build mode: per-chip opacity ramp, stagger 0.085s, capped total ≤1.5s. Trivial once module scheduling exists. |
| 9 | **Evidence ribbon / footnote chip** — mono source+date receipt on claim-bearing cards | "CLAIM SOURCE OPENAI GPT-5.6 RELEASE JUL 09 2026" ribbon; deflating footnote "Not proof it wins everything." (84s) | MED — credibility texture + hooks the claims gate (§5.6) | **S** | New slot in takeover/stat comps: `evidence: {source, date}` composition variable, mono caps style, lands LAST in the build. Brain authors it through the fill spec; the claims contract (§5.6) makes it checkable. |
| 10 | **Empty-frame beat between statements** | T-E: 1–2 empty frames at 186.0 | MED — punch | **S** | Part of `statement-card` v2 (T-E above). |
| 11 | **Light/dark two-mode alternation** — cream rail chapters vs dark PIP-canvas chapters as the video's rhythm | ~14 takeovers alternating LIGHT/DARK, one per narration beat, 9–18s holds | MED (longform 16:9 lane) | **M** | Light skin = token theme on `glass-rail` (T-B); dark canvas = new `module-takeover.html` comp (near-black + grid texture + content column; PIP slot only if §4 approves — until then full-frame with no face hole, entered via hard cut per current doctrine). Hold ceilings already allow 9–18s? Check: `MOTION["hold_max_s"]["longform"] = 11.0`, `takeover_max_s = 10.5` — the reference holds 9–18s. If we adopt the lane, raise ONLY under a module preset (mode-keyed override in `producer_config.py`), justified by the measured 9–18s band; do not flatten globally. |
| 12 | **Face-bridge choreography** (rail-push over face is rank 11/T-B; PIP shrink-grow is this) | T-C/T-D: face shrinks into PIP 150–200ms, expands back 100–160ms | HIGH if approved | **L** | BLOCKED on §4. Wire `graphics/pip_takeover.py`, add eased footage transform, flip presence audit to HARD for PIP plans. |

**Validated, no action:** pixel-frozen holds (we already hold; do NOT add drift);
`punch-shout-lockup` (different lane, different law); our SAFE_BOX/free-space placement
(the reference's PIP-safe right zone is the same idea, solved differently).

---

## 4. OPERATOR ADJUDICATION REQUIRED — cutaway vs face-bridge

Stored doctrine (`feedback_pro_graphics_are_cutaways`): "pro graphics are full-frame
CUTAWAYS, hard-cut, never panels-on-face" — measured from a different reference. This
reference demonstrates the OPPOSING treatment and it demonstrably works: the presenter is
reframed THROUGH every transition (rail pushes beside the live face; face shrinks into a PIP
card inside dark takeovers; PIP persists across chapter cuts), and light-mode rails ARE side
panels next to the live face — though never ON the face.

This is a **treatment axis, not a universal law**. Both references are internally coherent:
the cutaway grammar is cut-carried (high cut density), the module grammar is
transition-carried (1.3 cuts/min). Proposal: make it a preset axis
(`target.treatment_style: "cutaway" | "face-bridge"`) the same way pace and treatment are
axes — but ONLY after the operator rules. Items T-C, rank 12, and the PIP half of rank 11
are blocked until then. Nothing in §5 items 1–9 depends on the ruling.

---

## 5. ADOPTION PLAN — ranked, with effort

Order = impact ÷ effort, dependencies respected, blocked items last. Effort: S ≤ half day,
M ≤ 2 days, L > 2 days. Every item names its files.

1. **[S] Comp grammar micro-pack: eyebrow-first + two-line accent headline + opacity-first
   text.** `statement-card.html` (+ takeover comps): add eyebrow slot (mono caps + dot,
   `EYEBROW_LEAD_S = 0.25`), `headlineLines` variable with line-2 accent, replace 22px
   word-rise with in-place opacity ramp (`TEXT_RAMP_S = 0.2`) as the module variant.
   Tokens in `templates/motion/tokens.css` + `motion-tokens.js`. Punch pack untouched.
   (Evidence: §3 ranks 3–5.)

2. **[S] Exit grammar: `exit: "blur-recede"` + statement-replace with empty beat.**
   Comp-side graphics-layer-only blur+fade 0.15s (`EXIT_BLUR_S`), and `statement-card` v2
   `statements[]` internal swap (blur-dim 0.15s → 2 empty frames → 0.3s ramp). Lint:
   blur-out completes before the `exitOnCut` clamp. Files: `statement-card.html`,
   `motion-tokens.js`, `plan_lint_motion.py`. (Evidence: T-D 67.12→67.28, T-E 185.8→186.3.)

3. **[S] Skeleton-first build helper + evidence-ribbon slot.** `skeletonFirst()` in
   `motion-tokens.js`, applied to `list-build`/`stat-card`/`glass-rail`/takeovers; new
   `evidence: {source, date}` mono ribbon slot landing last. (Evidence: MG-1 52.73 skeleton
   + 600ms hold; the CLAIM SOURCE ribbon.)

4. **[M] Narration-paced module builds through the `fill_*_spec` seam.** `graphics_copy.py`
   fill specs gain `moduleLands` computed from transcript word timestamps via
   `compile_timeline`; comps schedule module builds off the variable; `plan_lint_motion`
   validates lands (increasing, ≥0.25s apart, inside hold). The single highest-leverage
   change — everything the reference's cards do that ours don't reduces mostly to this.
   (Evidence: §3 rank 1 measurements.)

5. **[S] Word-locked seams.** `snap_to_word_boundary` planner util; apply to
   `motion/transitions.py` event times and graphic out-starts at plan time; lint WARN >150ms
   off-boundary. (Evidence: T-G, 4/4 VTT spot checks.)

6. **[S] Claims contract, pre-render (truth gate on card copy).** SKILL step-4 addition: the
   brain verifies every claim-bearing graphic's copy against the transcript/source before
   render, mirroring `hook_contract.py`'s shape (content-derived obligations) — plus one
   deterministic check: numeric copy in a card must appear in the transcript within the
   card's source window (arithmetic string/number match, not regex semantics). New
   `claims_contract.py` beside `hook_contract.py`. Closes gap §1.2#11 at the CHEAP point —
   before render, which is exactly where his pipeline is weakest. (Evidence: his check d,
   run only post-render at full-render cost.)

7. **[M] Factual spot-check, post-render.** Reuse FRAME.IO REVIEW machinery
   (`scripts/frameio/`) against `graphicsTrack` windows — we know every graphic's on-screen
   time from the plan, so no pHash dedup pass is needed: sample one settled frame per entry
   hold, vision-confirm rendered copy == plan copy, brain confirms plan copy == transcript
   claim. Wire as an optional Audit B lane or SKILL step. (Evidence: his check d; our
   FRAME.IO REVIEW covers mechanics only today.)

8. **[M] Rail-push entrance + light-mode skin.** `glass-rail.html` `entrance: "rail-push"`
   (width-grow 0→33% in 0.33s power-out, headline at 65% growth, rows +0.25/+0.40s
   container-first) + cream/ink token theme. Our first 16:9 longform rail lane. (Evidence:
   T-B 13.35→13.72 measurements.)

9. **[M] Dark-takeover comp + two-mode chapter rhythm (module preset).**
   `module-takeover.html` (near-black #0c1014 + grid, content column, semantic dual-accent
   tokens `--accent-result`/`--accent-process`, in-card payoffs: speed-hierarchy bar fills,
   chip sweeps, delta chips via items 3–4) + `graphics_planner_style.py` semantic accent
   mapping + preset-scoped hold-ceiling override in `producer_config.py` (measured 9–18s
   band vs current longform 11.0s cap). PIP slot EXCLUDED until item 10 clears. (Evidence:
   §3 ranks 6–8, 11.)

10. **[L, BLOCKED on §4 operator ruling] Face-bridge lane.** If approved: wire
    `graphics/pip_takeover.py` into `render.py`, build the eased shrink-to-PIP footage
    transform (~5-frame eased scale+position, `punch_in.py` technique family), lift the
    `plan_lint_motion` `needsPip` HARD-REJECT for the lane, and flip `audit_motion` presence
    to a HARD gate for PIP plans (his check c). (Evidence: T-C/T-D measurements; §1.2#7,#10.)

11. **[S] Per-run telemetry.** Append a run ledger (wall clock per stage, render count,
    incremental-vs-full path taken; token counts when the skill flow can report them) to the
    render output dir — `render.py` + `assemble.py` already print stage timings; persist
    them. Closes §1.2#15. (Evidence: his 450M-token / 2.5h accounting came free from logs.)

12. **[no-build] Doctrine confirmations.** Record in the SKILL: (a) holds stay pixel-frozen
    — never add drift/Ken Burns to cards (measured dy=dx=0); (b) takeover-exit-onto-punch-in
    is a named plan move (T-A); (c) screen-share segments should enter mid-motion (T-F).

**Deliberately not adopted:** agent-swarm rendering (his own cost data argues against it);
fresh per-video comp authoring (producer-study mints comps instead); post-render-only QC
(inverts our cheapest-failure-first architecture); research/fact pipeline before scripting
(rag-system's domain, not PRODUCER's).
