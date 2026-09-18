# A tiny presenter proof does not establish full-resolution performance

The shared presenter graph passed exact tiny-prefix and encoded-picture tests.
A representative 1920×1080 sample then exposed a large runtime cost. Correctness
at 64×36 was necessary, but it was not a useful performance qualification.

## Measured sample

One opt-in TEST cohort rendered 30 frames at 30000/1001 (1.001 seconds of media).
The base and selected assets contained moving test textures and colored grids,
not uniform frames. The video asset contained real AAC; every output had only
one picture stream and passed complete30-frame decode to EOF.

All cases used the same existing shared compositor and unchanged libx264,
CRF12, `composite_preset=veryfast`, native1920×1080 and yuv420p. These are
single observations on this host, with baseline then still then video order,
not repeated statistically controlled measurements.

| Case | Shared graph + single encode | Complete output QC | Observed encode throughput |
| --- | ---: | ---: | ---: |
| No presenter layout | 0.169433 s | 0.474557 s | 177.061 frames/s |
| Manual inset + still | 47.219787 s | 0.476465 s | 0.6353 frames/s |
| Manual inset + video | 50.108235 s | 0.462755 s | 0.5987 frames/s |

Actual asset setup and selected-picture observations took0.931501s. That is
separate from the expensive graph/encode. The new observer was not called
again by the subsequent prefix checks.

The baseline prefix oracle took1.059481s. The still prefix oracle took
151.082885s, including150.781934s in actual pre-encode graph execution. It
emitted30 full,18 core and30 review frame hashes. The retained field named
`actualGraphFrameTraversals=78` describes these emitted hashes, **not** the
number of intermediate frames/pixels the filters evaluated.

## The original budget stopped the cohort

The entire work clock was fixed at300s before setup; every child had at most
60s and was clipped to the original remainder. The video prefix child started
at252.545042s with47.454980s left. It timed out and was reaped; the cohort did
not restart it. Terminal status was failure, at301.036245s including roughly
1.036s of bounded cleanup. Shell time was304.11s including initial imports.

All28 exact recorded local process groups had matching spawn/reap records and
were independently observed absent. No Docker, isolated admission, catalog,
provider, full workflow, or creator source was used.

## Preserve the old bytes before optimizing

Evidence root: `/private/tmp/sniper-presenter-1080p-2r3kbvg4`.

- `TEST-benchmark-evidence.json`: original failed cohort, commands, held
  code/tool/source hashes, complete timings, actual cleanup and partial results.
- `TEST-retained-framehash-index.json`: exact original MP4 hashes plus existing
  all-frame yuv420p hash stdout and all six completed baseline/still prefix
  hash streams. A0.060755s read-only diagnostic validated/indexed those already
  decoded rows. It did not render or decode anything again.
- `owned-processes.jsonl`: actual owned runner lifecycle, including timed-out
  video-prefix child72591 and its reap.

The sustained-layout throughput measured here is a serious risk to the
two-hour engineering goal. It is **not** a ten-minute render prediction or
a production deadline guarantee. Geometry, cache state, window duration,
content and other stages can change cost. Source inspection suggests repeated
per-pixel mask expressions deserve a focused optimization; attribution still
requires a controlled comparison. Any change must preserve all-frame pixels,
binary mask boundaries, resolution, encoder quality and original timing.

The reusable harness is
`scripts/producer/tests/benchmark_presenter_1080p.py --run`. It deliberately
has no timeout, resolution, preset or retry override. Do not rerun it against
an ongoing production workload or silently replace these failed baseline
artifacts with a later successful optimization experiment.

## One expression-only optimization, independently compared

The next distinct cohort used the unchanged harness and original 300-second
setup-inclusive clock. The only difference in its captured production code
closure was `graphics/presenter_layout_geometry.py`: the alpha expression
stored repeated per-pixel calculations in four FFmpeg expression registers.
Every register was initialized during each evaluation; there was no
cross-pixel state, lower resolution, encoder change, or relaxed mask test.

| Operation | Original | Optimized | Observed ratio |
| --- | ---: | ---: | ---: |
| Still inset graph + encode | 47.219787 s | 5.873505 s | 8.039× |
| Video inset graph + encode | 50.108235 s | 6.414887 s | 7.811× |
| Still prefix oracle | 151.082885 s | 18.987182 s | 7.957× |

The optimized baseline encode took 0.317885 seconds, its prefix took 1.080588
seconds, and the now-completed video prefix took 19.384358 seconds. All three
complete output-QC checks took 0.466–0.496 seconds. The cohort completed in
54.711089 seconds on its original work clock (57.85 seconds including imports).
All 30 exact spawned groups were reaped and independently observed absent.
The failed original video prefix has no successful timing to compare.

A separate 0.25-second read-only comparison reused the retained frame-hash
outputs; it performed no additional decode. It required and confirmed:

- Identical generated input bytes, tools, encoder settings, TEST helper and
  declaration code, and all non-alpha native arguments after root-path mapping.
- Equality of all 30 decoded native **yuv420p** frame hashes for each output,
  not just initial frames. The three complete encoded MP4 hashes also matched.
- Equality of all six completed old baseline/still pre-encode hash streams
  (30 full, 18 core, and 30 review frames per case).
- The exact original still declaration and graph projection, checked against
  both retained full/opening graph hashes, without constructing cold execution
  authority from a saved receipt.

Optimized evidence root: `/private/tmp/sniper-presenter-1080p-x_ui1q_9`.
`TEST-benchmark-evidence.json` retains actual commands, times and cleanup;
`TEST-pixel-comparison.json` retains the raw old/new report hashes, both code
closures, their one-file difference, and every comparison result. The
separately held original index SHA-256 is
`5b7c23a2c345892a71cb41ea990ec8f768a1ef7bc8a0294564a02fe77ac71016`.
The pure comparator/control cohort passed seven tests, including a changed
last-frame negative and source/tool/encoder mismatch rejection.

This isolates a substantial avoidable expression cost for this sample. It
does **not** prove ten-minute performance or the two-hour whole-workflow goal.
The optimized inset graph still achieved only about 5.11 still / 4.68 video
frames per second, and its independent prefix checks added roughly 19 seconds
each. Those measured costs remain relevant to long sustained layouts. Real
framing, other layouts, content, source admission, full delivery QC, and profile
release remain separate qualifications. Do not use a one-second sample or
these observed ratios as a deadline guarantee.
