# A reused opening master does not preserve graphic timing by itself

The September 7, 2026 held-assembly check found a small but visible mismatch:
the approved opening's compositor used integer half-open frame intervals, while
ordinary full-program assembly used rounded decimal seconds with inclusive
endpoints. Reusing the exact same base and audio master did not fix that.

## A same-duration shift can hide in frame-count checks

A synthetic red marker was requested on frames `[4, 10)` over a blue base.
At both 24 fps and 30000/1001 fps, the legacy path displayed frames 5 through 10.
Both the intended and actual intervals contain six frames. A total frame-count
or graphic-duration check therefore would not detect the one-frame shift.

| Selection | Visible marker frames |
|---|---|
| Intended / exact-frame opt-in | 4, 5, 6, 7, 8, 9 |
| Preserved ordinary legacy default | 5, 6, 7, 8, 9, 10 |

The TEST marker intentionally outlives its placement window so the compositor's
gate, rather than marker EOF, decides visibility. This is a decoded pixel test
of the shared stage, not catalog-animation or perceptual-quality evidence.

## Narrow fix

`AssembleJob.graphic_frame_clock=(rate, total_frames)` is an internal opt-in.
It is rejected without an actual held source-float-v2 program. The held loader
requires the supplied clock to equal the retained source bus. The graphics stage
also checks the real base clock and frame count before catalog execution.

The same existing half-up plan-time mapping creates `startFrame` and
`endFrameExclusive`; empty, outside, malformed, or contradictory windows reject.
The existing compositor then uses `gte(n,start)*lt(n,end)`. No graphic is silently
dropped. Exact output count has zero tolerance. The ordinary legacy default is
unchanged.

This exact compositor is deliberately picture-only. The final audible track
comes from the already selected full-program master through the existing
delivery function—not the base's transport audio or a newly normalized snippet.

## Evidence and limits

- Before patch: 5 tests, 6 failures and 1 TEST canonical-temp-path setup error,
  2.26 seconds wall; `/private/tmp/sniper-held-frames-before-20260907.log`.
- First patch attempt: rejected the missing picture-only option, preserving the
  compositor's guard; `/private/tmp/sniper-held-frames-after-20260907.log`.
- Focused frame/quantization/compositor cohort: 16/16 passed in 2.20 seconds;
  `/private/tmp/sniper-held-frames-focused-20260907.log`.
- Held media/publication cohort: 25/25 passed in 34.65 seconds;
  `/private/tmp/sniper-held-frames-media-cohort-20260907.log`.

The actual held final smoke is retained under
`/private/tmp/sniper-held-preparation-3j0kdxhq/exact-frame-clock/`.
It has 120 frames at 30000/1001, 192192 presented 48 kHz samples, one audible AAC
encode, -14.01 LUFS and -6.04 dBTP. AAC decoded 192512 samples with 320 trailing
padding samples trimmed by its clock contract. Strict full-decode delivery and
Audit B passed. Original opening inventory, selected master identity, and picture
packet equality were checked. This full-final fixture has no graphics; the
separate marker fixture proves graphical endpoints.

No body CLI or approval was enabled. Future body execution must require this
opt-in, qualify **all** body presentations and assets, preserve exact approved
opening content, and own process/container cleanup and full-output review.
This does not qualify PiP, free-band, captions, camera motion, creator listening,
or a complete two-hour workflow. Historical render proofs were not rewritten.
