# Native Short QC can be faster without changing pixels

The September 11 local integration compared two verification paths on the
same 13.04-second, 326-frame follow-up Short. Both final MP4s have SHA-256
`5651b14c8061b03d7685174dd17f6c37b33b52ab08268ee454116636be83878d`.
Both checked the same 149 encoded frames against native JPEG95 references.
Every MAE and PSNR result was exactly equal; maximum metric difference was zero.

The original picture/decode stage took **62.099 seconds**. The new stage took
**5.989 seconds**, including additional reverse-image comparisons: about 10.4
times faster for this stage in these runs, not a universal rendering speedup.

The waste was temporary PNG compression. Decode selected frames once to RGB24,
verify the complete byte inventory, memory-map one frame at a time, compare in
declared sRGB, and remove only successfully checked derived scratch. Retain the
MP4, native frames, hashes and measurements. Encoding thresholds remain MAE ≤2
and PSNR ≥40 dB, without alignment or color fitting. Full A/V decode remains.
`scripts/producer/studio/native_short_delivery.py` owns this shared implementation.

Full supervisor time changed from 133.193 to 67.840 seconds, but that also
includes audio reuse and other changes; attribute the measured QC speedup to
its own stage. Do not describe a prepared rerender as a complete creative edit.

## Snapshot source, not generated caches

The old code-snapshot collector included the newly materialized runtime and PNG
cache under `templates/motion/`, plus historical `scripts/producer/artifacts`.
A native history test took 98.110 seconds and failed the 512 MiB snapshot bound.
Excluding generated artifacts and `.sniper-native-runtime` restored its passing
time to 10.704 seconds. Runtime patch source, transport, implementation and
required assets remain captured; native exports separately pin their runtime.
`native-pipeline-cache-exclusion.test.ts` guards this boundary. Do not exclude
directories containing actual runtime inputs merely to shrink a snapshot.

## Reverse seeks and browser edge antialiasing

Expanded checks initially required identical JPEG hashes after a reverse seek.
The offer calendar differed at a few antialiased edges while visible computed
paint state and source frames were identical. Calendar-step, initial-color and
border-clip experiments did not establish a fix and were not retained. All failed
attempts remain in `artifacts/native-shorts-integration-2026-09-11/`.

The shared canvas initializes exit masks explicitly. Final seek checks compare
visible geometry, text, paint, normalized matrices and source frames exactly.
Hidden source video elements are excluded; actual injected frame images are
included. Equivalent identity transforms are normalized. Reverse images then
require MAE ≤0.01 and PSNR ≥60 dB, separately from encoded-picture quality.

The offer diagnostic checked 25 reverse frames: worst MAE 0.000147, minimum PSNR
84.805 dB. The regression test rejects changed text/state and a 50×30-pixel missing
region, while allowing one intensity level at one pixel. This is bounded raster
consistency, not byte identity; exact painted-state/source checks remain required.

Pixel checks cannot measure hook strength, story quality or whether a dog shot
establishes a health claim. Those remain editorial decisions.
