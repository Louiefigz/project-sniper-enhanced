# A clock observation guard must not advance the same clock

## Real failure

The2026-09-07 `sniper-body-live-5ZURW5` TEST run rendered a complete five-minute
video and passed all blocking Audit B checks. The separate post-worker media
readback completed in126.506s. Final candidate selection still failed with
`wall clock moved backwards across attempts` after21m2.896s overall.

This was not evidence of an OS clock adjustment. The caller captured its
observation time before running an ownership/budget guard. That guard checked
the budget by appending a newer observation to the same durable clock. The
outer observation then compared its older time against the newly advanced
high-water mark and correctly rejected that ordering.

An independent21.032ms metadata-only reproduction used strictly increasing
time: outer captured `.000`; its nested budget guard wrote `.001`; outer
attempted `.000` and failed. The application created its own apparent rollback.

## Keep two responsibilities separate

`guided-body-readback.ts` now uses an ownership-only guard when persisting an
explicit clock observation. Combined budget/ownership checks still surround
the expensive reads and candidate transaction. The clock's rollback rule,
original origin,55-minute work limit and request deadline are unchanged.

The regression uses actual durable clock files and controlled increasing time,
not a no-op budget mock. It also tests a genuine1ms rollback, expiry after an
expensive read, and lost ownership. The old wiring failed three tests; the
corrected wiring passes all four. Adjacent clock/body regressions37/37 pass.

## What not to do

Do not clamp an older timestamp to the high-water mark, reset the origin, add
tolerance to hide the bug, disable deadline checks, or retry a failure with a
new UUID. Those changes could conceal genuine rollback or renew work credit.
Do not promote this failed run merely because its media/readback succeeded:
its candidate transaction never committed, and its failure markers remain.

The general lesson applies beyond clocks: a validation callback that mutates
the state being validated is not a pure guard. Make that side effect explicit
and test the actual ordering around slow reads and durable writes.
