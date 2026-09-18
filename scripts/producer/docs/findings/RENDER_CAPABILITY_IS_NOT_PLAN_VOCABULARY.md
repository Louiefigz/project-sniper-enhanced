# Render capability is not plan vocabulary

## The question that taught it (2026-07-28)

An operator asked what sounds like a simple feature question:

> *"What happens when I ask for custom animations at certain timestamps? For
> instance: I want the Claude icon over a beach with palm trees, and it comes
> down from the sky and then goes down into the ocean."*

The first answer given was **wrong in a specific and instructive way**: it
reported that the beach was unreachable because comp assets are restricted to
`.svg` files under `templates/motion/icons/`. The operator pushed back — *"but
by using HyperFrames, couldn't we create that code?"* — and they were right.

The restriction is real, but it governs something much narrower than the first
reading assumed. The correction is the finding.

## Two layers that look like one

```
edit_plan.json graphicsTrack   →  SELECTS a kind + fills DECLARED variables   ← CLOSED
catalog comp / project bundle  →  governed HTML/CSS/SVG/canvas/GSAP authoring ← OPEN
```

The rendering layer is **not capped by the `graphicsTrack` vocabulary**.
HyperFrames renders a pinned headless Chromium page with a paused GSAP timeline,
seeked frame by frame. A mark falling out of a gradient sky into a gradient
ocean is ordinary governed web animation.

That is broad, not literally unlimited. Browser/runtime support, deterministic
seeking, declared assets/fonts, measured canvas/alpha behavior, the local or
OCI sandbox, and the released scene contract still bound what can ship. This
does not imply After Effects plug-in, arbitrary 3D, tracking, rotoscope, or
native NLE-keyframe parity.

The **plan** layer is deliberately closed. A `graphicsTrack` entry can say only:

| Field | Meaning |
|---|---|
| `outStart` / `outEnd` | output-time window (derived from `triggerWords` via `compile_timeline.py`; the brain never freehands timestamps) |
| `kind` | which comp file — must exist in `templates/motion/compositions/` |
| `spec` | values for variables the comp **declares** in `data-composition-variables` |
| `anchor` | placement slot, never raw pixels |
| `exitOnCut` | clamp `outEnd` to the next cutTrack seam (G4) |
| `takeoverBase` | `"blur-desat"` treatment of the footage beneath |
| `recompose` | `{clearX: [x0,x1]}` → a synced face-anchored push |
| `pipHole` | scale the base footage into a transparent hole |
| `spec.entrance` | `glass-rail` only, from a fixed enum |

There is no motion-path, keyframe, easing, or waypoint vocabulary anywhere in
that list. **Animation is a property of the comp, not of the plan.**

So the honest answer to "can Sniper do a custom animation at a timestamp" is:
*yes through a governed authored comp or project-scoped scene bundle.*
`graphicsTrack` still cannot describe arbitrary keyframes itself, and
`plan_lint` fails closed on an unknown `kind` rather than approximating
(`template_contract.validate_entry`, plus the no-fallbacks rule). The released
P4 route is direct Codex/Claude Code → `scene_package_cli.py`; it is not an
Ask Editor field or a general one-shot planner that silently invents arbitrary
motion vocabulary.

## What the asset restriction actually governs

`graphics/template_assets.py:38-55` (`_selector_path`) rejects absolute paths,
`..` traversal, and any extension that is not `.svg`, then resolves against
`templates/motion/icons/` with a `commonpath` containment check.

It runs from `selector_errors`, which iterates **only** `icon_keys(declared)` —
variables whose id is `iconFile` or matches `iconN` (`_is_icon_key`). That is a
guard on **what a plan is allowed to point at**. It is not a sandbox on comp
authoring, and it inspects no comp HTML.

Measured against the live catalog (46 comps):

- **10** use `background-image`; **8** embed `data:image/svg` URIs directly.
- `glass-takeover-bg.html:53-70` builds its entire "sky base" from CSS
  `linear-gradient` grid lines plus a `radial-gradient` glow. No asset file.
- `logo-card.html:105` sets `img.src` at runtime from `iconFile`, resolving
  bare names to `/icons/<name>.svg` in comp JavaScript.
- At the time of the 2026-07-28 audit, **45 of 46** comps loaded GSAP from
  `cdn.jsdelivr.net`. The 2026-07-29 P0 fix moved all 46 to the exact vendored
  GSAP 3.14.2 runtime. The first post-migration probe honestly exposed 31
  blocked rows; after fixing measurement-before-enforcement and half-frame
  quantization, the real offline reprobe completed **46 of 46** release-ready
  rows. Local dependency closure and successful render proof remain separate
  requirements even though both now pass.

A comp that pulls a third-party script over the network on every render is not
a comp operating under an asset sandbox. The lesson: **a validator's blast
radius is the set of inputs it iterates, not the topic it appears to be
about.** `_selector_path` reads like "comps may only use approved SVGs"; it
means "plan-supplied icon selectors may only name approved SVGs."

## How a custom animation actually gets built

Reusable catalog motion can still be one new file in
`templates/motion/compositions/`, following the authoring contract in
`templates/motion/CLAUDE.md`. One-off/project-specific P4 work instead enters a
hash-bound scene bundle through `graphics/scene_package_cli.py`, with declared
variables, independently renderable units, local assets, provenance, QC, and
baked-regenerable Palmier bindings. Both paths obey the same core rules:

1. Declare params as JSON on `<html data-composition-variables='[…]'>` and read
   them at runtime via `window.__hyperframes.getVariables()`. `--variables`
   fills these.
2. One **paused** timeline registered by composition id:
   `window.__timelines["<id>"] = gsap.timeline({ paused: true })`.
3. `data-duration` on the root element **is** the render length. It is fixed at
   compile time and ignores `--variables`; the pipeline rewrites the root attr
   per window via `composition_transform.set_root_duration` (aliased into
   `graphics_render`). Do not try to parametrize duration.
4. Determinism only — no `Date.now()`, no `Math.random()`, no `repeat: -1`. The
   content-hash render cache depends on byte reproducibility.

Format follows the anchor automatically (`graphics_render._FORMAT_BY_ANCHOR`):
own-screen takeover → opaque `.mp4`; every overlay anchor → ProRes 4444 alpha
`.mov`. Never `webm` — it drops alpha (proven, edge G2).

Verification is `template_contract.validate_entry` (schema + declared
variables) and `asset_proof.prove_rendered_asset` (format/alpha/dimensions/
duration) — not any `npm run` target. New comps join the catalog through the
`producer-study` Phase 4 bar: spec → builder agent → lint clean → realistic-data
render → alpha via RGBA-PNG-first (G18) → settled frame reviewed beside the
reference → sample into `renders/samples/`. Then re-run
`graphics/comp_catalog_probe.py` so the new comp appears in
`comp_capabilities.json` (see COMP_CAPABILITIES_ARE_MEASURED_DATA).

For the beach specifically: gradient sky, SVG palm silhouettes, gradient ocean
with a shimmer, `<img src="/icons/claude.svg">` for the mark, `power2.in` on the
fall for gravity, then a scale-and-fade into a ripple ring at the waterline.
Nothing about it is architecturally novel.

## The delight gap is now bounded but not fully integrated

The graphics doctrine is **form follows information shape** — comparison →
bars/scoreboard, process → pipeline/rail, evidence → receipt/ledger, thesis →
statement. Every proposer lane in `planner/graphics_planner_*.py` keys off
`planner/motion_triggers.py`, a deterministic detector for numbers,
enumerations, entities, contrasts, and sequence markers.

A beach drop is **decoration**, not information. It will render fine and clear
the applicable gates as an operator-named scene.

The original proposal gap now has a bounded deterministic
`planner/creative_proposer.py` lane for visual metaphors, comic beats,
emotional emphasis, world visualization, and showable referents, with separate
short/long decorative budgets. Its tests prove that those reasons do not depend
on fact-shaped motion triggers. It is not yet invoked by the production
graphics planners, so autopilot still does not turn a proposed delight beat
into a custom authored bundle and integrated final project without the direct
agent/CLI authoring step.

## Adjacent state: long-form is the more finished product

Audited the same session, for the "is it optimized for long vs short" half of
the question:

**Genuinely mode-aware.** `plan_lint_smooth.py` (longform-only smooth grammar —
off-seam scale pops are an ERROR); region-aware still gaps (`hook_still_gap_s:
4` vs `max_still_gap_s: 20`, the front-loaded envelope); a dedicated
`planner/graphics_planner_longform.py`; PIP-hole takeover legal for longform and
banned for shorts; `reframe.layout: "split"` shorts-only; longform SRT +
chapters sidecars; the `edit_scope` trim/light/produced/full lane system.

**Correction since the audit.** Incremental graphics is no longer
longform-only. `graphics_base_effects.py` projects long-form recompose and
legacy-caption suppression as the only current graphics-to-base dependencies;
`render.py --skip-graphics` removes suppressed legacy cues before encoding the
base, while explicit caption authority is composited post-base. Ordinary scene
copy and `presenterFrame` alpha/format changes reuse the base for shorts and
long-form. Fresh retained short/LF-14 parity controls now bind the current
toolchain and registry, dirty only scene/composite/final, reuse
source/timeline/base, and match isolated forced-full FrameMD5 and PCM exactly.
This closes the bounded P0 graphics/base freshness exit, not the P5
fine-grained renderer or complete-product performance gate.

**Still not optimized:**

1. **The animated PIP takeover is dead code.** `graphics/pip_takeover.py` is
   unwired — `render.py` never calls it and `plan_lint_motion` hard-rejects
   `needsPip`/`canvas-pip-list`. Only the static face-in-hole version ships.
2. **No subject tracking.** `reframe.track` is reserved and accepts only
   `false`. A graphic cannot follow a moving subject.
3. **Terminal polish remains measured debt, not hidden failure.** All 46 comps
   now render/decode offline, but the matrix classifies 19 as
   `partial-fade`. Plan lint warns on those measured residuals; a clean fade or
   deliberate cut-bound exit is preferable when the edit affords it.

## The principle

When a system has a **fixed vocabulary over an open substrate**, "can it do X?"
has two different answers and they are routinely conflated:

- *Can the substrate render X?* — usually yes, and the substrate's own docs will
  tell you so.
- *Can the vocabulary name X?* — only if someone extended the vocabulary first.

Answer both explicitly. Answering only the second reads as "the system can't do
that," which is false and discourages the one-file fix. Answering only the first
reads as "just ask for it," which is also false and produces a plan that fails
lint.

## When NOT to reach for a new comp

- **When an existing comp's information anatomy genuinely matches.** The
  `template_usage_contract` tracks cross-project reuse for a reason; a catalog of
  60 near-duplicates is worse than one of 46 well-chosen forms. Reuse when the
  information shape, layout chassis, and animation grammar all match — not when
  only the copy differs.
- **For a genuine one-off you will never repeat.** Prefer a project-scoped P4
  bundle instead of expanding the global catalog. Native Palmier keyframe
  authoring remains unqualified until connected mutation/readback evidence
  passes; do not use its mere adapter surface as a release claim.
- **When the ask is photographic, not designed.** A real beach is b-roll
  (`broll/broll_pool.py`), not a comp. Layer order permits a graphic over an
  inserted cutaway. `test_graphics_broll_layering.py` now pins `render.py` to
  b-roll before graphics, then runs b-roll → alpha graphic → caption burn on
  real media. The same pixel oracle rejects a missing graphic and the reversed
  graphic → b-roll pipeline; it also preserves exact encoded audio across the
  controls. That proves the generic layer mechanism, not the visual quality of
  every authored comp or a full-length delivery.
- **Before checking `comp_capabilities.json`.** The measured matrix already
  records every comp's real canvas, aspect, fade class, and declared spec
  fields. Read it before concluding nothing fits.
