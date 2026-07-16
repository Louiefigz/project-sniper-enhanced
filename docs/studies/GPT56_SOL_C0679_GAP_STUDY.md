# GPT-5.6 Sol benchmark → C0679 gap study

Date: 2026-07-15
Reference: Nate Herk, `J_jswzXhYJA`
Reference scope: AI-created section only, 0:00–3:07
Candidate: `C0679_mastered.mp4`, 11:10 at 1920×1080/24fps

## Executive verdict

C0679 does not miss the benchmark because Project Sniper lacks templates or
because the cards need more polish. It misses at four deeper layers:

1. The benchmark edits with two whole-frame editorial chassis; C0679 mostly
   leaves the camera composition unchanged and floats widgets over it.
2. The benchmark varies information anatomy while repeating design tokens;
   C0679 repeats a small set of generic anatomy.
3. The benchmark cards expose evidence and mechanisms; many C0679 cards merely
   restate narration.
4. Most importantly, the Palmier delivery path mutated a known-invalid plan and
   bypassed the deterministic gates that already knew these rules.

The output is therefore not evidence that the reference studies or templates
failed. It is evidence that study → planning → Palmier execution → exact-export
review was not one authoritative chain.

## Evidence and method

The reference was clipped at the point where the host begins the live reaction.
The comparison used:

- full-frame fingerprinting and cut detection;
- a 5fps zoom/face pass;
- chronological 4×3 contact sheets covering every detected reference state;
- settled/mid/exit frames for all 33 planned C0679 graphic windows;
- 12fps one-second burst grids around the benchmark's rail entry, dark-PIP
  entry, bar build, and final statement swap, plus C0679's first two card builds;
- direct comparison of the source `edit_plan.json`, Palmier `plan.build.json`,
  `graphicsDecisions`, auto-edit logs, and deterministic audit output;
- a fresh run of `plan_lint.py` against both source and live plans.

The slow OCR branch of `study_deep.py` was stopped after it completed the
30fps signal/event scan and stalled in serial Tesseract work. This does not
reduce card coverage: the earlier exact reference study already includes a
fine-step pass that found the one vendor-proof card missed by coarse perceptual
deduplication. Production should reuse this stored study instead of rerunning
OCR inside a job.

Artifacts:

- reference contact sheets:
  `docs/studies/gpt-5-6-sol-benchmark-2026-07-15/analysis/benchmark-ai/labeled-sheets/`
- C0679 graphic-window sheets:
  `docs/studies/gpt-5-6-sol-benchmark-2026-07-15/analysis/c0679-planned-graphics/sheets/`
- entrance/build bursts:
  `docs/studies/gpt-5-6-sol-benchmark-2026-07-15/analysis/bursts/`
- deterministic fingerprints and zoom maps:
  `docs/studies/gpt-5-6-sol-benchmark-2026-07-15/analysis/`

## Measured delta

| Measure | Benchmark AI section | C0679 live output | Meaning |
|---|---:|---:|---|
| Designed-graphic coverage, 0–187s | about 93% after 13.5s | 49.37% | C0679 repeatedly falls back to an unchanged talking head |
| Graphic windows/forms, 0–187s | 20 windows / 19 forms | 23 windows / 6 kinds | C0679 has enough slots but far less structural variety |
| Whole delivered plan | n/a | 33 windows / 9 kinds | repetition continues through the body |
| Graphic coverage, full C0679 | n/a | 152.07s / 670s = 22.70% | the promised produced scope becomes sparse after the hook |
| Zoom events | 5 / 187s = 1.6/min | 31 / 670s = 2.78/min | C0679 spends more rhythm on the camera |
| Zoom magnitude | median 6.5%, max 13.9% | median 11.9%, max 31% | C0679 camera accents are materially more aggressive |
| Plan kind mutations | none | 12 replacements + 3 additions | Palmier did not render the approved source plan |
| Bound decision/kind mismatches | none | 8 | the decision ledger and actual timeline disagree |

The most revealing comparison is 23 live C0679 windows versus only six kinds in
the first 187 seconds. The issue is not graphic count. It is what each window is
allowed to become.

## Reference view-by-view anatomy

The exact payloads and animation measurements live in `NATEHERK_CARDS.md`; this
table records what each view contributes to the editing system.

| Time | View | Editorial job | Why it works |
|---|---|---|---|
| 2.5–5.0 | terminal prompt | show the literal input | starts with a receipt, not a claim |
| 5.5–13.0 | analysis HUD + disclosure ledger | frame authorship and disclosure | meta chrome persists while facts build beneath it |
| 13.5–15.2 | cream intake/queue | introduce the process | rail enters as a new spatial world; state is typed `RECEIVED` |
| 15.5–25.5 | dark session ledger + four-way fan-out | configuration and orchestration | face persists in a stable right PIP while the system expands left |
| 26.0–32.0 | dated vertical timeline | chronology | time is represented spatially rather than as a sentence |
| 32.5–45.5 | four-agent grid | parallelism | the layout itself proves “parallel”; a source footnote receipts the claim |
| 46.0–52.0 | five-step rail list | sequential handoffs | each step has a compact outcome tag and lands with narration |
| 52.5–67.0 | benchmark bars + delta | numerical comparison | hero and baseline have different visual weight; delta waits for both |
| 67.5–78.0 | six-row checklist | obligations resolved | items accumulate, pass badges resolve, footer concludes |
| 78.5–94.0 | 97% scoreboard | result with distribution and caveat | hero metric, wins/ties/loss, 13-item strip, and limit coexist |
| 94.5–104.0 | four bullet bars against a cap | measurements versus threshold | every bar relates to one amber limit; verdict is visible |
| 104.0–110.5 | vendor proof cards | authorized tools | identity and authorization status are explicit modules |
| 111.0–122.5 | real UI before/after | mechanism proof | actual captures replace an illustrative text card |
| 123.0–141.5 | transcript-anchor diagram | word-timed editing | chips, waveform, playhead, marker, and lock visualize the domain |
| 142.0–159.5 | four scanner lanes | adversarial QA in progress | continuous dot motion means active searching, not decorative drift |
| 160.0–169.0 | inspect/fix/render loop | iteration | the return arc makes the repeated cycle legible in one glance |
| 169.5–179.5 | six-node pipeline | whole-chain synthesis | connected nodes summarize the argument without repeating prior anatomy |
| 180.0–187.0 | statement → kicker | close the thesis | same chassis, in-place ghost swap, uninterrupted presenter bridge |

### What repeats

The reference repeats cream, near-black, lime, cyan, mono eyebrows, heavy sans
headlines, thin connectors, rounded cards, stable PIP geometry, and progressive
build rhythm.

### What does not repeat

It does not reuse the same information skeleton for unrelated beats. Ledger,
timeline, grid, bars, checklist, scoreboard, threshold chart, UI evidence,
domain diagram, scanner, loop, and pipeline each appear because the content has
that shape.

That is the benchmark's central design trick: it looks consistent without
looking templated.

## Frame-by-frame animation findings

### Cream rail entry, about 13.1–14.1s

The old disclosure panel clears; a cream plane wipes from the left edge in about
0.3s; the presenter remains full-height on the right; eyebrow and headline
resolve; the first state card appears; connector and queue card follow. The
transition, presenter placement, and card build are one action.

C0679's opening rail instead leaves the wide camera world intact. A small dark
heading and one white pill grow in available headroom. The item build itself is
competent, but it never creates a new editorial state.

### Dark-PIP entry, about 15.1–16.1s

The cream world exits while the background goes near-black. The same footage
scales continuously into a tall rounded right PIP. Before dense content arrives,
the viewer already understands the new left/right contract. Eyebrow, headline,
ledger container, rows, and fan-out then land in order.

C0679 has no equivalent recurring macro transformation. Its occasional lower
third and payoff panels occupy the same camera composition and often cover the
torso or compete with it.

### Comparison build, about 52.2–53.2s

The presenter PIP is stable before the first content appears. The eyebrow lands,
the headline ghost-resolves in place, then an empty comparison container and
labels establish the measurement frame before the bars fill. The viewer sees
structure before data.

C0679 commonly enters a finished-looking pill and types one narration fragment
into it. There is less visual causality because container, relationship, result,
and caveat are not separate stages.

### Final statement swap, about 185.5–186.5s

The first thesis blurs/ghosts away on the same dark chassis. The PIP does not
move. A new eyebrow and `THIS IS / DAY ONE.` resolve in place, with a one- or
two-frame empty beat. It feels decisive because only the information changes.

C0679 uses repeated entrances/exits of widgets. It rarely earns the stronger
move of holding the world fixed and changing the thesis inside it.

## What C0679 actually does

The 33 live graphic windows use:

- `glass-rail` ×10;
- `fragment-payoff` ×9;
- `glass-lower-third` ×5;
- `whiteboard-connector` ×3;
- `whiteboard-map` ×2;
- four one-off kinds.

In the first 60 seconds, eight windows collapse to only three kinds:
`glass-rail`, `fragment-payoff`, and `glass-lower-third`.

This creates four visible symptoms:

1. **Card sameness.** Different ideas share one white pill + blue number + short
   sentence anatomy.
2. **Narration paraphrase.** Cards say “who this is for,” “you’re probably
   using,” or a short payoff instead of exposing proof, states, dependencies,
   limits, or mechanism.
3. **No chapter world.** The presenter remains in the same wide desk shot, so
   every graphic feels temporary and optional.
4. **Camera-motion compensation.** Larger, more frequent punch-ins attempt to
   supply retention energy that the information system should provide.

Color/contrast changes to the generic cards may improve legibility, but they do
not address any of these structural symptoms.

## Where the system went wrong

### 1. The study existed but was not canonical

`NATEHERK_STUDY.md` and `NATEHERK_CARDS.md` already captured the benchmark in
unusual detail. Until this audit, none of its rules had been appended to
`REFERENCE_STYLE_STUDY.md`, which is the producer-study skill's canonical rule
sink. Knowledge existed as a report, not as binding doctrine.

### 2. The templates existed but the assignment was not authoritative

The repository already contains `nateherk-rail`, `nateherk-takeover`,
`nateherk-ledger-dark`, `nateherk-scoreboard`, `nateherk-bullet-bars`, and
`nateherk-pipeline`. The source C0679 plan selected some of them. Palmier later
replaced those selections with generic fallbacks.

Template availability is not delivery. A selected form must remain the selected
form through rendered asset, imported clip, candidate readback, and export.

### 3. The source plan was already below benchmark

Before Palmier mutation, the source plan had 30 graphic windows and 11 kinds,
only 18.83% graphic coverage over the full 670s, and 47.01% during the direct
first-187s comparison. A fresh lint run rejects it for:

- 16 produced-intro still gaps above the four-second ceiling;
- missing measured recomposes;
- late first-content lands;
- only 8 distinct early forms where 15 are required;
- only 11 whole-plan kinds where 15 are required.

So there were two failures, not one: the planner had not converged, then Palmier
downgraded the unconverged plan further.

### 4. Palmier violated plan parity

The live build changed 12 existing graphic kinds and added three ad-hoc body
graphics. The most damaging replacements include:

| Graphic | Source decision | Palmier live kind |
|---|---|---|
| `g-evhzvx3c` | `nateherk-bullet-bars` | `fragment-payoff` |
| `g-alq59502` | `nateherk-ledger-dark` | `glass-lower-third` |
| `g-ulk3rqzd` | `nateherk-ledger-dark` | `glass-lower-third` |
| `g-oawrgolp` | `nateherk-ledger-dark` | `glass-rail` |
| `g-hkrcw1wv` | `whiteboard-map` | `glass-lower-third` |
| `g-3wq72249` | `whiteboard-list` | `glass-rail` |

The `graphicsDecisions` rows still name the source kinds. The existing lint
therefore emits eight explicit bound-kind errors. This is the strongest forensic
proof in the incident: semantic intent survived in the ledger while the visible
timeline was silently simplified.

### 5. The quality gates were bypassed, not ignorant

The live plan currently fails `plan_lint.py` with errors for:

- 19 produced-intro still gaps;
- missing rail/lower-panel recomposes;
- first-content lands after empty chrome;
- consecutive repeated kinds;
- only two information-bearing first-minute forms where four are required;
- only five information-bearing forms through 180s where ten are required;
- 9 whole-plan kinds where 17 are required;
- all eight decision/kind mismatches;
- only two uniquely bound first-minute graphic decisions where four are needed.

The linter even cites `NATEHERK_CARDS` and its 20/23 reference ratio. The system
knew. The old global `.sniper-palmier-livedrive` bypass made knowing irrelevant.

### 6. The authoring workflow stalled before convergence

The auto-edit log shows authoring starts at 14:33, a respawn at 15:03, and a
termination at 15:48 after a 1200-second timeout. The old skill asked for several
serial whole-plan reviews before a visible candidate. Once the governed route
stalled, the manual route had no scoped worklist or comparison-and-swap guard.

### 7. QC never approved this exact 670s master

The available render audit covers 47.3 seconds and already fails black-frame,
eye-trace, and composite-reference checks. `final-render` contains no final file.
The delivered `C0679_mastered.mp4` is 670 seconds. There is no exact-candidate,
full-duration approval receipt connecting that master to its plan, fingerprint,
deterministic audit, and visual reviews.

## Required correction

### A. Make the authority chain non-bypassable

The staged Desktop → Palmier work now in this branch is the right architectural
correction:

1. gate and build a cut-only candidate first;
2. advance only with a converged, hash-bound visual plan;
3. render catalog-selected graphics before Desktop receives mutation authority;
4. authorize only operations in the bound worklist;
5. compare-and-swap against the last readback fingerprint;
6. pause on drift or unobservable mutation;
7. export the exact candidate and bind both visual reviews to its hash.

The legacy global live-drive marker must remain ignored.

### B. Treat face-bridge as a named treatment, not `overlay-rich`

For this benchmark family, the plan must explicitly choose:

- cream rail + full-height presenter right;
- dark canvas + stable right portrait PIP;
- no floating lower third as a substitute;
- stable geometry across all windows in the chapter;
- chassis alternation at semantic chapter changes.

`overlay-rich` remains a broad axis for other operator styles. It cannot be the
only instruction for benchmark parity.

### C. Require semantic payloads

Each factual beat should carry form-specific fields:

- configuration → key/value + status;
- chronology → dated nodes;
- comparison → hero, baseline, units, delta;
- measurement → values, threshold, verdict;
- QA → lanes/checks + searched failure;
- vendor/tool → identity, role, authorization/provenance;
- mechanism → domain diagram or actual UI evidence;
- claim → source and limitation where applicable.

If those fields do not exist, the planner must choose a statement beat or omit
the graphic; it must not disguise a paraphrase as evidence.

### D. Budget by coverage and anatomy, not slot count

For a direct attempt at this benchmark grammar, target:

- graphics continuously present after the first disclosure/setup;
- about 0.8+ distinct information forms per graphic window;
- no consecutive reuse of the same information anatomy;
- macro-chassis changes instead of extra punch-in pairs;
- first meaningful content within 0.6s of entry;
- progressive module lands throughout long holds.

These are reference-profile targets, not universal longform defaults.

### E. Rebuild a proof slice before the full master

The next honest proof is not another full 11-minute manual attempt. Rebuild
0:00–1:00 from a lint-clean plan through the staged Desktop path and require:

1. at least four semantically distinct forms;
2. at least one cream rail and one dark face-bridge takeover;
3. no decision/track mismatch;
4. measured presenter-safe geometry for every rail;
5. no still gap above four seconds;
6. exact-candidate deterministic QC plus composition/editorial passes.

Only after that slice passes should the same authority chain extend to the full
670 seconds.

## Bottom line

The benchmark works because it is an editorial operating system, not a pile of
nice templates. It holds the presenter through two stable worlds, changes the
information shape for every idea, builds evidence in the order the audience can
understand it, and spends motion inside the argument.

C0679 reduced that system to animated labels over a talking head—and the
delivery path did so even when the plan said otherwise. The fix is to make style
selection, semantic payload, rendered kind, candidate fingerprint, and final
review one unbroken contract.
