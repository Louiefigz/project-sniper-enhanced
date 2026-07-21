# Versioned Readers Must Dispatch Before Materialization

## What failed in the obvious design

The frozen selected-generation reader validates every commit with the R0 profile.
Wrapping that reader and dispatching afterward cannot read genesis R1 or quality-pass
V2 at all. Loosening the frozen reader to accept every version also silently changes
the behavior of existing R0 callers, including the legacy null-parent R0 specimen.

A second tempting design is to copy the selected generation first and reject an
unsupported profile afterward. That remains non-authorizing, but it lets an invalid
manifest consume copy time and disk space before its class/version mismatch is known.

## The useful pattern

The safe copy engine now accepts an internal profile-validation callback. The frozen
public reader supplies its unchanged R0 validator. The new versioned reader supplies
an exact dispatcher that checks both the approved-card class and the publication edge
before `_manifest_tree` or `_walk` runs.

The versioned path accepts exactly three cases:

- null parent + `genesis-approved-card-v2` + CURRENT sequence 1;
- non-null parent + `quality-pass-approved-card-v2` + immediate sequence continuity;
- non-null parent + frozen `approved-parent-v1` + immediate sequence continuity.

Null-parent R0 is therefore rejected by the new path without deleting the frozen API
needed by old tests and migration tooling.

The lock is released after the exact snapshot is copied, so the result is deliberately
tagged as point-in-time evidence. Every result retains an explicit
`FINAL_CURRENT_AND_FENCE_RECHECK` blocker; a later operation must recheck CURRENT under
its execution/publication fence.

## Evidence

The disk test campaign covers real sealed trees for all three accepted profiles plus
null-parent R0 fallback, a genesis CURRENT at sequence 2, card/profile mismatch, stale
source bytes, an unsafe symlink, a wrong card schema version, and a post-copy byte
change. The focused campaign passed 13 tests and 4 parameterized subtests; the nearby
legacy/versioned regression campaign passed 88 tests and 79 subtests.

## When not to use this

Do not add a version-aware branch to a frozen semantic parser when a new tagged seam
can preserve the historical contract. Do not treat successful profile dispatch as
runtime, execution, or publication authority: it proves only which closed schema may
interpret the selected immutable bytes.
