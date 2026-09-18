# One frame probe can own both stream clocks

## Assertion

When one fail-closed `ffprobe -show_frames` invocation already emits every
video and audio frame plus `media_type` and `nb_samples`, reuse that document
for the decoded-audio sample total. Running the same ffprobe decoder a second
time against the same output adds latency and I/O, not an independent oracle.

## The incident

The qualification mezzanine worker validated its output twice:

1. a full output probe decoded every H.264 and AAC frame and emitted
   `media_type`, timestamps, durations, and `nb_samples`;
2. a second audio-only ffprobe decoded the AAC stream again solely to sum
   `nb_samples`.

Both commands used the same pinned ffprobe binary and the same error policy.
The second run therefore did not add tool or implementation independence.

## Evidence

The shared output probe is still a complete decode. It remains responsible for:

- all 20,024 expected C0679 video frames at `24/1`;
- zero-based, contiguous video PTS and progressive-frame evidence;
- all decoded AAC frame sample counts;
- 40,048,032 authoritative timeline samples per channel plus separately
  disclosed decoder padding;
- status-zero stderr rejection.

The worker now filters the already decoded frame document to
`media_type === "audio"` and sums the same positive `nb_samples` values. The
host contract binds `audioDecodeArgv` to the exact full-output probe argv, so a
fabricated separate or reduced command fails closed.

This changes the post-transcode media work from two output decode commands to
one. For an interleaved MP4 it also removes up to one extra full output demux
traversal. It does not remove the independent full output validation pass.

The qualification suite passes 51 tests plus 42 subtests across the mezzanine,
clock, cadence, output-termination, and plan-rebind contracts. The live
pinned-image acceptance remains the authority for the exact FFmpeg build.

## Principle

Independence comes from a different trust root or validation method, not from
repeating the same decoder over the same bytes. A single complete observation
may support several derived facts when the evidence records that shared
authority explicitly.

## When not to use this

- Do not reuse a video-only probe for audio facts.
- Do not reuse a probe that omits `media_type` or `nb_samples`.
- Keep a second pass when it intentionally uses a different decoder or a
  separately governed oracle.
- Do not remove the source frame probe, the output frame probe, or the
  pre/post byte observations; each proves a different part of the current
  fail-closed contract.
