# Transcript-first cut authority

## Finding

A plan can satisfy every graphics, hook, and motion rule while preserving the
wrong spoken take or cutting through a word. Visual quality checks cannot repair
an invalid editorial spine. The cut must become a separate fail-closed authority
before any retention treatment is planned.

## Enforced order

1. Read every manifest-referenced word-level transcript.
2. Author the kept `cutTrack` and an explicit rationale for each kept range.
3. Record every inter-cut removal in `cutDecisions.removals`, including exact
   source bounds, reason, and transcript evidence.
4. The controller runs `transcript_cut_contract.py --previsual` and atomically
   persists its hash-bound approval receipt.
5. The controller publishes that approved cut as the first Palmier working
   checkpoint, so the operator can inspect the editorial spine immediately.
6. A separate visual-author process may then add hook, graphics, motion,
   transitions, b-roll, music, and other treatment, but it may not change the
   approved `cutTrack` or `cutDecisions`.
7. The controller runs the contract again with `--approval <receipt>` before
   accepting the visual plan or running the downstream planning gates.

This is a controller-owned state transition, not a prompt convention. Cut and
visual authoring run as separate bounded processes. A visual author that mutates
the cut digest fails closed, and downstream planning gates are short-circuited.
Resume reuses an approval only when the saved receipt still validates against
the current manifest, transcripts, and cut track.

## What the receipt proves

The previsual verdict carries SHA-256 values for the exact cut-only plan bytes,
manifest bytes, aggregate transcript authority, and canonical `cutTrack`. It
also records the word immediately before and after every boundary. The final
check permits visual-lane changes but requires the manifest, transcript,
cut-track, and cut-decision digests to match that receipt. The planning review
packet persists the final
verdict under the same authority snapshot, so later authority changes invalidate
the approval.

## Why explicit removal evidence matters

An empty gap can honestly be labeled `dead_air`; a gap containing transcript
words cannot. False starts, retakes, filler, and deliberate content removals must
quote a verbatim excerpt from the removed words. This prevents a generic
"tighten pacing" rationale from hiding dropped meaning.

## When not to use the single-source monotonic rule

Do not use it for intentional replay edits. Project Sniper currently forbids
replayed source ranges because caption remapping assigns a source word to its
first containing segment. Supporting replay requires a new occurrence-aware
timeline identity; weakening this gate would only conceal that missing model.
