# AAC peaks require an encoded-output check

The full C0679 cut on September 9, 2026 had an integrated level of −28.17 LUFS.
The shared full-program mastering path produced PCM at −14.18 LUFS and
−1.97 dBTP. That PCM met the current −14±1 LUFS / −1.5 dBTP delivery limits.
The subsequent AAC encode measured −14.19 LUFS and **−1.28 dBTP**, however:
encoding introduced enough peak overshoot to fail the unchanged ceiling.

Do not qualify a video from its pre-encode PCM measurement. Decode and measure
the complete AAC output, and keep failed candidates separate from the requested
output. This failure was caught after 225.983 seconds of admission, source-bus
preparation, mastering, delivery and checks; the failed AAC was not promoted.

The retained source bus and PCM master made recovery cheaper than another cut
or picture render. The trial derived a uniform attenuation from the observed
excess plus a small explicit margin:

```python
attenuation_db = ceil((peak_excess_db + 0.20) * 100) / 100
# observed excess 0.22 dB -> attenuation 0.42 dB
```

The predicted loudness remained within the existing tolerance. The correction
was applied to the complete retained **float PCM**, followed by one fresh AAC
encode; the rejected AAC was never used as the new audio source. The corrected
PCM and AAC were measured again. The final AAC passed at **−14.61 LUFS and
−1.86 dBTP**. All 16,394 picture packets were copied unchanged, and audio
presentation remained exactly 32,820,788 samples at 48 kHz. Recovery, including
strong input readback and all checks, took **142.696 seconds**.

A new versioned derivative receipt identified the exact parent master, failed
AAC measurement, gain, and resulting float bytes. The read path independently
recomputed the parent/filter PCM hash and compared it with the retained
derivative. This was not a re-labeling of an old ordinary-master receipt.

Do not apply this gain rule to missing/partial measurements, a decode failure,
a changed candidate, or a correction that would leave loudness outside target.
Do not lower the delivery standard just because the PCM had passed. A predicted
peak reduction is not qualification: the next actual AAC encode must pass.
The bounded trial script is not yet a general automatic recovery API. Cache
selection and future assembly must explicitly understand its derivative type.

Automated loudness, sample-clock and packet checks do not establish natural
speech timing, listening quality, engagement, or user approval. Native Studio
playback is a separate check from encoded media quality.
