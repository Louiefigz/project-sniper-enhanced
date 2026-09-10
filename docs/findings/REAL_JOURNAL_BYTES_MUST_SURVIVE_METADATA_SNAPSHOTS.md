# Real journal bytes must survive metadata snapshots

## The failure

An unchanged real journal was rejected by the source-color cleanup writer even
though reduced unit fixtures passed. The actual `readCutPreviewObject` result
contains a Node `Buffer` alongside its raw SHA, size and parsed JSON. The test
fixtures originally supplied only selected fields of that observation.

`structuredClone` converts a Node Buffer into Uint8Array. Comparing that clone
to the original with `isDeepStrictEqual` therefore reports a change immediately.
The error was not a stale journal or a bad source; it was a broken metadata
snapshot. The positive actual-file regression failed before native work in
1.01 seconds wall time.

## The correction

`snapshotSourceColorMetadata` in `guided-source-color-staging-hold.ts` uses Node's
V8 serialize/deserialize pair for an in-process metadata snapshot and checks
deep-strict parity immediately. It preserves Buffer type, exact bytes, repeated
references and cycles. It does not freeze caller-owned Buffers or drop fields.

Only the six original held-metadata snapshots were changed. Receipt generation,
canonical JSON hashes, raw-file hashes, inode checks and publication formats
were not changed. Later byte mutation and Buffer-to-Uint8Array substitution
still fail the original comparisons.

## Evidence and limits

- The fixture now incorporates an actual new-only temporary journal read,
  including its Buffer, raw SHA, size and parsed value, before creating holds.
- The expanded regression cohort passed 145/145 in 20.97 seconds wall time.
- Nine dedicated snapshot/type/mutation cases passed in 2.89 seconds wall time.
- Type checking, scoped lint and mechanical limits passed.

Those tests exercise real local metadata and the actual cleanup recording path,
but native media, original source admission and daemon execution remain explicit
test leaves. They do not establish output quality or ten-minute render speed.

## When not to use this

Do not use V8 serialization for persisted receipt bytes or cross-language
contracts. Python and TypeScript still need their existing explicit JSON/raw
hash domains. This helper is not a replacement for filesystem observation,
schema validation, live ownership, process settlement or a deadline.

For JSON-only data, ordinary structured cloning remains appropriate. The lesson
is to test the exact shape returned by the real boundary—not to replace every
clone in the repository or weaken equality to make a partial fixture pass.
