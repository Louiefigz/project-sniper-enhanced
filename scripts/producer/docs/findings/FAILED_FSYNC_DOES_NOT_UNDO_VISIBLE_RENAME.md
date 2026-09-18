# A failed fsync does not undo a visible rename

## Finding

A durability syscall may report failure after the preceding write, rename, or
append is already visible. Treating that failure as proof that nothing was
committed creates a dangerous replay gap: a retry can observe exact final
bytes, skip every durability barrier, and return success for state that was
never re-flushed.

The counterexample is small:

1. Write and flush a pending record.
2. Rename it to the final deterministic name.
3. Make the parent-directory `fsync` report an error.
4. Retry the exact request.

The final path exists on the retry, but its visibility does not prove that the
rename survived a crash. Exact replay therefore has work to do.

## Recovery rule

Before an exact replay can succeed, the writer now:

- opens the expected final file or record tree through pinned directory file
  descriptors;
- verifies that held and named directory/file identities still match;
- re-flushes the exact retained files and directories from leaves to parents;
- reparses or rehashes the bytes after that barrier; and
- returns only if the second observation still matches the request exactly.

The descriptor pins must remain live through any final named reload. Closing
the flushed inode and then reopening the path leaves a same-byte substitution
gap: the replacement may parse correctly without being the inode that crossed
the durability barrier. Operation, enrollment, and cross-ledger replay now
compare the named reload while the flushed file/record/store descriptors remain
open and return the parsed pinned observation.

This applies to operation admissions, unit enrollments, cross-ledger order
records, graphic receipt sets, and the standalone active-fence projection. A
pathname equality check is insufficient because another inode can contain the
same bytes.

## Partial scratch is a different case

Recovery may reconstruct a pending file only when its expected content is
fully deterministic and the retained bytes are a bounded strict prefix of
those expected bytes. It must retain the pending status and re-flush it; it
must not infer that admission occurred or promote the record on its own.

Complete conflicting bytes, non-prefix corruption, oversized data, unknown
closure, symlinks, FIFOs, hard links, unsafe modes, and inode replacement all
remain preserved and fail closed.

## Performance lesson

Durability recovery should be scoped to records that can affect the current
decision. The cross-ledger writer still performs stable read-only scans for
global uniqueness and pending discovery, but it re-flushes only records that
collide on the current idempotency key, attempt ID, or intended child ID. This
removes an avoidable up-to-50,000-record `fsync` tax without weakening the
set-level conflict checks.

## Evidence and limits

Failure-injection tests cover visible rename/frame state after reported sync
failure, exact replay, strict-prefix pending reconstruction, unsafe residue,
and same-byte named-inode replacement. The combined ordered-admission suite
passes 161 tests plus 104 parameterized subtests; the focused cross-ledger
suite passes 51 tests plus 17 subtests.

These are local filesystem and process-crash proofs. They are not a hardware
power-loss campaign, a guarantee about every network filesystem, disk-capacity
reservation, publication authority, or permission to trust arbitrary damaged
scratch.
