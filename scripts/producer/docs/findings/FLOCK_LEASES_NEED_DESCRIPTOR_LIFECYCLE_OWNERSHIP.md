# Flock leases need descriptor-lifecycle ownership

## What failed

A correct `flock()` call and an inode check were not enough to make the
publisher mutex safe. The first design retained one private guard descriptor
and exposed a duplicate as the live witness. If the guard number was closed
and reused for a fresh open of the same inode, teardown preserved the public
duplicate but closed the replacement guard. The duplicate—and therefore its
flock—remained live. On Darwin, a fresh `LOCK_EX | LOCK_NB` probe then stayed
blocked after the context had failed.

Forking exposed a second lifecycle bug. A fork child inherits every duplicate
of the same open file description. Rejecting the inherited witness by PID
prevents API use, but it does not close the inherited descriptors. If the
owner dies while that child remains alive, the child can retain the flock
indefinitely.

## The correction

Each lock acquisition now has three descriptor roles:

1. validation guards retained by the live-witness registry;
2. borrowed public descriptors used by already-held APIs; and
3. closure-private cleanup anchors that are never stored in the live-witness
   registry or returned to the caller. Their numbers appear only in the
   process-local at-fork close set.

Teardown compares public descriptors and guards to the private anchors. A
completed close/reuse attack on either exposed role therefore cannot make the
context lose its exact unlock-and-close capability. One singleton at-fork
registry tracks all live lock descriptors. Its child callback raw-closes a
deduplicated snapshot without calling `LOCK_UN`; explicit unlock in the child
would release the parent's shared open-description lock. An owner-PID check
also prevents an inherited generator's later `finally` block from closing a
child descriptor that reused the same number.

Lock context managers must not broadly catch filesystem exceptions around
their `yield`. An `OSError` raised by caller work is caller evidence, not an
acquisition failure. Acquisition normalization now ends before the body, so
the exact exception object survives teardown.

## The remaining boundary

POSIX has no portable atomic operation that means "close descriptor N only if
it is still this open file description." The flag-challenge check can detect a
replacement that completed before validation, but a hostile thread in the
same process can still close and reuse N between the final check and
`close(N)`. Raw witness descriptors are therefore borrowed capabilities:
caller code must not close, `dup2`, change flags on, or concurrently sabotage
them. Use this design for cooperative code isolated inside the headless
controller process. Do not claim it protects against arbitrary code execution
or adversarial threads in that same process; use process isolation for that
threat model.

## Empirical evidence

The focused regression covers exact body-exception preservation during normal
and reused-public-FD teardown, unhashable forged tokens, hostile path,
descriptor, identity, PID, and lease fields, malformed generated lease and
context tokens, same-inode validation-guard reuse, owner crash with a live fork
child, and child-side descriptor-number reuse before an inherited context
unwinds. The nine adversarial cases pass on Darwin, and the preexisting active
fence lease/under-lock suite remains green.
