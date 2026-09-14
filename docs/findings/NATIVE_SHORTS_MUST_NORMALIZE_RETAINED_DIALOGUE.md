# Normalize retained dialogue before mastering a native Short

Measured locally on September 13, 2026. These results qualify two audio paths
for one 38.64-second Short; they do not establish listening approval or a
completed video export.

## The missing shared step

The native Short route preserved a stereo recording with nearly silent audio
on the left and dialogue on the right. Its float master passed loudness and
true-peak checks, but the encoded AAC exceeded the delivery peak ceiling.
Signal similarity alone could not catch the channel problem: preserving an
unbalanced reference faithfully still preserves one-ear dialogue.

Long-form already has a content-bound channel policy for this recording
pattern. Native Shorts now reuse that policy on the **retained lossless
dialogue**, before loudness measurement and mastering. Observing the 38.64
seconds actually retained avoids an unnecessary scan of the full recording
and binds the decision to the sound that will be delivered.

The shared policy detected dead channel 0 and live channel 1. It selected:

```text
pan=stereo|c0=c1|c1=c1
```

This filter is the measured decision for this input, not a hardcoded preference
for the right channel. The sealed authority is verified before use. The
[channel receipt](../../artifacts/native-short-storytelling-2026-09-13/audio-regression-01/normalized-dialogue/channel-normalization.json)
records the actual filter, input hash before and after processing, output hash
and both float clocks. Both files retain exactly **1,854,720 samples at 48 kHz**,
two channels, start PTS zero and time base `1/48000`.

Channel normalization precedes mastering because the chosen channel layout
changes the program's measured energy. Reusing the long-form policy makes that
decision consistently before the shared master algorithm chooses gain and
limiting. The normalized float hash also becomes the mastering input identity;
an AAC donor made from the old unbalanced reference cannot silently qualify as
the same input.

## What the supervised regression measured

The [owner receipt](../../artifacts/native-short-storytelling-2026-09-13/audio-regression-01/inspection.render.json)
reports **44.490443 seconds** for both cases, successful exit and verified
cleanup with no recorded survivors. Individual audio-finishing times below
exclude the outer setup and channel-normalization work.

| Input and candidate | Internal peak target | Decoded AAC loudness | Decoded AAC true peak | Result |
| --- | ---: | ---: | ---: | --- |
| Normalized dialogue, first candidate | −2.5 dBTP | −14.09 LUFS | −2.38 dBTP | Pass |
| Raw unbalanced regression, first candidate | −2.5 dBTP | −14.42 LUFS | −0.65 dBTP | Peak failure |
| Raw unbalanced regression, second candidate | −3.6 dBTP | −14.82 LUFS | −3.19 dBTP | Pass |

The [normalized case](../../artifacts/native-short-storytelling-2026-09-13/audio-regression-01/normalized-dialogue/audio/receipt.json)
finished in **13.866019 seconds**, with one AAC encode and the original
`native-short-v1` profile. The
[unbalanced codec regression](../../artifacts/native-short-storytelling-2026-09-13/audio-regression-01/unbalanced-codec-regression/audio/receipt.json)
took **29.361146 seconds** and two candidate encodes. Its first encode reproduced
the failure, then the bounded peak correction qualified the second candidate.
This comparison supports the channel fix and exercises the separate codec
defense; it does not prove that every unbalanced input causes AAC overshoot.

Both selected outputs passed the actual float-master, local signal, exact
sample and packet clock, copied-picture and decoded AAC checks. The picture
packets remained identical, with zero picture encodes. The
[results record](../../artifacts/native-short-storytelling-2026-09-13/audio-regression-01/results.json)
explicitly states that listening was not performed.

## Keep codec correction separate and bounded

The final delivery requirements remain **−14 LUFS ±1 LU** and **at most −1.5
dBTP**, with complete decode and all existing signal, clock, picture and input
stability checks. Passing the float master cannot substitute for measuring the
encoded AAC.

Only a fully decoded candidate that passes loudness and every other gate may
request a true-peak correction. The next internal target subtracts the measured
peak excess and a 0.25 dB margin. In the regression, the 0.85 dB excess changed
the internal target from −2.5 to −3.6 dBTP. There are at most three candidates,
with a −9 dBTP internal lower bound and the original owner deadline unchanged.
Any other failed gate terminates the path.

Every candidate starts from the same unchanged lossless premaster through the
shared mastering algorithm, then receives one AAC encode. No candidate is
encoded from a rejected AAC file. Receipts distinguish total encoder
invocations from the selected output's single AAC generation. They also retain
the originally requested profile separately from each effective candidate
profile. Reuse reconstructs the effective profile from the recorded measured
failures and verifies the full settings and hashes; a matching label is
insufficient.

## When not to force channel repair

Do not duplicate a channel merely because stereo levels differ. The shared
policy requires a dead-channel peak below −50 dBFS, a live-channel peak at least
−50 dBFS and a difference of at least 25 dB for this repair. Valid stereo stays
stereo. Mono and multichannel inputs follow the existing shared conversion
policy. Missing, stale or invalid authority must fail instead of guessing
which channel contains the intended program. This policy is not semantic
speaker identification or a substitute for listening to ambiguous material.

The implementation reuses
[channel normalization](../../scripts/producer/audio/channel_normalization.py),
[sealed channel receipts](../../scripts/producer/audio/channel_normalization_receipt.py)
and shared float mastering from
[native dialogue delivery](../../scripts/producer/audio/native_dialogue_delivery.py).
The retained-reference integration lives in
[native Short delivery](../../scripts/producer/studio/native_short_delivery.py),
with the separate bounded policy in
[AAC peak candidates](../../scripts/producer/audio/aac_peak_candidates.py).
Thirty-two focused tests passed, covering profile compatibility, candidate
bounds, failed gates, mutation detection, effective-profile reuse, both possible
dead channels and unchanged stereo. Independent review approved the change
before the supervised media regression. These checks establish processing
behavior and measured fidelity; human listening remains a separate review.
