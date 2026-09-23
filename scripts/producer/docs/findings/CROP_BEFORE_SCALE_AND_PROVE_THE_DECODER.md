# Crop before scaling, and observe the decoder that actually ran

The expensive revision work was happening before the overlay stage: short cuts
were encoded at the source's full 4K size, then encoded again to crop and scale
for a 1080×1920 delivery. Reducing the first encode to the required geometry
helps a cold render as well as a revision.

## The qualified order

For a crop whose geometry is already known:

```text
source pixels → exact trim/retime → native-size crop → delivery-size scale
              → rational CFR clock → one libx264 encode
```

Scaling the entire landscape frame first would throw away detail needed by the
portrait crop. The fused route uses the same `crop_scale_vf` geometry as the
existing reframe, with crop before scale. It removes one lossy picture generation;
picture bytes therefore are not expected to match the old two-pass output.

At 30000/1001 fps, audio is still clamped using the cumulative frame count. The
sample count is `samples(frames_before + part_frames) - samples(frames_before)`.
Neither the crop nor the decoder optimization changes that clock or the incoming
J-cut source. Synthetic portrait/landscape fixtures cover integer and NTSC clocks,
short segments, a 1.25× retime and a J-cut; frame counts and decoded float PCM
match the old route, and picture SSIM exceeds 0.98. The real rotated 4K fixture
has 79 output frames, identical part PCM and SSIM 0.989363. A paired frame check
showed the same crop without a visible structural shift.

## The bounded performance result

Final integrated source, using the shipped FFmpeg 8.0.3 runtime: three
repetitions per condition, with rotating order, on three short ranges of one
4K Main10 phone recording (79 frames, 2.63 seconds of output). These are cut-plus-reframe times, including the
new execution observations. Other development/qualification activity was running
on the host; this is a bounded local comparison, not an isolated benchmark or a
whole-render service-level promise.

| Route | Median | Range |
|---|---:|---:|
| Original ten-second pre-roll, software, two picture encodes | 26.53 s | 25.43–27.67 s |
| Qualified pre-roll, software, fused crop | 7.44 s | 6.97–8.20 s |
| Qualified pre-roll, observed VideoToolbox decode, fused crop | 5.62 s | 5.50–5.87 s |

That is a 72.0% reduction with software decoding and 78.8% with hardware decoding
for this stage pair. All six fused runs had identical encoded part hashes. The
encoder remained libx264. Final VBV masters can still differ between renders.
The optional per-part cache is unnecessary for this measured target and remains
unimplemented. There is no review carry-forward.

An earlier developer-runtime comparison measured 33.24 / 13.08 / 8.07 seconds
for the same three routes. Keep that observation separate: changing the runtime
means the difference between those rows and the final rows is not a code-only
speedup. Both sets of logs are retained with the incremental revision plan.

## Exit zero is not proof of hardware decoding

A sandbox probe selected VideoToolbox, logged an initialization failure, fell
back to software and exited zero. Calling that a hardware success would have
made the performance receipt false.

The production route considers only macOS, 4K-or-larger HEVC, and 8/10-bit 4:2:0.
It captures the actual FFmpeg attempt's decoder diagnostics. A successful
hardware-format selection without an initialization failure is recorded as
VideoToolbox. An unverified or failed attempt is followed by an explicit software
execution; both complete argv arrays are retained. Subsequent parts of that
source use software after such a failure.

Actual production tests on generated 4K 8-bit 29.97 fps and 10-bit 30 fps sources
matched software's encoded part bytes, including a retimed J-cut. This does not
qualify other codecs, pixel formats, operating systems or hardware encoders.

The installed FFmpeg 8.0.3 runtime also passed the actual compile/cut/reframe
entrypoints on the real rotated 4K source: 79 frames at 1080×1920, identical
software/hardware hashes for all three encoded parts, and observed VideoToolbox
selection on every automatic part. Reframe returned the cut-stage path, proving
that this route avoided the second encode. The package was not modified by the
probe; later live-source changes still need their own release freeze.

## When not to fuse

Landscape face tracking still needs measured windows. Manual crops, split
layouts, mixed source geometry, baseline looks, protected source/color owners,
resumed intermediate paths and proxy profiles keep their existing owners and
render order. Portrait face passthrough is eligible because the existing face
planner chooses the same geometry independently of detections.

The full command, both source identities, cumulative frame clock, completed part
hash, tool build/binary and code closure are retained in `cut_execution.json`.
These are execution observations. They do not approve a video or make a future
cache safe merely by existing. Full-output QC and editorial review still apply.
