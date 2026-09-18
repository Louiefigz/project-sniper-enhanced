# Replay authority is a retained-set invariant

## What failed

The first V3 admission store validated every retained record independently, then
looked up the submitted idempotency key and returned an exact replay. That order
missed corruption between otherwise valid records.

Two canonical records could have different idempotency keys and filenames while
sharing the same attempt ID or intended child generation ID. Replaying either
record still returned `replay_arbitrated = true` because the duplicate check ran
only when admitting a new key.

The adversarial reproduction created each record through a clean authority store,
copied both valid record directories into one store, and replayed the original.
Both duplicate-attempt and duplicate-child cases were accepted before the fix.

## Correct validation order

Replay must validate the complete retained denominator before any early return:

```text
lock authority root
  -> validate authority identity
  -> close the store directory
  -> reparse and bind every retained record
  -> prove global attempt and child uniqueness
  -> resolve exact replay or admit a new record
```

The same principle applies to authority initialization. V2 and V3 cannot use
different outer locks to mint `authority.json`; a shared, never-unlinked authority
lock now serializes first binding, and the post-write identity must equal the
requested built-in string exactly. A missing authority record may not be recreated
over orphaned admission state.

Artifact paths are also rejected before the first store mutation unless they are
strict NFC UTF-8, control-free, at most 32 components, at most 255 UTF-8 bytes per
component, and at most 4096 UTF-8 bytes overall. This prevents a valid JSON request
with an unrepresentable path from leaving a permanent pending-record poison.

## Result

The focused store campaign passed 20 tests and 13 subtests. A wider headless
authority campaign passed 199 tests and 241 subtests. It includes forked-process
duplicate-attempt and cross-protocol initialization races, hostile string equality,
unsafe lock inode, orphan-state, Unicode, exact replay, and torn-record attacks.

These checks do not authorize rendering. Unit enrollment, cross-protocol attempt
arbitration after an authority already exists, runtime execution, child sealing,
and publication fencing remain separate unresolved authorities.

## When not to use this result

Do not treat a valid individual admission as proof that its store is coherent.
Do not reuse V3's attempt IDs in a legacy registry merely because both stores have
the same authority ID. Do not turn the returned diagnostic dataclass or any forged
boolean field into an execution capability; the execution guard remains closed.
