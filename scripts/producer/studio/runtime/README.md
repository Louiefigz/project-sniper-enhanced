# Qualified native runtime adaptation

`native_runtime.py` installs these hash-bound patches into an isolated,
content-addressed directory. It never changes the installed HyperFrames package.
The inputs are the installed 0.8.31 distribution and the verified native Shorts
runtime from the September 10 three-case evaluation. The patch set reproduces
those exact runtime/CLI bytes; `native-capture-library.mjs` exposes the same SDK
capture primitives for local QA without running the CLI entry point.

The library also exports the unchanged SDK `extractAllVideoFrames` and
`isHdrColorSpace` primitives. Explicit `--cached-native-batches
--acquire-source-cache` exports call the SDK sequentially for one local video at
a time, publishing its exact original-size PNG cache before browser capture.
The shared adapter verifies the exact cache key and consecutive frame inventory;
it never manufactures a completion marker. All source probes happen first and
HDR sources are rejected because per-video calls do not reproduce the SDK's
composition-wide HDR negotiation. Existing cache-only and SDK streaming requests
keep their behavior. This addition changes the library's exports and hash, not
the CLI, video extractor, color conversion or picture encoder implementation.

The new content-addressed runtime leaves earlier runtimes and caches intact.
`source-cache.json` records each hit, extraction and failure within the existing
supervised export. Structural SDK-boundary tests do not establish resource use
or pixel equivalence on real footage; those require a supervised export and its
current native/encoded QC.

The adaptation supplies file-backed frame transport and same-document DOM realm
checks. See `docs/producer/SHORTS_REAL_EXPORT_QUALIFICATION_2026-09-10.md` for the
paired transport measurement and its limits. It is not an upstream release or a
claim that an arbitrary upgraded SDK is compatible. Patch offsets require the
complete input SHA-256 and verify the complete resulting SHA-256.

Upstream HyperFrames is Apache-2.0; its original distribution, license and
notices remain authoritative. `frame-source-transport.mjs` is the local adapter.
