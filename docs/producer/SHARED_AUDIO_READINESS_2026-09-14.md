# Shared audio cleanup and qualification — 2026-09-14

Long form and native Shorts now share dialogue cleanup/gain processing and
rendered-audio diagnostics. The offer Short has a technically qualified RNNoise
revision. After the comparison controls were clarified, Aaron said the cleaned
sample sounded great. This records positive listening feedback on that sample;
full editorial review and two brief historical long-form channel flags remain
open. This is not a claim that every recording is free of echo or that technical
measurements establish professional listening quality.

Review: [original/cleaned comparison and long-form moments](http://127.0.0.1:4001/).
The original video files and the earlier style-review page are preserved.

## Implementation and reuse

- `audio/dialogue_cleanup.py` extracts the existing source-float-v2 processor.
  Both routes use its same preset chain, latency probe, tail flushing, 50 ms
  gain-window ramps and exact 48 kHz stereo float clock. No copied Shorts DSP.
- `audio/native_audio_finishing.py` adapts the native decision to the existing
  `finishing_request` and gain parser. It records source/model/output hashes,
  settings, removed latency and output clock. Installed presets are `voice`,
  `voice-strong` and `voice-rnn`; no runtime model downloads are implicit.
- `SHORT-PROJECT.json.audioFinishing` is validated by the real writer and cold
  reader. Enhancement must match the prepared app request; unavailable or
  silently omitted processing fails. Audio analysis is now an explicit request
  stage and part of shared Shorts editorial instructions.
- Audit B and native AAC qualification call the same `check_audio_quality`.
  It checks stream timing, channels, local channel intervals, hum and declared
  section energy. Existing whole-program LUFS/true-peak qualification remains.
- Fresh and reused AAC both run current checks. The code uses Audit B's actual
  `FAIL`/`WARN` constants, not new string spellings. A regression explicitly
  proves a donor's earlier pass cannot bypass a current failed assessment.
- Final native results surface `audioQuality` and `audioReviewRequired`. Checks
  and model files are included in export input pins. No publishing or hearing
  approval follows from a passing technical result.

Ordinary long-form defaults remain `legacy-v1`; this change does not silently
roll out source-float-v2 or change legacy codec settings. Legacy cleanup already
uses the shared preset definitions; the extracted sample-exact execution path
serves explicit source-float-v2 and native Shorts. Both long-form execution paths
receive the shared Audit B diagnostics.

## Actual retained-media results

All complete files below were decoded and measured, including the 839.964125 s
long-form export. Inspection times exclude planning, ingest and picture rendering.

| File | Duration | LUFS / true peak | Result | Inspection time |
|---|---:|---|---|---:|
| Original offer | 24.52 s | −14.10 / −2.46 dBTP | Channels/sections pass; sustained 62 Hz hum at −44.8 dBFS | 0.93 s |
| Member full-stage | 8.24 s | −14.04 / −2.49 dBTP | Technical gates pass; one section, so cross-clip comparison unavailable | 0.40 s |
| AI corrected story | 38.64 s | −14.09 / −2.38 dBTP | Channels, three sections, hum and timing pass | 1.39 s |
| Retained 14-minute long | 839.964125 s | −14.15 / −1.70 dBTP | Two 100 ms channel flags; global balance, declared sections and hum pass | 26.14 s |

The long-form flags are at 77.400–77.500 s (L −53.51 / R −40.99 dBFS) and
165.900–166.000 s (L −37.71 / R −50.27 dBFS). Exact measurements match the retained
`base_final.mp4`; no new source or cause is inferred. They remain flagged. Do not
flatten or pan the entire recording to clear two low-level intervals without
listening to them. The comparison page provides three-second contexts.

All three installed cleanup presets were actually run on the offer's retained
normalized dialogue, followed by shared mastering and AAC. The `voice` and
`voice-strong` results still had hum findings. `voice-rnn` passed all shared
checks: −14.10 LUFS, −2.49 dBTP, 10 measured cut sections and exact 24.52 s duration.
Its cleanup + fresh delivery took 6.82 s. Picture was copied, not rendered again.

The chosen result was requalified under the corrected final failure gate, then
received the existing sRGB metadata correction with identical AAC and picture
slice payload. It is `artifacts/shared-audio-2026-09-14/review-02/review.mp4`.
This final requalification plus both complete long-form interval inspections
took 9.52 s. These are audio-stage timings, not end-to-end edit timings.

## Open-source evaluation

The existing [RNNoise implementation](https://github.com/xiph/rnnoise) and local
vendored model provided the successful noise-reduction candidate. Reusing it
avoided introducing another noise-reduction runtime.

[NARA-WPE 0.0.11](https://pypi.org/project/nara-wpe/) is a separate MIT-licensed
weighted-prediction dereverberation option. Its 34.6 KB wheel and Click 8.1.8 were
downloaded to an isolated artifact folder. The NARA wheel matches PyPI SHA256
`ce5f51478da5fa87925c85b8f5fecc784d2b4775488ada64e7b36099d3438711`.
No project dependency installation, model-weight download, Torch or TensorFlow
was needed. It imported and executed on the project's Python 3.14.4.

The experiment used upstream NumPy WPE independently on each real channel,
1536-sample STFT / 384-sample hop, 10 taps, delay 3 and three iterations. The
inverse transform reconstructed the original clock within numerical precision;
processed output retained every required sample. This is execution/clock
evidence, not proof of better voice quality or echo removal. It did not remove
the offer's hum. It remains a labeled research comparison, not a production
preset. [Upstream algorithm](https://github.com/fgnt/nara_wpe/blob/master/nara_wpe/wpe.py),
[transform implementation](https://github.com/fgnt/nara_wpe/blob/master/nara_wpe/utils.py).

[DeepFilterNet](https://github.com/Rikorose/DeepFilterNet) remains an alternative
denoiser to compare if RNNoise is insufficient. Its code offers MIT/Apache-2.0
licensing; model provenance and delay compensation still need binding before
adoption. It was researched, not installed or tested in this pass.
[Resemble Enhance](https://github.com/resemble-ai/resemble-enhance) was researched
but not installed: its larger reconstruction runtime is unnecessary for the
hum fix and would need separate voice-fidelity and performance evaluation.

## Verification and limits

96 distinct Python tests passed across focused runs: shared finishing contract,
real cleanup/gain/media, final AAC, donor reuse/failure, source-byte mutation,
channel intervals, malformed/nonfinite clocks and level-change controls. The
larger first completed suite exposed two stale legacy-donor test assumptions;
the updated seven-test native media suite passed. The final 52-test fast suite
also passed, including changed-master failure precedence. Type-check, focused
ESLint and 44 TypeScript request/project/strategy tests passed.

Initial supervised test attempts stopped on incomplete macOS process-footprint
samples during rapidly exiting test processes. The completed synthetic suites
used a 150 ms idle interval after process waits, with the same resource limits.
Their duration is not a production benchmark. Actual retained-media processing
used no such pacing. Resource receipts retain the failures and verified cleanup.

The comparison page was visually inspected. Separate orange Original and green Cleaned players loaded
the exact 24.52 s files; each has a permanent label and its own play/pause control.
Playing either version paused the other; the long-form button sought to the requested context.
This verifies playback behavior, not hearing. No private audio/transcript was
sent to an external model or service, and no paid service was invoked.

Section energy is 120–3400 Hz active signal energy, not LUFS or semantic speech
detection. It can include music/noise. Native sections follow the executed
frame-to-sample cut clock; long-form sections are declared picture-cut intervals,
which do not establish spoken boundaries for J-cuts or quantized legacy edits.
These checks do not automatically diagnose de-essing, clipping already present
in the source, lip-sync content, reverberation severity or perceptual artifacts.
Background music/SFX integration for native Shorts is still outside this audio
delivery path. A source-specific listening pass remains required.

Evidence lives in `artifacts/shared-audio-2026-09-14/`: discovery metrics in
`evaluation-01`, current chosen-result proof in `review-02`, regression logs and
receipts in `tests-04` and `tests-native-05`, and the exact-file review manifest.
