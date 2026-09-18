# Cleanup filters delay the signal and drop their tail: measure, pad, then trim

**Date:** 2026-09-08. **Where it bit:** source-float-v2 audio finishing (`audio/program_finish_bus.py`),
confirmed independently by the Codex reviewer before integration.

## The lesson

An ffmpeg "denoise" chain is not a per-sample gain. `afftdn` works on FFT blocks and `arnndn`
(RNNoise) on 480-sample frames, so their output is a delayed copy of the input, and at end of input
they do NOT flush the delayed part. Two consequences that length checks never catch:

1. **Everything comes out late.** Measured on FFmpeg 8.0 with a single-sample click: the catalog
   `voice` / `voice-strong` chains arrive 1200 samples (25 ms) late, `voice-rnn` 480 samples (10 ms)
   late. The sample COUNT is unchanged, so `-shortest`, duration probes and "audio == video length"
   assertions all pass while every word sits 25 ms behind the picture.
2. **Removing the delay silences the tail.** If you trim the leading delay to re-align the audio and
   pad the end back to the original length, the last 1200 (or 480) samples are now padding, because
   the filter never emitted the processed version of those source samples. Interior checks pass;
   the final syllable of the program is gone.

## The fix that is actually correct

```
apad=pad_len=<latency + guard>, <cleanup chain>, atrim=start_sample=<latency>, asetpts=N/SR/TB,
apad=whole_len=N, atrim=end_sample=N
```

Pad the INPUT by the measured delay (plus a guard, 4800 samples here, so block-based filters never
see end-of-input inside the program range), run the chain, then drop the leading delay and pin the
exact original sample count. The result is bit-exact against an oracle that runs the same chain on
the program padded far past its delay: whole-program max error 0.0 for all three chains, tail
impulses at N-900 and N-300 survive, and the unpadded control reproduces the defect (afftdn:
digital silence in the last 1200 samples; RNNoise: a wrong partial block).

Measure the delay per exact chain at run time (`measure_chain_latency`: a click at one second through
the chain, locate the peak) and record it in the receipt; do not hard-code 1200. A different FFmpeg
build, model or preset changes it, and the click going missing is itself a loud failure.

## Why "measure, don't assume" matters here

The guard was needed even after the obvious fix: padding by exactly the delay left a ~2e-5 artifact
in RNNoise's last frame because the end of input fell inside a partial block. Only the oracle
comparison over the whole program surfaced it.

## When not to use this

- Zero-latency filters (`volume`, `highpass`, `equalizer`, `acompressor` without lookahead) need
  none of this; the probe reports lag 0 and the padding is harmless but pointless.
- Do not apply the trick to the legacy `audio_enhance.py` stage as a quick patch: that path
  re-encodes AAC per stage and its 25 ms delay is a separate, reported issue; the source-float path
  keeps float and fixes it where the audio is actually finished.

Regression: `scripts/producer/tests/test_program_finish_media.py::test_01`, `::test_01b`, `::test_01c`.
