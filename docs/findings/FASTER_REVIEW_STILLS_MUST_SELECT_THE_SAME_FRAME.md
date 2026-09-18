# Faster review stills must select the same frame

An isolated experiment on2026-09-06 found a fast path worth qualifying, and a concrete reason not to ship it after a speed-only test.

Audit B currently launches one FFmpeg process for each required JPEG. Nearby cut/graphic phases often seek into the same short part of a video. One decoder split into several output branches can avoid repeated startup and overlapping decode work without removing any review sample.

## Measured synthetic experiment

Each source was a3-second640×360 H.264 test pattern. Required samples were0.200,0.600,0.900,1.000,1.100 and1.600seconds. JPEG quality was3 in both paths. This is not a creator-video or complete Audit B benchmark.

| Rate | Six legacy processes | One corrected batch | Decoded JPEG pixel comparisons |
|---|---:|---:|---|
|24fps|0.403s|0.089s|6/6 identical|
|30000/1001fps|0.427s|0.096s|6/6 identical|
|60fps|0.410s|0.096s|6/6 identical|

These numbers are from one measured trial per rate, not a distribution or a total editing-time improvement.

## The first attempt was wrong

The initial batch sought to0.200seconds and selected each branch using a relative decimal offset, for example `gte(t,0.800)` for the1.000second sample. At24fps the decoded image differed from the legacy1.000second extraction. The other17 comparisons passed, making it easy to miss the defect in a casual review.

Seek time and frame timestamps live on a discrete media time base. Subtracting an apparently exact decimal seek offset is not necessarily equivalent to comparing the original presentation timestamp. A rounding difference at a frame boundary can select the following frame.

The corrected experiment preserves original timestamps with `-copyts`, selects against the absolute requested timestamp, then resets the selected branch's output PTS:

```text
-copyts -ss 0.200 -i source.mp4
[branch]select=gte(t\,1.000),setpts=PTS-STARTPTS[image]
```

This matched all18 decoded JPEG pixel hashes against the existing one-frame extractor. Both passing and failed media were retained; production extraction was not changed by this experiment.

## Integration requirements identified by the experiment

- Preserve every planned label, timestamp and reviewer note, including duplicate times belonging to different events.
- Bound batch size and timestamp span. Decoding an entire ten-minute file to gather a few distant frames can be slower than independent seeks.
- Qualify supported zero-origin final media explicitly. Nonzero origins, multiple video streams, VFR, rotation/display transforms and alternative pixel formats need their own comparison cases, not assumptions.
- Retain the existing JPEG quality, dimensions and decoder behavior. Fewer or smaller images would be a different review-coverage change.
- Reject missing/partial output and stale JPEGs from older attempts. A zero FFmpeg exit code alone is not proof that every requested frame was written.
- Keep source identity and deadline/cleanup guards. Batching cannot turn a failed candidate into approved media.
- Run longform/full-size trials and report failed attempts and actual process/decode work before making a speed claim.

Use this approach for clusters of nearby review samples after those checks pass. Do not extrapolate a roughly4× local extraction improvement into a4× video-editing improvement: model review, rendering, audio and other stages remain separate costs.

Evidence roots: `/private/var/folders/3m/8rxbwgds5z7c3r72ccfqb9280000gn/T/sniper-frame-batch-spike-j3_rb3bh` (failed relative-time version) and `sniper-frame-batch-spike-y5vm_0b8` (global-PTS comparisons). Prototype runner: `/private/tmp/sniper-review-frame-batch-spike.py`.

## Subsequent bounded production qualification

The same-day integration in `scripts/producer/audit/audit_frame_batch.py` now preserves all required samples and uses the ordinary Audit B probe without another probing subprocess. Admission is limited to zero-origin single-video H.264/yuv420p, square pixels, no display transform and eight declared frame rates. Groups contain at most six samples, span at most1.5seconds, and split at neighboring gaps over750ms. Unqualified or sparse samples retain the existing serial path. Missing/partial batch output rejects the whole group; private fresh JPEGs must all validate before publication.

The latest cohort passed17 tests in27.43s wall, including the current renderer-effect registry and121 actual decoded JPEG pixel comparisons:11 sample times across eight small-frame rate classes and three full-size classes. Time zero, exact boundaries, duplicate event times and near-tail samples matched the existing extractor. A separate ordinary Audit B/audio-fault cohort passed24 tests in24.09s wall. These cohorts overlap and are not a full regression-suite total. Independent inspection found no concrete blocker in the sampling/publication seam.

Ten-frame single-trial extraction at full size measured0.962→0.391s for1080p landscape,0.992→0.382s for1080p portrait and1.878→0.827s for4K. Evidence and per-case measurements are retained under `/private/tmp/sniper-review-batch-media-a9r2jy8g`, `sniper-review-batch-media-ct1nb5g6` and `sniper-review-batch-media-ou2v29w5`. Longform end-to-end timing and creator-output quality still require independent qualification. Metadata frame-rate checks are not an all-frame CFR attestation, and no gain is claimed for unqualified formats or dispersed samples.

A final rerun after mechanical helper extraction passed9 actual tests in29.42s wall, with all121 pixel comparisons still identical. Its11-sample full-size measurements were1.738→0.819s landscape,1.801→0.687s portrait and3.673→1.755s4K; evidence: `/private/tmp/sniper-review-batch-media-n_yr7f_e/measurements.json`. Those are another local trial with a different sample count and system load, not directly interchangeable with the ten-sample timing example or a controlled speed distribution. The quality-equivalence assertion concerns these exact decoded review samples, not overall video quality.
