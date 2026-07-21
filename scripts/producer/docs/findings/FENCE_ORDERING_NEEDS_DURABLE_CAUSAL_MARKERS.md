# FENCE ordering needs a durable causal marker

## Finding

A live outer lock can serialize `FENCE` and admission writes, but the lock
disappears on process death. After restart, the files alone must prove that the
exact active fence existed before the cross-ledger order entered `PREPARED`.

Neither of the obvious records proves that:

- `FENCE.activeAttemptId` binds only an attempt UUID. A changed request can
  reuse that UUID after a crash unless an immutable request reservation already
  exists.
- A request reservation binds exact bytes, but it does not prove whether the
  fence preceded `PREPARED`.

The safe sequence therefore needs three distinct durable facts under the same
publisher-to-cross-ledger lock lineage:

```text
exact request reservation
  -> exact active FENCE revision/token
  -> exact fence-order-start intent
  -> cross-ledger PREPARED
  -> V3 admission
  -> COMMITTED receipt
```

The start intent binds the reservation digest, full cross-ledger order identity
digest, fence revision, fence token, active attempt, and authority. It is
non-authorizing evidence; it cannot start a worker or publish a generation.

## Replay rule that matters

Replay may create a missing start intent only while the exact order state is
still `absent`. Once `PREPARED`, `commit-pending`, `committed`, or `rejected`
exists, replay may only reobserve an already durable exact marker. It must not
promote a pending-only marker or create a new one, because that would manufacture
the missing causal edge after the fact.

| Reobserved state | Reservation/FENCE | Marker on disk | Start action |
|---|---|---|---|
| order absent | exact | missing or exact | create or exact replay |
| order non-absent | exact | exact | read-only exact reobservation |
| order non-absent | exact | missing | reject without creating |
| any | missing or changed | any | reject without healing |

An inactive fence plus a preexisting order is also rejected before reserving a
new fence. This prevents a legacy standalone admission from being
retrospectively wrapped in stronger evidence.

## What the tests disproved

The first integrated pass covered crash cuts after reservation, after FENCE,
after start-intent persistence, and after order commit. It also exercised a
changed-child replay, UUID-only public fence reservation, preexisting standalone
order, missing start marker after commit, wrong cross-lock lineage, root swap,
and downstream failure. The focused start/controller run passed 33 tests and 25
subtests on 2026-07-20.

Those tests also establish an important failure policy: do not automatically
cancel or release the active fence when ordered admission fails. The retained
fence is the recovery barrier. Clearing it requires a separate exact terminal
protocol, not generic exception cleanup.

## When not to use this result

Do not treat the composed admission result as:

- a trusted-runtime or resource-capacity proof;
- worker-launch authority;
- the final pre-publication fence recheck;
- permission to seal a generation, advance `CURRENT`, or publish an MP4;
- a terminal `RELEASE` decision.

Those later transitions require their own durable records and recovery rules.
This pattern solves request identity plus FENCE-before-order causality only.
