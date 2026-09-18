# Graphic receipts must bind the admission payload graph

A canonical render receipt can be perfectly well-formed while every important
digest in it is only a caller claim. Syntax validation is necessary, but the
receipt becomes useful only when each identity is recomputed from retained
controller-owned bytes.

For the qualified R0 graphic path, the binding is a graph:

```text
approved plan row -> exact render-overlays request bytes
request bytes -> requestDocumentDigest in admission manifest
render-build receipt bytes -> render-build.json manifest row
source-seal bytes -> source-seal.json manifest row
source snapshot -> render-input.tar row and renderInputKey
admission manifest bytes -> admissionArtifactDigest in graphic receipt
```

The render key is independently reconstructed rather than copied:

```python
material = snapshot_sha256.encode("ascii") + b"\0" + build_digest.encode("ascii")
key = sha256(b"sniper-overlay-key-v2\0" + material).hexdigest()
```

This caught two late edge cases. First, an admission manifest could name a
valid build digest while its `render-build.json` row described unrelated
bytes. Second, the source seal and receipt could agree on a snapshot while the
`render-input.tar` row named another digest. Both were self-consistent at the
receipt layer and wrong at the payload-closure layer.

The focused implementation suite now passes 30 tests plus 49 adversarial
subtests. The wider receipt/build regression passes 59 tests plus 83 subtests.
Cases include independent request, manifest, source, key, build, tool, image,
media, ordinal, and selection substitutions; malformed rows; hostile equality
objects; and the legacy 40-hex direct-render key.

Binding source-seal bytes is also insufficient if their embedded semantics are
not checked. The binder validates composition hash/path and template contract,
copy/assets/dimensions, snapshot-manifest structure and derived rows, plus media
dimensions and timing. The admitted controller also reopens and hashes the
attempt-cache media through a pinned directory/file path immediately after lane
validation and again after receipt persistence, on replay, and on explicit
load. Mutation at either handoff boundary rejects the result.

## Production integration and replay

The real `AdmittedRenderLane` now feeds the exact receipt writer. Only the outer
MP4 request digest and quality-policy digest enter as controller authority;
ordinal, graphic ID, plan row, admission/build/image/tool identities, render
key, source snapshot, and media facts are derived from retained admission bytes
and the parent-validated lane result. The media destination is the deterministic
generation-relative `graphics/<graphicId>.mov`, never the worker's absolute
cache path.

The controller persists the complete R0 receipt set under the attempt. Its
canonical manifest additionally binds `authorityId` and `attemptId`, preventing
a valid set for one attempt from being copied into another attempt that admitted
the same artifact. R0 currently allows exactly one `graphic-media-v1` and one
`graphic-render-receipt-v1`, so multiple overlays reject before worker launch;
supporting more requires a versioned generation profile.

Persistence writes receipt files and the set manifest into one private pending
directory, flushes them, renames the directory atomically, and flushes the store.
An exact final set replays without a worker. Replay reopens and flushes pinned
manifest/receipt FDs plus the final and store directories before success. A
same-byte filename or final-directory inode replacement still rejects. Stale
pending cleanup accepts only files whose bytes are a prefix of the current
intended document, pins each inode through unlink, and rejects a different set.

The focused controller/store suite passes 20 tests plus 6 adversarial subtests.
It covers pre-rename interruption, post-rename response loss, failed store and
replay `fsync` barriers, malformed/missing/extra/symlink/hardlink bytes,
cross-attempt copying, conflicting pending writers, concurrent exact replay,
same-byte inode replacement, and media mutation both before persistence and
before handoff.

Do not use these receipts as execution or publication authority. Individual
receipt and set claims remain false even when the live controller outcome says
that media bytes were reobserved. The controller does not append a verified
terminal event, seal a generation, publish `CURRENT`, or authorize Palmier.
A crash before final receipt-set publication leaves a `RUNNING` attempt plus
pending evidence that requires reconciliation and is never rerendered blindly.
