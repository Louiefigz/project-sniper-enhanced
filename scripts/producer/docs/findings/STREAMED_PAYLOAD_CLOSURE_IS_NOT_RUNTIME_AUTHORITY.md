# Streamed Payload Closure Is Not Runtime Authority

## Finding

A generation can contain hundreds of megabytes of media even when its authority
documents are small. Building a `dict[path, bytes]` for every committed artifact
duplicates the whole generation in memory. For genesis R1, the profile permits up
to 2 GiB in aggregate, so an all-bytes structural check can become the dominant
memory cost or fail before rendering begins.

The safer pattern is to keep only bounded semantic documents in memory and stream
the rest:

1. Resolve the selected `CURRENT` generation under the publication lock.
2. Copy the exact sealed manifest closure into a private materialization.
3. Reopen the materialization through directory descriptors with no-follow flags.
4. Require the exact directory-entry set at every level with an early-fail scan;
   never allocate a list from attacker-controlled extra entries.
5. Stream SHA-256 and byte counts for every manifest row.
6. Compare file descriptor, directory entry, inode, owner, mode, link count, size,
   modification time, and change time before and after each stream.
7. After the last stream, recheck every source and materialized row against its
   original snapshot, and rescan nested closure, so an earlier subtree cannot
   change during a later stream.
8. Return only committed relative artifact references and digests. Never return a
   host path, file descriptor, store object, or lease.

In the current R1 fixture this closes all 44 committed rows while retaining only
nine bounded authority/policy JSON documents. The proof size is O(manifest rows),
while payload memory stays O(stream chunk + semantic documents).

## What this catches

- a missing or extra materialized artifact;
- symlink replacement, added hardlinks, unsafe modes, and ownership drift;
- same-size post-copy byte changes;
- same-inode changes during hashing;
- same-inode mutation, inode replacement, or hardlink insertion against a row that
  was already hashed while a later row is still streaming;
- an extra entry added to a nested directory after that directory's first pass but
  before a later directory finishes streaming;
- a hostile `Mapping` subclass that changes semantic document values between
  closure validation and authority binding;
- a forged observation dataclass or an observation borrowed from another commit;
- an oversized semantic document before JSON parsing.

## What it does not prove

Exact bytes are not semantic or runtime authority. A correct media digest does not
prove that the media decodes, that effects are visible, that the named compositor
or FFmpeg executable actually ran, or that the output satisfies quality policy.
The observation is also point-in-time: it does not perform the final `CURRENT` and
operation-fence recheck required immediately before execution or publication.
The final snapshot sweep narrows the intra-pass race window, but is not a durable
seal: a writer acting after the sweep remains the later fence's responsibility.

Accordingly, the streamed result keeps runtime, execution, publication, and final
fence flags false. It may close structural manifest-byte authority, but it must not
be accepted as a render-start capability.

## When not to use this approach

Do not use streaming alone when a consumer must parse or transform the entire
artifact. In that case, give the parser a separate class-specific size limit and a
descriptor-scoped stream. Do not weaken the semantic limit merely because the
generation-level aggregate cap is larger.
