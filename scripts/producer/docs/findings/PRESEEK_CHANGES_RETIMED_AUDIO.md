# Shorter pre-seek can change retimed audio

## Context

The cut stage uses a fast input seek followed by an accurate trim. Decoding less
pre-roll is an attractive speed improvement, particularly for long 4K sources.
The incremental revision plan proposed reducing the pre-seek pad from ten seconds
to two seconds while preserving the produced part bytes.

That claim needs separate picture and audio checks. Matching video packets do
not establish that an encoded part is identical.

## Experiment

`tests/test_cut_preseek_media.py` generates a 15-second HEVC/AAC source at both
30/1 and 30000/1001 fps. It runs the complete cut stage with these source spans:

| Start | End | Speed | Audio lead |
|---|---|---|---|
| 10.437 s | 11.157 s | 1.0 | 0 ms |
| 12.083 s | 12.983 s | 1.25 | 120 ms |
| 13.221 s | 14.413 s | 1.0 | 0 ms |

With an unconditional two-second pad, normal-speed parts matched their ten-second
counterparts byte for byte. The retimed part differed at both frame rates.
Separating the streams found matching encoded picture packets and different
decoded float PCM. This establishes a difference, not an audible defect.

For the 30/1 retimed part, both picture hashes were:

```
8fc77d162dc57e78e0d1318387fc62eb4cb31e982814c3decbc272bbf21cf2a8
```

Its decoded audio hashes were:

```
10-second pad: a5f394e8bce52331b19cf906b11a6c1bd0bdf9e47b4039bc1d05611810de7224
 2-second pad: b1d4db454b92543c4b3209eecdac9856a9b5214106ba51dc3babeb76d77858d1
```

The 30000/1001 fixture reproduced the same picture-match/audio-difference pattern.
The experiment did not isolate which decoder or retiming state caused it.

## Implemented boundary

Normal-speed segments use two seconds of pre-roll. Retimed segments retain at
least ten seconds:

```python
pad = PRESEEK_PAD_S if seg.speed == 1.0 else max(
    PRESEEK_PAD_S, RETIMED_PRESEEK_PAD_S,
)
```

With this policy, all six part hashes matched the ten-second baseline, including
the J-cut case. Each frame-rate fixture produced the expected 79 total frames.
The regression exercises actual encoded media rather than only generated argv.

## When not to generalize

These small fixtures do not qualify every codec, channel layout, retiming filter,
or decoder implementation. They do not measure a production 4K speedup, and they
do not make final mastering byte-deterministic. Keep full output review.
Do not shorten retimed pre-roll solely because picture hashes match.

Re-run the fixture when changing the cut filter graph or supported media tools.
Further retimed optimization needs evidence for the full audio path and source
families it will admit, followed by a representative performance measurement.
