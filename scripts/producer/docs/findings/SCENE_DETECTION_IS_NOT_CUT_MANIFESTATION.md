# Scene detection is not cut manifestation

## The assertion

A same-camera dialogue cut can be editorially real and frame-exact while
remaining invisible to scene detection and local pixel-delta thresholds.
Post-render QC should use visual discontinuity as an observation, not as the
only proof that a compiled cut executed.

## The incident

The connected-qualification short compiled three retained source ranges:

```text
347.70–376.04
377.03–382.64
383.90–401.74
```

Those ranges intentionally remove two same-shot false-start spans. The cut
stage encoded **850**, **168**, and **535** frames. Their concat and the
assembled final both contain exactly **1,553** frames.

Whole-file scene detection nevertheless reported zero hard changes. The local
seam probe also rejected both cuts:

| Seam | Pixel step | Local motion baseline | Required floor |
|---|---:|---:|---:|
| 28.34s | 15.12 | 10.32 | 20.65 |
| 33.95s | 23.66 | 24.72 | 49.43 |

The subject's ordinary mouth and hand motion was as large as, or larger than,
the splice. Raising sensitivity would trade this false negative for false
positives during normal talking-head movement.

## The contract that works

At cut execution, seal a strict receipt containing:

- the current `cutTrack` digest;
- the exact compiled `timeline_map.json` hash;
- every part's compiled source/output coordinates;
- every part's exact frame count and byte hash;
- the concatenated mezzanine's exact frame count and byte hash;
- lossless H.264 Annex-B evidence that the concat video bytes equal the
  ordered elementary-video bytes of all parts;
- the compiler-duration assertion and tolerance.

After mastering, bind that receipt to the exact graphics-free base. After
assembly, extend it to:

```text
manifestation receipt
  → exact base bytes and frame count
  → assembled authority sidecar
  → exact current final bytes and frame count
```

Audit may accept this lineage only when every current authority link reopens and
re-hashes successfully, the part count still equals the compiled segment count,
and the final frame count still equals the exact concat. Missing or malformed
authority fails closed.

The retained per-part observations survive cleanup of `work/cut-parts`; the
current timeline, base, assembled sidecar, and final remain re-observable.

## The principle

Content analysis answers, “Do these neighboring frames look different?”
Execution lineage answers, “Did these exact compiled ranges become these exact
delivered frames?” They are complementary checks, not substitutes.

Keep scene and local-delta detection because they can expose a frozen or stale
render with no lineage. Use sealed lineage for same-scene cuts whose visual
discontinuity is inherently ambiguous. Never turn an unbound JSON assertion
into a pass: the receipt must be written by the execution path and extended by
the mastering/assembly path.

## When not to use lineage as the only check

Do not use frame-count lineage to claim that a cut is aesthetically good,
word-safe, or free of an audible click. Transcript-boundary approval and
audio/visual seam review remain separate gates.

Do not recover a receipt when the per-part artifacts are gone and no earlier
sealed receipt exists. In that case the execution observation is unrecoverable;
rerender the cut stage or keep the visual QC failure.
