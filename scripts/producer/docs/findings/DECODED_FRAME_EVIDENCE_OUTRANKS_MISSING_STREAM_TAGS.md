# Decoded Frame Evidence Outranks Missing Stream Tags

## Assertion

A missing stream-level scan tag is not evidence that a video is progressive,
and it is not evidence that the video is interlaced. When the retained decoder
version omits that tag, qualify scan mode from every decoded frame and fail if
any frame disagrees.

## The incident

`C0679.MP4` is a 10.28 GB, 3840x2160 H.264 source with 20,004 frames at
`24000/1001`. Its first isolated qualification run decoded the complete source
and then rejected it as having inconsistent clock or scan authority.

The host's FFprobe 8 stream header reported:

```json
{
  "field_order": "progressive",
  "r_frame_rate": "24000/1001",
  "time_base": "1/24000",
  "start_pts": 0,
  "nb_frames": "20004"
}
```

The approved renderer image retains FFprobe 4.4.2. For the same immutable
source bytes, that version omitted `field_order` entirely. It also emitted
decoded timestamps as `pkt_pts` plus `best_effort_timestamp`, and frame
duration as `pkt_duration`, rather than the newer `pts` and `duration` names.
The validator had mistaken a tool-schema difference for a media defect.

## Evidence and correction

A read-only probe in the approved image showed that decoded video frames carry:

```json
{
  "pkt_pts": 0,
  "best_effort_timestamp": 0,
  "pkt_duration": 1001,
  "interlaced_frame": 0,
  "top_field_first": 0
}
```

Decoded PCM frames similarly use `pkt_pts`,
`best_effort_timestamp`, and `pkt_duration`. The source audio stream is exact
48 kHz stereo PCM with 40,048,080 timeline samples. That is 72 samples
(1.5 ms) longer than the nominal 20,004-frame video clock, safely below one
source frame.

The qualification worker now:

1. accepts stream scan declarations only when they are `progressive`,
   `unknown`, or not reported;
2. requires all 20,004 decoded video frames to have
   `interlaced_frame == 0` and `top_field_first == 0`;
3. accepts known timestamp aliases only when every alias present has the same
   integer value;
4. still requires exact zero epoch, integral 1001-tick frame steps, contiguous
   48 kHz audio samples, and immutable source hashes before and after work; and
5. rejects any `-v error` decoder stderr even when FFprobe exits with status
   zero; and
6. retains `streamFieldOrder` and `decodedProgressiveFrames` in evidence.

The focused qualification suite passes 33 test methods, including an
FFprobe-4.4-shaped fixture, C0679's measured 1.5 ms PCM/video delta, and
adversarial interlace, timestamp, filter-binding, and decoder-stderr cases.

## Principle

Versioned probe output is an observation vocabulary, not the media itself.
Use the strongest decoded evidence the retained tool can produce, preserve the
tool version and argv, and cross-check aliases. Never turn a missing metadata
field into an unsupported positive claim.

## When not to use this

Do not infer progressive scan when any decoded frame reports
`interlaced_frame != 0` or `top_field_first != 0`, when an explicit stream tag
declares an interlaced order, when timestamp aliases disagree, or when the
complete decoded frame count is unavailable. Those cases require rejection or
an explicit deinterlace policy with separate visual approval.
