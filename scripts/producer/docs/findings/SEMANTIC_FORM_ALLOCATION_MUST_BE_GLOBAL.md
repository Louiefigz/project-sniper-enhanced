# Semantic form allocation must be global

## The defect

The C0679 intro exposed eight deterministic, transcript-bound information beats.
Their compatible-form union contained seventeen built wide templates, and the
compatibility graph admitted an eight-beat/eight-form perfect matching. A writer
could still stop at the four-graphic minimum, mark the other strong beats
`omit`, and repeatedly choose familiar forms one beat at a time.

That output was locally legal but globally wasteful. A floor answers "what is
the minimum?" It does not answer "did every strong opportunity resolve?" And a
per-beat legal choice does not prove that repeated anatomy was necessary.

## The invariant

For Produced/full longform, every `decisionRequired` semantic beat resolves to
one bound graphic or a matching b-roll window. `omit` cannot discharge the
beat. When the b-roll lane is off, every required beat is a graphic.

Form diversity is a bipartite matching problem:

- left side: selected transcript beat ids;
- right side: built graphic kinds;
- edges: only that beat's deterministic `compatibleKinds`;
- objective: maximize the number of distinct kinds used.

The proposal exposes `maximumFeasibleDistinctKinds` and one deterministic
`recommendedAssignment`. Catalog order is not a preference: form names and beat
ids are stabilized before matching. The writer may use a different legal
assignment, but only if it reaches the same maximum distinctness.

The gate recomputes the optimum from the selected graphic beats. If the plan
uses fewer distinct kinds than feasible, it fails with beat-specific compatible
replacement witnesses. If the maximum matching itself requires repetition, the
reuse is legal; the system never forces an incompatible form for novelty.

## Why project history is separate

Approved-project history answers whether a form is stale across shipped work.
Global allocation answers whether repetition is avoidable inside this plan.
The latter must run even when the approved history window is empty. Drafts and
raw reference studies remain ineligible as usage history.

## Verification

`test_form_allocation.py` covers the real eight-beat C0679 perfect matching,
catalog-order stability, semantic legality, avoidable witnesses, and unavoidable
reuse. `test_template_usage_contract.py` proves the allocation gate remains
active with zero approved projects. Intro semantic tests prove all eight C0679
beats become graphics when b-roll is off.
