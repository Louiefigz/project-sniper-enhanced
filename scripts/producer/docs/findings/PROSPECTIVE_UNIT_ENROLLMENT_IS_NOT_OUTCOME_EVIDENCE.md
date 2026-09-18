# Prospective unit enrollment is not outcome evidence

## Finding

A unit must exist before the operation that can succeed or fail, but an
idempotency record created at operation submission is too late to establish that
denominator. The prospective enrollment ledger therefore has a separate closed
schema and durable store.

The enrollment binds a caller-issued `unitId` to:

- one authority and enrollment key;
- an external clock identity, sequence, and canonical UTC observation;
- immutable project, lineage, and experiment digests;
- one declared operation kind, lane scope, release, build, and execution policy;
- one immutable enrollment-policy digest.

Feedback, ratings, success, failure, fallback, and outcome fields cannot appear
in the schema. The quality-pass wrapper validates the enrollment against the
exact V3 admission, persists the enrollment first, rereads it under its
never-unlinked authority lock, then admits the operation. It removes only
`UNIT_ENROLLMENT_AUTHORITY` at the enrollment-binding layer. The composed path
now uses a separate durable order transaction before V3 admission and removes
`DURABLE_CROSS_LEDGER_PROSPECTIVE_ORDER_RECEIPT` only after reobserving its
exact committed receipt. Runtime execution, child sealing, fencing, and
publication remain false and unresolved.

## Why global arbitration matters

Checking only the requested enrollment key permits two different keys to retain
the same unit. Exact replay must validate the complete retained set before an
early return:

```text
lock authority root
  -> verify immutable authority identity
  -> bounded-scan and reject unknown, torn, or over-capacity store entries
  -> reparse every canonical enrollment
  -> prove global unitId uniqueness
  -> resolve exact replay or create one new enrollment
```

Exact closure must not call `listdir()` and materialize an attacker-sized list or
set before rejecting it. The enrollment store now uses `scandir()` to reject an
unexpected record member immediately and caps valid-looking enrollment records
at 4096 before allocation can grow further.

The focused campaign passed 30 tests plus 19 subtests. Six forked processes
submitting the same identity created exactly one record. Concurrent distinct
keys for the same unit produced one winner and one unit conflict. Concurrent
fresh-root claims by different authorities also produced exactly one authority
winner. The campaign additionally covers changed-key identity, retained-set
duplication, orphan state, byte mutation, unsafe modes, hardlinks, symlinked
locks, hostile equality, noncreating reads, a 4097-entry valid-looking directory
flood, and later composition failure.

## What this does not prove

The enrollment ledger alone still does not prove cross-ledger order. That proof
comes from the separate order protocol described in
`CROSS_LEDGER_ORDER_REQUIRES_SHARED_OUTER_LOCK.md`. Callers that use only this
store and the V3 admission store still have no prospective-order receipt.

The timestamp remains an externally supplied observation with whole-second
precision. The binder now rejects only `observedAt > firstSubmittedAt`; equal
seconds are compatible but do not prove order. The durable PREPARED-before-
admission receipt supplies order without inventing subsecond clock precision.
Neither mechanism attests when a human first formed feedback.

Enrollment also says nothing about whether an operation ran correctly. A valid
unit may have no attempt because validation, capacity, cancellation, or
controller startup failed. That is the point: those units stay in the
denominator instead of disappearing.

## When not to use this result

Do not use the enrollment record as an attempt, queue item, render-start token,
success receipt, statistical analysis, or publication fence. Do not reconstruct
it from a V2 admission after feedback. Exact V3 admission and enrollment are
separate authorities and become useful together only through the reobservation
binder.
