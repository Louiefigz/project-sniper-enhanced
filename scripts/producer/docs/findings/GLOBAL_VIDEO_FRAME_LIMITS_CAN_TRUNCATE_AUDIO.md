# Global video frame limits can truncate audio

## Assertion

Do not use FFmpeg output option `-frames:v N` to terminate a qualification
transcode that also carries audio. Bound the video inside its filter graph and
let the independently bounded audio filter drain.

## The incident

The over-cap qualification worker converted a `24000/1001` source to Palmier's
integer `24/1` project clock. It used `-frames:v N` to make the video length
exact and separately used `atrim` to make the audio length exact.

That looked like two independent bounds. They were not. With FFmpeg 4.4.2,
reaching `-frames:v` ended the output before the AAC stream drained.

## Evidence

In the pinned renderer image, a 48-frame target should contain:

- 48 video frames at `24/1`
- 96,000 program samples per audio channel at 48 kHz

With `-frames:v 48`, the video was correct but one run exposed only 1,008 AAC
timeline samples. The same command could vary with encoder scheduling.

The replacement is:

```text
fps=fps=24/1:start_time=0:round=near,
trim=end_frame=N,setpts=PTS-STARTPTS
```

There is no global `-frames:v`, `-t`, or `-shortest`. Audio is bounded in its
own graph. Image-backed probes for 49 and 50 video frames then produced exact
video clocks and complete audio:

| Video frames | Program samples | MP4 timeline samples | Silent tail |
| ---: | ---: | ---: | ---: |
| 49 | 98,000 | 98,016 | 16 |
| 50 | 100,000 | 100,032 | 32 |

AAC-in-MP4 in this renderer uses a 1 ms presentation quantum: 48 samples at
48 kHz. The worker therefore trims source audio at the exact program boundary,
pads with silence to `ceil(program / 48) * 48`, and records that 0–47 sample
tail separately from AAC decoder padding.

For `C0679.MP4`, the governed expectation is:

- 20,024 exact video frames at `24/1`
- 40,048,000 program samples per channel
- 40,048,032 MP4 timeline samples
- 32 samples (0.667 ms) of declared silence

The contract still requires exact video `duration_ts`, time base, frame count,
zero epoch, complete A/V decode, and decoded audio coverage.

## Principle

Each stream owns its termination. Container presentation quantization is not
program content: align it only after trimming the program, disclose the added
silence, and bind the rule to the pinned toolchain.

## When not to use this

- A video-only render may safely use a video frame output limit.
- A lossless container/codec with an exact sample clock may not need the AAC
  presentation-alignment tail.
- Do not copy the 48-sample quantum to a different sample rate, container, or
  FFmpeg build without measuring and pinning that toolchain first.
