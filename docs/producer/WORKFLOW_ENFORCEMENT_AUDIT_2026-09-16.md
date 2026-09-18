# Critical workflow enforcement audit

Status: mandatory wiring implemented; focused and real-media qualification passed.
Repository-wide verification results are recorded below. This is not approval of
Trevor's video, a production deployment, or a ten-minute editorial benchmark.

Aaron requested mandatory long-export wiring and an audit of critical workflows
that depend on instructions. Scope: Producer native and compatibility editing,
preparation, render, recovery, review and delivery entry points, and their shared
source/resource/authority controls. The executable matrix inventories **50 API
routes in 19 groups**. Critical shared boundaries were traced in code; the matrix
also preserves unsupported and unqualified product paths. Separate publishing,
RAG, Clipper and Segmenter applications are not consumers of this render workflow.

## Instruction-to-result record

Short automatic recovery follow-up (complete): Aaron authorized closing the
Short-specific discovery gap. Acceptance: the normal Short export selects and
registers attempts under the shared reservation; compatible sealed media/capture,
qualified picture and prepared audio can be reused without flags; changed inputs
or policy cannot reuse old work; active owners and corrupt selected evidence fail
closed; explicit recovery remains supported. Evidence: 493 native Python tests,
79 focused recovery/authority tests (a subset), and the real, explicitly synthetic
Short lifecycle in `short-integration-05` below. TypeScript type checking and the
fixture's lint check passed. No production or human review approval is implied
by technical fixtures.

| Requirement | Source | Implemented boundary | Evidence |
|---|---|---|---|
| Native jobs cannot silently omit the shared export checks | Current request; PIPELINE.md | Public adapter selector, common owner admission, guarded installed SDK/capture CLIs | Python workflow enforcement tests; Node export guard tests; actual export lifecycle |
| Compatible completed work is selected without remembering a resume flag | Current request; prior recovery audit | Bounded sibling + per-project immutable history discovery under a project reservation; existing stage proofs remain mandatory | Automatic recovery tests; actual recovery across output parents |
| New exports require current recorded editorial review | Native prebuild doctrine | Short strict export reader; Long complete-project review using the existing TS validator | Missing/stale/failed/provenance tests; changed media changes review binding |
| Long delivery reaches the shared review package | Local MP4 + Studio handoff rule | Actual Long delivery/capture seals admitted; original visual HTML preserved, checked AAC copied to editable fork | Actual bundle publication and cold read; HTML byte-preservation tests |
| Explicit reference matching remains attached to Long export | Reference reuse doctrine | Persisted `LONG-PROJECT.json.referenceMap`; map/source/catalog pins included in review and export | Real mapper tests for current, changed and stale evidence |
| Alternate HTTP routes retain the same review/QC requirements | Canonical pipeline | Old render/assemble URLs delegate to saved-plan Auto Edit controller | Production bridge tests; route-matrix and mutation-route tests |
| Remaining critical paths enforce their own prerequisites | PIPELINE.md; executable matrix | Existing source admission, stored intent, gates/review, mutation leases, final approval and downstream readers traced | Existing regression suites plus the inspection table below |

## Nine gaps closed

| Before | Now |
|---|---|
| Generic native ownership accepted per-video wrappers; callers could avoid the shared export sequence. | `native_export.py` chooses exactly one declared adapter. `NativeRun` admits only the official worker/phase/output vocabulary for native exports, and the installed SDK render CLI requires the active owner and exact request. Nested remote `render` and `render-batch` commands cannot bypass it. Long picture launch requires passed encoded seams. |
| Recovery required a remembered `--resume-from` path; choosing another output parent lost discovery. | Normal Short and Long invocations discover compatible completed work across sibling attempts and immutable per-project history under a shared reservation. Short also selects independently proved SDK/batch picture and qualified float/AAC audio. No duplicate fresh work after a matching active/interrupted attempt; no quiet rerender after a corrupt selected seal. |
| Native Long editorial review existed only in instructions. | New Long exports require `PREBUILD-REVIEW.json`, the complete current project digest, seven coverage assessments, pinned evidence and a separate declared reviewer with a passing plan review and no material issues. |
| Historical unreviewed Shorts were readable, and export used that permissive read too. | Historical inspection remains possible. New export uses strict `check-export` and cannot treat historical readability as current review authority. |
| Compatibility `/render` and `/assemble` HTTP endpoints directly ran stages outside the controller used by the current UI. | Both enter that controller with saved-plan review required. Inline plans, another project's plan and review/QC overrides are rejected. Stored intent, source authority, pending-cut guards, mutation leases, planning reviews, gates and final QC remain controller-owned. |
| Shared review preparation understood Short status/manifests and Short-specific canvas/wrapper shapes. | Actual original and recovered Long exports are admitted through their own exact protocol. A Long canvas uses its one complete-program audio segment; scene checkpoints remain Long scene checkpoints. Studio preparation preserves Long visual bytes and does not impose Short wrapper rewrites. |
| Long reference evidence could remain in a separate optional preflight invocation. | A declared Long reference map is read automatically by review binding and export, with exact format/project/readiness and dependency checks. Map or evidence changes invalidate that review/reuse authority. |
| The normal `npm test` command omitted the native Node regression files. | It now runs `test:native`, covering native admission, capture, cache, clock, encoding and QC tests with a bounded runner, one file at a time. New Python/TypeScript gate tests are discovered by their existing default suites. |
| Native dialogue concatenation and the audio review clock were missing from the enforced audio/render registries. | The native concat has a non-exempt program owner, exact normalization dependencies and tests proving a failed normalization stops finishing. The QC clock has an authority-only render classification and mutation coverage. Static discovery now covers both readers and the audio consumer. |

Missing, ambiguous, aliased or changed inputs fail before expensive work at their
admission boundary. Input pins are rechecked after waiting for capacity, closing
the interval in which source bytes could change while a valid job was queued.
Short external review evidence is retained in export pins, and Long evidence
cannot overwrite an earlier input snapshot. Owner status updates publish whole
JSON snapshots atomically, preventing starting workers from reading a partially
written status record. Python readers retry only an observed atomic replacement,
with a three-read bound; malformed or stale evidence still fails.

## Existing enforcement retained and inspected

| Critical workflow | Code authority inspected | Result / practical boundary |
|---|---|---|
| Original media ingress | `ingest.py`, source-set admission and admitted manifest readers | Source admission is required by normal ingest/controller paths. Explicit migration paths do not constitute newly approved delivery. |
| Stored operator intent and cut acceptance | Auto Edit request/saved-plan resolution, `planning-gates.ts`, guided pending-cut authority | Current stored intent, source selection and accepted cuts are required; unsupported/disabled lanes cannot become an automatic permission expansion. |
| Pre-render contracts | `planning-gates.ts` and planning loop | Operator intent, transcript cut, plan lint, hook, template usage, claims, composition measurement and geometry feasibility are required. Missing required gate verdicts fail. Selected reference checks are conditional on recorded reference intent. |
| Independent planning and rendered review | Planning loop, quality loop, review contract and QC authority | Current plan/manifest/authority bindings and sufficient clean rounds are required. Deterministic audit plus composition/editorial reviews precede final promotion. A success-shaped stale checkpoint is insufficient. |
| Concurrent edits and interrupted promotion | `_lib/project-mutation.ts`, promotion readiness/reconciliation | Leases, checkpoint journal and pending guided authority prevent ordinary writers bypassing an unresolved owner. Durable QC promotion is reconciled before another writer. |
| Memory, disk, time and child cleanup | `NativeRun`, native resource policy, heavy-work lease, lifecycle/stage readers | Mandatory for native export phases and review-media preparation. Missing telemetry or unverified cleanup cannot qualify output; duplicate jobs do not acquire independent heavy lanes. |
| Approved final consumed downstream | Quality-policy reader; `palmier/master.py`, `palmier/quality_evidence.py`; push/preflight API admission | Current schema-v2 approval binds final bytes, assembly proof, deterministic audit, planning reviews, rendered reviews, quality summary and coherent completed job. Missing/corrupt managed policy does not silently become legacy approval. |
| New route inventory and product qualification | `short-long-route-matrix-v1.json` and route-matrix test | Every Producer API route must have one declared disposition. Unsupported continuous reframe and unqualified recovery/hybrid/word-repair paths remain explicitly fenced rather than being advertised as released. |

This inventory is not a claim that every function in the monorepo was proven
correct. The strongest coverage here is supported Producer export, recovery and
review admission, plus the shared controller and delivery boundaries.

## Verification

### Short automatic-recovery follow-up

Final real Short lifecycle:
`artifacts/workflow-enforcement-2026-09-16/short-integration-05/`.
The two-second, 50-frame portrait fixture uses actual browser/FFmpeg output and
an explicitly synthetic TEST prebuild review. It uses the production compiler,
strict review reader, shared owner, default SDK capture route, shared audio gates
and public export selector. Its audio profile is explicitly `default-v3` on every
invocation. It is not an editorial performance benchmark.

1. A deliberate regular-file collision at the final destination caused the real
   worker to fail after picture and AAC qualification. The failed attempt and
   all original proof files were preserved.
2. A normal preparation with no donor/resume flags automatically selected that
   picture and AAC. The real worker recorded **zero additional picture encodes
   and zero additional AAC encodes**. A deliberate later capture interruption
   then exercised the coordinator's ordinary failure handler.
3. Public `native_export.py` retried under another output parent without a recovery
   flag. It reused the sealed final media and completed capture and encoded QC.
4. A further ordinary public retry reused both final media and completed capture,
   running only final verification. The final MP4 hash was unchanged, the shared
   Short review reader admitted it, and all failed-attempt files stayed unchanged.

Both checked retries have SHA-256
`10198678746dc9e96430f5ba338048169c155f0075eb722f544347bf8630b91b`.
`integration-result.json` records each assertion; `humanApproved` remains false.

The actual test also exposed a narrow SDK donor rule: it recognized only a
failure in the later audio-quality list, missing the preceding signal gate and
a subsequent metadata failure. The reader now admits those failure positions
only with the existing complete SDK, owner, packet, clock and input proof. It
does not approve failed audio. The deliberately failed signal fixture and two
earlier fixture-authoring errors remain retained in attempts 01–03. Attempt 04
separately passed completed-media/capture recovery; attempt 05 adds actual partial
picture/AAC recovery.

Current checks in `verification/`:

- `short-recovery-native-python-final.log`: **493 native tests passed** (24.7 s),
  including Long recovery and both SDK/batch Short donor readers.
- `short-autoresume-focused-final.log`: **79 focused tests passed**, including
  policy/source changes, active attempts, changed evidence, complete donor-chain
  preservation, cross-parent history, explicit overrides and partial audio.
- `short-recovery-typecheck.log`: repository TypeScript check passed.
- `short-recovery-fixture-lint.log`: new technical fixture passed ESLint.
- Changed Python logic remains below the repository's file/function/parameter
  limits; whitespace validation passed. No render or audio quality gate was loosened.

The earlier repository-wide findings below remain open; this follow-up does not
claim a new whole-repository green run or production deployment.

### Earlier Long and shared enforcement qualification

Final real lifecycle: `artifacts/workflow-enforcement-2026-09-16/integration-09/`.
The four-second technical fixture uses real local browser/FFmpeg output and an
**explicitly synthetic TEST prebuild review**. It does not claim actual independent
editorial review, human listening, production footage approval or browser playback.

1. Real capture and picture encoding completed, then the harness intentionally
   failed before mux/final QC. The ordinary failure handler retained the seals.
2. Public `native_export.py` retried into a different output parent with no resume
   flag. It reused the picture and qualified audio, and performed **zero additional
   picture encodes** before passing final checks.
3. A further ordinary retry reused the finished MP4 and capture evidence and ran
   final verification only; output SHA-256 stayed identical.
4. The shared review bundle prepared an unchanged local MP4, scene checkpoints and
   editable Studio fork. AAC packet identity passed with **zero audio re-encodes**;
   cold read reported unchanged prepared files. Playback approval remained false.

Earlier integration failures are retained, including the denied host telemetry
attempt, two genuine Long/Short handoff-shape bugs, and a receipt serialization
compatibility issue caught and repaired before this result. They are not relabeled successful or deleted.

Focused final checks:

- Native Python regression suite: **474 tests passed** in `native-python-handoff.log`.
- Native Node regression suite: **144 tests passed** with a bounded serial host runner.
- The actual final `npm run test:native` alias passed all **144 tests** in
  `npm-test-native-handoff.log` (17.8 seconds).
- Registry, native channel ordering, early audio and dialogue consistency:
  **43 tests passed**, including two new fail-closed channel-order tests. The audio
  registry now owns 22 consumers (18 program, four asset-only exemptions),
  19 discovered mix occurrences, 18 dependency rules and three boundaries.
- Focused Python reference/workflow/review tests: **66 passed**.
- Final TypeScript prebuild validator, compatibility bridge, project mutation
  wiring and complete route matrix: **15 tests passed** in
  `critical-typescript-final.log`.
- The actual installed runtime returned help successfully and refused both an
  unowned local render and a remote batch render before SDK work, recorded in
  `installed-guard-final.json`.
- Changed Python logic checked for file/function/parameter limits. The final
  owner writes preserve the previous JSON tuple-to-array representation while
  publishing complete snapshots atomically.
- Repository lint: **0 errors, 41 existing warnings** outside the changed TS files.

The isolated production build, final TypeScript type check and real HTTP smoke
checks passed. Both old endpoints rejected review overrides with 409 and routed
valid request shapes to the existing controller, which rejected a nonexistent
project with 404 before provider/media work. The Producer page served 200. This
is server routing verification, not a new complete editorial GUI run.

The repository-wide Python run completed **7,549 tests**, with **10 failures,
42 errors and 16 skips**. A host rerun of the seven modules affected by socket,
process and preview restrictions passed all **74 tests**. Both missing registry
entries were then fixed and passed the 43-test focused run above. These reruns
do not turn the original full-run log into a passing result.

The full host `npm test` run stopped at an older prompt-limit fixture missing its
required target format. Two related incomplete fixtures were also corrected;
production prompt limits and review requirements were unchanged. The initial run
and post-failure continuations completed **350 of 476 default TypeScript files**.
The extra broad sweep was then stopped at a completed-test boundary: its current
28-test adoption file passed and cleaned up before its parent runner was stopped.
The remaining 126 files were not reached in that sweep. This is explicitly **not
a complete green `npm test` result**. The final focused TypeScript checks above
separately passed, including the new prebuild review tests.

An updated concurrent native Node run reported 144 passing tests but timed out
one file's process at 120 seconds. That file and the updated guard passed in
isolation; all 144 native tests passed serially in 17 seconds. The default native
alias now runs one file at a time with the same complete inventory and timeout.
The timeout log is retained rather than relabeled successful.

Logs and exact broad-file coverage are retained in
`artifacts/workflow-enforcement-2026-09-16/verification/`, including
`typescript-broad-coverage.json` and `broad-continuation-stop.log`. Sandboxed
`npm test` failed at host process-identity inspection, and the sandboxed build
could not fetch existing Google Fonts. Host reruns are separate evidence.

### Remaining broader verification findings

| Finding | Evidence / required resolution |
|---|---|
| Eight retained qualification checks reject old or incomplete evidence. | `test_current_system_inventory_check`, `test_comp_rate_matrix`, `test_p0_adversarial_ingress_artifact`, `test_p0_render_effect_parity_artifact`, `test_p2_row1_claim_artifact`, `test_p4_exit_closure_artifact`, `test_p5_compositor_artifact`, `test_p5_review_repair_artifact`. Their original measured qualification must be rerun on current code before claiming those product paths qualified. Updating hashes alone would falsely approve them. |
| The findings-ledger ordering check fails. | `test_learning_loop.test_real_ledger_lessons_parse` sees `LESSON-048` before the earlier lessons. This is a documentation-order issue, not evidence that a render gate can be skipped. |
| A private graphics fixture is stopped by the actual motion audit. | `test_private_graphics_audit_reference` retained an Audit B failure: zero visible hard changes and zero local frame steps for three declared cuts. The gate rejects the fixture rather than approving it; its cut execution/fixture needs separate diagnosis before restoring that broader test. |
| The entire default JavaScript suite has not completed green on this working tree. | The failed prompt fixtures were repaired and rechecked; the additional broad sweep completed 350 files and stopped at a test boundary. The remaining sweep is pending, despite the changed critical paths' separate passing tests. |

These are open verification items. They prevent a whole-repository green claim;
none was hidden by weakening approval, discovery or motion checks. The changed
supported native export and recovery lifecycle has its own current passing proof.

## Compatibility and trust limits

- Old render/assemble API consumers must save the plan first and submit its saved
  project directory. Inline plans and arbitrary manifest overrides now receive
  `409 REVIEWED_RENDER_REQUIRED`. The normal GUI already uses the same controller.
- New unreviewed exports are intentionally blocked. Earlier artifacts/runtimes
  remain evidence for their original implementation, without retroactive approval.
- Review independence and subjective judgments are declared evidence, not
  cryptographic identity or proof of attention. Human editorial, listening and
  actual local playback/live Studio review remain distinct required activities.
- Standalone native projects must record relevant intent, including an explicit
  reference match. Software cannot recover an instruction omitted from its inputs.
- Supported entry points are enforced. An operator can deliberately run a separate
  external renderer or edit local files; that does not create approved workflow
  evidence. Low-level compatibility stage CLIs produce stage artifacts, not a
  substitute for managed final-delivery approval.
- Default test discovery includes the new checks. This repository has no checked-in
  `.github` workflow; remote branch protection was not inspected or changed, so
  this audit does not claim that every future merge is forced through CI.
- Changed source, implementation, tool, runtime, cache or audio-policy bindings
  invalidate reuse. Keep the selected audio profile consistent. Matching
  interrupted owners require reconciliation rather than an unsafe duplicate.
- Studio Long visuals are preserved rather than automatically converted to Short
  wrapper conventions. Actual Studio playback still needs review; bundle creation
  alone does not prove it. No production GUI/provider editorial loop was rerun for
  this server/CLI enforcement change.
- The four-second lifecycle and earlier simple 15-minute stress fixture do not
  establish an ETA for a complex 10–15 minute production edit.
