# Terminal results must be committed before recovery

## The failure

A durable terminal event that records only `FAILED` or `SUCCEEDED` does not bind
the outcome payload. If the process dies after appending that event but before
publishing `terminal-manifest.json`, recovery can attach different result bytes
to the same terminal trace.

The original G1 primitive reproduced this window:

1. append `TERMINAL_SEALED {disposition: FAILED}`;
2. stop before the terminal manifest replace;
3. resume with any JSON result;
4. publish that result beside the old terminal event.

The manifest referenced the terminal trace digest, but the trace digest did not
commit the result. The reference therefore proved ordering, not content.

## The first correction: bind integrity

Canonicalize the result before the terminal append and calculate:

```text
SHA256("sniper-terminal-result-v1\0" || canonicalResultBytes)
```

Persist that `resultDigest` in the terminal trace event and in the manifest.
Replay must revalidate the terminal sequence, trace digest, disposition, result
digest, and immutable attempt identity against the actual trace instead of
trusting the manifest alone.

That stopped substitution but exposed a second failure: after a process death,
the digest proved whether proposed bytes matched but could not reconstruct bytes
that had never been stored. Integrity and availability are different contracts.

## The complete correction: retain exact bytes before the terminal event

The pre-release schemas now use trace-frame version 3, terminal-intent version
3, and terminal-manifest version 4. Completion order is:

1. validate the closed terminal-result union;
2. write and directory-flush exact canonical `terminal-intent.json` bytes;
3. append and sync `TERMINAL_SEALED` with the result digest;
4. derive, replace, and flush `terminal-manifest.json`; and
5. on startup, recover the terminal boundary before ordinary torn-trace
   classification.

That last ordering matters. A retained terminal intent authorizes repair of its
own torn terminal frame; classifying the torn tail first incorrectly strands an
otherwise recoverable result.

The focused suite includes changed-result, changed-trace, lost-result-byte, and
torn-terminal-before-recovery counterexamples. The G1-focused composition-root
suite passes 57 tests, but still does not implement publication authority.

## When this is not enough

This closes one local crash window. It does not prove that the result describes
a valid MP4, that `CURRENT` points to the claimed generation, or that a remote
Palmier mutation completed. Those require byte revalidation, publisher recovery,
and target-specific reconciliation before terminal sealing.
