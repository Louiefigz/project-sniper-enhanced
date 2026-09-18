# Producer ingest admission is not all-ingress admission

## The incident (2026-07-29)

Project Sniper already had a strong external-media primitive: a stable
full-byte snapshot followed by a non-root, networkless, read-only,
resource-bounded full decode. It had live evidence for timed media, still
images, SVG, and fonts. But no product ingress called it.

The tempting fix was to say “media admission is wired” after adding one call to
`ingest.py`. That would still be false. Producer has several independent ways
for media to enter execution.

## What is now actually protected

The canonical `/producer/ingest` worker now admits, before any host ffprobe or
transcription:

- every top-level raw source;
- top-level images and no-audio videos later reclassified as b-roll;
- every supported file under the input project’s `broll/`;
- every supported audio file under the input project’s `music/`.

Each file is copied with no-follow inode checks into
`.sniper-external-media/<sha256>.media`, fully decoded by
`headless/external_media_probe.py`, and bound to an exact retained admission
receipt. The generated `asset_manifest.json` points its source, b-roll, and
project-music executable `path` fields at those snapshots—not at the mutable
originals.

The manifest also binds a content-addressed
`.sniper-source-sets/<sha256>.json` by exact file SHA-256 and source-set
digest. A failed re-ingest therefore cannot overwrite the receipt still named
by the last good manifest. Every source-set row binds:

| Field | Meaning |
|---|---|
| `lane` | `source`, `broll`, or `music` ingress |
| `originalPath` | provenance only; never the executable media path |
| `snapshotPath` / `sha256` / `sizeBytes` | exact admitted bytes |
| `mediaKind` | validated decoder classification |
| `admissionReceiptPath` / `admissionReceiptSha256` | exact sandbox evidence |

`verify_source_set_binding` rehashes the source-set document, each admission
receipt, and every snapshot byte. Changing the original after ingest does not
change execution; changing a snapshot makes verification fail. `render.py` and
`assemble.py` invoke that revalidation whenever the manifest carries the new
binding, and the `/producer/ingest` response refuses to publish a new manifest
without a structurally exact binding. Canonical render, assemble, Auto Edit,
Palmier preflight/push, and Palmier checkpoint spawns pass
`--require-source-set-admission`; a missing manifest or stripped binding fails
before media work or MCP access. Direct render, assemble, Palmier push,
checkpoint, draft, and desktop CLIs now enforce the same rule by default.
Legacy operation requires the explicit `--allow-legacy-unadmitted` migration
escape. No production API route passes that escape, and a closed source scan
fails if one starts doing so.

The first execution wire accidentally read every large snapshot four times at
one boundary: the “if present” helper verified the set, its caller verified it
again, and each entry verified once directly plus once through its receipt.
Returning the already-verified entries and making the receipt validation the
single byte pass reduced that boundary from **4 full snapshot hashes to 1**.
Integrity checks on the receipt, source-set digest, and executable manifest
projection remain fail-closed.

Focused proof: `tests/test_ingest_admission.py` covers all three lanes,
non-symlink enforcement, fail-before-source-set publication, original mutation,
snapshot mutation, and manifest paths.

The 2026-07-29 live integration run used one 0.5-second H.264/AAC raw take, one
PNG b-roll image, and one WAV music bed against the approved Docker image. It
completed with one source, one b-roll row, and three admitted source-set entries
at digest
`8c842431f820ca8e62220a93fcca62701bb7a20ca82ecfb77f039e30a86095f1`.
`tests/live_ingest_admission_acceptance.py` retains the reproducible opt-in gate.

## The additional ingress paths

Local and URL reference registration use a separate
`sniper-reference-media-admission-v1` authority over the same networkless
full-decode primitive. URL acquisition forces yt-dlp's native downloader and a
single already-muxed format; neither registration route invokes host ffmpeg or
ffprobe before admission. The reference library rehashes the exact receipt and
snapshot and no longer exposes legacy unadmitted video files. The opt-in live
reference-wrapper test passed a real 0.5-second H.264 full decode. Local and
downloaded VTT sidecars are copied from bounded `O_NOFOLLOW` descriptors and
must retain the same inode, size, mtime, and ctime through EOF. Each copy now
publishes a `sniper-reference-text-admission-v1` receipt binding its exact
path, SHA-256, size, and receipt SHA-256. Reference discovery rehashes both
the VTT and the content-addressed receipt before returning word timing; the
reference-media verifier rejects the whole reference if either changes.

The decode deadline is also receipt authority, not an unrelated wrapper
constant. `max_decode_seconds` is exactly validated in the retained receipt
(1,200 seconds for reference intake), passed into the container, and given
bounded parent-side cleanup slack. The TypeScript worker allows 25 minutes for
snapshot I/O plus decode, so it cannot kill a legal 20-minute sandbox decode at
the old four-minute ceiling.

Managed source placement also now opens each at-most-2-GiB input with
`O_NOFOLLOW`, binds device/inode/size/mtime/ctime, copies from that descriptor,
and rechecks the same identity after EOF. Concurrent source replacement fails
and removes the staging tree.

The late b-roll pool is no longer an exception. All four
`broll/broll_pool.py` commands now require the current
`asset_manifest.json`. Before scan, annotation, manifest projection, or receipt
resolution, `open_pool`:

1. rehashes the source-set receipt, every per-file admission receipt, and every
   admitted snapshot;
2. revalidates the executable manifest projection;
3. retains only source-set rows whose lane is `broll` and whose provenance
   path is inside the exact real, non-symlink pool root; and
4. enumerates the current pool and rejects any media path not present in that
   admitted set.

The scanner passes only each row's immutable `snapshotPath` to host ffprobe and
ffmpeg; `originalPath` is used for provenance, category, and stable identity,
never decoding. Adding a file after ingest therefore fails with an explicit
canonical-reingest requirement. Replacing an already admitted mutable original
does not change the reviewed catalog because the admitted snapshot remains the
executable object. The emitted catalog row carries the exact
`path`/`originalPath`/source hash/admission-receipt projection that
`verify_execution_media_authority` expects downstream. Symlinked pool roots and
duplicate catalog `originalPath` identities fail closed instead of being
resolved or silently collapsed. The pool consumes the verified entry list
returned by execution authority, so it hashes each admitted snapshot **once**,
not once for projection verification and again for pool selection.

Thumbnail publication is a separate write boundary. Cached asset IDs are
restricted to a 96-character filename-safe alphabet; duplicate retained IDs
fail closed. `.frames` must be a real non-symlink directory, each JPEG renders
to a private staged regular file, and rename publishes it atomically. A
poisoned cache therefore cannot use `../` or a symlinked thumbnail directory to
steer ffmpeg output outside the pool.

Focused late-pool authority proof is retained in
`tests/test_broll_pool_admission.py`: **9 tests** cover post-ingest additions,
snapshot tampering before catalog access, unbound catalog substitution,
symlink-root preservation at CLI dispatch, duplicate catalog identity,
snapshot-only probe/extraction arguments, one-pass source verification,
thumbnail-path confinement, and acceptance of emitted rows by downstream
execution authority. The combined b-roll/ingest/execution sweep passed
**32 of 32** tests, including real-ffmpeg frame and insert tests.

## The closed all-ingress registry

The all-ingress claim is now represented by
`external-ingress-registry-v1.json`, not by this prose. Its executable checker
discovers each registered byte-entry token, requires exactly one named owner,
checks every released entry/authority/test path, and verifies cross-boundary
guard tokens. The current retained inventory has:

- **10** ingress families, of which **8** are released;
- **24** discovered entry occurrences and **24** exact owners;
- **5** cross-boundary invariants.

The released families cover canonical project media, the shared sandbox
primitive, reference video, bounded VTT text, governed scene-package assets,
sealed render archives, Palmier delivery of governed derivatives, and trusted
repository build assets. Two explicitly unreleased families keep the boundary
honest: Palmier live-build direct import is disabled, and
`--allow-legacy-unadmitted` exists only as a non-production migration escape.

The interactive Palmier live-build tool list no longer contains
`import_media`. Palmier push, checkpoint, draft, and desktop paths revalidate
the admitted manifest snapshot or a hash-bound Sniper derivative before MCP
access and again at the worklist boundary. Palmier components can no longer be
populated from arbitrary plan paths. An ungoverned `palmierAudioMaster` or
baseline-look LUT is rejected; the released color path remains the governed
Sniper color derivative.

Scene-package/generated assets remain a distinct authority rather than being
silently attributed to canonical ingest. They enter through
`scene_package_assets.py`, where bytes, rights, attribution, and sandbox
admission are bound into the published package.

Finally, current-render candidate staging, storage, verification, activation,
and rollback rehash the exact source-set receipt and every admitted snapshot.
A mutation after initial ingest therefore cannot produce an activatable final,
even if an earlier consumer completed.

The pool still has the same process-level verify-then-use limitation as other
path-based host consumers: source-set verification closes its descriptor before
the later ffprobe/ffmpeg subprocess opens the admitted snapshot path. A
concurrent same-user mutation of the content-addressed store in that interval
can still make that individual downstream subprocess fail or observe different
bytes. Final promotion rehash prevents that result from becoming current, but
descriptor-to-subprocess handoff remains separate hardening. Admission proves
bounded decode; it does not make media intrinsically trusted. Pool thumbnails
still decode admitted bytes with host ffmpeg, so moving that derivative render
into the approved container remains a downstream isolation improvement.

Finally, `broll_catalog.json` remains mutable operator-authored metadata. Its
media projection is checked against admission, but tags and descriptions are
not a content-addressed revision authority. Once a receipt resolves to an
`assetId`, the plan and manifest—not later tag changes—must remain the
load-bearing execution inputs.

No generic multipart/byte-upload route exists under `src/app/api/producer`.
The current “upload” UI supplies an absolute local `inputPath`, and the ingest
route either copies or references it before launching `ingest.py`; that path is
the canonical source lane covered above.

Repo-bundled music and SFX are trusted build inputs, not external ingress. They
still need build/source-closure hashing, but repeatedly treating the repository
itself as an external upload would be the wrong boundary.

## The principle

A sandbox primitive is not a product security property until the actual
ingress calls it, consumes the admitted copy, and binds the receipt into the
authority used downstream. Wiring one convergence point is meaningful progress;
renaming it “all ingress” hides the remaining bypasses.

## When not to use this path

- Do not run sandbox admission on repository-vendored music, SFX, fonts, or
  renderer code; bind those through the build/source closure.
- Do not use `originalPath` after admission. It exists only for provenance and
  operator diagnostics.
- Do not treat a retained receipt as timeless. Rehash the receipt and snapshot
  immediately before a downstream authority promotes output.
- Do not use the prior source-set receipt as proof for media added to the b-roll
  directory later. The pool rejects it until canonical re-ingest creates a new
  source-set authority.
- Do not use canonical ingest as proof for reference transcript sidecars or
  scene-package assets. Reference video/VTT and scene packages have separate
  retained authorities, while canonical direct `music.path` is constrained to
  admitted manifest rows.
- Do not use `--allow-legacy-unadmitted` in a product route. It is an explicit
  unreleased migration boundary and the registry scan must remain at zero
  production occurrences.
