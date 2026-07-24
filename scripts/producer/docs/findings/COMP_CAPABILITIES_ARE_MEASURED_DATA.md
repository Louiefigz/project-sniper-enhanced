# Comp capabilities are measured data, not catalog claims

## The night that taught it (2026-07-23)

Five comps failed one at a time through the render/mint cycles. Each failure
followed the same loop: pick a comp from the catalog, author its spec, mint the
render, watch it fail (or land wrong), diagnose, pick again. Roughly **one hour
of serial iteration** was spent discovering facts about the catalog that were
true before the session started — which canvas each comp is actually authored
on, and whether its terminal frame fades out or holds alpha to the cut.

The worst instance was the fragment case (FAILURE_LEDGER **LL-036**): a
free-band 16:9-authored comp bound onto a 9:16 short. The composite bus scales
only same-aspect canvases, so the comp composited **raw and clipped** at the
frame edge. Nothing upstream could have refused it, because nothing upstream
knew the comp's real canvas: the plan-time comp-size gate (`comp_measure.py`)
SAFE_BOX-checks only 9:16-authored comps, the planner's canvas map derives from
*declared* `data-width`/`data-height` attributes (which drift from the rendered
root), and the fade behavior lived only inside render-proof rejections
(**LL-037**: the catalog advertised no aspect/fade capability at all).

The root defect is structural, not any one comp: **catalog capability lived
nowhere a planner could read**, so capability was discovered by render failure,
one comp per failure, at mint-cycle cost.

## The fix: measure the whole catalog once

`scripts/producer/graphics/comp_catalog_probe.py` measures all 46 registered
comps in one batch (**~15 minutes one-time**, content-hash cached — re-runs on
an unchanged catalog are nearly free) and emits
`templates/motion/comp_capabilities.json`:

- **STATIC pass** (all comps, cheap): the real authored canvas from the
  `#<id>-root` CSS rule (px or `--canvas-w/h` token indirection, not the
  declared `data-*` attributes) → `canvas` + `aspect` (`"9:16"`/`"16:9"`),
  declared spec fields/defaults, and position knobs.
- **RENDER pass** (one real render per comp through the production
  `render_entry` path): terminal-frame alpha → `fadeClass`
  (`fades-clean` / `hold-to-cut` / `partial-fade`) and the settled content
  bbox. Comps that fail record `renderError` honestly.

One hour of discovery-by-render-failure per session becomes a 15-minute
one-time measurement whose answers are readable at plan time, forever.

## Where the matrix is consumed

- `graphics/comp_capabilities.py` — the reader:
  `is_aspect_legal_kind(kind, aspect)` (sibling of
  `form_allocation.is_gate_executable_kind`, the canvas-pip-list precedent).
  Measured aspect is **authoritative**; an unmeasured kind stays permissive so
  the derived MG-4.3 filter and render proofs still stand behind it.
- `planner/graphics_planner_longform.canvas_ok` — the funnel every proposal
  lane runs through (both modes, all three styles, plus the gauge/reference/
  whiteboard lanes) now consults the matrix before the declared-dims
  derivation, so **the planner can never propose an aspect-illegal comp**.
- `graphics/form_allocation.py` (`_is_allocatable_kind`),
  `graphics/intro_semantic_contract._wide_forms`, and
  `planner/graphics_planner_items._long_list_candidate` — the semantic
  allocation seams drop measured-9:16 kinds from the 16:9 lane.
- `.claude/skills/producer/SKILL.md` step 3.5 "Comp physics" — the brain reads
  the matrix before choosing forms: aspect mismatch = hard no; `hold-to-cut`
  comps must end on a cut seam (`exitOnCut`) or under a transition, never
  mid-shot expecting a fade.

## The principle

When a catalog's entries have physical behavior (canvas, fade, geometry), that
behavior is **data to measure once**, not knowledge to rediscover per failure.
The test for whether you need this: if learning a catalog fact costs one failed
expensive cycle (a render, a mint, a deploy) and the fact is stable until the
artifact is edited, batch-measure it and gate on the measurement. A
content-hash cache makes the measurement idempotent; honest `renderError`
entries keep broken comps visible instead of silently unmeasured.

## When NOT to use this

- **Never hand-edit the matrix.** It is measured output; a hand-patched entry
  is a catalog claim again — exactly the failure class it exists to kill.
  Regenerate with the probe after any comp edit.
- **It does not replace render proofs.** The matrix is plan-time capability
  data; per-render terminal-alpha/occupancy proofs still gate every real
  artifact (a spec can change a comp's behavior vs its defaults probe).
- **An absent matrix is not an error.** Predicates degrade to permissive and
  the declared-dims filter still applies — fail-closed here would brick every
  fresh checkout on data only the probe can create.
- **Don't stretch it to per-spec questions.** The probe renders each comp once
  with defaults; content-dependent geometry (long copy, extra rows) stays the
  job of `comp_measure.py`, which renders the *actual* plan entry.
