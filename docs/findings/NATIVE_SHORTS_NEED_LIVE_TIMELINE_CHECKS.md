# Native Shorts need live timeline checks

On September 10, 2026, three source-selected Shorts tested full presenter,
full-screen comparison, and diagram-plus-presenter direction. They lasted
13.04s, 23.32s and 8.24s at 25 fps. All final static checks had zero errors.
That did not establish correct Studio behavior.

In the 8.24-second diagram case, the installed SDK 0.8.31 preview displayed
multiple timed pictures, diagram states and captions together. A fresh browser
document reproduced the problem; the native source-frame capture still looked
correct. Rewriting the composition based only on the broken player would have
mixed a runtime defect into the creative strategy.

The long-form work already retained a realm-safe Studio runtime reconstruction
recipe. Its element checks avoid relying on a constructor belonging to another
window: an iframe's element need not satisfy the outer window's
`element instanceof HTMLElement`. The existing fix uses same-document structure
and media capabilities. We reconstructed that exact recipe into an isolated SDK,
verified its runtime and CLI hashes, and replayed the unchanged Short. Timed
visibility, restart and selected forward/reverse seeks then worked. The final
comparison-card transition was also checked using this variant.

The reproducible entry point is:

```bash
node artifacts/shorts-strategy-validation-2026-09-10/reconstruct-realm.mjs
```

Read the recipe and target hashes in the
[runtime receipt](../../artifacts/shorts-strategy-validation-2026-09-10/realm-sdk/RECONSTRUCTION.json),
and the source/preview limits in the
[three-case report](../../artifacts/shorts-strategy-validation-2026-09-10/QA.md).
The reconstruction script refuses changed SDK inputs. Installed SDK files were
not edited. The separate file-backed export transport was not combined here.

Use three distinct checks: static source validation, native frame capture, and
live playback/seek/restart. A frame capture can pass while the player displays
the wrong timed layers. Conversely, a blank player at an exclusive end time is
not proof of an encoded black frame; inspect the last valid frame and qualify
the actual export separately.

Do not apply a historical runtime patch blindly to another SDK version, use it
to excuse source-geometry mistakes, or treat this preview evidence as audio or
export qualification. The same tests independently caught a clipped head, title
over a chin, late split and premature empty card. Those required direction
changes; they were not runtime faults.

## Check the space a moving object actually occupies

The September 13 story test exposed another direction error. A client-video
object began at y650 and moved to y320 above a tool label. That cleared the tool
label but covered the second line of the explanatory heading at y270–391.
The overlap was visible at native frame 528; contract checks alone had not
measured that relationship. The interrupted full attempt and its frames remain
in `artifacts/native-short-storytelling-2026-09-13/export-v4-guarded-04/`.

Project-v5's single-line heading fixed that collision, and its 16-checkpoint
preflight passed heading/file and file/caption clearance. Visual inspection then
caught a different collision: the file crossed the Drive label at frame 624.
The test did not measure the tool labels, so its passing result was incomplete.

Project-v6 reduces the file group to approximately 114 pixels high and moves it
between rows through the empty center lane. The file's top positions are 368,
588 and 808; tool boxes start at 490, 710 and 930. This leaves at least seven
pixels between the moving group and each settled tool label. The heading ends
at y300 and captions begin at y1080.

The revised preflight captured 78 actual native frames, including every frame
of every file movement. It checked heading/file, file/caption and all five
tool-box clearances, as well as source frames and typography. It passed in
67.139 seconds with verified cleanup. Independent visual inspection of ten
frames found no blocking issue. This is preflight evidence; it does not replace
finished encoded playback or listening.

Review motion starts, settled positions and intermediate crossings before a
complete export. A correct endpoint does not prove the travel path is clear.
Use bounds for required separation, then inspect the pixels: intentional visual
overlays should not be prohibited by a universal no-overlap rule.

## Inspect the displayed media replacement at an exit

The complete revision-6 encoded inspection caught a second class of transition
bug at frame 327. The original Claude video had the expected `inset(100%)` clip
path, but its exact-frame replacement image remained visible over the next
presenter's head. Both the retained native JPEG and encoded PNG contained the
defect. The original element's computed style was insufficient evidence.

Revision 7 masks the containing article window over its complete [197,327)
interval. This contains both the original element and any injected sibling.
The new checks cover frames 196/197, 326/327 and 328–336, including consecutive
frames around the exit. The general rule also applies to source-frame injectors
outside this project: put timing masks on the visual container, and check the
actual pixels at the handoff. Record the result of that rerun separately.

That revision's 92-point forward preflight passed in 83.734 seconds. Its full
export then exposed a reverse-only failure at frame 326: the article window was
visible and its source PNG was correct, but the injected page image was hidden.
All 806 QC occurrences completed in 115.205 seconds; the unchanged state check
correctly rejected the export. Owned cleanup passed at 430.355 seconds.

The remaining mask on the original video was the cause. The pinned SDK starts
the timeline seek, copies the original video's computed styles to its frame
replacement, and then waits for seek completion. A backward entry can therefore
copy the previous hidden mask. Animating the wrapper as well does not repair
the already copied child style.

Revision 8 removes the original video's mask and keeps the wrapper as the sole
clipping owner. Its regression includes the exact failing order
`965 → 343 → 336 → 335 → 328 → 327 → 326 → 320`, with forward/reverse state and
JPEG comparisons. Do not fix this by ignoring replacement images in QC or by
adding extra seeks that conceal the original sequence's behavior.

The corrected `story-layout-05` passed 100 captures across 13 bounded sessions
in 81.024 seconds. The backward frame 326 is byte-identical to its forward
baseline, including the page; frame 327 shows only the returning full portrait.
Root and independent visual review remain separate from final export checks.
The preceding `story-layout-04` never launched a renderer: its outer sandbox
blocked the required host resource measurement. Its failed receipt is retained.


The revision-8 complete export subsequently passed all 806 native state checks,
280 reverse pixel checks, 526 final encoded comparisons and full audio/video
decode. The final frame record is `encoded-review-01/frames.json`; independent
original-detail inspection of encoded frames 326/327 confirmed the clean
handoff. This closes the reproduced visibility defect. Continuous playback,
source listening and human caption approval remain separate review steps.
