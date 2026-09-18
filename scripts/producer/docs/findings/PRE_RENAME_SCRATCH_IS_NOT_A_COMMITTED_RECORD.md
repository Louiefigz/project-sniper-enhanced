# Pre-rename scratch is not a committed record

## Finding

Failing forever when any `.pending-*` directory exists is fail-closed but not
crash-recoverable. A normal process crash or `ENOSPC` before the final directory
rename left scratch that poisoned every later record scan across the entire
authority.

For both cross-ledger intents and V3 admissions, the directory rename is the
only record commit point. Before that rename returns, no compliant caller has
received an admission and no later order transition may run. A subsequent
writer holding the same outer-to-inner locks can therefore abandon the safe
subset and reconstruct it.

## Safe cleanup contract

Cleanup is a write transaction, not a reader side effect. It requires a live,
PID-bound registered lock witness and operates through pinned directory file
descriptors. It verifies:

- canonical `.pending-{64hex-record}-{32hex-nonce}` naming;
- no pending/final coexistence and no duplicate pending target;
- owned mode-0700 directories and owned single-link mode-0600 regular files;
- exact bounded closure and maximum byte sizes;
- any complete canonical document maps back to the embedded target record;
- a V3 artifact subtree is only the admitted bounded relative path, with the
  leaf no larger than the admitted artifact size.

Unknown nodes, wrong-target valid documents, symlinks, FIFOs, devices,
oversized files, deep extra paths, or concurrent set changes remain untouched
and fail closed. Receipt scratch is different: `.receipt.pending` is an exact
post-admission transition and is recovered by validating and completing its
rename, never discarded.

## Evidence and limits

Tests crash both writers immediately before the directory rename, prove a
write retry recovers, prove a read does not clean, and prove wrong-target and
nonregular scratch remain. This is process-crash recovery at an atomic rename
boundary. It is not a hardware power-loss guarantee, permission to clean while
a legacy writer may still be live, or a substitute for disk preallocation.
