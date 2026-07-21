# Sealed proofs must not reread live inputs

## What failed

The renderer correctly snapshotted asset A, but the proof builder later resolved
the asset path again. Replacing the live source with asset B between those steps
produced a self-consistent proof for B beside media actually rendered from A.
The media was deterministic; the evidence described the wrong input.

## The correction

While creating the sealed archive, record one canonical binding for every
resolved asset:

```text
{field, selector, archiveRelativePath, sha256OfExactReadBytes}
```

Carry those bindings with the sealed snapshot. The proof builder copies them
from the snapshot object, and the parent requires exact equality among:

- controller-expected asset bindings;
- proof `assetInputs`;
- the sealed snapshot manifest; and
- the retained input archive revalidated beside the media.

The regression snapshots A, mutates the live source to B, and requires the proof
to remain bound to A.

## When live rereads are acceptable

Live rereads are acceptable only for explicitly non-authoritative diagnostics.
They must be labeled as observations and cannot decide cache identity, approval,
publication, recovery, or which bytes the render claims to contain.
