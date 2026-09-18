# Pending cleanup must prove commit identity

A deterministic temporary-directory name is not ownership proof. If two seal
requests reuse one `generationId` but carry different commit bytes, both map to
the same pending path:

```text
generations/.seal.<generationId>.pending/
```

Deleting that path merely because its name matches can erase the first
request's crash evidence while processing the second request. A lock prevents
concurrent mutation; it does not prove which prior transaction created durable
residue.

## The safe sequence

The generation sealer now uses this order:

1. Exclusively create an empty pending directory.
2. Write the exact canonical future `commit.json` bytes to
   `.seal-intent.pending` and `fsync` the file.
3. Atomically rename it without replacement to `.seal-intent.json`, then
   `fsync` the pending directory.
4. Copy and verify payload bytes.
5. Promote that exact intent inode to `commit.json` last.
6. Seal the tree and atomically install it without replacement.

Cleanup accepts only three identities:

- an empty directory created before any intent byte;
- a sole `.seal-intent.pending`, which proves payload copying never began;
- an exact `.seal-intent.json` or `commit.json` equal byte-for-byte to the
  caller's commit.

A complete canonical temporary intent is still an identity: if it belongs to a
different commit, cleanup rejects it. Only a malformed prefix from an
interrupted write is safely discardable.

Unknown files, multiple identity files, payload next to a torn temporary
intent, or different commit bytes fail closed and remain available for manual
inspection.

Identity validation and deletion must also use the same held inode. Re-reading
a path to validate it and later unlinking that path leaves a replacement window.
The shared pending-file helper now opens one private descriptor, validates
semantic bytes through that descriptor, rechecks that its metadata still
matches the named entry immediately before unlink, and requires the held inode
to have `st_nlink == 0` afterward. Cross-ledger, enrollment, and admission
regressions inject a replacement at the post-validation check and prove the
replacement survives while cleanup fails closed.

## Counterexample

The regression test crashes after payload copy for commit A, then submits
commit B with the same generation ID and changed media bytes. Commit B must
receive `generation ID collision or equivocation`; commit A's intent and
payload residue must remain untouched. The equivalent test also runs after the
intent has become the final `commit.json` inside a sealed pending tree.

The focused sealer suite currently covers 40 tests plus 25 parameterized cases,
including torn intent writes, exact recovery, equivocation, unknown residue,
nonregular nodes, no-replace installation, and normalized `ENOSPC` failure.

## What this does not prove

This pattern is not publication, execution attestation, or writer liveness.
It does not revoke descriptors held by an unreaped same-UID process, reserve
disk capacity before copying, prove hardware power-loss durability, or authorize
`CURRENT`. Use it only after writer-capable descendants have been reaped and
before a separately fenced publisher revalidates the sealed generation.

Portable POSIX does not offer atomic compare-inode-and-unlink. A malicious
same-UID process can still race after the final pathname check; the post-unlink
link-count proof detects that race only after possible damage. The cleanup
contract therefore depends on the declared private filesystem and cooperating
writers obeying the held kernel lock. It is not a hostile same-user boundary.
