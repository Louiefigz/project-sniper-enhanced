# Reference matching can reuse part of a component

An inspected component can be useful even when it cannot reproduce the entire
requested shot. Treating its fit as a single yes/no answer hides that opportunity.

For example, an existing comparison card may already provide readable layout,
type hierarchy and a reliable parent timeline. If the reference needs a per-digit
reveal that the card lacks, retain the card and add that reveal. Rebuilding the
whole card repeats work and opens new layout/timing failure paths.

## Encode the missing behavior, not a blanket rejection

The first mapping validator required every retained component to be `usable`,
while a custom comparison required it to have a `gap`. That made it impossible
to retain the same component whose gap justified the custom extension.

The corrected custom route allows that component in both `pieces` and `closest`
when the record names its limitation, the specific changes and the bounded custom
scope. `retainedRefs` and `retainedPiecesRationale` preserve what is reused.
An unresolved asset/source/adapter prerequisite still cannot become a selected
piece or a claimed capability failure.

This belongs only to an explicitly requested reference-shot/style match. General
library inspiration does not need a project-bound reference map. Use the
[shared workflow](../producer/REFERENCE_SHOT_REUSE.md) for Short and Long planning.

## Evidence and limits — September 15, 2026

- 21 core mapping tests cover partial reuse, all routes, exact evidence and
  stale/changed inputs. Two cases specifically exercise retaining a component
  with a gap and refusing an unaccounted gap.
- 25 CLI/native integration tests cover optional activation, project/format
  checks, conflicting pins, before/after checks and sealed export recovery.
- A real-catalog draft for one explicitly synthetic shot retrieved ten candidates
  in 0.18 seconds. Checking it rejected its pending decision as intended.
- An inert Long fixture passed the installed native static SDK with a completed
  test map in 0.304 seconds. No media executed and no style/quality approval was
  asserted.

These numbers measure planning infrastructure, not creative review, rendering or
total production time. Do not use them to promise a faster finished video. Do not
retain a component merely to improve a reuse count when it compromises the target's
readability or behavior; document the quality gap and build the necessary part.
