# DC offset is not background noise

The ten-minute Sniper qualification recording transcribed successfully, but its
silence measurement refused to run. The detector measured a noise floor of
−51.17 dBFS and a median frame of −46.24 dBFS. Its floor-plus-8 dB gate was
−43.17 dBFS, above much of the speech. Refusal correctly prevented unsafe cuts.

The cause was a constant electrical bias, not just a quiet voice. Both channels
had a mean sample value near −0.0027. That offset alone contributes about
−51.4 dBFS to ordinary RMS. The detector was counting it as acoustic energy.
The channels' correlation was −0.014; this was not an anti-phase cancellation
problem that selecting one channel would fix.

## Correct measurement, same guards

The shared measurement now subtracts one mean across the decoded recording
before computing its 20 ms frame RMS:

```python
samples = samples.astype("float64") - np.mean(samples, dtype="float64")
frames = samples[:usable].reshape(-1, size)
rms = np.sqrt(np.maximum((frames ** 2).mean(axis=1), 1e-20))
```

This changes the diagnostic signal only. It does not modify the source file,
apply gain to the delivery audio, lower a threshold, or rewrite transcript words.
The cut applier and gate still share the same measurement, hysteresis, peak and
containment requirements. Subtracting a different mean in each frame could
remove meaningful changing low-frequency energy; that is not this operation.

| Measurement on the actual source | Before | After |
|---|---:|---:|
| Tenth-percentile floor | −51.17 dBFS | −64.69 dBFS |
| Median frame | −46.24 dBFS | −47.84 dBFS |
| Gate after the existing clamp | −43.17 dBFS | −55 dBFS |
| Median clears gate plus 3 dB | No | Yes |

The corrected measurement found 349 silence runs totalling 143.16 seconds.
That is diagnostic evidence, not a recommendation to delete all of those runs.
It also found 105 of 1,699 approximate ASR word windows wholly inside measured
silence. Those mismatches require source-aware editorial review; ASR timing is
not a ground-truth record of where each syllable occurred.

## Verification and limits

Real WAV regressions compare the same quiet speech and pauses with and without
a −0.0027 bias. Their silence spans and gates match, the real pause qualifies,
and the quiet spoken interval does not. A low-signal recording still refuses
after bias removal; a constant DC signal also refuses. The existing inward-only
word refinement and word-safety tests remain in place.

Do not use DC removal as permission to force a noisy recording through a gate.
It does not solve microphone noise, changing hum, clipping, missing audio or
bad ASR alignment. The Short qualification source still has a separate trailing
word timing error. A provenance flag now reports whether all words actually fit
inside the audio endpoint instead of claiming an endpoint clamp unconditionally.

Evidence: `outputs/project-sniper-release-rc4-2026-09-18/evidence/final/`
`realedits/run-55902aa/longform-{channel-diagnosis,dc-investigation,dc-measurement}.json`.
The actual source SHA-256 is
`07e3279f909e6555b78fa68995b48d300c67be02efe6eba302b9996181e1f55e`.
Source correction tests are in `37-dc-speech-edges.log`; the cut integration
checks are in `38-dc-cut-integration.log`. These do not establish listening or
approval of a finished long-form edit.
