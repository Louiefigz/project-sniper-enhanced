# Cut selected media before native authoring

Date: September 15, 2026.

## Problem

A 55.32-second native Short referenced a 31-minute-44-second, 5.50 GB recording.
Its HTML selected five spoken passages, but Studio could still prepare a preview
of the whole recording. Restricting the timeline did not restrict that input file.
The final renderer already extracted selected frames; this finding addresses the
separate full-source preview and working-media problem.

Aaron proposed cutting the chosen sections first and working with those files.
The implementation now does that through a reusable selected-source package.

## Measured result

The final tested preparation used the same recording and selected speech:

| Measurement | Observed value |
| --- | ---: |
| Original recording | 5,503,511,319 bytes |
| Five prepared picture clips plus float audio | 219,410,307 bytes |
| Working-media reduction | 96.01% |
| Media preparation and checks | 15.88 seconds |
| Supervised owner, including cleanup | 19.21 seconds |
| Additional picture encodes | 0 |
| Output-time picture frames compared | 1,383; all identical |
| Dialogue frames compared | 2,655,360 stereo sample frames at 48 kHz; all identical |
| Maximum dialogue sample difference | 0 |

These are preparation/equivalence measurements, not total editing or final
graphics-render times. The source-wide editorial selection remains necessary.

Evidence: [final automatic preparation](../../artifacts/selected-sources-proof-2026-09-15/final-project.sources/package/run/result.json),
[resource owner](../../artifacts/selected-sources-proof-2026-09-15/final-project.sources/package/run/selected-sources.render.json),
[decoded equivalence](../../artifacts/selected-sources-proof-2026-09-15/final-equivalence/equivalence.json),
[small project inventory](../../artifacts/selected-sources-proof-2026-09-15/final-project/PROJECT-MANIFEST.json).
The separate comprehensive equivalence test took 106.05 seconds, including its
owner and cleanup. It is a development qualification test, not an extra step
silently added to every normal preparation. Native final-render/Studio performance
was not benchmarked by this change.

## How it works

1. Review the original transcript and choose speech/supporting-video ranges.
2. Add short trim handles and merge overlapping ranges, including repeated views.
3. Copy original compressed picture packets into small MP4s. Retain the keyframe
   lead-in needed to decode them. Prepare matching bounded float PCM dialogue.
4. Record the exact original-to-local timestamp translation. Keep the original
   cuts, caption occurrences and source evidence unchanged.
5. Stage only small media in the executable project. Bind each media element to
   its prepared file and local offset in `PREPARED-SOURCES.json`.
6. Reuse the sealed package when graphics, titles or framing change. A source
   change or a range outside its handles requires new preparation.

```bash
# Direct native Short builds now prepare selected media if no binding exists.
node --import tsx scripts/producer/native-short.ts build plan.json new-project

# Explicit preparation from an authored plan, reusable before further iteration.
node --import tsx scripts/producer/native-short.ts prepare-media plan.json new-media
```

For preparation before the visual plan, supply original ranges directly to
`edit/selected_sources.py`; the complete request shape is in the
[native Shorts workflow](../producer/NATIVE_SHORTS_WORKFLOW.md#prepare-the-selected-media-first).

## Timestamp lesson

Copying video packets can produce a nonzero presentation start because decoding
and presentation order differ. A correct packet hash alone does not prove a
correct seek. Normalize the presentation clock, prove the uniform rational
translation of PTS/DTS, and compare decoded output-time frames. This test also
compared the complete dialogue edit after all five joins.

## Limits and when not to expect the same benefit

- A long-form edit retaining most of a recording will shrink much less. The
  legacy long-form path already creates a cut/speed base before graphics.
- Native long-form now has an explicit, additive
  [project preparation adapter](../producer/NATIVE_LONG_SELECTED_SOURCES.md).
  It preserves working cut-base projects and qualified export packages. Guided
  stored-proposal automation remains separate from the direct Short CLI.
- The current packet-copy input contract is zero-based H.264/HEVC MP4 picture
  with at most one audio stream, using zero-based 48 kHz mono/stereo source audio.
  Unsupported media fails explicitly; a new resampling phase is not silently added.
- Browser-specific preview conversion may still be needed for a small clip.
  The selected package does not establish universal codec support.
- Graphics rendering, encoding, review and other cache allocations still take
  time. Do not infer a total-production speedup from a 96% media-size reduction.

## Long-form extension: preserve the working path

The follow-up long-form implementation creates an isolated project and changes
only selected media references and source offsets. It preserves an existing
complete-program narration WAV byte for byte and uses the same source engine,
static validator, native SDK and process owner. An already-cut presenter base
does not need another preparation pass.

The bounded C0679 test selects two 3.003-second passages at 100.1 and 300.3
seconds. Working media falls from 10.28 GB to 129.75 MB; preparation ownership
takes 19.90 seconds and adds no picture encoding. This unusually small selection
is useful for compatibility testing, not a representative long-form size saving.
All 144 decoded native output frames and all 288,288 stereo program audio sample
frames match the native render from original sources exactly. Both source-range
comparisons also pass. The native sample render times are essentially unchanged
(56.83 seconds prepared versus 56.68 original), consistent with native export
already extracting selected ranges. The benefit targets oversized working inputs.
The new adapter's use, measured test and limits are recorded in the
[long-form workflow](../producer/NATIVE_LONG_SELECTED_SOURCES.md).
