# A transcription API key is not spending permission

The September 7, 2026 ASR policy correction separates a credential from the
user's permission to incur an API charge. This is a spending-admission change,
not an ASR accuracy or performance qualification.

## The defect

The previous shared provider resolver selected Deepgram unless local execution
or a local provider was explicitly configured. Ingest could discover a key in
environment files, and study/word-lock helpers treated a present key as enough
reason to use the paid worker. Consequently an ordinary CLI invocation could
upload audio and spend money without an affirmative choice for that invocation.

Four focused before-change provider checks had two failures in 0.11 seconds.
The failing evidence is retained at
`/private/tmp/sniper-asr-policy-before-20260907.log`.

## Current enforced boundary

`scripts/asr_policy.py` is the shared policy. An ordinary invocation now selects
`local-whisper`, even when a Deepgram key or a cloud execution setting exists.
An ambient `SNIPER_TRANSCRIBE_PROVIDER=deepgram` is rejected, not silently
honored. Malformed provider values also reject.

The preserved manual paid capability requires both exact CLI options:

```text
--provider deepgram --authorize-paid-asr deepgram
```

These options are only appropriate after explicit user authorization. They were
not used to invoke a real paid SDK during this work. The current user policy
does not authorize paid ASR. A key alone, a provider-only option, or a made-up
authorization environment variable cannot grant the capability.

The capability is scoped to the invocation and explicitly forwarded to child
workers as arguments. Actual paid call sites and the lazy SDK constructor check
the capability. Local children do not receive a Deepgram key. Ingest no longer
searches environment files for one. Missing local tools, failed local execution,
or rejected word timing never choose a paid fallback.

SEGMENTER and CLIPPER remain distinct workers. Their channel, diarization,
sample, and timestamp behavior was not merged. In particular, local CLIPPER
still requires separate lav inputs or genuinely isolated stereo video; this
change does not invent local diarization for mono/crosstalk audio.

## Evidence and limits

- The expanded regression cohort passed 91 tests in 32.00 seconds wall time:
  `/private/tmp/sniper-asr-policy-expanded-20260907.log`. It included an existing
  deterministic synthetic video/OCR fixture with an explicitly supplied TEST
  transcript, not an ASR/model/provider invocation.
- The final no-media cohort passed 49 tests in 1.45 seconds wall time:
  `/private/tmp/sniper-asr-policy-final-20260907.log`. Ten cases launched the
  actual SEGMENTER/CLIPPER entrypoints using the project virtual environment,
  nonexistent TEST inputs, and fake keys, with SDK imports, sockets, and
  media/model child creation actively blocked.
- The first expanded attempt had a test-only context-field typo, retained in
  `/private/tmp/sniper-asr-policy-focused-20260907.log`; its failure was not
  discarded or represented as a pass.
- All SDK-positive tests used in-memory stubs. No real credential, actual ASR
  model, paid provider, or creator footage was used to qualify this policy.

Existing source-binding and word-timing gates remain necessary. Existing
transcripts may still be reused under their existing authority contracts; this
spending change does not requalify them. It also does not enforce every other
service's billing policy or prove an end-to-end two-hour video workflow.
