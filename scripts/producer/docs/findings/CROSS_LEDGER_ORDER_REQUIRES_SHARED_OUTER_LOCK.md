# Cross-ledger prospective order requires one shared outer lock

## Finding

Calling the enrollment store and then the admission store in source-code order
does not prove that enrollment preceded admission. Another process can use the
public admission API between an absence check and an order-intent write. A
timestamp cannot close that race, especially when both wire schemas record only
whole seconds.

The durable solution is a timestamp-free transaction with one global lock
order:

```text
.cross-ledger-order-v1.lock
  -> reobserve the exact retained enrollment
  -> .operation-admission-v3.lock
  -> discard only descriptor-validated pre-rename V3 scratch records
  -> preflight idempotency, attempt, child, and reserved capacity
  -> fsync and rename PREPARED intent while both locks remain held
  -> persist/replay and reobserve the exact admission bytes
  -> release the V3 lock
  -> reobserve the exact enrollment again
  -> append and reobserve COMMITTED receipt
```

Every public V3 admission write takes the shared outer lock exactly once. The
transaction uses a registered, PID-bound live-lock witness to enter its
already-held V3 path, so it cannot recursively flock the outer lock. A forged
dataclass, an expired context witness, and a witness inherited across `fork()`
are rejected.

## Durable states and recovery

Each order key is derived from the admission idempotency key, not the unit ID.
That distinction matters: one enrolled unit can legitimately contain multiple
attempts or fallbacks, and each exact admission needs its own order receipt.
The identity binds authority, unit, enrollment key/record/digest, admission
idempotency key, attempt ID, intended child generation ID, admission
record/digest, and a domain-separated identity digest. PREPARED reserves all
three V3 uniqueness roles, not just the filename-producing idempotency key.

The on-disk states are:

- **absent** — no order claim exists;
- **prepared** — exact intent is durable, but admission or receipt may be
  incomplete;
- **commit-pending** — exact receipt bytes were flushed but its final rename was
  interrupted;
- **committed** — exact intent and receipt are both retained;
- **replay** — a call reobserved an already committed exact transaction;
- **rejected** — the matching admission existed before any intent, so the key
  is permanently tombstoned instead of retroactively blessed.

A crash after PREPARED can create or replay only the admission named by that
intent. A crash after admission can append COMMITTED only after the exact
admission and enrollment are reobserved. An exact pending receipt is completed
deterministically. An initial `.pending-{record}-{nonce}` directory has not
crossed its record-rename commit point, so a writer holding both required locks
may discard only its bounded, private, target-bound safe subset and retry.
Wrong-target, oversized, unknown, symlinked, FIFO, over-capacity, or
identity-conflicting state fails closed. Reads never perform cleanup and create
no lock, store, record, or authority bytes.

## Why same-second timestamps are safe now

`observedAt == firstSubmittedAt` is no longer treated as evidence either for or
against order. It is accepted only as a compatible coarse-clock observation.
The PREPARED file is flushed and renamed while the V3 admission lock remains
held after preflight, which supplies the actual prospective-order proof. An
enrollment clock strictly later than `firstSubmittedAt` remains inconsistent
and is rejected.

## Adversarial evidence

The focused V3/order campaign currently covers 51 tests plus 27 subtests:
exact commit/replay, two
distinct admissions for one unit, crashes after intent and admission, exact
pending-receipt recovery, permanent rejection of preexisting admissions,
same-idempotency equivocation, attempt/child theft after PREPARED, capacity
reservation across a crash, initial pending cleanup, wrong-target scratch,
noncreating reads, concurrent exact calls,
direct-admission racing, self-deadlock timeout, forged/stale/forked witnesses,
late mutation of an earlier scanned record, symlink/FIFO/torn state, and both
order-store and admission-store capacity boundaries. The broader enrollment,
admission, and composition regression passed 132 tests plus 101 subtests.

## What this does not authorize

The receipt closes only
`DURABLE_CROSS_LEDGER_PROSPECTIVE_ORDER_RECEIPT`. It does not attest runtime
tools, execute a renderer, recheck an active fence, seal a child generation, or
publish `CURRENT`. Runtime, fence, execution, and publication flags remain
false. Do not use the receipt as a render-start token, success outcome, or
publication capability.
