# Adding B-roll must preserve the complete input set

A project may keep a large recording at its original location rather than copying
it into `source/`. It may also classify a top-level photograph as B-roll or retain
music and supporting footage in the original input folder. Rescanning only the
project's `source/` folder can therefore lose valid media even when nothing was
removed. Retaining only the primary recording list fixes one symptom but still
loses old supporting assets.

The additive rescan now starts from the verified previous source-set entries.
Those entries carry original paths and lanes; manifest rows carry stable asset
IDs and verified transcript bindings. The scanner merges newly supplied files,
re-admits the complete input set through the existing sandbox, preserves prior
IDs, and rejects changed or missing originals. The caller publishes the new
manifest only after these checks and exact transcript-byte comparisons succeed.

```python
inventory = RetainedIngest(previous_manifest, verified_source_entries)
current = build_manifest(input_path, manifest_path, True, inventory)
# Verify source identity, exact transcript bytes and the new admission set.
# Then let the existing ingest caller atomically publish the manifest.
```

This mode cannot repair or replace speech. A source edit must go through normal
transcription and downstream invalidation. `--no-transcribe` is also different:
it intentionally creates no transcript bindings; it is not a reuse shortcut.
The additive mode invokes no ASR and never falls back to it on failure.

Five inventory tests and ten transcript-reuse tests cover this behavior alongside
six existing resume and ten format checks: 31 passed. These are structural/local
file checks. Three actual sandbox-admission cases subsequently passed in 11.137s
worker time (58.967s including full owner/cleanup); the
[receipt](../producer/SUPPORTING_MEDIA_AND_GUIDED_BUILD_2026-09-13.md) records the
synthetic fixture scope and exact cleanup. Avoided ASR is
an architectural optimization; its wall-clock savings have not been benchmarked.

A related stream failure taught a cleanup lesson. A lease guard thrown inside a
Node stream's `data` callback does not reject its enclosing Promise automatically.
Destroy the reader with that error so `pipeline` rejects and the owned staging
cleanup runs. A regression now checks this exact mid-copy failure, not just an
already-rejected copy stub.

Two further real-media tests exercise `ingest.main()` and its actual atomic
writer. Holding the old manifest file descriptor open proves replacement:
its inode differs from the new path's inode, and the held descriptor still
reads the complete previous bytes. A rejected PNG keeps the original inode
and content and emits no success status. Both passed in 5.608s worker time
(24.908s with supervision and exact six-container cleanup). These tests are
main-entry integration, not a separate CLI process or full HTTP transport.
