# AAC noise substitution must pass local fidelity checks

Measured locally on September 13, 2026. A native Short exposed an AAC failure
that whole-program signal averages concealed. Disabling perceptual noise
substitution (PNS) qualified the unchanged master without relaxing any gate.

## What failed and what isolated it

The 24.52-second offer Short's float master passed at −14.08 LUFS and −2.50
dBTP. Its AAC passed the exact presentation and packet clocks, but the first
0–1 second left-channel window had **16.151 dB SNR**, below the 20 dB floor.
The right channel measured 38.293 dB; all other 48 windows passed. Global SNR
was 28.847 dB, so a whole-file average would have missed the local failure.

The [controlled diagnostic](../../artifacts/shorts-workflow-completion-2026-09-13/aac-diagnostic-02/results.json)
encoded the exact retained master with the same 320k bitrate, sample filter,
stereo output and copied picture. Only the indicated encoder option changed:

| AAC options | Minimum active-window SNR | Global SNR | Decoded loudness | Decoded true peak |
| --- | ---: | ---: | ---: | ---: |
| Defaults | 16.151 dB, fail | 28.847 dB | −14.09 LUFS | +1.16 dBTP, fail |
| `-aac_ms 0` | 33.287 dB, pass | 39.971 dB | −14.10 LUFS | −2.38 dBTP |
| `-aac_pns 0` | 32.227 dB, pass | 42.182 dB | −14.10 LUFS | −2.46 dBTP |

With PNS disabled, the first left/right windows measured 32.227/36.139 dB.
Both alternatives passed every unchanged signal and delivery gate. PNS off
provided the highest global fidelity of these options while retaining the
encoder's default mid/side behavior. The baseline reproduced the original
signal failure exactly. All three retained **1,176,960 presented samples at
48 kHz**, with 1,024 priming samples accounted for by packet metadata and 640
trailing decoder-padding samples reported separately.

This isolates an encoder-option-sensitive failure on the retained input. It
does not establish that every PNS encode fails, that a persistent sample offset
caused this failure, or that these measurements prove perceptual superiority.
The [diagnostic owner](../../artifacts/shorts-workflow-completion-2026-09-13/aac-diagnostic-02/inspection.render.json)
completed in 7.854847 seconds with verified cleanup and no recorded survivors.

## The native policy and its reuse boundary

[Native AAC encoding](../../scripts/producer/audio/native_aac_encoding.py) now
provides the exact argument vector consumed by
[native dialogue delivery](../../scripts/producer/audio/native_dialogue_delivery.py):

```text
-c:a aac -b:a 320k -ar 48000 -ac 2 -aac_pns 0
```

The vector is recorded in `aacEncodingPolicy` for the actual candidate encode
and final receipt. Unspecified encoder options remain tied to the owner's
pinned FFmpeg binary. Shared mastering, channel authority, sample filters,
picture copying and clocks remain unchanged. Ordinary long-form defaults were
not changed without their own qualification.

Donor reuse requires the exact current policy at the top level and in every
recorded candidate. **A historical donor missing `aacEncodingPolicy` is
rejected even under `--audio-profile default-v3`.** A matching mastering name,
bitrate or formerly passing receipt cannot substitute for the consumed encoder
options. Generate fresh audio; a completed picture can still be reused when
its independent dependency and cleanup checks pass. Do not patch old receipts
to assert that different encoder settings were used.

Signal failure remains terminal and retains the failed files. It does not
trigger an encoder-option search or the existing peak-only correction loop.
Final gates remain −14 LUFS ±1 LU, at most −1.5 dBTP, local active-window SNR
at least 20 dB, and all existing signal, clock, decode and stability checks.

## Actual regression and completed export

The [production-path regression](../../artifacts/shorts-workflow-completion-2026-09-13/audio-policy-regression-01/results.json)
qualified both real sources on their first AAC candidate:

| Source | Exact samples | Signal windows | Global SNR | LUFS / dBTP | Audio-finishing time |
| --- | ---: | ---: | ---: | ---: | ---: |
| Stereo offer | 1,176,960 | 49, all pass | 42.182 dB | −14.10 / −2.46 | 7.039624 s |
| Normalized Claude dialogue | 1,854,720 | 77, all pass | 37.793 dB | −14.09 / −2.38 | 14.217957 s |

Each used one AAC encode and zero picture encodes. The
[regression owner](../../artifacts/shorts-workflow-completion-2026-09-13/audio-policy-regression-01/inspection.render.json)
completed in 21.964071 seconds with verified cleanup. The subsequent
[saved offer export](../../artifacts/shorts-workflow-completion-2026-09-13/saved-offer-export-02/pipeline.render.json)
completed final QC and cleanup in **35.151962 seconds**, using its verified
picture donor and newly encoded audio. Its
[checks](../../artifacts/shorts-workflow-completion-2026-09-13/saved-offer-export-02/checks.json)
report 272 picture frames checked, complete audio/video decode, zero additional
picture encodes and zero provider calls. This time excludes the earlier
picture-render cost.

The following focused command passed **55 tests**, including five new tests
for consumed options, stale and altered donor policies, candidate histories,
unchanged shared settings and terminal signal failure:

```bash
PYTHONPATH=scripts/producer/tests:scripts/producer:scripts \
  .venv/bin/python -B -m unittest \
  test_native_aac_encoding test_native_aac_peak_candidates \
  test_native_dialogue_channels test_native_dialogue_profile \
  test_mastering_profiles test_native_short_runtime \
  test_program_delivery_signal test_program_delivery_budget
```

Independent review approved the patch before supervised qualification. AST
syntax, file/function/parameter bounds and production nesting checks passed;
ruff, flake8 and black were unavailable. The receipts explicitly retain
`humanListeningApproved: false`. This evidence establishes the measured
processing and delivery behavior, not human listening approval.
