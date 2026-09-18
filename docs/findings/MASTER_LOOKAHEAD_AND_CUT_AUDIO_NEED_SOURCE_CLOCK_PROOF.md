# Mastering lookahead and cut audio need source-content proof

2026-09-06. Synthetic FFmpeg 8.0_1 acceptance only: these findings are not a
creator-footage listening comparison, a two-hour benchmark, or delivery approval.

## A correct sample count concealed two failures

The shared static master used an oversampled five-millisecond lookahead limiter:

```text
aresample=192000,alimiter=limit=0.794328:attack=5:release=100:level=false
```

Without `latency=true`, a 48 kHz synthetic interior event moved **239.742281
samples / 4.994631 ms** later. Input and output both contained exactly48,000
samples. An independent event in the final three milliseconds disappeared
entirely. A duration-only test cannot see either defect.

The shared chain now requests latency compensation and end flushing. Both
source-content tests pass within one sample of energy-centroid position, with
the same sample count and end-event energy preserved. The linear/static/dynamic
selection and -14 +/-1 LUFS / -1.5 dBTP delivery policy were not relaxed.
`MASTERING_POLICY_VERSION=3` distinguishes newly processed bytes; mechanical
measurement evidence stays policy v2 because its targets did not change.

Tests: `test_master_audio_clock_media.py`.

## Saved intent does not prove which processing code executed

Legacy fingerprint loading recomputed current fields from `base_plan.json`.
Adding a new processing-policy field to that recomputation would falsely upgrade
an old render without touching its audio. Recovery of an old audio-only commit
intent had the same bug: the intent stored plan/hash but not the executed DSP
policy, so recovery could label pre-fix bytes as v3.

New base records and audio commit intents retain their observed mastering policy.
Snapshot refresh does not upgrade or invent it; old/missing policies require a
full base rebuild, not an audio-only edit atop delayed audio. Legacy crash intents
remain missing-policy on recovery, so they are not falsely blessed. An explicit
`--auto-base` request without a verifiable base and rebuild manifest now fails
instead of silently reusing an unverified base.

Tests: `test_mastering_policy_cache.py`, `test_audio_intent.py`,
`test_audio_fast_path.py`, `test_assemble.py`.

## First ordinary source-float final adapter

The private cut preview had separately exposed an 8.83 ms compressed-part
problem and a 12.535 ms identity-`atempo` problem. The ordinary renderer now has
an explicit fresh `--audio-clock-policy source-float-v1` capability. It uses
shared canonical source/J-cut filter builders, omits unity tempo processing,
keeps source audio in float, and derives sample windows from accumulated actual
cut-part frame counts. It does not read the concatenated AAC as dialogue.

The final picture is encoded through ordinary settings, then copied with exact
packet/PTS proof while the measured float bus receives one AAC encode. A real
four-cut 30000/1001 fixture, using 48 kHz stereo, a 44.1 kHz right-only microphone
source, and a no-audio source, produced exactly192,192 presented audio samples.
Five decoded source events—interior, incoming J-cut, later-cut and ending—were
within3 ms after the final AAC encode. All120 final picture packets/PTS matched
the ordinary legacy picture output exactly. Full Audit B passed; this still
does not establish subjective audio, grading or visual equivalence.

This first adapter intentionally retains ignored legacy AAC inside its picture
transport. Therefore it has **one AAC encode on the delivered audio path**, not
one AAC command in the entire job. It is not yet the default GUI/RenderGraph
lane. Nonunity speed, enhancement/gain, authored SFX/music, and post-master
caption-shard mutation are explicitly unqualified in this capability; the
existing legacy route remains supported and reports source/final audio-clock
parity as unqualified. Existing source admission, lint and final QC still apply.

Tests: `test_render_source_audio_media.py`. The positive fixture explicitly
requests a clean trim treatment; synthetic tones are not labelled transcripts.
Actual silent-source mutation, missing incoming-channel proof, and a real s32
WAV re-sealed as float all reject. A deliberately under-level real candidate
fails measured QC while preserving both the existing final and its sidecar.

The first pulse-only fixture was correctly rejected at **-15.17 LUFS**—outside
the unchanged -14 +/-1 range. It remains under
`/private/tmp/sniper-f1-ordinary-q7t8zago/`; it is a retained example of the
known bounded-master high-crest limitation, not a repaired/qualified output.

## Whole-output measurement must bind the bytes being promoted

Audio candidates are isolated and measured before promotion. The helper now
hashes the candidate before and after whole-output qualification; a mismatch
rejects and retains the unapproved candidate instead of replacing the final.
This costs two whole-candidate hashes in addition to existing audio and picture
probes. It is deliberate correctness-first work, not a demonstrated speedup.

Tests: `test_audio_candidate_identity.py`. Reusable float-bus cache admission,
ordinary effect/music integration, source-profile breadth, calibrated creator
listening comparisons, and ten-minute performance qualification remain separate
work. Do not infer them from passing these small deterministic fixtures.
