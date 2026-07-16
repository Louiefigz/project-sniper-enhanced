# Palmier divergence invalidates Sniper template-history evidence

## The defect

Plan-hash and QC checks can prove that a Sniper plan was once approved. They do
not prove that it still describes what shipped after a human edits the
authoritative Palmier timeline. Learning template usage from the stale Sniper
plan teaches future runs that forms were delivered even when the operator
removed or replaced them in Palmier.

That is worse than forgetting: it is confident learning from the wrong source
of truth.

## The invariant

A project with no Palmier state may teach when its current plan hash matches a
valid QC approval. Once Palmier state exists, history admits the project only
when all authority evidence agrees:

- ownership is Sniper;
- the workspace is a verified visual-master mirror;
- the last-pushed plan hash equals the approved current plan hash;
- a current timeline id exists;
- parity says the mirror is ready;
- readback verification is successful and binds that same plan hash and
  timeline id.

Palmier-owned, manually diverged, stale, malformed, missing-proof, or
unverifiable states are excluded from the usage window. They remain valid
authority for their own project; they simply cannot claim what Sniper shipped.

## Why exclusion is safer than reverse inference

A Palmier diff proves that elements changed, but it does not automatically map
every native or baked element back to a Sniper template kind. Guessing that
mapping would contaminate global memory. Until a verified reverse translator
exists, the honest choice is to exclude the project from Sniper template
history rather than infer a lesson from incomplete parity.

## Verification

`template-usage-history.test.ts` builds Sniper-only, verified-mirror,
Palmier-owned, and stale-plan fixtures. Only the Sniper-only and current
verified-mirror projects contribute template counts.

## When not to use it

Do not delete or roll back a Palmier-owned project because it is excluded.
Exclusion changes only cross-project learning eligibility. Palmier remains the
source of truth for that edit, and its verified before/after evidence can enter
the separate doctrine-proposal workflow without masquerading as a current
Sniper plan.
