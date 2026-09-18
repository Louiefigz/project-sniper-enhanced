# A thread signal mask does not defer Python cancellation

The September 10, 2026 regression run exposed an interruption during mandatory
grade-container cleanup. Blocking `SIGUSR1` in the main thread looked sufficient
in isolated tests, but failed after the larger suite had started background
threads.

POSIX signal masks belong to individual threads. An unblocked background thread
can receive the signal, after which Python schedules its handler on the main
thread. That handler can interrupt cleanup even while the main thread's POSIX
mask blocks `SIGUSR1`.

## Reproduction and repair

A diagnostic started one owned thread, explicitly unblocked `SIGUSR1` there,
and targeted that thread with `signal.pthread_kill`. The original implementation
recorded only `cancelled`; it never reached `exact absence observed`, and
`cleanupVerified` remained false. No user application or real container was
signaled or removed by the diagnostic.

`color.deadline.defer_owner_cancellation` temporarily records cancellation in a
Python handler as well as blocking delivery in the main thread. It restores the
original mask and handler, then requeues the deferred signal specifically to the
main thread. The original caller still receives cancellation. A preexisting
blocked signal remains pending until that caller unblocks it.

Single-container grade cleanup completes its removal evidence and elapsed-time
bookkeeping inside this scope. Batch cleanup finishes its exact-name
reconciliation inside it. The separate `SIGALRM` timer remains active: this
does not extend the 90-second single-container cleanup allowance or the batch
caller's original deadline.

The initial repair had its own exception-safety issue: an alarm between setting
a handler or mask and entering restoration could leave changed process state.
The final implementation snapshots the original mask before mutation and places
all mutations under restoration. Tests inject exceptions after the actual
handler/mask installation and restoration operations.

The focused cleanup, deadline, subprocess, import-boundary and timing run passed
**96 tests in 7.421 seconds**. It covers real thread-directed cancellation,
nested scopes, original blocked/ignored/default dispositions, a raising caller
handler, setup/restoration faults, both grade cleanup entrypoints, and a real
alarm that still interrupts work. It does not qualify a real Docker cleanup or
native video render.

## When not to use this

Use this scope only for mandatory cleanup already owned by the caller. Do not
wrap ordinary editing or rendering work to avoid cancellation. Do not use it
from a background Python thread, replace the caller's work deadline, or treat a
successful removal request as proof that a container is absent. The daemon
absence checks remain necessary.
