# Cross-project template memory must learn only from approved truth

## The defect

A large template catalog did not produce diverse edits. Each run began with the
same ordered candidate menu, so locally reasonable choices repeatedly converged
on the same familiar forms. Within-plan variety checks could stop consecutive
duplicates, but they had no memory of what shipped in earlier videos.

## The invariant

Creative memory is a run input, not mutable global taste. Capture a bounded
window of recent, same-mode projects before authoring and accept a project only
when its final QC approval is still valid **and** the current `edit_plan.json`
hash exactly matches the approval's `planHash`. A stale approval must never bless
post-approval plan edits.

The capture is stored once per run and its path plus digest are bound into the
durable job before the writer launches. Authoring, revision, independent review,
and the controller gate therefore reason against the same historical evidence.

Passing the gate must also leave a delivery receipt. That receipt binds the
exact plan bytes and semantic content, manifest, transcript hashes, gate
implementation, and immutable history snapshot. Saving another draft removes
the receipt; HTTP and CLI render/assemble/Palmier entrypoints reject a
produced/full system-owned graphics lane until the current plan is reviewed
again. Otherwise a correct authoring loop can still be bypassed at the last
inch by a direct render command.

Whether that wall applies comes from the stored resolved operator intent in
`project.json`, never from mutable `plan.target`. A plan cannot turn its own
graphics lane off to waive governance. The receipt also binds the exact
operator-intent authority and `operator_intent_contract.py` implementation that
passed, so any plan or intent mutation requires the controller to rerun both
contracts before delivery.

## The selection rule

- Measure project incidence, not only raw window count. A template is overused
  only after it appears in at least 3 recent projects and at least half of the
  bounded 8-project window.
- Compare only transcript-compatible forms from the beat's information-shape
  family. Catalog order is never rank.
- Prefer a compatible underused form when one exists.
- Reuse remains legal when it is the best anatomy, but the plan must name the
  underused alternatives and record a transcript-specific `reuseReason`.
- If no compatible underused form exists, do not manufacture novelty. Semantic
  fit always outranks diversity.

## When not to use it

Do not learn from drafts, failed QC candidates, other output modes, invalidated
approvals, or reference assets themselves. Reference studies teach mechanics;
only verified shipped plans provide local product-usage history.
