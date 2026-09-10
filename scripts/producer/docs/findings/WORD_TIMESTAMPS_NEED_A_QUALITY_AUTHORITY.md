# Word timestamps need a quality authority

## Assertion

A transcript can have valid JSON, valid media lineage, and the expected ASR
runtime/model/settings while still being unsafe for karaoke captions or
word-safe cuts. Source authority proves *which bytes were transcribed*; it does
not prove that the returned word timings are usable.

## Incident

Two local Whisper runs processed the exact same admitted `IMG_7134.MOV` bytes:

- source SHA-256:
  `a274b44c998edf21f59383ebac5e7f9b01cb3f0099d29347ee1e4ab926e9351a`
- source size: `1,459,105,572` bytes
- runtime, model, and settings hashes: identical

The fresh run collapsed phrases such as “I have spent over 1,000 hours…” into
`347.66–347.67`. It had 959 words, 28 words at or below 11 ms, 28 overlapping
pairs, and a maximum nine-word collapsed run. The earlier run had 964 words,
one 10 ms word/overlap, and a maximum run of one.

Both results had otherwise valid `sourceMediaAuthority`. Treating lineage as a
timing-quality signal would therefore have admitted broken karaoke timing.

## Encoded correction

`transcript_timing_quality.py` now measures malformed/non-positive words,
backward starts, words at or below 11 ms, overlaps, and consecutive collapsed
runs. One isolated boundary anomaly is tolerated; a multiword collapsed run or
an anomaly rate above 1% fails closed.

Local Whisper now:

1. Parses and gates the GPU result.
2. Retries exactly once with `--no-gpu` when timing quality fails.
3. Fails closed if the CPU result also fails.
4. Records the actual `executionPath` (`gpu` or `cpu`) and timing policy in
   transcript provenance.

Producer ingest gates before publishing a transcript, and resume-ingest treats
a bound but timing-invalid transcript as pending.

For an already available good result, the faster recovery is the guarded
`POST /api/producer/transcript-authority` route. It holds the canonical project
mutation lease while its runner:

1. Re-verifies both retained source-set receipts and snapshot bytes.
2. Verifies the donor transcript's own source authority and timing quality.
3. Requires identical SHA-256 and size across donor and target media.
4. Preserves ASR provenance, adds a content-addressed promotion receipt, and
   rebinds the result to the target admitted source path.
5. Stages and verifies the rebound transcript before one atomic replacement.

The repaired transcript passed with 964 words, one isolated 10 ms
word/overlap, no malformed/non-positive words, no backward starts, and no
violations. The canonical three-cut short plan then passed the transcript-cut
contract with 157 kept words, zero suspicious spans, and zero errors/warnings.

## Principle

Keep three separate questions separate:

- **Media authority:** are these the admitted source bytes?
- **Transcript authority:** is this result cryptographically bound to them?
- **Timing quality:** can these timestamps safely drive cuts and captions?

All three must pass before word-addressed editing begins.

## When not to use promotion

Do not promote a transcript merely because filenames, durations, dialogue, or
perceptual hashes look similar. Do not use promotion across transcoded,
normalized, trimmed, or otherwise different bytes. If either admitted
source-set verifier fails, the donor binding is invalid, SHA-256/size differ,
or timing quality fails, run a fresh governed transcription instead.
