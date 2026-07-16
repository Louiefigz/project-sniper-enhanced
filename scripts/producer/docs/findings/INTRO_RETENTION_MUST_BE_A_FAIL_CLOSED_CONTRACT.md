# Intro Retention Must Be a Fail-Closed Contract

## Finding

A plan can satisfy several presence checks and still produce a visibly bare
intro. The July 13 regression was a 44.23-second longform excerpt with four
source cuts, three graphic windows, five planned punches, and zero transitions.
Its non-head coverage was only 12.97 seconds (`29.3%`), and its final quiet span
was 15.8 seconds. It passed because three independently weak policies aligned:

- the hard Hook Contract said 60 seconds, but pacing reverted to the longform
  30-second zoom-cadence window;
- the 40% first-minute non-head floor emitted a warning;
- `transitions: []` counted as lane coverage without explaining a hard-cut
  decision.

The result was technically planned but editorially unfinished.

## Contract

Produced/full longform now fails before render when any of these is true:

1. A <=60-second longform output, or an explicit excerpt, contains a visual
   quiet span above the four-second hook ceiling. The pacing model counts cuts,
   graphic/b-roll/title entrances, internal graphic lands, treatment visual-state
   boundaries, transitions, and semantic/recompose punches.
2. Non-head visuals cover less than 40% of `min(output duration, 60s)`.
3. A checked/automatic transition lane contains no actual transition. A
   `transitionRationale` receipt cannot replace a deliverable the operator
   explicitly selected.
4. Any eligible intro cut seam has neither an authored transition nor a
   `transitionRationale` receipt with `decision: "clean-hook"`, a meaningful
   reason, and `{outTime, evidence}` for that seam within ±0.25 seconds.
5. The first `min(output duration, 180s)` contains a quiet span above the
   four-second retention ceiling. A measured live-panel recompose and an
   explicit screen-share/mixed zone are exempt because their base is
   continuously active; a static talking-head card is not.

These checks use the authored plan, so failure happens before expensive render
or Palmier publication.

## Operator Escape

Do not apply the produced contract when the operator explicitly selects a trim
or light scope, or assigns the relevant lane `off`/`operator`. Absence is only
intentional when controller-owned intent says so. A produced/full plan cannot
quietly downgrade itself by returning empty tracks.

## When Not to Use This Rule

- Do not require 40% non-head coverage for a deliberate trim/light treatment.
- Do not turn the four-second activity ceiling into a hard-cut quota. Internal
  builds, reframes, graphics, b-roll, and purposeful transitions all count.
- Do not transition every seam merely to make the edit busier. When the lane is
  checked, at least one measured, motivated transition is required; every
  remaining hard cut is legal only when that exact seam has concrete,
  time-bound evidence explaining why it is cleaner. If the operator wants zero
  transitions, they must uncheck/waive the lane explicitly.
- Do not count continuous 1.00→1.01 aliveness creep as a perceived change; it
  cannot rescue an otherwise static intro.

## Regression Test

`tests/test_intro_retention_contract.py` reconstructs the 44.23-second failure
shape and requires all three original defects—29% coverage, the 15.8-second
quiet tail, and the unjustified empty transition lane—to fail closed.
