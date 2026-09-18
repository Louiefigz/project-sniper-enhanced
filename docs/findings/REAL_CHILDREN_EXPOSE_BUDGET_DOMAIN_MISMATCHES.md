# Test timeout composition through a real child

## The failure

The September 7 fresh synthetic 300-second, 1080p integration exercised the
production opening CLI, actual sealed rendering, cleanup, selection and a
clearly marked TEST-only approval. It then failed at body admission with
`cut preview requires a bounded POSIX process-group runner`.

The body attempt had a 55-minute allowance. Its readback reused the opening
verifier, whose child process class allows at most 25 minutes and requires
integer milliseconds. Passing the whole body remainder directly violated that
existing contract. Stubbed verifier tests had accepted the value; the actual
runner refused it before spawning the verifier child.

The failed driver took 660,184.9 ms overall; the failing body hold took
2,456.4 ms. Opening engine time was 421,834.8 ms. These are observed synthetic
run timings, not a creator-video SLA, and nested phase times overlap.

## The correction

Capture one verifier subdeadline before authority reads. Its allowance is the
minimum of the original body remainder and the existing opening-verifier cap.
Every subsequent read uses the smaller of the live parent remainder and the
initial allowance minus elapsed monotonic time, rounded down to milliseconds.
Expiry, malformed clocks or clock rollback permanently invalidate that closure.
Recheck after the child and after the final authority reads.

The important regression invokes the actual process runner with a tiny Node
child through the body-hold path. The 32-test deadline/authority/claim cohort
passed independently in 4,265.4 ms, including this real child. This does not
replace the pending fresh end-to-end media run.

## When not to use it

Do not widen the verifier's process limit to match a caller. Do not capture a
fresh allowance for each poll or retry. A local timeout is not a renewed
request clock, and successful cleanup does not erase time already consumed.
Safety cleanup may remain necessary after a deadline, but the overrun must be
reported and cannot qualify a successful candidate.

## Evidence

Retained failed workspace:
`/private/var/folders/3m/8rxbwgds5z7c3r72ccfqb9280000gn/T/sniper-body-live-OJXYq0`.
Its `body-live-evidence/` contains actual CLI logs and failure timing. The
synthetic attestation is not evidence of creator listening or acceptance.
