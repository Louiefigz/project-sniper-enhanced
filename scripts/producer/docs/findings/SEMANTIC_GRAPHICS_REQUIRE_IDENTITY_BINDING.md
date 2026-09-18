# Semantic graphic density requires identity-bound evidence

## The defect

A density gate can be fooled while every individual row looks plausible. Two
decisions can repeat one `beatId`, multiple beats can point at one long graphic,
or an unbound filler window can raise a raw graphics count. An incomplete beat
detector can create the inverse loophole: if the required count is capped by the
number of detected beats, detecting only two opportunities silently turns an
explicit four-graphic promise into two.

All four cases confuse records with independently realized editorial ideas.

## The invariant

The controller, not the model, mints each graphic id. A semantic realization
counts only when all of these identities agree:

- exactly one decision has the opportunity's `beatId`;
- exactly one graphics-track row has the decision's `graphicId`;
- that row's `semanticBeatId` equals the same `beatId`;
- its window covers the beat and its form belongs to the beat's compatible
  information-shape family.

Duplicate decision rows make that beat ambiguous and therefore unbound. One
graphic id may realize only one beat. An unbound card may still be legal for
another editorial reason, but it cannot satisfy semantic density or structural
variety.

For produced/full longform, the first-minute requirement is absolute: four
unique transcript-bound graphics. If transcript analysis surfaces fewer than
four opportunities, the run fails and the detector or plan must be corrected.
The system must never reduce the promise to match incomplete evidence.

## Why proximity is insufficient

Time overlap can help validate a declared binding, but it cannot create one.
One broad card can overlap several nearby phrases; counting those phrases as
separate graphics would report variety the viewer never sees. Stable ids make
the one-to-one relationship auditable across authoring, revision, save, lint,
render, and Palmier handoff.

## Verification

`test_intro_graphics_binding_adversarial.py` covers duplicate shadow rows,
shared graphics, filler windows, and the absolute floor when only two beats are
detected. `graphic-ids.test.ts` covers controller minting and refuses ambiguous
`semanticBeatId` reconciliation.

## When not to use it

Do not require a semantic binding for captions, decorative chrome, or a
deliberate multi-state animation that is already one graphic realization. Such
elements may exist, but they do not count toward the transcript-bound floor.
