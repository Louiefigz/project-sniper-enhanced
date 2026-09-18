# Fresh-inode sealing is not publication

## The lesson

Changing a staging file from mode `0600` to `0400` does not make it immutable.
A process that opened the file while it was writable may keep writing through
that descriptor after `chmod`. The reliable boundary is a new inode namespace
that no writer-capable child has ever opened.

The headless generation sealer now performs this narrower transition:

1. Parse an exact canonical V1 commit and reject file/directory prefix
   collisions before writing authority state.
2. Open an owned mode-`0700` staging root by descriptor and require an exact
   manifest tree of mode-`0700` directories and owned, single-link mode-`0600`
   regular files. Preflight node types before opening leaves, so a static FIFO,
   socket, or device is rejected without invoking its open behavior.
3. Copy and hash each declared row into a new mode-`0700` pending directory,
   then reopen and rehash the complete source and destination closures.
4. `fsync` payload bytes and directory entries, create canonical `commit.json`
   last, change files to `0400` and directories to `0500`, and reverify the
   sealed closure.
5. Install with descriptor-relative `renameatx_np(RENAME_EXCL)` on macOS or
   `renameat2(RENAME_NOREPLACE)` on Linux. If neither primitive exists, fail;
   never fall back to replacement-capable `rename`.

The installed directory is deliberately not published. The result contains
only `{generation_id, commit_digest, replayed}`. It does not create or inspect
`CURRENT`, a fence, a publish intent, an execution receipt, or a runtime
attestation.

## Bounds are necessary but not capacity admission

The first implementation rejects commits above 16 MiB, more than 4,096 rows,
paths deeper than 32 components, individual rows above 16 GiB, and declared
payload totals above 64 GiB. Streaming reads stop at the declared size plus one
byte, so a concurrently growing file cannot force an unbounded read.

Those numbers bound parser and copy work; they do **not** reserve disk space.
A valid 64 GiB declaration can still exhaust a volume. Production admission
therefore still needs durable capacity reservation, an `ENOSPC` fault campaign,
and a recovery rule for reservations and partially allocated files. Do not mark
resource admission closed from the numeric caps alone.

## Crash cleanup must identify before deleting

A deterministic pending name makes recovery possible, but it is not deletion
authority by itself. Recovery first preflights the whole reachable pending tree:
every name must be a subset of the requested commit tree, every node must be
owned and on the authority device, files must be single-link regular files, and
modes must be one of the mutable/sealed pairs. Only after that full preflight
does cleanup make sealed parent directories writable and unlink their children.
An unknown entry or symlink blocks recovery and is preserved for inspection.

The focused campaign currently covers one complete 42-row R0 payload across
four sealer test modules: 27 tests plus 18 parameterized subtests. It includes
same-inode mutation,
same-byte inode replacement, symlink/hardlink/FIFO/socket rejection, missing and
undeclared paths, unsafe modes, digest/size abuse, prefix collisions, exact
replay, authority equivocation, thread/process concurrency, crashes before and
after installation, sealed-tree recovery, ambiguous crash residue, missing atomic
no-replace support, and an injected empty-final install race.

## When not to use this primitive

Do not invoke the sealer while a model, renderer, verifier, or descendant may
still hold a staging or pending write descriptor. The final source recheck is a
bounded observation, not a future-write fence; writer process groups must be
reaped and proven dead first.

Do not use it as proof that artifact semantics, execution, media decode, policy,
external CAS retention, parent fencing, or publication succeeded. Those are
separate prerequisites. In particular, a sealed generation is unreachable
production data until a future trusted publisher validates the expected parent
and atomically advances `CURRENT` under its own durable fence.
