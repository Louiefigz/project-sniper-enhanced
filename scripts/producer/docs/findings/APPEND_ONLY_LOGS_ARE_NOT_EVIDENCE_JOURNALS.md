# Append-only logs are not evidence journals

## Finding

Opening a file with append mode prevents one easy overwrite. It does not prove
that concurrent writers formed one history, that a killed write is recoverable,
or that a reboot did not invalidate the clock used by later events.

Project Sniper's first isolated trace proof needed all of these together:

- a never-unlinked `flock` inode and private, no-follow, single-link files;
- canonical bounded frames with sequence, predecessor digest, payload length,
  CRC32, and event digest;
- a locked scan/append cycle followed by `fdatasync` and directory `fsync`;
- recovery of only an incomplete final physical frame, never complete corruption;
- repeated immutable attempt identity and an explicit cross-reboot rule.

The initial 11-test proof survived a child killed after durable admission, a
child killed during a partial append, and 16 simultaneous writers. One hundred
fully synced appends averaged about 20.3 ms each on the test machine.

Adversarial review then found a reboot flaw: `bootId` was part of immutable
attempt identity. That made an unsealed attempt impossible to recover after a
real host reboot. Removing boot identity entirely would have created the
opposite problem because `CLOCK_MONOTONIC` can reset.

The corrected contract keeps attempt identity immutable while recording boot ID
per frame. A boot transition is accepted only on `RECOVERY_RESUMED` or
`TERMINAL_SEALED`; monotonic time must never move backward within one boot.

The next adversarial pass found three more state-machine holes: a prior boot ID
could recur, work could continue after `TERMINAL_SEALED`, and an ordinary stage
event could request torn-tail truncation. The corrected 18-test suite makes
terminal state absorbing, rejects boot bounce, gives recovery/terminal events
closed reason/disposition schemas, and limits torn repair to those events. It
also retains accepted recovery on boot B, rejects ordinary work before recovery,
and rejects same-boot clock rollback.

## Rule

Treat admission, evidence, and completion as a state machine, not text output.
Every clock needs a declared validity domain. Every restart boundary needs a
typed transition that preserves the original sequence and digest chain.

The journal is still not the admission registry. Keep a separately durable
idempotency/denominator record and a terminal manifest so a missing trace cannot
erase an admitted attempt from the measured population.

## When not to use this approach

Do not pay an `fsync` for every debug message. Keep high-volume diagnostics in a
bounded ordinary log and journal only low-volume state transitions and digests.
For a single-process disposable experiment with no crash recovery or cohort
claim, an atomic final receipt may be sufficient. Do not use a JSONL journal as
an authorization boundary against another process running as the same OS user.
