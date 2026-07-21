# Durable admission is not render authority

## Finding

Persisting an operation admission closes replay ambiguity, but it does not prove
that the operation may execute. These are different authority questions.

The V3 store now retains the exact canonical admission and exact canonical
operation bytes under one never-unlinked authority lock. A record directory is
renamed into place only after both files and their directories are flushed.
Replay reopens and reparses both files, rebinds their digests, and returns the
original admission. A changed record under the same idempotency key conflicts;
an attempt ID or intended child generation already owned by another record also
conflicts.

In the focused campaign, 6 concurrent processes produced exactly 1 new record
and 5 exact replays. After adversarial expansion, the focused store/authority
suite passed 20 tests plus 13 subtests. It covers byte mutation, unsafe mode,
hardlink, unknown-entry, torn-pending, missing/orphan authority, Unicode and
filesystem path bounds, retained-set duplication, and cross-protocol authority
initialization races.

## Why this matters

An admission record proves:

- which exact request won idempotency arbitration;
- which exact operation bytes and child identity were retained;
- that later retries did not substitute another attempt or child.

It does **not** prove:

- that `unitId` was prospectively enrolled;
- that the current parent and fence are still unchanged;
- that the operation runtime or executable closure is trusted;
- that a child was executed, sealed, or published.

The durable result therefore remains
`DURABLE_OPERATION_ADMISSION_V3_REOBSERVED_NOT_EXECUTION_AUTHORIZED`, and its
authorization guard always rejects—even if a caller forges a boolean field.

## When not to use this approach

Do not use this store as a job queue, render-start token, liveness record, or
publication lock. Those protocols have different state transitions and crash
recovery requirements. Also do not reuse the older V2 registry: its free-form
parent and older identity projection cannot express the typed V3 operation
authority.
