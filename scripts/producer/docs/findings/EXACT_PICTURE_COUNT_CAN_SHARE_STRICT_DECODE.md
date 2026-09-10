# Exact picture count can share the strict decode

## What changed

`guided_opening_picture.observe_picture` previously decoded a complete video
with `ffprobe -count_frames`, then decoded the same bytes again with strict
FFmpeg. The first operation supplied a frame count; the second rejected decoder
errors. Counting the terminal frames from that second operation removes the
redundant count decode without trusting the container's `nb_frames` metadata.

The new `guided_picture_decode` adapter uses the existing owned process runner
and the existing strict audit progress parser. Its command has one stdout
writer, no seek, frame limit, filter, rate conversion or audio decode:

```text
ffmpeg -nostdin -hide_banner -nostats -v error -xerror -err_detect explode
  -i INPUT -map 0:v:0 -an -fps_mode passthrough
  -progress pipe:1 -f null -
```

Only a successful complete child with exactly the expected terminal frame count
qualifies. Missing, duplicate, torn or nonterminal progress fails. The adapter
does not borrow the audit scanner's approximate duration tolerance: exact
rational packet PTS, CFR, origin and time-base validation remain separate.

## Measured example

Three alternating old/new observations of the same synthetic H.264 file,
360 frames at 30000/1001, 1280×720, 12.012 seconds:

| Observation | Old wall time | New wall time |
| --- | ---: | ---: |
| Pair 1 | 750.455 ms | 285.097 ms |
| Pair 2, reversed order | 735.378 ms | 302.960 ms |
| Pair 3 | 736.949 ms | 282.544 ms |

The median reduction was approximately 61.31% (451.853 ms) **for this small
fixture**, not a longform or creator-input forecast. The removed count probe
took about 499 ms; metadata-only probing took about 48 ms. Strict decoding and
packet-clock observation still took about 114 ms each. Whole-file hashing was
retained before and after both algorithms.

Evidence: `/private/tmp/sniper-picture-decode-nxvmbwzz/measurements.json`, with
the complete equal old/new observations and 22 retained rejected observations.
The measured input was 4,373,008 bytes, SHA-256
`1c33a5a03e5e826e95a86b916d16dceae6a24bc5215b5cbf9e2eca36e2ab9877`.

The final frozen integration cohort passed 50/50 in 48.221 seconds suite time,
52.00 seconds wall. This includes 13 focused new tests, actual tiny whole-body
result and opening preparation/readback tests, and the existing strict progress
and owned-runner tests. Full log:
`/private/tmp/sniper-picture-decode-integration-20260907.log`.
The full-body result read took 0.906 seconds at
`/private/tmp/sniper-held-preparation-621u8f64/body-result-adapter`; opening
preparation evidence remains at `/private/tmp/sniper-opening-preparation-y5pvi97e`.

## Defect recall and limits

The literal old observer is retained only in a TEST helper, never a production
fallback. Both algorithms returned identical observation records on integer
and NTSC clips and an A/V file whose audio outlasted its video. One-frame
clips passed at 24, 25, 30, 50, 60, 24000/1001, 30000/1001 and 60000/1001.
Both rejected actual late packet corruption, truncation, nonzero origin, VFR,
non-square SAR, rotation, multiple videos and mismatched frame/canvas/rate
authority. A post-observation byte mutation still failed the final hash.

The first test run retained a fixture-construction failure: FFmpeg 8 did not
write rotation from the legacy `-metadata rotate=90` option. The corrected
fixture uses `-display_rotation:v:0 90` and verifies the actual display matrix
before asserting rejection. No earlier failed evidence was replaced.

The new process captures at most 1 MiB across both output pipes, under the
existing remaining timeout. Actual overflow and TERM-resistant timeout tests
proved ledger completion and owned-group absence. This is a text-capture bound,
not a native decoder RSS limit or an overall media-memory qualification.

Do not remove independent selection, approval, body-admission or current-source
checks. Do not reuse a prior receipt across changed bytes, clocks, tools or
implementation pins. This optimization does not change audio, whole Audit B,
creative review, approval or delivery authority, and does not retroactively
requalify a stored result under newly changed code.
