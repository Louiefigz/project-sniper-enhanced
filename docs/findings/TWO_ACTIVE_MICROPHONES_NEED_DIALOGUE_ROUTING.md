# Two active microphones need a dialogue-routing decision

IMG_7138 contained two live microphones: Aaron on the right and Trevor on the
left. Only Aaron stayed on camera. A generic dead-channel repair was insufficient:
both channels contained real signal, so neither qualified as a dead channel.
The first 44-second native export failed the shared audio check because multiple
100 ms intervals differed by more than 12 dB between the ears.

For these five dialogue edits, a local preparation step reused
`ChannelAuthority.filter_for('mono')`. It wrote 48 kHz lossless ALAC dialogue while
copying the video packets. All 57,077 coded picture packets and their rational
presentation timestamps matched the original. The ordinary native delivery path
then duplicated the mono dialogue into both output channels and applied its
existing voice cleanup and mastering. No rendering or audio quality gate changed.

The first successful final export, the 26.60-second pricing Short, measured
−17.0 dBFS on both output channels. All 267 interval checks passed, including the
last partial interval. Its three dialogue sections measured −17.1, −15.1 and
−15.6 dBFS in the existing speech-band energy check. Those measurements are energy
observations, not speaker-separated loudness measurements or proof of natural
delivery. Normal-speed listening remains necessary.

The preparation receipt and final checks are in
`artifacts/img7138-strongest-shorts-2026-09-14/source-centered-receipt.json` and
`export-03-v4/checks.json` under that artifact directory. The original upload is
unchanged. The prepared asset's provenance identifies the local transformation.

## Apply the decision before delivery

Identify whether channels represent spatial stereo or separate dialogue mics.
Record who owns each mic and who is visible. Decide which voices belong in each
retained passage; do not infer the speaker merely from the camera framing. A
quiet off-camera reply may need a label and an editorial level adjustment if it
is retained. The final point-of-view edit instead removed that interjection and
a repeated explanation, so it needed neither.

Do not indiscriminately collapse music, intentional stereo ambience, or all
multi-mic recordings. Delayed bleed and phase cancellation can require choosing
or aligning the relevant microphone rather than averaging both. This batch is
an explicit editorial preparation using shared code, not a new claim that the
automatic workflow can make every multi-mic decision by itself.

## Centering and noise cleanup are separate decisions

The fifth retained edit passed all431 channel intervals and all six dialogue
sections but failed the unchanged narrow-tone gate at182Hz. A fixed181Hz
component also remained in quieter intervals while the main voice frequencies
varied. On the same35.5–36.0s output interval, the mastered `voice` candidate
measured about−40.3dBFS at181Hz. The installed shared `voice-rnn` preset reduced
that component to−54.4dBFS (about14.1dB) and passed the complete encoded audio
checks at−14.06LUFS and−2.37dBTP. The supervised comparison took19.91seconds.

This justified a source-specific cleanup revision for that edit. It does not
make RNNoise a mandatory preset for every recording, and it does not establish
perceptual quality without listening. A low-frequency detector can also flag a
steady voiced fundamental: inspect the interval and preserve the original; do
not notch out voice frequencies merely to obtain a passing score.

Comparison evidence: `artifacts/img7138-strongest-shorts-2026-09-14/05-hum-diagnosis.json`
and `audio-comparison-05-rnn-v2` beneath that artifact root. The shared cleanup
processor preserves the exact sample clock and pins the installed model.

## September15 review: centered audio can still carry the wrong microphone

The user identified blender noise in the24-second AI-editor Short. The prior
mono preparation centered both microphones together; a balanced final mix did
not establish that the intended voice was clean. Inspecting the original1733–1742
interval at matched speech level showed a useful improvement before stronger
noise processing: Aaron’s right microphone alone reduced quieter-window energy
from−43.16 to−54.06dBFS, approximately10.9dB, versus the two-microphone mix.

These were the same9seconds and the same active-voice matching mask, with shared
voice cleanup. They measure contamination reduction, not isolated blender energy
or subjective listening quality. The one replacement Short therefore uses the
right microphone and ordinary voice cleanup. The original picture packets and
exact rational times remain identical; only the dialogue routing changed.

Evidence: `artifacts/img7138-journey-shorts-2026-09-15/revision-audit-01/editor-mic-comparison-v2/COMPARISON.json`
and `artifacts/img7138-editor-visual-short-2026-09-15/source-aaron-right-receipt.json`.
Do not select the right channel by convention in another recording. Identify
whose microphone and intended speech each channel actually contains first.
