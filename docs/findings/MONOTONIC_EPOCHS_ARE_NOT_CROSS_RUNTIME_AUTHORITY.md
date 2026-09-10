# Share a deadline budget, not an assumed cross-runtime clock origin

## Observed failure

The first bounded durable V8 presenter-input test failed before generating any
media. A Node `process.hrtime`-derived absolute expiry was passed to a Python
generator that compared it against `time.monotonic()`. The Python gate rejected
the expiry as invalid. Being on the same host did not make the two timestamp
origins interchangeable in this execution environment.

The failed test took109.9ms inside the test callback and0.91s for the complete
command. Its one owned Python process group was observed absent; it exited
without a forced stop. No successful readiness, saved-input, media or timing
qualification was produced by this attempt.

Retained log:
`/private/tmp/sniper-v8-presenter-durable-input-20260907-first.log`

Retained failed workspace:
`/private/var/folders/3m/8rxbwgds5z7c3r72ccfqb9280000gn/T/sniper-v8-presenter-durable-8x61fy`

## Correction

Keep the original parent deadline authoritative. Immediately before launching
the child, derive only a decreasing duration:

```text
child allowance = min(stage ceiling, current original parent remainder)
child local expiry = child monotonic now + handed allowance
```

The owned parent independently re-reads its original remainder at the actual
spawn, caps the child group timeout, and checks that deadline after observing
group settlement. The child's later local origin must never grant work beyond
the parent's original expiry. An expired original parent cannot be rescued by
an earlier positive handoff value.

The TEST-only generator handoff was changed to this duration contract with a
20-second ceiling. Ten TypeScript pure/inert-process tests and two Python
tests passed after the correction; the media scenario was still skipped at
that checkpoint. This is a fixed test transport, not evidence that the whole
video editor meets its target. The failed attempt must remain in the ledger.

The separately launched corrected attempt subsequently passed:13.973432s work,
13.975099s Node subtest,14.60s command wall. All15owned process groups were
independently confirmed absent. It exercised actual generated source bytes,
cut preview and durable14-document routing, but admission decoder facts,
writer/critic/gate decisions and human cut acceptance were explicit TEST stubs.
It did not render a presenter or produce an approved opening/body.

## Report the actual timing scope

The300-second test work clock begins in its callback, before fixture and media
setup. Node module loading/test-runner startup precede that callback and are
included only in the complete command's wall time. Do not call the callback
clock a process-start-inclusive budget.

Some legacy media leaves inherit the actual owned Python process group and
rely on the parent's60-second/current-remainder backstop. That is an effective
elapsed-work bound, not proof that each leaf's requested timeout was itself
set to60seconds. Children that detach into new sessions require separate owned
cleanup; a wrapper timeout does not magically cover them.

## When not to use this shortcut

Do not pass a relative allowance to an independently scheduled worker and
then abandon parent enforcement. Queue delays, startup delays and retries can
renew work accidentally. A durable distributed job needs an authenticated
original deadline, explicit clock/rollback semantics, and accountable cleanup.
Nor should this finding be generalized into a claim that all Node/Python
monotonic clocks always differ: this attempt established that assuming their
origins matched here was unsafe.
