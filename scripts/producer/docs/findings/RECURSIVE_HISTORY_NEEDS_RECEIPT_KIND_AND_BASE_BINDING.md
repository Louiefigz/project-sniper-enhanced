# Recursive History Needs Receipt Kind and Base Binding

## Finding

A commit's `expectedParent` proves which immutable generation bytes the child names.
It does not prove that the child's rendered artifact was assembled from that parent.

For a mixed history, every selected edge needs three independent checks:

1. The child commit and receipt name the exact parent reference.
2. The child names the correct parent authority kind and receipt bytes.
3. The immutable base card and the assembly's base observations equal the parent.

The distinction matters at genesis. Genesis R1 has an
`initialization-origin-receipt-v1`, not an assembly receipt. The first child must
use the V2 tagged parent authority:

```json
{
  "kind": "genesis-origin",
  "artifactClass": "initialization-origin-receipt-v1",
  "receipt": {"path": "...", "sha256": "...", "sizeBytes": 123}
}
```

Frozen R0 only has `parentAssemblyReceiptSha256`. It can remain readable after an
assembly parent, but it must not reinterpret a genesis-origin digest as an assembly
receipt. That would restore the alias the versioned bridge was designed to remove.

## What the implementation proved

The disk campaign used a four-node selected chain:

```text
quality-pass V2 -> frozen R0 -> quality-pass V2 -> genesis R1
```

All 3 edges were checked recursively. The resolver rejected a receipt-kind/digest
mismatch, a publication-sequence gap, a cycle declaration, a wrong genesis tail,
a class relabel, and stale committed bytes. An unselected fork remained outside
the proof and did not become a false global-uniqueness claim.

The returned report contains generation and digest summaries, not filesystem paths
or open stores. Runtime, execution, and publication remain false, and the execution
guard always rejects even if a caller forges those booleans.

An adversarial follow-up also closed two reader-boundary problems. A `str`
subclass with hostile equality could make a noncanonical `a/../a` root compare
equal to `realpath(a/../a)`; root opening now requires an exact `str` before the
canonical-path comparison. Historical closure checks now reuse bounded
`scandir()` enumeration, so an attacker-controlled directory cannot force a
full in-memory list of unexpected entries. The expanded focused reader set
passed 68 tests and 47 subtests.

## Concurrency boundary

This result is a path-free historical observation, not a live lease on generation
bytes. The shared publication flock prevents a cooperating publisher from moving
`CURRENT` during the walk. It cannot make a same-UID process that ignores the lock
or retains a writable file descriptor unable to mutate an already checked inode.
The future trusted sealer must create fresh final inodes after writer-capable
descendants are reaped, and any execution consumer must re-resolve under its own
active fence. The report therefore keeps final-fence, runtime, execution, and
publication authority false.

## When not to use this proof

Do not use selected-history authentication as:

- proof that no other fork exists in `generations/`;
- runtime or executable attestation;
- evidence that media quality was remeasured;
- authority to begin a render or publish `CURRENT`;
- a replacement for the final fenced `CURRENT` recheck.
- a capability that keeps observed generation bytes immutable after return.

It closes recursive lineage and genesis-origin continuity only.
