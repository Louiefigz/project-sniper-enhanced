# Historical resolution proves selected ancestry, not global uniqueness

## Finding

`Mp4GenerationV1` stores its parent reference, while `publicationSeq` for the
tip lives in `CURRENT`. There is no append-only publication ledger. A reader can
therefore prove the one ancestry selected by a pinned `CURRENT`, but it cannot
prove that an orphaned directory was never published or that no fork ever used
the same sequence number.

The historical resolver now walks from `CURRENT` to genesis under the publish
flock. Every edge must decrement by exactly one and bind the parent's authority,
generation UUID, commit digest, and approved-plan digest. Every traversed R0
generation is fully hashed, its exact closure and descriptor are checked, and
the requested target is materialized only if its complete `ParentRefV1` occurs
on that selected chain.

The returned status is deliberately
`selected-current-ancestry-only`. A valid orphaned fork does not make selected
resolution fail, but it can never satisfy a historical request through this
API.

## When this is insufficient

Do not use this proof to claim global fork uniqueness, a complete audit of all
past publications, or safe automatic garbage collection. Those claims require
a durable append-only publication ledger (or an equivalent authenticated
history) in addition to immutable generation directories.
