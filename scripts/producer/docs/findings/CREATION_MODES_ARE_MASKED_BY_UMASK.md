# Creation modes are masked by umask

## What failed

The cache owner receipt was created with `os.open(..., 0o600)` and immediately
written, but the first version did not inspect it afterward. With a restrictive
`umask(0o777)`, the first call created a mode-000 receipt and reported success.
The next call correctly rejected the same file, making cold success
non-reproducible.

## The deeper rule

The mode passed to file or directory creation is only a requested upper bound;
the process umask removes bits. Durable authority code must set the final mode
explicitly on the newly opened descriptor, verify type/link/owner/mode, flush,
then read back the canonical bytes. Newly created private directories need the
same explicit correction before use. Existing paths should never be silently
repaired because that can adopt someone else's state.

## When not to use this pattern

Ordinary disposable scratch files can inherit a conservative umask. Explicit
mode correction and readback are required when the file controls identity,
idempotency, cache reuse, approval, recovery, or publication.
