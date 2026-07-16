# Palmier locks must not share semantic queues

## Finding

A mutual-exclusion lock and a work queue are different contracts. Palmier's
`SyncLock` originally used one pending `planHash` slot for every same-project
contender. That is valid for repeated mirror pushes because the active mirror
worker can drain the newest plan hash. It is unsafe for a native edit,
authority readback, or draft creation: a mirror worker cannot interpret a
native request hash as mirror work.

The dangerous sequence was:

1. A mirror push holds the per-project Palmier lock.
2. A native edit calls the same acquisition method.
3. The lock records the native request hash in the mirror pending slot.
4. The mirror worker claims that value and attempts the wrong operation type.

The reverse ordering could also report a mirror push as queued even though a
native holder would release and discard that pending entry.

## Rule

Only operations whose current holder knows how to drain the queued payload may
queue behind that holder. All other Palmier operations acquire with
`queue_if_busy=False` and return a retryable waiting result.

Use both layers:

- the project writer lease serializes Sniper's routes and rejects conflicting
  writes while a detached job owns the project;
- `SyncLock` serializes Palmier itself across processes, including direct CLI
  callers that do not pass through the web app.

## Verification

`test_non_mirror_contender_waits_without_entering_mirror_queue` holds a mirror
lease, attempts a non-queuing native acquisition, and proves the result is
`WAITING/PALMIER_BUSY` with no `.palmier.sync.pending.json` created. The full
offline Palmier suite passes with mirror latest-wins behavior unchanged.

## When not to use this rule

Do not disable queuing for repeated mirror pushes of the same operation type.
Their one-slot latest-wins behavior intentionally collapses redundant updates
and is safe because the active mirror worker understands the pending payload.
