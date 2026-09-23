# C0679 independent edit and timing trial

## User instruction and sequence

The user authorized this sequence on 2026-09-09:

1. Finish the current edited video and its HyperFrames Studio handoff.
2. Save that attempt for a later quality comparison.
3. Edit the same original raw footage again, from beginning to end.
4. Do not use the previous attempt as a reference for the new edit.
5. Measure the actual time needed from a fresh start to the completed result.

Production owner: Codex task `01a0753f-8b94-7461-804d-831c621658ce`.
Baseline package owner: Codex task `01a0863a-c43e-78f0-b227-54ea2c5c6e0d`.
These owners have received the instruction. One production owner controls media
jobs; the benchmark must not compete with the current validation or render.
This document defines the test; it is not evidence that the test has started.

## Preserve Attempt A

The existing saved package is:
`PROJECT_SNIPER/artifacts/c0679-native-hyperframes-2026-09-09/`.
Its `PACKAGE_MANIFEST.json` records the copied files and qualification scope.
Complete pending current-attempt checks before declaring the baseline finalized.
Preserve the final video, editable composition, local assets, source provenance,
cut decisions, receipts, and unresolved limitations as Attempt A.
Record a final manifest digest and the output digest at the baseline handoff.
Store later comparison reports outside the package. Do not overwrite Attempt A
with new output, silently update its evidence, or delete the original footage.
The protected source-frame cache also remains untouched.

## Permitted fresh-trial inputs

The creative source is `/Users/maintainer/Downloads/C0679.MP4`.
Confirm its identity during the timed run. Do not substitute a previously cut
presenter video or assume the earlier edit's duration or segment count.
Carry forward the user's general brief:

- Make the opening minute engaging, with meaningful graphics, motion, cards,
  or transitions approximately every two to four seconds.
- Use lighter treatment afterward, with explanatory graphics throughout where
  they support the spoken material; remove outtakes and unnecessary pauses.
- Keep the presenter in frame when shown, including transitions to presentation,
  split-screen and smaller presenter layouts. Constant head tracking is not required.
- Deliver an editable HyperFrames Studio project and a checked full-video export.

Installed generic skills, catalog components, fonts, tools and engineering fixes
may be reused. Record their versions at the start. Do not rebuild the software
from scratch merely to call this a fresh editorial run.

## Excluded inputs and isolation

Do not open or reuse Attempt A's transcript, word timing, cut list, edit plan,
scene timing, generated graphics, soundtrack, project, output, review stills,
clip-specific notes or extraction/transcription caches during authoring.
Do not consult earlier timestamp-specific editorial feedback as a cut recipe.
Use separate output and temporary directories and a new empty source-specific
cache. Do not clear OS caches, close user applications or delete baseline data
to manufacture a cold-machine test. This is a fresh-input edit, not an OS-cold test.
Do not copy the baseline's clip-specific runtime assumptions into the trial:
old audio hashes, frame counts, donor AAC and cut-dependent checks do not qualify
a newly edited timeline. Derive those facts from the new edit.
The current agents have prior exposure to Attempt A; do not claim that this is
a blinded evaluation. Log any accidental reference access as a limitation.

## Timing and completion

Start UTC and monotonic timing before the first new source inspection, hashing,
transcription, analysis or editorial planning. Record an append-only event log
in the new run directory, with start/end times and outcome for each phase.
Include setup specific to this footage, retries, repairs, rendering and validation
in total elapsed time. Do not restart the clock after a failed attempt.
Record human work and waiting separately while retaining total wall-clock time.
General baseline repair before the fresh trial is outside its clock and must
be disclosed as existing software preparation, not hidden benchmark work.
If a tool defect is discovered during the fresh trial, its repair time counts.

Record distinct milestones for source-ready, transcript-ready, plan-ready,
first-minute preview, full Studio-ready project, exported video and completed QC.
Studio-ready requires actual moving picture, intended graphics, usable timeline,
presenter framing and an audio playback check; opening a page alone is insufficient.
Report objective audio tests separately from actual listening and creative review.
Do not mark user approval if only an agent or automated check has reviewed it.
The two-hour target applies to the complete defined workflow, not rendering alone.
If it is missed, retain elapsed time and the unfinished phase at 120 minutes,
continue the authorized work, and report the actual final duration.

## Comparison after Attempt B is sealed

Finish and save the independent Attempt B before consulting Attempt A.
Record its source/output/manifest hashes and exact qualification limitations.
Only then compare the two on opening engagement, narrative clarity, natural cuts,
usefulness and pacing of graphics, presenter framing, audio continuity,
Studio usability and export quality. Report concrete timecoded examples and
remaining defects. Keep subjective preference separate from objective failures.
Do not revise Attempt B using Attempt A and still call that the independent trial.
Any such revision must be a separately named follow-up with its own timing.
