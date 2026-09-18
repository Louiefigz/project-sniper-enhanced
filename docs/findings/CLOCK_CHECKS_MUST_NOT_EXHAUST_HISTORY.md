# A deadline check must not exhaust its own scheduling history

## Observed problem

On September 8, 2026, the actual Project Sniper code inventory required
**2,415 guard calls** for **1,150 implementation files**. With an inert guard,
the read-only inventory took **241.596 ms** (0.40 seconds shell wall time).
No footage, decoder, renderer, or network service participated.

The existing `guardGenerationAttempt().remainingMs()` is not a cheap clock
read. It calls `observe()`, then `retainGenerationClockObservation()`. That
function scans the retained history, validates every old JSON record and writes
a new content-addressed file for each distinct execution/timestamp pair.

The history has a **512-file limit**. A separate real-file test in a new,
explicit temporary directory attempted 513 increasing millisecond timestamps:

- 512 observations were accepted.
- Observation 513 failed with `Generation clock history capacity exhausted;
  no automatic reset`.
- The attempt took **17,017.250 ms**, or **17.29 seconds shell wall time**.
- The test used an inert ownership callback and no source/native work.
- Its exact temporary directory was removed afterward.

Those results are diagnostic evidence, not a finished-video benchmark.

## Why the intuitive composition fails

The inventory correctly checks its original deadline between filesystem reads.
The generation wrapper correctly persists scheduling high-water observations.
But directly composing those functions makes a read-only safety check consume
thousands of durable event slots. Each new check also rereads all previous
records, giving quadratic work in the number of distinct timestamps.

The new all-source staging path must not be activated with this composition
unchanged. Even a small output can fail before any video processing begins.

## What must be preserved in a repair

A fix must retain the same original request and attempt deadlines, check every
relevant operation, and reject backwards time across attempts. Expired/failed
attempt observations must not become fresh allowances. Existing immutable
history must remain readable and must not be silently deleted or re-sealed.

Do not solve this by increasing the limit alone, skipping guards, restarting
the clock, ignoring malformed records, or treating unknown cleanup as a retry.
Those approaches either retain the scaling problem or change safety semantics.

A bounded per-execution high-water record is now implemented as an additive
schema2 format. The key distinction is scheduling state versus audit events: a
monotone high-water mark need not create a new permanent event file for every
millisecond-level check. Actual phase timings and failures still belong in
their own durable execution records.

## Verification required before claiming the repair

1. More than 512 increasing checks must complete within the same execution
   without renewing any allowance.
2. Fresh attempts must reject timestamps below every retained legacy or new
   high-water mark, including after failure or expiry.
3. Corruption, aliases, lease loss and concurrent record changes must fail
   closed; a stale writer must not overwrite a newer timestamp.
4. Existing records must remain byte-identical and old consumer behavior must
   be explicitly versioned, not inferred from matching field names.
5. Repeat the same inventory and timestamp diagnostics with real local files,
   then measure actual request-to-master timing separately.

## Implemented repair and measured limits

New checkpoints update one UUID-named scheduling watermark per execution.
Every check rereads and validates the mixed legacy/new history under the
original caller lease. Existing schema1 content-addressed records are retained
byte-for-byte. Publication uses one file fsync and a parent-directory fsync;
postpublication failure retains the advanced timestamp rather than restoring
older time. This is lease-serialized publication, not a lock-free guarantee
against arbitrary writers ignoring that lease.

An initial wrapper called the original remaining-time method again after
persistence. Review reproduced an unretained second wall-clock observation:
the durable mark could remain at00:00 while a failed deadline check sampled
00:11, allowing a later00:10 attempt to recover time. That version is superseded.

Both real clock owners now share a finite synchronous checkpoint: sample the
original wall and monotonic clocks once, persist that exact wall observation,
then sample only the original monotonic clock to charge persistence cost. The
charged elapsed value is carried forward as a floor. A wall jump not sampled
during IO is not claimed observed. Clock callback replacement is rejected.
Review also reproduced rollback during a failing persistence callback; actual
monotonic rollback is now sticky-invalid for subsequent observations, while
preserving the original failure. No clock or allowance is restarted.

The latest independently reviewed67-case clock selection passed in36.61s wall.
Its2,415-check real-file case completed in28,243.843ms and retained one execution
watermark. This is still about28s of metadata overhead, not a cheap clock read
or an established speedup over earlier runs. The main repair eliminates
per-check capacity exhaustion and history growth.

A separate actual1,150-file inventory used a real project lease and real clock:
2,415 inventory guards,7,251 budget lease callbacks, one watermark,34,739.265ms
inventory time and35.06s complete command wall time. Original600,000ms allowance
ended with565,212ms remaining. This diagnostic used the superseded second-read
wrapper, so it is not a full composition test of the final checkpoint fix.
Its lease used the existing sandbox PID-only fallback, not boot/start identity.
Artifacts remain in `/private/tmp/sniper-real-inventory-clock-20260908.MSd3T8`.

The512 TOTAL-entry limit remains: a saturated legacy folder is still fenced,
not silently migrated or cleared. The active goal remains unfinished, and no
two-hour video target is established here.
