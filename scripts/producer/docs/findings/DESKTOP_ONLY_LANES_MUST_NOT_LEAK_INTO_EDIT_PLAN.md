# Desktop-only lanes must not leak into the render plan

## Finding

A field can be valid for an editable Palmier timeline and invalid for the
canonical renderer. Putting that field directly into `edit_plan.json` makes all
downstream consumers appear to agree when they do not.

The first native banner used a top-level `persistentText` array. Desktop repair
could add it to Palmier, but the in-house renderer had no corresponding stage.
Before the fix this caused three contradictory outcomes:

- the base fingerprint changed, triggering an expensive base rebuild;
- the final plan hash claimed the banner affected delivered pixels;
- Palmier parity treated the same field as unknown and blocked a flat mirror.

## Fix

Palmier-native additions now travel in `palmier-revision-set` sidecars. The
sidecar is bound to the base plan hash and candidate fingerprint, participates
in Desktop QC authority, and supplies changed-window review frames. It is not
silently consumed by the in-house renderer.

Legacy `persistentText` is stripped from Python and TypeScript render hashes so
it cannot invalidate a base or claim nonexistent pixels. Parity intentionally
continues to reject it as an unknown canonical lane.

## Rule

Add a new top-level `edit_plan.json` lane only when all of these consumers ship
together:

1. Python and TypeScript canonical render hashes.
2. In-house render/assemble behavior.
3. Palmier parity and checkpoint translation.
4. Plan lint and UI plan types.
5. Final provenance and regression tests.

Until then, keep destination-specific data in a destination-specific,
hash-bound sidecar. Do not make an unsupported renderer field look canonical by
merely teaching one executor how to read it.
