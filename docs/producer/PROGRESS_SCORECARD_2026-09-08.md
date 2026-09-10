# Sniper development progress scorecard

Baseline date: September 8, 2026.
Prepared in the task “Assess Sniper enhancements progress” from the current
implementation records and a live snapshot of “Assess Project Sniper enhancements.”
This is an analyst-defined planning metric, not a release decision or a time estimate.

**Development: 60 / 100 weighted points complete; 40 / 100 remain.**
**Real-video release acceptance: none of the three bundled milestones below closed.**

The weights and stage assignments are engineering judgments, made explicit here
so future updates use a stable method. The arithmetic is reproducible; the weights
are not measured historical labor. Do not describe 60% as statistical confidence,
60% of elapsed engineering hours, or proof the editor is ready for use.
This is the first scored baseline. Earlier conversational 50%, 65%, and 70%
estimates used no comparable model and cannot establish a trend or regression.

## Scope and ownership

Score the existing video-editor enhancement scope: local footage preparation,
authored cuts, collaborative treatment, catalog-first graphics/transitions,
presenter/presentation layouts, captions, audio/color finishing, full-video
execution, Studio review, scoped revisions, and the retained one-request policy.
Short/long variations are included within the applicable rows, not counted twice.

Presenter framing means full talking head to inset/bubble/split and back, with
the presenter visibly in frame. Continuous face-following is not required.
Studio scope is the existing base-video plus editable-graphics projection and
its round-trip; a fully native source/effect timeline is not required.
Catalog discovery includes the broader inventory and selective reusable ports,
not mandatory integration of every item before the editor can be useful.
Human decisions are legitimate in guided mode; they are not missing automation.

SDK experiments and selective external workflow ideas are implementation choices
under the existing rows. They earn credit only by advancing those capabilities.
This document does not add tasks, waive gates, activate a renderer, authorize
resource-intensive runs, change approved scope, or assign work to another agent.
The implementation agent continues to own its working checklist and code.

## Scoring method

Each row receives one evidence-supported development stage:

| Stage | Development credit | Required evidence |
|---|---:|---|
| Not started | 0% | No usable implementation for this requirement |
| Foundation | 25% | Reusable engine or prerequisites exist; requested feature wiring is largely missing |
| Partial implementation | 50% | Material requested behavior and focused tests exist; major route connections remain |
| Connected implementation | 75% | Main command/component path is connected and tested; remaining supported cases or integration defects prevent completion |
| Development complete | 100% | This row's bounded implementation is callable and has applicable integration/media evidence, with no identified missing coding requirement for that scope |

Real creator acceptance and whole-workflow performance are tracked separately.
A 100% development row is not a claim of arbitrary-media support or an approved
whole video. Test counts, documentation length, and repeated audits earn no
additional credit. A partially completed new feature cannot receive 100% merely
because its older underlying engine works.

Formula: completed points = sum(weight × development credit / 100).
Remaining development points = 100 minus completed points.
Weights total 100 and stay fixed for comparisons against this baseline.

## Baseline assignments

| ID | Workstream | Weight | Credit | Completed points | Evidence and remaining coding |
|---|---|---:|---:|---:|---|
| S1 | Source preparation and local transcription | 10 | 100% | 10.00 | Existing immutable media preparation, multiple-source manifest handling, and local transcription; actual C0679 transcription is retained. Acoustic word-boundary correction is S2; source color is S7. No new ingest implementation gap is identified for the existing supported class. |
| S2 | Authored cuts and source-word corrections | 15 | 75% | 11.25 | The source-plus-brief author-cut command and bounded timing/text correction consumers are implemented and regression-tested. Actual model/source/preview integration still needs exercise, and unsupported correction combinations remain explicit. |
| S3 | Collaborative treatment planning and approval | 10 | 75% | 7.50 | Guided cut/treatment/opening commands, pre-opening brief replacement, and new approval/status dispatch are connected and tested. Complete clause coverage and the latest body handoff are not finished. Post-master revisions belong to S9. |
| S4 | Catalog discovery, graphics, transitions and B-roll | 10 | 50% | 5.00 | Curated renderable templates, semantic selection, transition/B-roll engines and a broader catalog mirror exist. Full-catalog-first discovery, selective retained integration and supported guided effect execution remain incomplete. The current catalog refresh is separately approval-blocked. |
| S5 | Presenter inset, bubble and split layouts | 10 | 50% | 5.00 | Requested layout primitives, authoring and partial opening/body bindings have actual small renders and native 1080p pixel-preserving optimization evidence. Complete production activation, framing/clearance integration and full-body consumption remain. |
| S6 | Captions and graphic text fitting | 10 | 75% | 7.50 | The default full-program caption route executed in a synthetic chain; caption-page reuse and complete-copy repair are implemented. Combined-output overlaps, supported styles/grouping and final layout integration remain. The failed visual run is not accepted output evidence. |
| S7 | Dialogue/music/SFX and source-aware color finishing | 10 | 25% | 2.50 | Existing audio engines and substantial music/source-color prerequisites are available. Requested guided gain/enhancement/SFX and source-aware grade application are still missing or not executable through the completed route. Metadata validation is not a finished color grade. |
| S8 | Full-video execution, recovery and efficient reuse | 10 | 50% | 5.00 | A synthetic baseline cut/opening/body/master chain and numerous real effect optimizations exist. The new source-color/presenter body path, cancellation/recovery boundaries and complete integrated performance remain unfinished. Raw render time is not total editing time. |
| S9 | Studio round-trip and scoped post-render revisions | 10 | 50% | 5.00 | Base-plus-graphics Studio generation/sync and older scoped edit engines exist. Current-workflow handoff, accepted finishing-intent changes and post-opening/body/master revisions with verified reuse remain incomplete. |
| S10 | One-request orchestration | 5 | 25% | 1.25 | Ordinary auto-edit provides reusable orchestration. The enhanced direct source-plus-brief command deliberately stops for guided cut review; the complete supported one-request policy remains missing in the current checklist. |
| | **Total** | **100** | | **60.00** | **40.00 weighted development points remain.** |

The guided-only subset S1–S9 is 58.75 / 95 points, or approximately 62% complete.
Use the full 60% score for the retained enhancement scope; do not switch between
these denominators when presenting a trend. This distinction accounts for the
existing one-request requirement without treating human help as a defect.

## Real-video release acceptance: separate from development

These three bundles are all open. Their count is an acceptance checklist, not
another estimate of how much code exists.

| Milestone | Current status | Closure evidence |
|---|---|---|
| R1: Representative real short and long output | Open | Real admitted footage through the actual current writer/cut/brief/opening/body path; complete requested treatments; actual picture, audio, text, framing and color review. A synthetic chain or fabricated human approval does not close this. |
| R2: Real revision and Studio round-trip | Open | Revise a completed master through supported commands and Studio, preserve unaffected material and human changes, verify the resulting complete output and recovery behavior. |
| R3: Whole-workflow quality and time qualification | Open | Required comparison/confirmation cases, retained failures, all preparation/generation/retry/review clocks, and demonstrated quality within the agreed workload. The 120-minute generation allocation is not proof of roughly two-hour raw-to-finished total time. |

Development 100% plus R1–R3 closed is required before calling this scope complete.
No estimate of remaining calendar or agent hours follows from the weighted score.

## Source evidence

- [Current completion checklist](REMAINING_WORK_COMPLETION_CHECKLIST.md): current requirements, verified foundations, and the six explicit missing-code categories.
- [Active implementation record](ACTIVE_IMPLEMENTATION_2026-09-07.md): latest source-color/approval/body work, actual media evidence, failed attempts and limitations. Prefer its newest continuation over stale historical pending text.
- [Command workflow](CODEX_COMMAND_WORKFLOW.md): clarified scope, current source preparation, direct authored-cut command, review and body boundaries.
- [Studio review lane](STUDIO_REVIEW_LANE.md): actual projection/sync behavior and unsupported edits.
- [Two-hour plan](TWO_HOUR_VIDEO_EDITOR_PLAN_2026-09-06.md): workload, finishing and timing acceptance. Later Codex-first and framing clarifications supersede older UI/tracking wording.
- [Catalog mirror boundary](../../vendor/hyperframes-catalog/README.md) and [catalog study](catalog-study/CATALOG_STUDY.md): discovery versus integrated rendering.
- Live working-task snapshot at assessment: the 70-test approval/body handoff suite passed; missing body-input records for reusing approved preparation were still being added. This is handoff evidence, not actual picture/sound qualification.

## Updating this metric

1. Preserve this dated baseline and its fixed weights.
2. Advance a row only when its next stage is supported by concrete code and test/media evidence; identify the newly crossed boundary.
3. Record old/new stage and weighted point delta. More tests within the same stage do not move its score.
4. Preserve failed real runs and open acceptance bundles. Move a row backward only for a real regression, explaining why.
5. Treat new user-requested scope as an explicit versioned denominator change; show its effect separately from implementation progress.
6. Keep developer progress, creator acceptance and estimated remaining time distinct in status reports.
