# Private native-runtime source checkpoint

This is frozen implementation evidence, **not an installed application route**
or a claim that a clean checkout can already run the qualified native workflow.
No media was regenerated and no live SDK/runtime or app integration was changed.

The archive at `evidence/native-private-runtime-2026-09-10/` preserves exact
authored helper bytes with `.source` suffixes. `manifest.json` identifies their
original paths, SHA-256 hashes, sizes and verified source-byte equality. Suffixes
prevent ordinary application lint/test discovery from treating frozen trial
scripts as supported new production code.

## Preserved

- Native guarded supervisor, owned-process registry, fixed runtime configuration,
  optional bounded-browser wrapper and their original tests.
- Bounded resource-measurement retry mixin and the cache-aware experimental
  admission helper (separate from the default admission rule).
- Localhost-only sandbox profile.
- File-backed source-frame transport and its original tests.
- Exact official-0.8.31 → private frame-transport CLI patch, without a full
  installed/vendored CLI bundle.
- Source-bound test-library builder; the large generated libraries are excluded.
- Source-bound capture/export/trace workers and their original phase runners.
- Copy-on-write clone helper and its archive dependency.

## Reconstruct the two separate SDK variants

Start from the exact official 0.8.31 files identified by the recipe hashes, in
separate disposable package copies. Never patch the installed SDK in place.
These were **two separate variants**, not one combined qualified runtime.

For frame transport, apply
`transport/official-0.8.31-frame-transport.patch.source` to `dist/cli.js`, then
place the exact `transport/frame-source-transport.mjs.source` bytes at
`dist/frame-source-transport.mjs`. Match the target CLI hash in the recipe.

For realm-safe preview, `realm/reconstruction-recipe.json` records exact
UTF-16-code-unit-offset edits to the official `dist/hyperframe-runtime.js`.
Verify the base hash, apply edits in reverse offset order while checking every
removed string, and verify the target hash. Both runtime alias files use the
same reconstructed bytes. Replace the unique `RUNTIME_IIFE` assignment in the
official CLI with JSON.stringify of that runtime after removing exactly one
terminal LF. Use slicing or a replacement **callback**: a replacement string
would interpret runtime `$&` tokens. Verify the realm CLI's target hash.

The archived library builder removes the CLI bootstrap at its exact marker and
exports existing SDK functions without body changes. It contains historical
absolute paths: adapt paths in a disposable copy, not these frozen bytes.

In-memory reconstruction checks matched the original realm runtime and CLI,
the frame-transport CLI and both generated baseline/candidate test libraries.
These checks establish byte reconstruction, not runtime regression coverage.

## Dependencies and remaining portability work

The helpers depend on repository `native_render_resources.py`,
`native_render_processes.py`, `native_work_lease.py`, `stage_timing.py` and their
imports. They also depend on installed pinned Node, Chrome headless shell,
FFmpeg/ffprobe, Python environment and the official SDK's npm dependencies.
Those installed packages/executables are deliberately not archived here.

Historical scripts retain `/private/tmp` project, media, cache, output and
helper paths. This archive is not their complete media/configuration dependency
closure. All saved original fixtures have NOT been relocated and rerun. The
browser wrapper, cache-aware admission, capture/export and archival helpers
must not be advertised as portable production modules merely because bytes
were preserved. Production integration, resolved path/configuration ownership,
relocated tests and representative audiovisual qualification remain open.

The small C0679 opening test authorized separately is still isolated under
`/private/tmp/sniper-short-native-20260910.dzPmYo/` and is not included as a
completed media result. Its first attempt was refused before child launch by
sandboxed host-measurement access; no quality or timing success is claimed.
