# Contact sheets need individual frame checks

Date: 2026-09-10.
Scope: visual-reference research and planning evidence.

## What happened

The first N27 mechanics review described a supposed conflict between annual
saved time in the narration and a weekly unit in the graphic.
That precise error was not supported by the original frame.

In the source, the left diagnosis says five hours per week.
A different result at the right says 200+ hours saved, with its remainder cropped.
In a dense atlas, the right edge of one image abuts the left edge of the next.
Reading across that boundary falsely joined the saved-hours result to / WEEK.

Two reviewers inspected separate 1080 × 1920 source frames:

- Frame 276 at 9.209 seconds.
- Frame 360 at 12.012 seconds.

The separate frames establish clipping.
They do not establish the claimed incorrect right-side time unit.
The unsupported unit-error finding was retracted in the old mechanics notes,
reconciliation notes and new complete-case record.

## Why this matters

A contact sheet is excellent for finding scene changes and repeated layouts.
It is poor evidence for tiny labels that sit at image boundaries.
Repeated human summaries do not make the original interpretation more reliable.
An independent check must return to the relevant pixels.

A similar timing check in N09 changed a supposed face zoom into a lateral pan.
The image translated while its scale remained broadly stable.
The motion suggested a different catalog mechanism once correctly observed.

## The reusable method

1. Use complete chronological contact sheets to understand the story.
2. Identify the exact image, region and time behind a consequential observation.
3. Open the individual source frame at adequate resolution.
4. For movement, inspect before, during and after at known source timestamps.
5. Record observation separately from inferred directing purpose.
6. Keep unknown or cropped information unknown.
7. Correct the earlier durable note when a later check changes its conclusion.

Store a gutter and time label between images in overview sheets.
Keep individual full frames beside each sequence rather than storing only an atlas.
Record the native frame index and presentation timestamp separately from the
requested seek time; the request is not itself an exact transition timestamp.

For native-frame extraction, selecting by decoded frame index avoids assigning
seek-relative labels to frames as if those labels were native source timestamps:

```sh
ffmpeg -threads 1 -i source.mp4 -vf 'select=eq(n\,276)' \
  -frames:v 1 -threads 1 frame-276.jpg
```

Obtain that index's timestamp from the same source's frame probe.
Do not infer timing from rounded fps alone when precise timing matters.

## When a full-frame check is unnecessary

A contact sheet can sufficiently establish a broad cut from a face to a map.
Do not extract every native frame merely to repeat that observation.
Use finer evidence when a label, geometry, motion mechanism or speech alignment
changes the actual planning decision.

## Evidence

- [Corrected complete N27 case](../studies/shorts-visual-playbook/nate-sequences/cases/N27.md).
- [N09 movement case](../studies/shorts-visual-playbook/nate-sequences/cases/N09.md#N09-B15).
- [Expanded directing guide](../studies/shorts-visual-playbook/nate-sequences/DIRECTING_GUIDE.md).
