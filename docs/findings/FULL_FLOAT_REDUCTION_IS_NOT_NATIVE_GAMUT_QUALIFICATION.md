# Complete float reduction is useful, but not native gamut qualification

## Later native-kernel checkpoint — September 8

The supplied-AVFrame implementation now exists in
`scripts/producer/color/native/source_gamut_avframe.c`. It reduces active rows
directly with installed libavutil and keeps padding out of pixel statistics.
UBSan and optimized builds match the Python framed reference's exact counts
and extrema bits, including negative/unaligned strides and nonfinite inputs.
This is a reusable reduction component, not a source decoder or grade receipt.

One hot synthetic 384 MiB kernel measurement took 0.155899 seconds (2.58 GB/s).
It excludes SHA, framing, decoding, zscale and source IO; do not compare it with
the complete Python reducer benchmark below as an equivalent end-to-end speedup.
The failed missing-sysroot build and ASan initialization abort are preserved
with the successful UBSan/optimized run in
`docs/producer/evidence/SOURCE_GAMUT_NATIVE_KERNEL_2026-09-08.json`.
ASan did not pass and no production source was opened by this kernel work.

The next real implementation step is the owned decode/filter-sink loop calling
this same kernel. It must join original frame timing, complete clean EOF and
active-row hashes, hold the actual linked runtime and original source/deadline,
and participate in the existing retained readback before any live activation.
The pure reference and its unchanged benchmark evidence follow.

## What was implemented on September 8

`color/source_gamut_reducer.py` now joins supplied original normalized V2 frames
to separately supplied measurement headers and exact planar float bytes. It
uses the unchanged `SourceFrameValidator`; unknown declared history remains
observable. It does not call the known-history APPLY/compiler gate.

For every frame the header must match the original index, integer PTS, duration,
time base and native dimensions. The fixed payload format is `gbrpf32le`:
one complete green plane, then blue, then red. Treating this as interleaved RGB
would label the measurements incorrectly.

The stream accepts at most 1 MiB of immutable bytes per call and retains at most
three partial-float bytes, aggregate counters and one frame's metadata. There
is no full-frame or full-source raw-pixel buffer/file. Each frame's payload SHA
is joined to both metadata records; the final digest includes both closed clean
EOF records. Missing/extra bytes or frames, mismatched clocks and late mutation
fail permanently. Every operation borrows the original guard, with no new time
allowance. This is not an authenticated source, tool or process guard by itself.

`color/source_gamut_samples.py` uses installed NumPy vector operations, not
Python per-pixel loops. Each channel records finite, NaN, positive/negative
infinity and finite below-zero/above-one counts, plus finite extrema. All
categories are exact counts; there is no gamut epsilon, clamp or sample skip.
Invalid-range values produce a useful diagnostic with `sampleRangeValid:false`.
Malformed or incomplete streams produce no successful diagnostic.

`color/source_gamut_result.py` rechecks the original binding/record digest,
integer coverage and count/extrema consistency. All native, gamut-qualified,
transform, grade and delivery flags remain false. A caller can construct these
records; parsing them is not permission to apply a transform.

## Two numerical edge cases mattered

The existing canonical JSON helper intentionally rejects integer-valued floats
outside JavaScript's exact-integer range. That is appropriate for media clocks,
but a finite float32 extremum can legitimately be larger. The pure result uses
standard finite JSON only after every closed bounded field validates. It also
compares the original numeric value to its float32 representation: the integer
`2**60 + 1` must not round silently into acceptance.

Mixed negative/positive zero exposed another defect. Before correction,
identical payload bytes split into different chunks produced differently signed
zero extrema in serialized summaries (genuine synthetic reproduction, 0.126 s
wall). Reported zero extrema now normalize to positive zero. The actual bytes
and their hashes are unchanged, so negative-zero payloads remain distinguishable.

## Measured cost, not an assumed speedup

The retained benchmark feeds the actual reducer, metadata checks and payload
hashes. Each case processes 128 synthetic 512x512 frames, or 384 MiB, under one
30-second engineering-test deadline. No media decoder, transform, pipe, Docker
or source-footage read is involved. Both complete original stdout records are in
[`SOURCE_GAMUT_SYNTHETIC_BENCHMARK_2026-09-08.json`](../producer/evidence/SOURCE_GAMUT_SYNTHETIC_BENCHMARK_2026-09-08.json).

| Immutable input case | Before | After finite-block optimization |
|---|---:|---:|
| Repeated 64 KiB chunk | 333.16 MB/s | 374.64 MB/s |
| Repeated 1 MiB chunk | 980.00 MB/s | 1,261.79 MB/s |
| Rotating 64 MiB ring, 1 MiB chunks | 989.27 MB/s | 1,248.47 MB/s |

The optimization first computes the complete finite mask/count. Only when every
value is finite can it omit three redundant nonfinite scans and a filtered
buffer copy. It still counts every finite outlier. Prior nonfinite observations
remain accumulated. An independent scalar oracle over explicit float32 bit
patterns and the existing framed tests verify both paths.

The two whole benchmark commands took 2.33 and 1.99 seconds. Process high-water
RSS reached 121.52 and 117.16 MB respectively. There was one measurement before
and one after, not a statistical throughput guarantee; the rotating ring is not
claimed to exceed every machine's cache. This does not establish container
NumPy availability or the cost of an owned decoder.

## Why this is not the production time solution

C0679's retained dimensions/count imply:

```
3840 * 2160 * 20,004 = 165,921,177,600 pixels
pixels * 3 channels * 4 bytes = 1,991,054,131,200 float bytes
float bytes / 1,200 seconds = 1.659 GB/s minimum traversal rate
```

At the best measured after-rate, reduction alone extrapolates to 1,577.95 seconds
(26.30 minutes), already 377.95 seconds beyond the existing 20-minute observation
phase. Decode, chroma reconstruction/linearization and transport would add work.
The baseline best was 33.54 minutes. Neither extrapolation is a source benchmark
or a two-hour full-video result. Do not wire this reference into production and
assume the declared phase still fits.

The next native implementation should reduce near the actual decoded/linearized
frame planes and emit small records, avoiding export of roughly 2 TB. It still
needs pinned runtime support, exact stride/plane/PTS/duration correspondence,
original source/tool/deadline evidence, clean EOF/settlement and authenticated
readback. Tiny uniform patches and this pure oracle do not prove spatial chroma,
all-source throughput or actual image quality. No existing APPLY/public-launch
fence or original policy has been relaxed.

## Verification boundary

The 33 gamut tests passed independently in 0.301 s wall; the root's full 67-case
gamut/source-record/frame-adapter/transform-reference cohort passed in 0.74 s.
All eight new production/test/fixture/benchmark files meet 300/50/4/2 limits,
including try nesting, and documentation/type checks. Initial retained failures
were a duplicate-key TEST construction error and a missing-PYTHONPATH loader
error, plus the real signed-zero inconsistency. This is a completed reference
implementation, not completed native color finishing or real-video QC.
