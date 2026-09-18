# Qualified native runtime adaptation

`native_runtime.py` installs these hash-bound patches into an isolated,
content-addressed directory. It never changes the installed HyperFrames package.
The inputs are the installed 0.8.31 distribution and the verified native Shorts
runtime from the September 10 three-case evaluation, with the September 15
source extraction clock correction below. `native-capture-library.mjs` exposes the same qualified SDK
capture primitives for local QA without running the CLI entry point.

The library also exports the qualified SDK `extractAllVideoFrames` and
`isHdrColorSpace` primitives. Explicit `--cached-native-batches
--acquire-source-cache` exports call the SDK sequentially for one local video at
a time, publishing its exact original-size PNG cache before browser capture.
The shared adapter verifies the exact cache key and consecutive frame inventory;
it never manufactures a completion marker. All source probes happen first and
HDR sources are rejected because per-video calls do not reproduce the SDK's
composition-wide HDR negotiation. Existing cache-only and SDK streaming requests
keep their selection behavior. Both the CLI and library use the same extraction
clock and cache identity; color conversion and picture encoding remain unchanged.

## Source extraction clock

Fractional input seeks can leave the first decoded PTS after zero. With plain
`fps=25` and `-t`, FFmpeg produced 56 frames for a 57-frame span, and the SDK held
the final frame. The qualified extractor now anchors CFR `fps` at `start_time=0`
and requests the exact positive ceiling frame count through `-frames:v`, with
the existing process deadline. Rational rates and floating boundary noise share
one count helper. VFR retains the SDK's `-fps_mode cfr`/`-r` conversion; final-frame
extraction retains its existing output-side seek and one-frame request. Actual
output and superset slices must cover every requested frame before publication.

The supervised September 15 experiment on the selected pricing source produced
56 stock frames and 57 corrected frames. All 56 stock frames match corrected
indices 1–56 byte for byte; corrected indices 0 and 1 repeat the first available
decoded image to cover the initial 23.3 ms gap. This is zero-grid alignment by
FFmpeg, not a reconstructed frame or an appended tail. That single-source check
does not establish quality for other media; complete native/encoded QC remains
required. Cache keys include `sniper-zero-clock-v1`, so old completion markers
cannot admit caches made with the previous sampling clock.

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

## Licence and modification notice

Upstream HyperFrames 0.8.31 is Copyright 2026 HeyGen, Inc. and licensed under
the Apache License, Version 2.0; its original distribution, license and notices
remain authoritative (upstream publishes no NOTICE file). The patch text in
`patches.json` contains portions of the upstream files, modified by Project
Sniper. Five upstream files are modified — `dist/cli.js` (28 patches; renamed
`native-render-sdk.mjs` in the adapted runtime), `dist/hyperframe.runtime.iife.js`
(2), `dist/hyperframe-runtime.js` (2), `dist/hyperframe.manifest.json` (1) and the
derived `dist/native-capture-library.mjs` (1) — 34 patches in total.
[`NOTICE`](NOTICE) in this directory is the prominent statement that these files
were modified by Project Sniper. It sits beside the patches, not inside the
patched files, because every adapted file is hash-verified against
`patches.json` before use. `frame-source-transport.mjs` and
`native-export-guard.mjs` are Project Sniper files, not upstream code.

September 16 long-export adaptation: video windows are half-open in all four
frame-lookup paths, so an outgoing clip is inactive at its exact end. Source
metadata, direct extraction and superset extraction use a sequential task map
inside the SDK. Complete metadata is still collected before the unchanged HDR
negotiation. This bounds decoder fan-out without changing source geometry,
PNG format, color policy, frame clock or cache publication. The same changes
are derived into the capture library and CLI, with verified whole-file hashes.
See `docs/producer/NATIVE_LONG_RELIABILITY_2026-09-16.md` for real qualification
and the distinction between the 15-minute stress run and subsequent hardening.

September 16 mandatory export entry: the installed `dist/cli.js` is now a small
guarded wrapper around the unchanged, hash-verified patched SDK at
`dist/native-render-sdk.mjs`. `native-export-guard.mjs` admits rendering only
under the current shared export owner, exact request/project/output and, for
Long, passed encoded seam evidence. Native capture CLIs use the same ownership
guard. Help and Studio preview remain available. The runtime identity includes
the wrapper and guard hashes; earlier installed runtimes are preserved, not
retroactively qualified. A separately installed external SDK is outside this
application boundary. See `WORKFLOW_ENFORCEMENT_AUDIT_2026-09-16.md` for limits.
