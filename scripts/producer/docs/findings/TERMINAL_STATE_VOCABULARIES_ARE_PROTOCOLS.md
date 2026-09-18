# Terminal state vocabularies are protocols

## What failed

The headless MP4 execution contract defined terminal dispositions as
`SUCCEEDED`, `FAILED`, `BLOCKED`, `STALE`, and `CANCELED`. The trace primitive
accepted a different set: `SUCCEEDED`, `FAILED`, `SUPERSEDED`, and the
double-L spelling `CANCELLED`.

An executable probe showed that a controller following the written contract
could not seal three valid outcomes. Conversely, it could persist two outcomes
that downstream recovery did not understand. Both components were individually
strict, but they were strict about different protocols.

## Why this matters

Terminal state is durable authority, not display text. A spelling mismatch can
strand an active fence, make recovery loop forever, or collapse a stale-parent
failure into an unrelated state. Retrying does not repair the mismatch because
the trace correctly rejects an invalid terminal frame.

## The safer pattern

Define one closed vocabulary at the authority boundary and exercise every value
through the real serializer and validator. Reject legacy aliases instead of
normalizing them after persistence. Schemas in another language should use a
golden fixture generated from the same versioned contract.

The regression test now asserts the exact five-value set, proves every value can
seal a trace, and proves `CANCELLED` and `SUPERSEDED` fail closed.

Closed words are not enough. The same audit showed that the trace accepted
`POINTER_COMMITTED`, then `WORKER_START`, then `SUCCEEDED`. The lifecycle now
requires first-event admission and the monotonic authority sequence
`ADMITTED → RUNNING → VERIFIED → PUBLISH_INTENT → POINTER_COMMITTED`.
`SUCCEEDED` requires the committed-pointer phase; non-success dispositions may
seal an admitted attempt earlier. Diagnostic events cannot create an attempt or
move authority backward.

## When not to use this pattern

Open-ended diagnostic events can remain extensible. The closed-enum rule is for
states that drive authorization, retries, publication, cancellation, recovery,
or statistical disposition.
