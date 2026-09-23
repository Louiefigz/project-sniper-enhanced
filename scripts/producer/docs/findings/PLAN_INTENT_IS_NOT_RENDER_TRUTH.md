# Plan intent is not render truth

## The lesson

A video pipeline can possess the right reference study, the right template, and
the right semantic decision and still ship the wrong visual. The rendered
timeline—not the planning document—is the product.

In C0679, the source plan selected several rich information forms, including
`module-bullet-bars` and `module-ledger-dark`. The Palmier live build later
replaced 12 planned kinds with simpler fallbacks and added three unplanned
graphics. Eight intro decision rows still named the original kinds, so plan
intent and render truth diverged in machine-readable data.

## Real numbers

- Source plan: 30 graphic windows, 11 distinct kinds.
- Palmier build: 33 windows, 9 distinct kinds.
- First 187s of Palmier build: 23 windows, only 6 kinds.
- Benchmark AI section: 20 windows, 19 information forms.
- Exact decision→track kind mismatches: 8.
- Existing lint result for the Palmier build: FAIL.
- Delivered master duration: 670s.
- Available prior deterministic audit duration: 47.3s, itself FAIL.

The historical Claude Desktop → Palmier first-60 run exposed the same failure at
a smaller scale. It proved substantial transport and mutation mechanics, but
failed later product-quality review: **56m48s** from capture to Desktop
completion, Palmier QC still pending, seven corrected captions stripped of
per-word karaoke timing, and a wrong 3840×2160 canvas accepted for a requested
9:16 short. Color comparison also found a severely lavender presenter after
small planned adjustments were interpreted as absolute values. The retained
review receipt's `wordLock: pass` despite the seven timing losses demonstrates
why self-attested review JSON is not render truth. This specimen is not
connected Palmier/P5 qualification.

The failed lint was not a weak heuristic. It named every mismatched graphic and
also caught density, variety, recompose, pacing, and empty-chrome defects.

The R2 layout repair exposed a second form of the same problem: stale stage
reuse. The plan and render log both claimed three presenter recompositions, but
`work/punched.mp4` was timestamped 20:13 while the defective final was built at
20:51. Resume treated “file exists” as “file is current,” so all newer camera
geometry was silently bypassed. The fixed render regenerated 1,051 punched
frames, pinned its fixed-edge rails to `[0,0,633,1079]` and
`[0,0,719,1079]`, and measured the face separately inside each rail window.
The 33% rail then landed the face at x=0.666 against a 0.665 target; the wider
limit card landed at x=0.658, the closest feasible point to 0.688 under the
1.34 tasteful zoom cap.

## The obvious approach that fails

Do not fix this class of defect by adding more reference text to an agent prompt
or by creating another template. Both were already present. An unconstrained
editor can still choose a familiar fallback, change a row after review, or add an
ad-hoc clip that has no semantic receipt.

Do not accept a visual review that says the approved plan “looked good.” A plan
cannot prove what the editor actually rendered.

## The contract that works

For every planned graphic, persist and verify the tuple:

```text
(planHash, graphicId, semanticBeatId, kind, renderedAssetHash,
 timelineId, candidateFingerprint, exportHash)
```

Enforce it at three boundaries:

1. **Before mutation:** deterministic gates pass; assets are rendered from the
   selected kinds; the exact worklist is hash-bound.
2. **After mutation:** read back the candidate; compare-and-swap from the last
   fingerprint; pause on drift, replay, or an unobservable result.
3. **Before completion:** export the exact candidate; deterministic QC and both
   visual reviews bind to the same fingerprint and export hash.

Every resumable intermediate also needs its own content receipt:

```text
stageFingerprint = hash(stagePayload, inputBytes, rendererCode, templateBytes)
```

An intermediate with no receipt is legacy and must rebuild. A receipt mismatch
must rebuild even when the output path exists. Fixed-edge templates are another
authorship boundary: a full-canvas rail owns its `(0,0)` position and must never
be passed through the floating-card free-space placer. Post-render placement
evidence should fail if a registered left/right rail is not flush to its authored
canvas edge.

The rendered review must include direct comparison with source truth for color
and identity-sensitive copy. Structural checks cannot decide whether an editor
API treats `saturation: 0.04` as a delta or an absolute value, and loudness
checks alone cannot decide whether normalization exposed a persistent tone.

The semantic invariant is simple:

```python
decision.graphicId == track.id
decision.beatId == track.semanticBeatId
decision.kind == track.kind
```

If any comparison fails, there is no stylistic rationale that makes the export
valid.

Until connected hybrid P5 qualification closes, the safe deliverables are the
exact audited MP4 and its approved one-clip flat mirror. Editable Palmier remains
a local, production-shaped, isolated experiment. Reference study/profile data
may guide an edit, but verified mimic is not released (P6 0/7), and the complete
short/long product is not P7/P8-qualified.

## Why this generalizes

The same failure occurs with b-roll identity, caption timing, music selection,
color settings, and presenter geometry. Any layer that can be changed after its
review needs an immutable receipt and a readback comparison. “The agent knew” is
not evidence. “The plan requested” is not evidence. Only the exact candidate and
its bound export are evidence.

## When not to use the full contract

For a disposable scratch preview, a full export-hash approval chain may be more
cost than value. Mark that output explicitly as a preview and prevent it from
becoming the publishable master. The decision/kind parity check and candidate
readback are cheap enough to keep even in previews. Stage fingerprints can also
be skipped for a true one-shot render that never resumes; once `--resume` exists,
existence-only reuse is not safe enough.
