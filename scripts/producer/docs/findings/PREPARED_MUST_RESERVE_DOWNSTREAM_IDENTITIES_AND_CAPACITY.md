# PREPARED must reserve downstream identities and capacity

## Finding

A durable PREPARED marker is not a reservation if it names only the storage
key. The V3 admission ledger has three uniqueness constraints:

```text
idempotencyKey
attemptId
intendedChildGenerationId
```

The first cross-ledger implementation stored only `idempotencyKey`. A request A
could flush PREPARED, crash, and then lose its `attemptId` to direct request B
with a different idempotency key. A's retry found a valid-looking intent but
could never create its admission. The same counterexample worked for the child
generation ID.

Capacity has the same problem. Preflighting one free slot before PREPARED is
not enough: after a crash, unrelated writers can fill the store before the
reserved request returns.

## Safe rule

Every admission writer now takes the shared outer lock and treats PREPARED
records as claims over all three identities and over one logical V3 slot. The
ordered path holds the inner V3 lock continuously across:

1. abandoned pre-rename cleanup;
2. one stable full-set scan;
3. exact/conflict/capacity preflight;
4. PREPARED persistence;
5. admission persistence or exact replay.

For capacity `N`, the claimed set is:

```text
retained V3 idempotency keys UNION unmaterialized PREPARED keys
```

A new unrelated admission requires fewer than `N` claims. The exact request
owning a PREPARED key may materialize that key without increasing the claim
count. A deterministic conflict found before PREPARED is tombstoned; a full
store fails before creating an intent.

The regression campaign proves that a one-slot store cannot be consumed by B
after A crashes at PREPARED, while A can still recover into that reserved slot.
It also proves direct and ordered attempt/child theft are rejected.

## When not to use this pattern

This is logical record capacity, not disk reservation. It does not guarantee
space for file bytes, receipt append, cancellation, terminal state, or
publication. `ENOSPC` still requires a preallocated resource budget and a
separate recovery policy. It also assumes rollout has quiesced legacy writers
that do not participate in the outer-to-inner lock order.
