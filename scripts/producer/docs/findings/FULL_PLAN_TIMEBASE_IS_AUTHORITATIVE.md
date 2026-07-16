# A complete plan owns its output timebase

## Finding

`base_plan.json` describes the timebase of an existing rendered base. It does
not describe the timebase of every newer `edit_plan.json`. A full-plan writer
authors cuts, graphics, motion, captions, and treatments together; those timed
lanes already target the new plan's own `cutTrack`. Re-running a cut-only refit
because the base cuts differ corrupts correct work.

## The C0679 incident

The authored snapshot had an exact 90.000-second cut and internally coherent
timing:

- the “real data” card occupied `57.03–60.50`;
- the final outcome card occupied `83.73–90.00`;
- treatment coverage was `0–60` and `60–90`.

Saved-plan preflight compared its cut track to a stale `base_plan.json` and
assumed every output lane was still on the old base timebase. It remapped 13
already-correct windows. One start at old output `57.03` landed inside removed
source content. The fallback then searched later source times and chose the
cold-open segment placed at output zero, producing a `0–56.87` graphics hold.
Treatment coverage ended at `83.73`, and the final card moved off the closing
segment.

## Contract

Every plan mutation declares provenance:

- **full-plan** — all output lanes are already in `cutTrack`'s timebase; never
  refit from the base;
- **cut-only** — the mutation supplies the exact pre-mutation plan; refit once,
  atomically, and bind a receipt to both source and target cuts plus promoted
  plan bytes;
- **unknown** — fail closed. Never infer a refit from base mismatch.

For a legitimate cut-only refit, removed endpoints walk forward or backward in
the **old output order** to the nearest surviving content. They do not search
globally by source chronology or choose the minimum/maximum new output time.
This matters for cold opens, reordered excerpts, repeated source ranges, and
multi-source edits.

Fresh auto-authored plans also quarantine a stale base before rebuilding. A
missing base forces a clean render from the plan as written and prevents the
generic assemble path from treating full-plan authorship like a cut-only edit.

## Recovery rule

Preserve the corrupted plan as history, restore the exact pre-refit snapshot,
quarantine the stale receipt, and rerun every planning gate and critic. Passing
lint after corruption is not enough: structural gates may shorten an illegal
hold without restoring semantic word-lock for the other shifted lanes.

## When not to use this pattern

Do not label a raw or third-party plan `full-plan` merely to bypass provenance.
If the writer cannot prove whether timed lanes moved with the cuts, stop and
ask for an explicit recovery source. Do not use output-order fallback to
invent content when an entire window was removed; drop it and report that loss.
