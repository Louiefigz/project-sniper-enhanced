# Why native Shorts production is taking too long

Date: September 15, 2026. Scope: diagnose the active 55.32-second pricing Short
and compare it with the earlier 56.24-second editor Short. The diagnosis below is
historical; the implementation record tracks the subsequently authorized change.
This is not approval of a new edited video.

## Implementation work — authorized September 15

### Long-form extension — subsequently authorized

Aaron requested the same preparation for long form, a small test, and particular
care to preserve the working pipeline. The current C0679 native project already
uses a cut presenter base plus separate narration. Its archived export is a
qualified fixed package, so it must not be rewritten to add this optimization.

| Requirement/source | Planned action | Evidence/status |
| --- | --- | --- |
| Extend selected preparation to native long form / user | New adapter writes a separate native project, using the existing selected-source engine and exact offsets | Implemented; real preparation/static checks passed, 10.28 GB → 129.75 MB in a 19.90-second owner |
| Protect working pipeline / user | Additive command; preserve legacy cut/base flow, qualified export packages, current source projects, SDK and mastering | Passed: 27-file working-project snapshot and 11 protected production-code hashes unchanged |
| Small compatibility test / user | Two distant passages in a six-second landscape fixture from C0679; compare all original/prepared source frames/audio, render both native projects, check output clock and audio alignment | Passed: all 144 decoded native frames and 288,288 stereo program sample frames identical before/after; source frames/audio also identical; zero sample displacement across both passages |
| Preserve existing narration / working long-form architecture | Standalone complete-program WAV copied unchanged; no changes to audio finishing | Byte-preservation unit test passed; working production project unchanged |
| Reuse and fail safely / standing agreement | Explicit reuse of sealed package; reject changed/missing sources, dynamic/ranged unsupported media and destinations inside originals | Real sealed-package reuse passed; 12 adapter unit tests passed |
| Verify current result / standing agreement | Focused long-form checks plus Shorts regression; original file snapshots before/after; report measured scope honestly | 37 unit/regression tests and mechanical checks passed; supervised native/source comparison passed with verified cleanup |

The [long-form workflow](../producer/NATIVE_LONG_SELECTED_SOURCES.md) records
commands, constraints and the exact before/after evidence. Sample render owners
took 56.83 seconds prepared and 56.68 seconds original; no final-render speed gain
was demonstrated. The working long-form route was preserved, and no full episode
was rerendered or promoted by this test.

The user authorized implementing extraction first and asked whether long form
shares the issue. The following acceptance record supersedes the earlier
diagnosis-only scope for this task; historical observations below remain unchanged.

| Requirement | Planned action | Evidence/status |
| --- | --- | --- |
| Physically prepare only selected sections | Shared supervised source-range package with bounded handles, packet-preserving picture and lossless working audio | Passed: 5.50 GB → 219 MB; final automatic preparation owner 19.21 seconds |
| Use small files in native Shorts | Bind package to original source identities; stage prepared media and remap executable source offsets while retaining editorial source clocks | Direct build CLI wired; real project built and cold-read with 5 small videos and 5 audio files, no full source staged |
| Preserve source, captions, picture and audio | Verify exact mappings, media bytes/packet timing, decoded output, stale/tampered package rejection and unchanged canonical speech plan | Passed: all 1,383 decoded source frames and 2,655,360 stereo sample frames identical; missing/altered/rehashed package and offset tests reject invalid states |
| Reuse preparation across visual revisions | Immutable package receipt admitted by build and cold reader; no new ASR | Passed binding reuse and title-only mapping tests; explicit prepared plan retained |
| Protect active production | Keep ongoing artifacts unchanged and integrate shared edits after its current pinned export | Passed: current task completed its export/playback before shared native implementation edits |
| Explain long-form applicability | Confirm legacy cut-first base versus native full-source project behavior | Legacy cut/base and shared native preview verified by code; native adaptation remains a separate integration |
| Verify implementation | Focused Python/TypeScript tests, type/lint checks and supervised real selected-source exercise | Passed: 54 Python and 38 TypeScript checks; type-check, targeted ESLint and diff whitespace checks; actual default CLI build, cold read and supervised decoded equivalence |

Implementation and measured evidence are explained in
[Cut selected media before native authoring](../findings/CUT_SELECTED_MEDIA_BEFORE_NATIVE_AUTHORING.md).
The direct native Short CLI now prepares missing selected media automatically.
Legacy reads remain supported. The subsequently authorized native long-form
adapter is documented in [its workflow](../producer/NATIVE_LONG_SELECTED_SOURCES.md)
and the extension record above. Stored-guided automation remains separate
integration work. Full-episode native render/Studio performance remains unmeasured.

### Verification scope

- Python: selected sources (10), native pipeline (15), runtime (8), channel
  normalization (3), reference-reuse integration (18).
- TypeScript: project/command/story regressions (29), selected-media behavior (5),
  real completed-package integrity (4). The real-package tests ran against
  `artifacts/selected-sources-proof-2026-09-15/final-project`, with no skipped tests.
- Final automatic build uses the unmodified pricing plan as its input. It adds
  the prepared binding, stages only five small videos and five audio files, and
  passes the source/strategy/cold-read checks.
- The final decoded comparison ran beneath `NativeRun`; its original and
  prepared pictures match at every selected output frame, and its two complete
  dialogue references match sample-for-sample before shared mastering. Cleanup
  completed with no retained owned survivors. No new editorial/video approval
  or total-production performance claim is inferred from those checks.

## Conclusion and accepted direction

Aaron's correction: physically cut the needed sections first, then work with those
clips instead of attaching the entire 31-minute recording to every downstream job.
This should become the first media-processing step after source-wide transcript
review and passage selection. It does not require finishing the long-form edit.

The core solution is a small, reusable package of selected clips shared by native
authoring, Studio and export. Merely restricting the timeline while retaining the
full recording as each element's media file leaves the observed preview problem.
For the pricing Short, the working media should represent its five spoken sections
and any separately selected supporting shots, with bounded trim handles. Six
video elements do not require six separate source copies when views reuse a clip.

Production is still exposing and repairing infrastructure while authoring each
Short. Preview preparation, storage planning and failed-stage recovery add verified
avoidable costs. Creative planning and required review also consume time; the timing
does not isolate every activity or justify a future time promise.

## Requirement and evidence record

| Requirement | Source | Action and evidence/status |
| --- | --- | --- |
| Diagnose the current Short | User request | Active pricing export logs, resource receipts and Studio preparation inspected; current failures identified below. |
| Explain the long elapsed time | User request | Earlier continuous production clock and timing analysis inspected; measured execution separated from unattributed preparation/review time. |
| Propose a durable solution | User request | Prioritized changes mapped to existing owners and explicit acceptance cases below. Proposed, not implemented here. |
| Cut needed sections first and work from them | User's later correction | Selected-clip package becomes the central solution for both editing and export; full-source selection remains upstream. |
| Preserve actual task and concurrent work | Working agreement | Read-only investigation of production; no extra renders, process stops, cache deletion or production-file edits. |
| Verify claims and limitations | Working agreement | Local code inspection, direct receipts, official media documentation and 15 focused recovery tests; no new video/listening certification. |

## Verified problems

### 1. Preview work scales with the recording instead of the Short

The pricing project is 55.32 seconds and retains five spoken passages from a
31-minute-44-second recording. The production task observed Studio launching a
full-source H.264/AAC proxy, with a partial output reaching about 1.28 GB before
it was stopped. The prepared production source uses ALAC dialogue audio.

`managed_preview.py` holds the shared heavy-work lease during startup, then
releases it after server readiness. A later browser request can therefore trigger
heavy conversion outside that startup exclusion. Its comment assumes an idle
lightweight server, which does not describe automatic media preparation.

The task has disabled `media.autoProxy` on this editable review copy. That does
not establish browser codec support or make it a universal preview policy.
Current HyperFrames documentation confirms automatic preview proxies and the
opt-out; installed-version observations above come from this project's receipts.
[Official media documentation](https://github.com/heygen-com/hyperframes/blob/main/skills/hyperframes-core/references/variables-and-media.md).

Evidence: [observed preview behavior](../findings/STUDIO_PREVIEW_CAN_PROCESS_THE_WHOLE_SOURCE.md),
[review preparation](../../artifacts/img7138-pricing-system-test-2026-09-15/STUDIO-PREPARATION.json),
and `scripts/producer/studio/managed_preview.py`.

### 2. Disk admission checks a reserve, not the upcoming allocation

The shared policy requires 10 GiB free disk. The current export's second attempt
passed initial admission, then stopped during source-frame extraction when free
space fell below that reserve. Its media owner lasted 65.43 seconds; the complete
export invocation lasted 82.54 seconds. These clocks include different work.

The production task evicted 20 inactive generated cache entries totaling
22,627,546,878 bytes (22.63 GB), leaving 30.62 GiB at that recorded instant.
Earlier, replacing two new source copies with verified APFS clones recovered
about 5.51 GB. These recoveries occurred at different times and are not a current
free-space total. Sources, finished outputs and audit records were retained.

The successful extraction phase of attempt 3 handled 1,383 selected frames across
six video elements, with six cache misses. This export phase did not extract all
31 minutes; whole-source processing was the separate Studio problem.

Evidence: pricing `export-02/pipeline.render.json`, `export-02/delivery.json`,
`export-03/pipeline.render.log`, `FRAME-CACHE-EVICTION.json` and
`STORAGE-CONSOLIDATION.json`; `native_render_resources.py` fixes the disk minimum.

### 3. Resource contention and brittle stage boundaries add retries

The current first export was refused before child launch because kernel memory
pressure was warning. This is not proof that a 64 GB machine exhausted its RAM
or that Studio was the sole contributor. The previous Short also encountered
an older compressor guard, an eight-minute picture timeout at 1,376/1,406 frames,
and a later reference-capture timeout after picture/audio had completed.

Shared code now separates media generation, native capture and encoded checks,
and supports `--verify-from` for an intact sealed render. I ran its 15 existing
unit tests successfully. They use mocked child execution; this confirms orchestration
contracts, not a newly completed real-video recovery. The picture subprocess still
has a fixed 480-second timeout inside its 600-second owner.

Evidence: `native_short_pipeline.py`, `native_short_resume.py`,
`native_short_worker.py`, and
[previous handoff](../producer/HANDOFF_ONE_SHORT_PLAYBACK_2026-09-15.md).

### 4. Authoring and orchestration remain a major part of delivery

The previous Short's measured continuous clock was 65m11s:

| Category | Duration | Interpretation |
| --- | ---: | --- |
| Successful picture, audio and metadata | 6m43s | Picture alone was about 6m24s. |
| Other measured media work | 16m30s | Necessary checks plus failed/repeated work; not all removable. |
| Outside measured media spans | 41m58s | Source preparation, planning, hand authoring, previews/repairs, critics, orchestration and unmeasured gaps. Not individually attributed. |

The active task also wrote project-specific timing, source-diagnostic, visual
and Studio-preparation scripts. Some implement necessary editorial decisions;
routine infrastructure should move into tested shared commands. The code already
provides caption grouping, exact clocks, audio finishing and native project writing.

Evidence: [timing analysis](../../artifacts/img7138-editor-visual-short-2026-09-15/TIMING-ANALYSIS.json)
and [continuous clock](../../artifacts/img7138-editor-visual-short-2026-09-15/EDIT-TIMING.json).

### 5. Successful encoding and dependable review are separate requirements

The prior MP4 passed decode/picture checks but its browser player showed black
until reloaded. Playback code was subsequently repaired and sampled replay/native
controls were verified in the other task. The exact browser-engine cause remains
unproven. Rendering the same valid video again would not establish replay reliability.

## Proposed solution: select, extract, then edit the small package

1. **Extract the selected sections before visual authoring and Studio.** Select
   source-backed passages using the transcript and necessary source review; then
   create reusable full-quality working clips containing only those sections plus
   bounded handles for cut adjustments. Include separately chosen B-roll ranges.
   Bind each clip to original source identity, exact source interval, local offset,
   frame/sample clock and preparation recipe. Native authoring and export consume
   this small package; Studio uses those clips directly where compatible, or small
   compatible review derivatives prepared under supervision. Keep the original
   recording available as source evidence and for selecting additional material.
   Preserve the independent editable graphics and dialogue tracks. Rebuild affected
   mappings/audio when cuts change beyond the prepared bounds. A fast keyframe
   remux and an exact arbitrary cut are different operations; verify retained
   picture/audio boundaries and color before admitting prepared clips. Reuse the
   existing cut/timing and native asset-admission utilities through a shared command.
   This changes downstream media scope; it does not remove source-context review.
2. **Budget scratch space before extraction.** Inventory cache hits and missing
   frame ranges; estimate decoded-frame storage, output/audio/temp files and
   reserve with a safety margin. Bound the cache to available capacity and evict
   only inactive reproducible entries under ownership checks. Count source staging
   and preview conversions in the same admission decision. If the work cannot
   fit, stop before expensive extraction with a required/free-space explanation.
3. **Make stage recovery the normal execution path.** Build on existing render
   seals and `--verify-from`; after a capture/check failure, retain finished media
   and rerun the failed/dependent checks. Never reuse stale dependencies or silently
   change render routes. Eventually preserve qualified capture stages too, using
   the existing evidence helper. Derive a bounded deadline from workload and observed
   throughput; keep independent no-progress, resource and cleanup limits.
4. **Turn repeated production mechanics into shared components.** Read the full
   retained script early, reuse verified transcript/microphone preparation, and
   select catalog components for the story's actual explanatory need. Parameterize
   proven title, caption, presenter and explanatory graphic components. Keep editorial
   choices and required independent review; a fixed layout is not suitable for every
   story. A title/graphic revision should not rerun transcription or unchanged audio
   processing. Asset staging should report whether it cloned or copied and avoid
   unnecessary repeated reads without weakening source-integrity checks.
5. **Expose one continuous delivery clock and clear stage status.** Record source
   review, planning, preparation, queue time, rendering, QC, replay and repairs.
   Show the current stage and what survives a retry. Treat missing listening review
   explicitly. Keep code/tool versions stable during each attempt and qualify the
   complete workflow before calling it routine production.

Selection-only review media is technically feasible, but exact cuts need careful
handling: FFmpeg stream copying can retain material from the preceding seek point;
accurate transcoding decodes/discards that lead-in. Preserve rational source/output
mapping and test joins rather than assuming an arbitrary stream copy is exact.
[FFmpeg seeking documentation](https://ffmpeg.org/ffmpeg.html#Main-options).

## Implementation priority and proof of success

First fix shared preview preparation and storage admission. Use the existing
stage-recovery work for later failures. Then consolidate authoring mechanics and
measure throughput before considering more invasive renderer optimizations.

Acceptance cases:

- A Short using distant passages from the same long source opens in Studio
  without a full-source transcode; source pictures, dialogue and editable graphics
  match the selected revision in actual play and seek checks.
- A near-full-disk case either clears eligible cache safely or refuses before
  extraction; no mid-run disk exhaustion from an unbudgeted expected allocation.
- A forced post-render QC failure resumes with identical final media and zero
  additional picture/audio encodes, retaining all mandatory checks and cleanup.
- Caption/title-only revisions reuse valid source analysis and eligible audio;
  changed cuts invalidate the appropriate mappings and receipts.
- Fresh play, end, replay and seeking show picture and accurate player status.
- Five representative Shorts include cold/warm cache cases and a revision; report
  complete elapsed times, failure/rework time and review quality together. This is
  a proposed qualification cohort, not a completed benchmark or a universal guarantee.

## Verification performed in this audit

Read active artifacts, relevant shared implementation and both tasks' timing/
handoff evidence. Ran `.venv/bin/python scripts/producer/tests/test_native_short_pipeline.py`:
**15 passed in 0.150 seconds**, without rendering or provider calls. The initial
pytest invocation could not run because pytest is absent in that venv; the suite's
native unittest entry point completed successfully. No production code was changed.

At 18:26:42 UTC (1:26:42 PM Chicago), pricing attempt 3 was still rendering,
with 509/1,383 streaming frames logged and no final delivery receipt. This is a
timestamped observation, not its eventual result. Final pricing playback and quality
approval belong to the ongoing production task.
