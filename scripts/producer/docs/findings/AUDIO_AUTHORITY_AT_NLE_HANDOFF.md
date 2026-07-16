# Audio authority at an NLE handoff

## Finding

An NLE export can have acceptable integrated loudness and still sound broken.
The C0679 Palmier export measured **−21.1 LUFS** yet clipped at **+0.3 dBTP**,
carried a persistent low drone, and ended on an unfaded music tile. Its picture
was useful; its audio mix was not a safe delivery authority.

The in-house render measured **−14.1 LUFS / −1.8 dBTP**, but its selected
starter bed was also unsuitable: almost all of that asset's energy sits at
**110, 165, and 220 Hz**. The rendered-audio gate found a stable **111 Hz**
line with **23.7 dB** prominence. Turning this track down made it quieter, not
less recognizable as hum.

## Root cause

Palmier received the raw camera clip and a tiled music asset. The exported bed
was essentially as loud as the source asset even though the editable timeline
reported a linear volume of `0.282`. The handoff also bypassed the in-house
dead-channel repair, `audioEnhance`, gain windows, sidechain ducking, two-pass
loudness master, bed crossfades, and end fade.

This created two competing audio implementations. Whichever one exported last
silently won.

## Rule: one delivery audio authority

Palmier is the picture authority. The in-house `final.mp4` is the audio
authority. A Palmier export is staged, then:

1. stream-copy Palmier's video packets;
2. replace its entire audio mix with the in-house master;
3. pad/trim audio to the frame-derived picture duration;
4. apply a 20 ms end de-click fade;
5. encode AAC 48 kHz stereo at 256 kbps;
6. reject the stage unless loudness, true peak, A/V endpoints, channel balance,
   sustained low-frequency tone, and ending dominance all pass;
7. only then atomically replace the prior `final.palmier.mp4`.

The Palmier timeline intentionally keeps music preview-silent. Music remains in
the in-house bus, where `gapDb` is measurable, sidechain ducking exists, and a
bad bed cannot bypass Audit B.

## Voice and music policy

- Produced longform defaults to the measured `voice` cleanup preset.
- On C0679, that preset improved quiet-window SNR from **40.94 dB to 46.57 dB**
  while preserving speech better than the RNNoise preset on this steady room
  noise.
- A declared music rest gap must be at least **3 dB** below dialogue; the normal
  mixer target remains about **11 dB** below at rest and **18–20 dB** below
  during speech.
- `duck:false` is rejected whenever the input carries dialogue; a rest-level
  integrated gap alone cannot protect a quiet phrase from the bed.
- Transition SFX are silent unless the plan explicitly opts in. Sparse,
  justified effects may remain; routine seams do not get automatic whooshes.
- A sustained tonal bed that reads as hum is rejected even if global LUFS is
  otherwise correct.

## Verification on the repaired C0679 delivery

The repaired Palmier-picture/clean-dialogue output measured:

- **−14.0 LUFS** integrated;
- **−1.9 dBTP** true peak;
- **0.000 s** A/V endpoint skew;
- **0.00 dB** stereo RMS imbalance;
- no sustained tonal-hum failure (strongest candidate: 202 Hz, 12.5 dB
  prominence, stable only 2% / 1.0 s).

The original Palmier export still fails the same gate at 110 Hz, 40.7 dB
prominence, stable 100% for an 80.5 s run. That before/after pair is the golden
real-output regression.

## Tests

```bash
.venv/bin/python scripts/producer/tests/test_audio_enhance_render.py
.venv/bin/python scripts/producer/tests/test_audio_mix_render.py
.venv/bin/python scripts/producer/tests/test_audio_quality.py
.venv/bin/python scripts/producer/tests/test_palmier_audio_finish.py
.venv/bin/python scripts/producer/tests/test_palmier_export.py
```

## When not to use this pattern

Do not replace NLE audio when an operator intentionally mixed or repaired sound
inside the NLE and that NLE mix is the declared authority. In that workflow,
export a single mastered stem from the NLE and run the same rendered-audio QC
over it. Never merge two independently mastered mixes or assume container LUFS
proves that voice, music, hum, channels, and the final tail are correct.
