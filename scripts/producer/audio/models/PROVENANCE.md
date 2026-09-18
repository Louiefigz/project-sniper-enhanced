# audio/models — vendored model provenance

## bd.rnnn (RNNoise "beguiling-drafter", 2018-08-30)

- Source: https://github.com/GregorR/rnnoise-models
  (`beguiling-drafter-2018-08-30/bd.rnnn`, vendored 2026-07-09, 299,693 bytes,
  header `rnnoise-nu model file version 1`).
- SHA-256: `ae3f7411e1e6a884f839a4a145c394408398f09854dbc1216ee02faafc98a17b`
  (verified before immutable pipeline capture; a mismatch fails closed).
- Trained for **voice over recording noise** (the repo's signal/noise matrix) —
  the right cell for talking-head camera footage. "Voice" includes non-speech
  human sounds (laughter), unlike the stricter "speech" models.
- Licensing: upstream README states "none of this work is creative and thus
  none of it is subject to copyright" (models are explicitly not copyrighted;
  only the repo's `tools/` directory carries a license). `README.upstream.md`
  is the verbatim upstream README kept alongside as the record.
- Consumed by `producer_config.AUDIO_ENHANCE["voice-rnn"]` via ffmpeg's
  `arnndn` filter; `audio/audio_enhance.build_filter` substitutes the
  `{models}` token with this directory's absolute path.
