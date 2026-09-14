# An accurate encode can preserve bad audio

The offer Short measured −14.10 LUFS and −2.46 dBTP, with correct timing,
balanced channels and a waveform matching its intended master. It still had a
62 Hz hum at −44.8 dBFS that remained stable for 6.5 seconds. Signal fidelity
proved that the encode preserved the master; it did not prove that the master
was clean.

Moving the existing long-form hum/channel checks into the native final-output
gate exposed the problem. Running the three installed cleanup presets showed
that the lighter chains retained a hum finding; the existing RNNoise preset
passed. Its cleanup and AAC delivery took 6.82 seconds for a 24.52-second Short,
with no picture re-render and unchanged target loudness.

Reuse both the DSP and the quality contract. A new adapter compared the status
to `"FAIL"` while Audit B emits `FAIL = "fail"`. Importing `FAIL`/`WARN` from the
shared module fixed the gate. A regression now injects a failed assessment into
both fresh and donor reuse paths and verifies a retained failed receipt.

Whole-program channel averages are also insufficient: alternating left/right
faults can cancel. Local windows reveal them, including the final partial
window. A 14-minute historical export had two quiet 100 ms imbalances at 77.4
and 165.9 seconds despite passing global balance. They remain flagged for
listening; a numeric flag alone does not justify flattening all audio.

Do not use spectral-energy changes as semantic speech detection, treat all
whispers as bad levels, or claim denoising proves dereverberation. Preserve the
original, compare at matched loudness and keep listening judgments separate
from clock, codec and measurement evidence.
