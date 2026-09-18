# Teacher-name rename — specification and migration plan

Accepted decision: **no paid teaching corpus and no teacher names in the distributed
product or public copy**; rename the shipped look labels without breaking the editing
system, and search text, filenames, metadata and visible asset text
(`build/decisions.md`, `build/packaging-spec.md`: "renaming is implementation work, not
a new permission question").

This is the specification, the measured blast radius and the migration order. It is
**not** a claim that the rename has been performed. The package builder records the
remaining occurrences in `PENDING-RENAME.txt` and marks the release not sellable while
any remain.

## Measured blast radius (shipped surfaces only)

Counted over `src`, `scripts`, `schemas`, `templates`, `.claude`, `.agents`, `assets`,
`public` and the three root instruction files. `docs/` and `artifacts/` are excluded:
their disposition is in `PROVENANCE-BLOCKERS.md`.

| Name | Shipped files touched |
|---|---|
| `caleb` | 34 |
| `jadenly` | 25 |
| `jaden` | 48 |
| `angela` | 34 |
| `nateherk` | 103 |
| **distinct total** | **147** |

Plus **17 files whose names must change**:

```
scripts/producer/docs/findings/JADEN_STYLE.md
scripts/producer/plan_lint_nateherk.py
scripts/producer/tests/test_jaden_gaps.py
scripts/producer/tests/test_nateherk_longform.py
scripts/producer/tests/test_nateherk_pack.py
templates/motion/compositions/angela-caption-dual-mode.html
templates/motion/compositions/angela-receipt-cell.html
templates/motion/compositions/angela-staircase-lockup.html
templates/motion/compositions/angela-takeover-deck.html
templates/motion/compositions/jaden-shout-lockup.html
templates/motion/compositions/nateherk-bullet-bars.html
templates/motion/compositions/nateherk-ledger-dark.html
templates/motion/compositions/nateherk-pipeline.html
templates/motion/compositions/nateherk-rail.html
templates/motion/compositions/nateherk-scoreboard.html
templates/motion/compositions/nateherk-takeover.html
templates/motion/nateherk-pipeline.js
```

## Why this is a migration and not a search-and-replace

The names are **identifiers, not labels**:

- `src/lib/producer/intent-presets.ts:42` — `PACES = ["talking-head", "client-reel",
  "caleb", "jadenly", "angela"]`
- `src/lib/producer/intent-presets.ts:48` — `STYLES = ["caleb", "jadenly", "angela"]`
- preset ids `caleb-light`, `jadenly-produced`, `angela-involved` (lines 449, 474, 500)
- `scripts/producer/producer_config.py:198,238,272` — the lint profiles
  `pacing_jadenly`, `pacing_caleb`, `pacing_angela`, selected by
  `plan_lint_motion.py:910-929` from `target.pace` via `f"pacing_{pace}"`
- composition names are **keys in `templates/motion/comp_capabilities.json`** and
  values in the card-form selection tables at `producer_config.py:1248-1290`
- `--nateherk-canvas` and `sc-root.nateherk` are CSS custom properties inside
  composition HTML

These values are written into **saved state**: `project.json` `intent.style` /
`intent.pace`, and `edit_plan.json` `target.style` / `target.pace` plus any comp
reference by name. A rename without a reader-side migration makes every existing
project fail validation.

Nine TypeScript and five Python test files assert the identifiers, including
`auto-edit-authority-cross-language.test.ts` and `intent-presets.test.ts`, which exist
specifically to catch TS↔Python drift. **They are the safety net: renaming one side
only will fail them, which is correct behaviour.**

## Proposed mapping

Neutral, mechanism-describing names. Each keeps the measured grammar it already points
at; only the identifier changes.

| Current | Proposed | Rationale |
|---|---|---|
| `caleb` (style, pace) | `restrained` | the grammar's own defining property: zero punch-ins, whisper captions, no bed |
| `caleb-light` (preset id) | `restrained-light` | |
| `pacing_caleb` | `pacing_restrained` | |
| `jadenly` (style, pace) | `punch` | breath-gap punch cuts, two-layer text, ~17 visible cuts/min |
| `jadenly-produced` | `punch-produced` | |
| `pacing_jadenly` | `pacing_punch` | |
| `angela` (style, pace) | `slideware` | full-frame takeover-deck graphics alternating with the presenter |
| `angela-involved` | `slideware-involved` | |
| `pacing_angela` | `pacing_slideware` | |
| `nateherk-*` (comps) | `module-*` | narration-paced module builds — the study's own description |
| `nateherk-takeover` | `module-takeover` | |
| `nateherk-pipeline` | `module-pipeline` | |
| `nateherk-rail` | `module-rail` | |
| `nateherk-scoreboard` | `module-scoreboard` | |
| `nateherk-bullet-bars` | `module-bullet-bars` | |
| `nateherk-ledger-dark` | `module-ledger-dark` | |
| `plan_lint_nateherk.py` | `plan_lint_module.py` | |
| `angela-takeover-deck` | `slideware-takeover-deck` | |
| `angela-receipt-cell` | `evidence-receipt-cell` | its selection table role is `evidence` |
| `angela-staircase-lockup` | `slideware-staircase-lockup` | |
| `angela-caption-dual-mode` | `slideware-caption-dual-mode` | |
| `jaden-shout-lockup` | `punch-shout-lockup` | |
| `--nateherk-canvas` | `--module-canvas` | |
| `sc-root.nateherk` | `sc-root.module` | |

Study documents keep their measured content but lose the name in the filename and the
body: `JADEN_STYLE.md` → `PUNCH_GRAMMAR.md`, and similarly for the others. The measured
numbers are the product's own measurements and stay; the attribution to a named creator
does not ship.

## Migration order

Do it in this order, running the suites between steps. **Do not** run a single global
`sed`: the CSS custom properties, the capability-matrix keys and the saved-state values
need different handling.

1. **Add the reader-side migration first, before any rename.** In
   `src/lib/producer/intent-presets.ts`, accept the old identifier on read and normalise
   it to the new one, then reject it on write. Mirror it in `scripts/producer/edit_scope.py`
   so both languages agree. Add a test that an existing `project.json` carrying
   `intent.style: "caleb"` still loads and resolves to `restrained`.
2. **Rename the pacing profiles** in `producer_config.py` and the `f"pacing_{pace}"`
   lookup, keeping a compatibility alias map for the three old keys.
3. **Rename the styles, paces and preset ids** in `intent-presets.ts`, then update the
   Python mirror. Run `npm test` and `selftest.py`; the cross-language drift tests must
   pass, not be relaxed.
4. **Rename the composition files**, then in the same commit update
   `comp_capabilities.json` keys, the card-form tables in `producer_config.py`, the
   `template_visual_contract.py` / `intro_semantic_contract.py` maps, and the CSS custom
   properties inside the comps. Nothing may be renamed on only one side.
5. **Regenerate or hand-verify `comp_capabilities.json`.** Its keys are comp names. If
   it is regenerated by `comp_capability_refresh.py`, that needs node and a browser, so
   budget a render-capable machine for this step.
6. **Rename the tests and study documents**, and update every reference to them.
7. **Sweep the prose**: `.claude/skills/*`, `.agents/skills/*`, `.claude/commands/*`,
   `CLAUDE.md`, `AGENTS.md`, `README.md`, `scripts/producer/CLAUDE.md`, the docs that
   ship, and `NATIVE_SHORTS_WORKFLOW.md`, whose example request currently says
   "Make a Nate Herk-style Short from this recording."
8. **Re-run everything**: `npm run type-check`, `npm run lint`, `npm test`,
   `selftest.py`. Then rebuild the package **without** `--allow-pending-rename`; the
   build's own scan is the acceptance check and must come back clean.

## What must not happen

- No test may be deleted, skipped or weakened to make the rename pass. The drift tests
  failing is the mechanism working.
- No saved project may be left unreadable. Step 1 exists for that and comes first.
- The measured grammar values must not change. This is a rename, not a retune.
- Renaming alone does not clear `PROVENANCE-BLOCKERS.md` B1: the reference libraries are
  a separate, larger problem than the identifiers.
