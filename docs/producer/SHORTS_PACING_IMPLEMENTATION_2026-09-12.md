# Native Shorts pacing — implementation and acceptance

September 12, 2026. This is a local implementation, not an automated creative
director or a claim that all styles and organic-media edge cases are qualified.

## Shared implementation

- `native-short-pacing-observations.ts` measures the existing kept-word clock:
  overall/phrase rate, exact phrase windows, speech coverage, every uncovered
  gap, source-cut frames and known motion. Overlapping ASR windows are unioned
  for coverage. Rendering and measurement share the same caption-end function.
- `native-short-pacing.ts` binds an editor-authored rhythm, lane rationale,
  complete speech-bound beats and viewing budgets to both speech and visuals.
  Known native motion cannot occupy the declared readable hold. Title, text
  and custom timed inserts require budgets. It does not invent minimum reading
  time from a creator name, rate threshold or asset duration.
- Native strategy version 2 is required by new direct and guided writers.
  Version 1 remains reconstructable for existing review projects. The project
  includes a reproducible `PACING-REPORT.json`, pinned during export and checked
  again on cold read. Source/caption/visual edits invalidate prior pacing.
- CLI `measure`, app/CLI request preparation, shared editorial instructions and
  project construction use these same modules. No second caption engine, ASR
  invocation, remote Director or independent model call was added.

## Predeclared real-source cases

The [case plan](../../artifacts/native-short-pacing-2026-09-12/CASE-PLAN.md)
was written before building isolated revisions of the existing three examples.
The [integration receipt](../../artifacts/native-short-pacing-2026-09-12/integration-checks.json)
records actual build/cold-read time and source-clock observations.

| Case | Measured clock | Planned test |
| --- | --- | --- |
| Follow-up | 49 words / 13.04 s; 225.46 words/minute | Regroup a 0.16 s standalone caption into its 0.64 s rhetorical phrase; preserve every word's original timing |
| Offer story | 65 words / 24.52 s; 159.05 words/minute | Reject the completed formula's 12-frame hold against a 25-frame budget; extend it to 29 frames within the same runtime |
| Member math | 19 words / 8.24 s; 138.35 words/minute | Preserve the developing arithmetic and local pause; confirm byte-identical HTML and reuse the prior qualified render |

These word rates describe the retained source; they do not by themselves prove
brisk or calm delivery. The new plans truthfully record timing-and-transcript
review. Audible performance and whole-Short feel still require playback review.

The rejected offer plan and its negative receipt are retained. The two changed
examples use fresh supervised native/encoded checks; the member-math executable
is byte-identical and its prior qualified render is reused.

Frame inspection of the first offer revision found the label switching before
the outgoing wording cleared. A second revision moved that label transition to
19.55 seconds and added boundary expectations. The first export attempt of that
revision stopped on a host `top` timeout; cleanup passed. The retry exposed an
injected dog-video frame surviving a video-only exit on forward seek at frame
583. Revision 3 added an untimed video container but retained the old video-only
mask; the active injected frame then disappeared on reverse seek at frame 582.
Revision 4 removes that direct video mask and uses the shared `nativeVisualExit`
primitive exclusively on the parent. No comparison was relaxed.

Revision 4 (`projects/offer-story-v4`) passed as `exports/offer-story-07`.
The final encoded inspection checks frames 479, 480, 489, 513, 564, 582, 583
and 612. The completed formula, label handoff, populated offer and dog video
to still transition are present at their intended frames. The initial
`build-cases.ts` creates the first revisions; the retained versioned plan JSON
files are the authoritative inputs for subsequent offer corrections.

The shared capture scheduler now always checks explicit scene expectations in
both forward and reverse order, alongside its existing boundary samples. Four
new schedule tests cover this behavior and its bounded inventory. The pacing,
writer/reader, request, composition, direction and web-asset tests total 28
passing tests, including eight new pacing tests. TypeScript, targeted ESLint,
diff whitespace and the changed logic files' line/function/parameter limits pass.

An ancillary encoded-frame extraction attempt omitted required supervision
fingerprints; its terminal receipt failed. A fresh pinned extraction completed
successfully. Both attempts remain under the case artifact directory. This did
not affect the two video export receipts.

## Final review and measured runs

The [three-video review page](http://127.0.0.1:3995/) uses the exact files in
the [review manifest](../../artifacts/native-short-pacing-2026-09-12/review-manifest.json).
The [qualification results](../../artifacts/native-short-pacing-2026-09-12/qualification-results.json)
retain every export attempt, including failures and the visually superseded run.

| Final candidate | Export and checks, with cleanup | Encoded frames checked | Maximum observed owned footprint |
| --- | ---: | ---: | ---: |
| Follow-up, `follow-up-01` | 68.78 s | 149 / 326 | 2.234 GiB |
| Offer, `offer-story-07` | 86.41 s | 243 / 613 | 2.709 GiB |
| Member math | Prior identical render reused | Prior qualification retained | No new render |

These are supervised export-and-check times for prepared local projects, not
raw-footage-to-finished-edit times. The eight export attempts totaled 418.35 s;
authoring, investigation and ancillary inspections are additional. Both final
new exports passed complete audio/video decode, sampled encoded/native picture
comparison, forward/reverse state checks, source pinning and verified cleanup.
They reused the qualified AAC packets with zero additional audio encodes and
made no provider calls.

Three first attempts on new offer project paths stopped when host `top`
measurement timed out; each verified cleanup, and the later attempts progressed.
A separate capture-only attempt stopped because the new project had no matching
extracted-frame cache yet. Cross-project cache reuse and the apparent cold-start
measurement interaction remain an optimization investigation. Resource checks
and comparison tolerances were not weakened. `encoded-review-03` extracted the
eight final offer PNGs under the same supervision in 5.17 s with verified cleanup.

## Limits

- A declared minimum is an editorial budget. Passing it does not establish
  audience comprehension or eliminate competition with captions and other text.
- Static clip bounds cannot prove internal custom CSS/GSAP visibility. Native
  expectations and actual encoded-frame inspection remain necessary.
- Source listening and complete audiovisual review are distinct from transcript,
  timing, still-frame and decode checks. Their status must remain explicit.
- Automatic brand/logo/creator asset-use contracts and broader sourcing cases
  remain in the separate organic B-roll audit; this change does not qualify them.
