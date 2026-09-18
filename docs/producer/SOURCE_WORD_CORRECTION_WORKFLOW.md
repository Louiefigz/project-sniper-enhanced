# Explicit source-word timing and text correction

This is a Codex command workflow over the existing admitted-source/cut pipeline,
not another editor or renderer. It corrects explicitly reviewed word boundaries
without overwriting the source, original transcript, manifest, plan or approval.
It does not establish acoustic alignment automatically. Timing v1 changes bounds;
the separate text v2 operation changes an explicitly reviewed transcription token.

## When to use it

Use this when source audition establishes that an ASR word's start/end is wrong.
Keeping or excluding an unchanged suspect span uses the existing
`transcript_timing_review.py` workflow instead. Do not infer a corrected boundary
from the next token, silence metadata, an attractive cut or the need to pass a
gate. A long span is uncertainty, not permission to discard the word.

The current class supports one selected admitted source per request and1–128
sorted, unique, zero-based source word indices. Each word must retain its exact
text, order, confidence and other fields. Proposed positive intervals must fit
the source duration, avoid neighboring words and pass whole-transcript timing
checks. Only affected containing utterance endpoints are recomputed. Chained
correction of an already corrected selected transcript, unsupported parent
structures, text changes in a timing proposal, and source auditions longer than
30 seconds are rejected.
Those are explicit limitations, not automatic approximation or fallback.

## Prepare, audition and record

Run from `PROJECT_SNIPER` using the installed venv and absolute input paths:

```text
.venv/bin/python3 -B scripts/producer/transcript_timing_correction.py prepare <plan> <manifest> <transcript> <proposal.json>
.venv/bin/python3 -B scripts/producer/transcript_timing_correction.py status <plan> <manifest> <transcript> <proposal.json>
.venv/bin/python3 -B scripts/producer/transcript_timing_correction.py record <plan> <manifest> <transcript> <proposal.json> <submission.json>
```

The closed proposal contains:

```json
{
  "schemaVersion": 1,
  "operation": "propose-source-word-timing-correction",
  "requestId": "<retained UUIDv4>",
  "sourceId": "<existing raw-N identifier>",
  "expectedPlanSha256": "<exact original plan bytes>",
  "expectedManifestSha256": "<exact original manifest bytes>",
  "expectedTranscriptSha256": "<exact original transcript bytes>",
  "corrections": [
    {"sourceWordIndex": 0, "newStart": 0.4, "newEnd": 0.6}
  ]
}
```

This is a shape example, not authority or a proposed correction to any real
footage. Use only the user's actual reviewed source/word/bounds. Preparation
returns the original words, proposed bounds and exact hashed source windows;
it does not play or listen to them. Present the complete windows in Codex.

Record only an explicit operator submission after actual source audition and
boundary comparison. The closed record request contains `schemaVersion:1`,
`operation:"record-source-word-timing-correction"`, the exact `requestHash`, a
retained UUIDv4 `idempotencyKey`, `expectedRecordHash:null`, and one review per
correction in the same order. Each review binds `correctionHash`, every
`listenedToSourceWindows` entry (`windowHash` and actual `listened` decision),
`comparedOriginalAndProposedBounds`, and a meaningful bounded `rationale`.
The required positive attestations must be supplied by actual review, not filled
by Codex because a command needs them. No command invents consent.

Each request uses a new directory below the original manifest directory:
`.sniper-timing-corrections/<requestId>/`. Preparation retains original parent
bytes and request. Recording uses an exclusive writer claim, immutable decision
and corrected transcript, then a final commit. Partial/conflicting/failed stores
are fenced; there is no silent repair or new-UUID workaround. An exact successful
replay is read-only. Status reconstructs the entire revision against current
parents, policy and admitted source bytes, including the held decision/commit.

The result distinguishes historical ASR provenance from explicitly corrected
bounds. `selected`, `cutApproved` and `deliveryApproved` remain false.

## Source-faithful text correction (v2)

Use the same prepare/status/record commands and exact original parent hashes,
but explicitly submit `schemaVersion:2` and
`operation:"propose-source-word-text-correction"`. Each correction is exactly
`{sourceWordIndex,newWord}`; no new timing fields are accepted. The source word
index is the original ordered word index, not an occurrence guessed from text.

Only a single lexical token of 1–120 characters is supported. No insertion,
deletion, splitting, merging, internal whitespace, controls, punctuation-only
replacement or unchanged text is accepted. All original timings stay exact.
Corrected words may carry only the supported original word/start/end/confidence
fields and bounded scalar speaker/id identities; unknown or duplicate lexical/
confidence fields are rejected, not silently retained or deleted. Unaffected
word metadata stays unchanged. Model confidence is removed only on a changed
word because it scored the old ASR token; the request retains that original
token and confidence. If an utterance has `text`, its original text must exactly
equal the single-space join of its original words before it can be recomputed.
Ambiguous layouts are rejected rather than globally replaced or normalized.

Record with `schemaVersion:2`,
`operation:"record-source-word-text-correction"` and the same top-level binding
fields as timing v1. Each review has `correctionHash`, the complete
`listenedToSourceWindows`, `comparedOriginalAndProposedText`,
`confirmsSourceFaithfulTranscription`, and `rationale`. Positive attestations
must come from actual source review. Names, numbers and negation must reproduce
what was said; this operation cannot silently improve facts, style or meaning in
the speaker's audio. Display-only caption edits use the existing caption route.

V2 returns `sourceWordCorrectionAuthority`, separate from v1's
`timingCorrectionAuthority`, with explicit human-source text origin and retained
historical ASR provenance. Exactly one marker is allowed. The legacy storage
directory and manifest filename still contain `timing`; this is a shared store
name, not permission to mix v1/v2 payloads. Both use the same strong publisher
and actual cut consumer below. Neither supports chaining a selected already
corrected transcript; combine all supported corrections in one reviewed request
of the appropriate kind. Mixed text-and-timing correction remains unsupported.

## Publish a new manifest, then author a fresh cut

After a committed correction, explicitly request a new manifest with:

```json
{
  "schemaVersion": 1,
  "operation": "publish-corrected-transcript-manifest",
  "expectedRequestHash": "<freshly observed correction request hash>",
  "expectedRecordHash": "<freshly observed committed review hash>",
  "expectedCorrectedTranscriptSha256": "<exact committed transcript bytes>"
}
```

```text
.venv/bin/python3 -B scripts/producer/publish_corrected_transcript_manifest.py publish <original-plan> <original-manifest> <original-transcript> <proposal.json> <publication.json>
.venv/bin/python3 -B scripts/producer/publish_corrected_transcript_manifest.py status <original-plan> <original-manifest> <original-transcript> <proposal.json> <publication.json>
```

Publication creates `asset_manifest.timing-<requestId>.json` in the **same
directory** as the original manifest. This preserves canonical admitted media
and receipt locations. Its only data change is the selected source's relative
`transcriptPath` pointing to the committed correction. Exact bytes may replay;
partial or conflicting files never get overwritten. A later failure can leave
the new unselected file; inspect status, do not assume rollback or success.

This command writes no plan or project head and transfers no approval. Codex
must author an explicit new cut revision, rerun normal cut/meaning/duplicate
gates, then use the fresh manifest/candidate hashes with the existing guided
bootstrap command. The original candidate remains available. The cut gate now
rechecks the correction's actual committed review, not just a renewed transcript
digest. Reserved correction paths require that lineage even if its marker is
removed; a named timing manifest cannot redirect its selected source to ordinary
ASR bytes. Copied/staged files are not original transaction authority.

Do not run `resume_ingest_transcription.py` or `promote_transcript_authority.py`
against the revised manifest. Their canonical transcript-write class deliberately
rejects it; they must not overwrite a reviewed correction. Keep the original
parents available for strong readback. This is not a cryptographic proof that
arbitrarily rewritten local files outside the correction route came from ASR.

## Budgets, evidence and remaining qualification

Each correction/publication command has one original work deadline of at most
120seconds, including source checks and serialization; an earlier caller expiry
only shortens it. This is not a renewed video-generation allowance or a clock for
human waiting. The cut reader also bounds its correction work, temporarily
shortening a longer parent alarm and restoring only that parent's original
absolute expiry. These commands use no ASR/model/provider, paid API or download.

Actual tiny TEST-store regressions cover timing and one-to-one text changes,
immutable originals, positive and
negative source authority, exact replay, conflicting/partial stores, marker
removal, stale commits, source transplantation, parent deadlines and readback
races. Their explicit simulated attestations are not real listening. No C0679
timing correction or creator approval has been recorded. Real tight-cut listening
and the full edit/quality/timing qualification remain separate requirements.
