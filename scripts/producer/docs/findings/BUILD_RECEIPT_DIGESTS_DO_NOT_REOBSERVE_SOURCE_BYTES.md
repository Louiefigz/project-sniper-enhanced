# Build receipt digests do not reobserve source bytes

A build receipt can prove that a declared digest was computed consistently from
its embedded manifest. It cannot prove that the manifest's source hashes came
from the source bytes that were built.

The retained render receipt has enough structure to recompute its build digest:

```json
{
  "schemaVersion": 1,
  "buildDigest": "<sha256(canonical manifest)>",
  "manifest": {
    "implementation": [
      {"path": "...", "sha256": "...", "sizeBytes": 123}
    ],
    "tools": []
  }
}
```

The semantic parser now requires the exact 60-file implementation path order,
the four exact tool roles, lexical role-distinct paths, and the frozen V1 build
policy. It rejects duplicate keys, path substitutions, reordering, and a stale
`buildDigest`. However, changing one declared source hash and then recomputing
`buildDigest` is still internally valid. The missing source bytes make that
self-consistent claim impossible to disprove from the receipt alone.

The V1 path catalog, policy literal, and digest domain must live with the V1
parser. Importing the active writer's private source list or digest function
would make yesterday's valid receipt change meaning when tomorrow's release
adds a file or advances its policy. A compatibility test now requires the live
writer and frozen V1 contract to match; changing the writer requires a new
versioned receipt contract instead of silently rewriting V1 history.

The parser also performs lexical absolute-path checks only. Calling
`realpath()` while parsing would make historical meaning depend on today's
symlink topology. Filesystem identity belongs in a separate live reobserver;
because V1 does not retain the source/tool bytes or historical inode facts,
that reobserver remains an explicit blocker rather than a parser side effect.

Writer/parser parity is part of the contract. The live writer now rejects
empty implementation/tool files and aliased tool paths or digests before it
can emit a V1-shaped manifest. Without that check, the writer could create a
receipt that the historical V1 parser correctly refuses.

The compositor now has the corresponding frozen V1 contract. Its canonical
receipt contains the exact six ordered source rows used by the historical
compositor digest. The live producer captures those rows through a pinned,
no-follow source root, checks them twice against its import-time snapshot, and
emits newline-terminated canonical JSON. The historical parser independently
freezes the path catalog, policy, digest domain, and legacy basename-plus-hash
algorithm. This closes the former opaque-receipt gap; it does not turn that
six-file declared set into a claim about every transitive Python dependency.

A separate callback-lifetime reobserver now tests the bytes that neither
receipt can prove by itself:

- it reopens all 66 declared compositor/render source rows before and after the
  callback;
- it compares SHA-256, size, and endpoint inode metadata while holding the
  release-root descriptor;
- it opens all four declared render tool roles without following symlinks and
  holds those executable and directory descriptors across the callback;
- it rehashes the held tool inodes before and after the callback;
- it rejects hardlinks, unsafe write modes, source/tool replacement, and
  self-consistent false source hashes; and
- it emits only counts and closed-set digests, so the build-closure report does
  not leak the source root or tool paths.

This is still an endpoint observation, not execution attestation. The callback
does not receive the held executable descriptors, source leaf descriptors are
not held for the entire callback, dynamic libraries are not closed, and no
process is proved to have executed the observed bytes. The report therefore
keeps runtime verification, execution, and publication false and its guard
always rejects authorization.

The separate `graphic-render-receipt-v1` is now parsed and cross-bound to the
approved plan, admission request and manifest, source-seal bytes, render key,
media reference, build, image, and proof-tool identities. This removes the
graphic semantic blocker, but it still does not reopen the retained source tar
or media bytes and therefore does not attest execution.

Do not treat the new static receipts or endpoint reobserver as a trusted worker
launch. The next authority step needs an admitted execution wrapper that uses
the pinned identities, records the actual process/runtime closure, and binds
its graphic and final-media receipts. Until then, a successful observation is
useful drift detection and nothing more.
