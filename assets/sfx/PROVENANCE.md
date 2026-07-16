# assets/sfx — starter SFX pack provenance

Every file in this directory is **synthesized in-repo** by
`scripts/producer/audio/sfx_library.py build` — seeded ffmpeg pink-noise
sweeps (`anoisesrc` → three crossfaded bandpass taps, the same technique as
`motion/transitions.py`'s whoosh and the repo music beds) and deterministic
sine/chirp envelopes (`aevalsrc`). Builds are reproducible: noise sources are
seeded per asset (seeds in `sfx_library.PACK`), tone recipes are closed-form
expressions, and every asset is two-pass normalized to −15 dBFS peak
(`MOTION["transitions"]["sfx_peak_dbfs"]`, the measured transition-peak band).

**No third-party audio is vendored** — there is no upstream license to carry.
Network CC0 packs (e.g. Kenney) were deliberately skipped in favor of
synthesis: bit-reproducible, no attribution audit, zero fetch flakiness.
These files are original works of this repository and are released under
**CC0 1.0** (public domain dedication) so downstream renders carry no notice
obligation.

| file | family | recipe | hit lead | built |
|------|--------|--------|---------:|-------|
| `whoosh-soft.wav` | noise sweep | pink seed 1101, taps 1200→600→300 Hz, 0.55 s | 0.33 s | 2026-07-11 |
| `whoosh-hard.wav` | noise sweep | pink seed 1102, taps 2400→1100→480 Hz, 0.32 s | 0.20 s | 2026-07-11 |
| `swish-up.wav`    | noise sweep | pink seed 1103, taps 420→900→1900 Hz (rising), 0.42 s | 0.29 s | 2026-07-11 |
| `click.wav`       | tone | 2.4 kHz + 5.2 kHz sines, exp(−90 t) decay, 0.12 s | 0.01 s | 2026-07-11 |
| `pop.wav`         | tone | 660→140 Hz chirp, exp(−16 t) decay, 0.18 s | 0.01 s | 2026-07-11 |
| `thud.wav`        | tone | 85 Hz + 170 Hz sines, exp(−14 t) decay, 0.28 s | 0.01 s | 2026-07-11 |

"Hit lead" is `lead_s` in the catalog: seconds from file start to the
perceptual hit. The transitions renderer starts playback at `seam − lead_s`
so whooshes swell INTO the seam and clicks/pops land ON it.

Consumed by `motion/transitions.py` via the SFX slot vocabulary
(`transitions[].sfx: true | false | "<name>"`); names resolve through
`audio/sfx_library.resolve` (fail-loud, no fuzzy matching). Regenerate any
asset with `scripts/producer/audio/sfx_library.py build <name>`.
