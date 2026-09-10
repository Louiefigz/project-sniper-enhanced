# Development estimate after the HyperFrames upgrade

Assessment date: September 8, 2026. Read-only implementation review in the task
“Assess Sniper enhancements progress”; the implementation task remains active.
This report does not change its requirements, approvals, or completion checklist.

## Scope of this estimate

The user's assisted workflow: approximately 20 minutes of supported raw footage,
collaborative cut/treatment decisions through Producer, supported catalog graphics,
presenter-to-presentation layouts that keep the presenter in frame, captions and
audio/visual finishing, MP4 output, and the existing Studio graphics round-trip.

Human decisions are intentional. Custom dashboard polishing, continuous face
tracking, porting the entire catalog, and a new fully native source/effect timeline
are not prerequisites. The wider retained one-request and source-qualification
requirements remain on the implementation checklist; they are not silently closed
by this narrower usability estimate.

## Verified changes and boundaries

- Root SDK and motion CLI declarations now both pin HyperFrames 0.8.31.
- The upgrade record documents the installed native runtime and actual container
  image probe. That record separately reports unfinished render qualification.
- Independently reran `npm run test:sdk`: 14 passed, zero failed/skipped;
  TAP suite duration 1.454 seconds. This is structural SDK compatibility evidence,
  not a browser render, production command, or final-video quality result.
- The adapter uses installed SDK parsing, declared-variable mutation, patch/inverse
  inspection, serialization, and reopening. The returned operation remains
  proposal-only with `applied: false` and `renderVerified: false`.
- Searches found the adapter's library callers in its tests; it also has a bounded
  standalone JSON entrypoint. Production command/publication integration remains
  explicitly unfinished in the upgrade record.
- The catalog mirror predates this upgrade: 371 installed entries from the old
  registry snapshot. It is reference material, not 371 newly enabled capabilities.
  The current upgrade is qualifying the 53-template integrated catalog separately.
- The latest recorded catalog attempt stopped at the new renderer's output-space
  check before rendering. The implementing task is repairing resource compatibility
  and checking declared runtime identity. Do not interpret an old checklist's
  approval-blocked wording as the latest upgrade state.
- Recent body/controller and Studio synchronization fixes are substantive separate
  progress. They are not hours saved specifically by changing HyperFrames versions.

## What work is avoided

The SDK supplies reusable composition parsing, typed edits, patch/inverse mechanics,
serialization and timing inspection. This reduces the bespoke graphics-editing
machinery needed for supported revisions. Sniper still owns the connection to its
plan, source timing, saved edits, actual render, and final output checks.

**Planning estimate: 8–24 focused engineering hours of future bespoke graphics
work could be avoided**, compared with completing equivalent bounded editing
without this SDK. This is a counterfactual engineering judgment, not measured
labor. Upgrade/adaptation costs remain, so net hours already saved are unknown.
Do not count pre-existing HyperFrames rendering or the old catalog mirror again.

No whole-video render-speed gain has been demonstrated by this upgrade. SDK test
duration, dependency-install time and earlier unrelated render optimizations are
not valid measures of end-to-end editing time saved.

## Remaining effort for the assisted workflow

These ranges are judgment-based implementation and testing allowances for work
with Codex, not estimates of a human implementing everything without assistance.
They include repairing ordinary integration failures, but have not been calibrated
against a measured completed-feature throughput.

| Work | Focused hours |
| --- | ---: |
| Finish runtime/catalog qualification and resolve upgrade incompatibilities | 4–8 |
| Connect SDK revisions, selected catalog reuse and Studio publication/readback | 8–16 |
| Complete guided opening/body execution and presenter/caption/graphic combinations | 12–24 |
| Connect requested audio controls and ordinary supported-source color finishing | 10–24 |
| Exercise real long-form output, revise it, inspect picture/sound and address timing defects | 12–24 |
| Total | 46–96 |

Use **roughly 50–100 focused hours** as the rounded planning budget. At eight
productive hours per day this is roughly 6–12.5 working days. It is not a promise
of completion within 50–100 uninterrupted wall-clock hours: approvals, rendering,
resource contention, usage limits and discovered defects affect elapsed time.

This is a low-confidence estimate for dependable assisted use on supported media.
It does not forecast closure of every wider release case or the special C0679
wide-gamut problem. The current wider checklist still governs full completion.
The approximately two-hour raw-to-finished editing target remains unproven.

The next estimate should use a complete current-version real-video run and a real
revision: record elapsed time, human decisions, missing features, failed attempts
and fixes. That supplies actual throughput evidence instead of another percentage.

## Evidence

- [Upgrade record](HYPERFRAMES_0_8_31_UPGRADE_2026-09-08.md)
- [SDK adapter](../../scripts/producer/studio/sdk_scene_variable_proposal.mjs)
- [SDK tests](../../scripts/tests/sdk_scene_variable_proposal.test.mjs)
- [Completion checklist](REMAINING_WORK_COMPLETION_CHECKLIST.md)
- [Command workflow](CODEX_COMMAND_WORKFLOW.md)
- [Catalog study](catalog-study/CATALOG_STUDY.md)
- [Catalog mirror boundary](../../vendor/hyperframes-catalog/README.md)

The existing weighted progress baseline is preserved. Installing a dependency or
adding tests does not automatically move a workstream to its next completion stage.

## Updated remaining effort after parallel implementation

Historical estimate checkpoint: the integration blockers and live-audio status
below have since been superseded by the later integration checkpoint at the end
of this document. Preserve this table as the basis of that estimate, not as the
current list of unresolved defects.

Checkpoint: all 53 fresh catalog renders published; actual warm SDK card revision
passed; Claude exported a frozen audio package; independent tail checks passed.
Two reproduced audio reuse-consistency issues still prevent integration. The live
audio implementation remains unchanged. This update uses the SAME assisted-use
scope and five work categories above; it does not redefine full release scope.

| Work | Previous allowance | Current remaining allowance | Reason |
| --- | ---: | ---: | --- |
| Runtime/catalog qualification and upgrade compatibility | 4–8 h | 2–4 h | Native catalog publication and actual launch/cancellation checks completed; affected regressions and compatibility reconciliation remain. |
| SDK revisions, selected catalog reuse and Studio publication/readback | 8–16 h | 4–8 h | A real targeted warm card revision passed; complete current-workflow saved-edit/Studio integration remains. |
| Guided opening/body and presenter/caption/graphic combinations | 12–24 h | 12–24 h | No evidence closes the complete requested production path yet. |
| Requested audio controls and supported-source color finishing | 10–24 h | 8–20 h | Audio code and native tests exist in Claude's snapshot; two reuse defects, final checks, caller integration and remaining color work are still required. |
| Real long-form output, revision, picture/sound and timing fixes | 12–24 h | 12–24 h | No complete current real-video-and-revision acceptance evidence closes this work. |
| Total | 46–96 h | 38–80 h | Rounded planning range below. |

**Updated planning budget: roughly 40–80 combined focused agent-hours remaining.**
This replaces the earlier rounded 50–100-hour allowance for this same assisted-use
scope. It is not 40–80 hours per agent. Parallel independent work can overlap in
elapsed time; final integration and output verification have dependencies.

These remain low-confidence engineering allowances, not measured remaining labor
or a guaranteed elapsed-time forecast. The range reduction credits observed
milestones; it does not claim a measured number of hours saved or change the
weighted completion score automatically. The two-hour editing target, special
source classes and wider release boundaries remain as described above.

## Later integration checkpoint — main Codex report

The main implementation task reported the following after the third Claude
catalog-discovery assignment became active. These are integrator-reported results;
the coordinating task has not independently rerun these checks.

- SDK, CLI and linter 0.8.31 plus all 53 refreshed native catalog probes are live.
- Reviewed route/cleanup fixes, the frozen audio package and the separate
  ACTIVE-pointer shape correction are now integrated into live code, with exact
  hashes matching the tested isolated copy. The two audio reuse defects and the
  residual ACTIVE-shape defect are resolved in that reviewed scope.
- Reported validation: 32 live cleanup/import tests, 43 Python metadata tests,
  seven real ordinary audio/assembly cases in 37.75 seconds, TypeScript checking
  in 7.79 seconds, and default lint with zero errors and 41 warnings in 20.88
  seconds. These timings are test timings, not full-video throughput evidence.
- All 445 original TypeScript test files were reached across retained split runs.
  This was not one all-green suite invocation; five cases remain explicitly
  skipped and unverified.
- Guided finishing and the audio revision-dependency follow-up remain isolated;
  actual graph revision tests and the Studio audit are ongoing. Live audio
  correctness does not establish full guided-control or creator-video acceptance.
- The independent Claude assignments are caption controls and catalog discovery.
  Each delivers its own implementation plus a separate shared integration patch.
  Their assignment does not establish package completion or integrated acceptance.

This supersedes earlier wording that the live audio implementation is unchanged
or that those reproduced audio correctness defects still block integration.
No new remaining-hour estimate or completion percentage was supplied. The earlier
40–80 combined-hour range remains a historical planning allowance, not a freshly
recalculated forecast or a claim that parallel work divides elapsed time by three.
Current detailed evidence is maintained in the upgrade and active implementation
records; a complete real long-form output and revision remain unproven here.

## Subsequent checkpoint — both parallel packages delivered

The main Codex task has now read the completed caption-controls and
catalog-discovery handoffs. Both packages are delivered and awaiting live
integration. Keep them frozen; Codex owns reconciliation rather than having
parallel agents apply shared hunks or reopen packages independently.

Codex reports guided inherited-finishing, the screened-body correction and shared
helper pins in its isolated integration copy, with 86 distinct TypeScript cases
across two runs, 47 Python cases and TypeScript checking passing. A native entry
fixture remains underway. Caption V9 is reserved for selected captions; the
proposed post-cut audio V9 must move to a reconciled later version.

An actual SDK 0.8.31 Studio smoke test exposed automatic ID stamping, premature
icon visibility and font/CDN fetches despite CLI options. Lifecycle/normalization
fixes remain isolated, with a localhost sandbox used only for testing. These
findings are unresolved combined-workflow qualification work in this report, not
evidence of full Studio acceptance.

These are integrator-reported checkpoints, not checks rerun by the coordinator.
Parallel work has produced two delivered handoffs awaiting integration while
Codex continued its own work; it has not yet established a measured elapsed-time saving, a new
remaining-hour estimate, or complete real-video-and-revision acceptance.
