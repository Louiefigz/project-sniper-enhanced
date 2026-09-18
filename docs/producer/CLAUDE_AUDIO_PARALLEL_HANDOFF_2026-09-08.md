# Claude Code parallel assignment: finish the shared audio path

Prepared September 8, 2026 for Aaron. Aaron has since confirmed that Claude Code
started this assignment. The running Codex task received the coordination note
and explicitly accepted the ownership split. Codex subsequently read
`/private/tmp/sniper-claude-audio-handoff.md` and verified the isolated snapshot,
baseline commit `33e8c16448e5ac22a70016e7b1ba948fefedd7a4` and reported pending
audio/shared-caller/test diff. No audio integration was enabled live. This updated
file is not proof that an already running Claude session has reread the update.

## Latest pre-integration QC request from Codex

**Latest delivery update:** Claude's coordination report now includes BOTH the
separate ACTIVE-shape correction (section 8, frozen September 9 at 02:05:47 UTC)
and the separate revision follow-up (section 7, frozen at 02:01:26 UTC). Their
patch files exist and their SHA-256 values were checked against the report:
`966a5adb838ea1ff6660267d942c39f8133fa46e53000c2a913dd21e4a2ff362`
for the correction and
`e9a18a0cfa9b03c13878df8abfc9ecd232d3f8294ca9d6a2767d54329bcdc66b`
for the follow-up. See `/private/tmp/sniper-claude-audio-handoff.md` sections 7–8
for absolute artifact paths and reported fresh test results. This verifies
delivery, not independent correctness or live integration.

Claude need not recreate those assignments in response to older instructions
below. Preserve the three delivered packages and address concrete integration
review feedback if raised. Codex owns their review, reconciliation and guided
TypeScript integration. The follow-up proves consistent dependency tracking and
no picture-render invocation in its fixtures; Claude explicitly reports no
measured wall-time improvement, so do not advertise one.

**Newest integrator update — frozen package `b1df1b8`:** Codex verified the fresh
frozen audio package, and its independent reviewer confirmed both earlier
metadata races are fixed. Preserve that original package and all evidence.
Codex's live TS regression suffix is under source freeze; it still owns live
integration after the reviewed TS fixes.

One narrow residual needs a **separate corrective patch against `b1df1b8`**:
`held_render_graph.held_active_generation` validates the raw ACTIVE pointer's
graph/receipt hashes but does not enforce the actual closed ACTIVE v1 shape.
A swap at the read boundary to `schemaVersion=2` or to a record with an extra
field is accepted and held, whereas ordinary `load_active` rejects it. The same
generation remains selected: this is a validation inconsistency, NOT a demonstrated
wrong-media or publication exploit.

Reuse the existing ACTIVE shape check. Add two pure regressions for the version
swap and extra-field swap, retain the valid v1 behavior, and deliver the small
patch with its new source/patch hashes. Exact independently retained reproducer:
`/private/tmp/sniper-audio-frozen-review-l6qlsI/raw_pointer_identity.py`, with
`raw-pointer-result.json` alongside it. It checks frozen hashes and uses its own
temporary metadata only; no native media calls or media approval are involved.
Keep this correction separate from BOTH the original frozen package and the
audio-revision-speed follow-up. No broad graph/schema changes, dependency
downloads or paid calls are needed.

Codex has independently reviewed the finishing DSP and five Python integration
changes, verified matching live originals, and applied the frozen correctness
package ONLY in `/private/tmp/sniper-upgrade-build-qOKgnu` for combined current-SDK
regressions. This is not live integration. Codex will audit the separate speed
patch after the ACTIVE-shape correction; coherent invalidation alone does not
establish measured wall-time savings.

**Remaining guided-workflow boundary, owned by Codex:**
`src/lib/server/guided-opening-media-input.ts`,
`src/lib/producer/contracts/guided-presenter-profile.ts` and
`src/lib/server/guided-opening-authority.ts` still reject or flag
`audioEnhance`/`audioGain`. Python admission and lower-level audio output do not
make finishing executable through the complete guided workflow. Keep these
TypeScript changes out of Claude's correction/speed packages unless ownership
is explicitly revised; Codex owns their later integration and actual caller tests.

This update supersedes earlier pending status for the two repaired metadata
races. Their descriptions and evidence below remain historical regression context.

**Latest independent checkpoint — September 9, 01:33 UTC:** the tail fix is
GREEN for all six tested final-impulse/speech-like-tail cases, with exact sample
counts and zero difference from the independently padded reference. The real
`WallBudgetExceeded` direct import is also confirmed. These results supersede
earlier pending wording for those specific checks; they do not close the complete
audio package. See the same shared review report's 01:33 UTC section.

Two remaining metadata issues need a narrow existing-reader repair and fresh
regressions. Reproducer:
`/private/tmp/sniper-audio-current-qc-AeiS7w/reuse_races.py`;
results: `reuse-race-result.json` and `reuse-race-run.txt` alongside it.

- `held_program_selection` uses separate reads to select a master and retain
  graph/receipt paths. A real valid A→B→A generation schedule returns master A
  with graph/receipt B while its returned hashes pass. Use the SAME original
  validated graph read for selection and retained paths/hashes, including the
  inherited reader in `assemble_picture_reuse._graph_authority`. Preserve raw
  agreement; do not introduce another graph or approval framework.
- A pointer hash captured after the loader can override the original
  `candidate.before` hold when input maps merge. The actual `_assert_held` then
  accepts the changed pointer, although `publish_files` correctly rejects the
  original-before mismatch. This is a fail-fast/original-hold defect, NOT a
  demonstrated publication escape. Capture the pointer before the loader,
  recheck afterward and reject conflicting overlapping holds, or check the two
  original hold maps separately.

Preserve the original RED diagnostics, fix and qualify the final frozen package.
No live audio integration has occurred at this checkpoint. The earlier review
details below remain historical evidence rather than proof that a repaired
current version still has the same defect.

**Independently reproduced in the reviewed audio checkpoint.** Read the complete
review before integration: `/private/tmp/sniper-audio-codex-review-20260908.md`.
It identifies the exact snapshot file and SHA-256, executable diagnostic and
retained six-stream actual FFmpeg comparison. Codex has not edited Claude's
snapshot or live audio code; Claude continues to own the correction.

The reviewed `program_finish_bus._dialogue_filter` removes cleanup latency and
then pads the shortened output. That erases the final 1200 source samples for
`voice`/`voice-strong` and final 480 for `voice-rnn`. In the retained one-second
48000-sample fixtures, the interior impulse survives while the impulse at sample
47760 disappears. Matching input padding before cleanup preserves both the final
impulse and the exact original output length.

Correct the current implementation if still affected: append the measured
latency allowance to the input before cleanup, then remove latency and trim to
the exact original sample count. Add final-impulse and speech-like-tail regressions
for each supported chain. Verify content as well as duration, source-picture
alignment and unaffected audio. Existing interior-only checks do not cover this
boundary. Keep this distinct from the separately reported legacy 25 ms delay.
Record the fix/current-version verification, test results and media paths in
`/private/tmp/sniper-claude-audio-handoff.md` before integration. These synthetic
checks do not establish perceptual listening or creator acceptance.

The separate early-SFX suspicion was dismissed: existing seam admission of at
least 0.5 seconds makes the inspected 0.30/0.33-second lead-clamping case
unreachable. Do not add an unrelated SFX timing fix for that suspicion.

### Additional confirmed blocker: cache reuse must preserve cancellation

The same review report now includes an independently reproduced control-flow
failure in `audio/program_master_reuse.py`, at inspected SHA-256
`526e7b09a4967a31d75c5f214b04fd51e25d3d17701c6bd872d97f36980217cc`.
The broad stale-cache catch swallows `WallBudgetExceeded`,
`ProcessDeadlineError`, `TimeoutError` and `PalmierError` from
`load_program_master`, then calls `build_program_master`. The active audio
`Deadline.remaining` path raises `PalmierError`, so that path must also propagate.

Retained actual-helper reproduction, with explicit TEST load/build leaves and
no generated audio:
`/private/tmp/sniper-audio-reuse-review-20260908.xEiYEc/deadline-reproduction.json`.
The adjacent `repro_deadline.py` supplies the runnable reproducer.

Preserve terminal deadline/cancellation errors before the stale-cache catch.
Add no-build regressions for each reproduced exception, including the active
audio deadline path. Preserve the already-correct propagation of
`subprocess.TimeoutExpired` and legitimate rebuilds for stale settings, receipts
or assets. Do not create a fresh time allowance or start work in the hope that a
later media subprocess will notice expiry. Report current-version verification
and fixes alongside the tail regression in the Claude coordination report.

Codex reports the audio-tail fix has been acknowledged and is under review;
the final audio package and live integration are still pending. This new cache
finding is a separate blocker and is not closed by the tail fix.

### Additional source-traced integration blockers

The shared review report contains the complete caller trace and directions for
these findings. They are missing production-call contracts identified in source;
do not describe them as native forged-media or completed-output reproductions.

1. **Authenticate reused-master selection independently.**
   `program_master_reuse` reads both path and expected hash from the mutable
   `program_audio.v2.json` pointer. The loader requires its caller to independently
   bind this selection to held execution/graph evidence. Reuse the existing held
   completion or prior `node-final.inputDigests.audio.programReceipt` selection
   and preserve its lifetime through readback. Graphics/caption revisions cannot
   rely on picture reuse to incidentally perform this check. New completion stdout
   cannot authenticate an old pointer-selected master. Without valid independent
   selection, do not reuse it. Add changed-pointer/foreign-master tests through
   the actual caller; do not build a separate approval framework.
2. **Do not silently omit finishing in standalone v2 output.** The proposed
   integration skips legacy enhancement/gain/SFX for admitted v2, while the
   standalone `render.py` master path still uses the raw bus. The combination
   `skip_graphics=False`, music disabled and requested finishing is not covered
   by base-then-assemble tests. Route that output through the same finished
   program master, or refuse/defer the unsupported combination before expensive
   work and direct callers to base plus assemble. Add the standalone regression
   and preserve no-finishing/legacy behavior. Never seal a final missing a
   requested treatment.
3. **Close adjacent shared-caller regressions.** Preserve the presenter negative
   for malformed `audioGain={gain:1}` using the existing explicit audio-policy
   validator. Moving fields out of the unsupported tuple must not make malformed
   settings valid. Retarget the moved build helper's test leaves in
   `test_guided_body_result_media` and `test_held_program_preparation`, then run
   those actual consumers. Do not delete the negative, weaken checks or count the
   reported 31-file audio cohort as coverage of these additional callers.

Keep live audio integration disabled until these findings and the earlier
confirmed blockers are resolved and independently checked against the final
package. Record precise evidence and remaining supported-path limits in the
Claude handoff report.

### Final packaging checkpoint after the reported fixes

Codex read Claude's report section 5b describing corrections for cancellation,
held-master selection and standalone finishing. Treat these as reported fixes
pending independent checks against a frozen final package; live audio remains
unmodified at this checkpoint.

- Freeze the final source state and record current hashes. Regenerate the owned,
  shared-integration and complete patches from that state against the original
  baseline, and record their hashes. Recheck source identity after the tests; if
  relevant code changes, refresh the affected results and patches.
- Run the new and affected tests against that final state. At Codex's inspection,
  `final-all/SUMMARY.txt` still listed the earlier six graph and six assembly tests
  and omitted `test_program_master_reuse`; that log cannot qualify newly added
  tests. Preserve it as earlier evidence, not the final post-fix result. Include
  exact test identities/counts, commands, failures/skips and the frozen source
  identity in the new report.
- Integration must use the live `color.deadline.WallBudgetExceeded` class through
  a direct import. Do not ship the snapshot-only `ImportError` stand-in. Keep the
  actual exception identity so terminal cancellation tests cover production.
  If the isolated baseline lacks a dependency, disclose and reconcile it rather
  than substituting a class and presenting that as live compatibility.
- Publish the final artifact locations in `/private/tmp/sniper-claude-audio-handoff.md`.
  Codex remains responsible for reconciliation and independent final verification.

## Integration requirements confirmed by Codex

Codex leaves audio implementation and tests to Claude and remains integrator for
shared guided command/opening/body files. Its current SDK/graphics work requires
no audio interface change. Opening and body must continue to use excerpts of the
same finished program and retain the original deadlines. Keep the source-float
refusal until implementation plus actual caller/media evidence support enabling
the requested audio behavior.

At the first interface checkpoint, provide the following to the integrator;
update it when the audio package is ready:

1. The **absolute Claude workspace path**, and confirmation whether any live
   project files were touched. Do not assume the prescribed isolation happened.
2. The **absolute path to the baseline manifest**, snapshot time and source
   checkout/commit identity where available. Include captured file hashes and
   relevant untracked files so Codex can distinguish inherited work from your
   edits. If the baseline was not captured before edits, disclose that; never
   relabel the final modified tree as the original baseline.
3. The intended **audio authority/policy, schema/receipt and cache changes**:
   current and proposed interfaces/versions, consumers affected, dependencies
   invalidated and historical behavior preserved. State explicitly when unchanged.
4. At completion, the audio patch, separate shared-caller integration patch,
   exact tests/results and actual media paths required below.

Write this coordination report to `/private/tmp/sniper-claude-audio-handoff.md`
so the running Codex task has a known read location; keep code, manifests, patches
and media in your isolated workspace and link their absolute paths from it.
This named report is a coordination artifact, not permission to modify the live
project. If it already belongs to another run, preserve it and report your unique
replacement path. No additional test or approval framework is required.

## Why this assignment

The running task, “Assess Project Sniper enhancements,” is currently qualifying
HyperFrames 0.8.31, rendering the catalog, checking actual graphics pixels, and
repairing associated compatibility issues. Its latest upgrade record also reports
the `propose-text` command connected as a candidate-only operation.

Audio is a distinct unfinished dependency. In the inspected code,
`audio/render_audio_authority.py::audio_policy_reason` explicitly rejects
`audioEnhance`, `audioGain`, and authored transition SFX on the source-float path.
The older enhancement, gain and SFX implementations already exist. The shared
float music mixer/master also exists. The task is to connect supported finishing
to that shared path, with actual media evidence, rather than rebuild those engines.

## Paste this assignment into Claude Code

You are implementing a bounded part of Project Sniper alongside an active Codex
agent. You are not alone in the codebase. Preserve all other agents' changes and
adjust to their interfaces. Deliver working code, focused tests, actual audio
outputs, and a small integration handoff; do not stop at a design document.

The current live project is:

`/Users/maintainer/ProjectSniperSource`

Your responsibility is **shared-program audio finishing**: supported local
dialogue cleanup, per-section dialogue gain, existing approved music ducking,
and authored SFX, all feeding the existing whole-program float master.

### Isolation and ownership

1. Work in an isolated checkout/copy initialized from the current working files,
   including relevant untracked implementation files. A worktree from HEAD alone
   will omit substantial ongoing work. Preserve a baseline manifest/diff so your
   handoff contains only your changes. Capture a consistent source snapshot and
   record any concurrent changes that require reconciliation.
2. Do not reset, stash, clean, switch branches, install dependencies, modify caches,
   or edit source in the running agent's live directory. Reuse installed tooling
   without changing it. Keep your outputs and test scratch files isolated.
3. Your implementation ownership is `scripts/producer/audio/` and directly
   associated audio tests/fixtures. Add a focused module only when existing code
   cannot reasonably own the responsibility; follow the repository size rules.
4. Necessary shared caller/schema changes must be a separately identified
   integration patch against your recorded baseline. Codex owns reconciliation
   and activation in the live command/opening/body pipeline. Provide executable
   integration tests, not only prose telling Codex to invent the connection.
5. Do not modify HyperFrames packages/locks, templates, graphics/Studio code,
   presenter or color code, shared render orchestration, global progress records,
   or production approvals in the live project. Do not start a second catalog
   refresh, full render cohort, or competing full regression suite there.

### Read before implementing

- `CLAUDE.md`, `scripts/producer/CLAUDE.md`, `docs/PIPELINE.md`.
- `docs/producer/REMAINING_WORK_COMPLETION_CHECKLIST.md`, especially finishing.
- `docs/producer/CODEX_COMMAND_WORKFLOW.md` and the latest HyperFrames upgrade
  record, to avoid relying on stale pending text in historical logs.
- Existing audio owners: `render_audio_authority.py`, `render_audio_bus.py`,
  `program_mix_bus.py`, `program_master_bus.py`, `program_master_cache.py`,
  `program_master_selection.py`, `program_master_delivery.py`,
  `program_master_excerpt.py`, `held_program_preparation.py`.
- Existing DSP helpers: `audio_enhance.py`, `audio_gain.py`, `sfx_library.py`,
  `audio_mix.py`, `audio_mix_bed.py`, `music_stage.py`, `master.py`.
- Shared callers for context: `guided_opening_audio.py`, `guided_proposal_music.py`,
  `guided_presenter_profile.py`, `render.py`, `assemble.py`.

This is development of the editor. Do not invoke an upstream text-to-video recipe
or start producing an actual creator episode as an unrelated task.

### Implement this behavior

1. Reuse the current plan vocabulary and time map. Validate requested enhancement,
   gain windows and SFX choices explicitly. Invalid, unavailable or unsupported
   choices must be reported before dependent work, never silently omitted.
2. Reuse installed local cleanup filters and models only. Preserve supported
   behavior when no cleanup is requested. No paid APIs, model downloads, source
   uploads, purchases, or automatic provider fallback.
3. Apply cleanup and gain to the dialogue signal before music/SFX are added.
   Reuse the existing smooth gain envelopes and existing transition/SFX timing
   semantics. Do not process the completed mix through voice-only cleanup.
4. Preserve float headroom through the premaster and use the existing single
   whole-program mastering authority. Opening/body audio must be excerpts of the
   same finished program; do not normalize each excerpt independently or cascade
   intermediate AAC encodes through the legacy media wrappers.
5. Bind actual finishing settings and consumed assets to the appropriate
   receipts/cache dependencies. An audio revision must invalidate affected audio;
   a graphics-copy revision must not unnecessarily rebuild unchanged audio.
   Reuse original admitted source dialogue when that dependency is unchanged.
6. Preserve exact source/output timing, sample count, picture bytes, original
   deadlines, cleanup behavior and accepted parent on failure. Extend existing
   lifecycle mechanisms rather than creating a new generic job framework.
7. Preserve historical policy/receipt meaning. A refusal may be relaxed only for
   newly implemented, tested supported behavior with matching downstream readers.
   Simply deleting the current unsupported-audio checks is not the implementation.
8. Supply the narrow integration patch needed for the actual guided callers to
   use this implementation. If another active owner must change a shared contract,
   identify the exact dependency early and continue independent audio work.

### Acceptance evidence

Use focused existing tests first, then tiny real FFmpeg media fixtures. Useful
starting cohorts include `test_program_master_bus_media.py`,
`test_program_mix_headroom_media.py`, `test_audio_enhance.py`,
`test_audio_enhance_render.py`, `test_guided_opening_audio_media.py`,
`test_guided_body_audio.py`, and the relevant existing gain/SFX tests.
Resolve the actual test/import setup from this checkout; do not claim skipped
native tests passed. Run native fixtures serially and avoid competing with the
current catalog render for CPU/memory. These fixtures are not timing benchmarks.

Deliver evidence that:

- Gain changes occur in the requested edited-time interval with the existing
  smooth boundaries, including after a cut removes a middle source passage.
- Cleanup operates on dialogue while authored SFX/music remain present.
- Music follows the requested level/ducking; disabled audio treatments stay off.
- Summed float audio preserves headroom until the final master; output meets
  existing loudness/peak requirements without changing their thresholds.
- Full master and opening/body excerpts agree on the exact sample clock.
- Audio revisions preserve unchanged picture packets and reject stale settings
  or assets; graphics-only changes preserve valid audio reuse.
- Invalid input, a failed render and interrupted publication preserve the last
  accepted parent. Requests cannot become successful by suppressing a lane.
- A real caller-shaped integration test reaches the new audio implementation
  and actual media output, not merely a mocked success record.

Retain a short listenable before/after WAV or MP4 with source/output descriptions.
Use synthetic fixtures and, if already available and authorized, a real speech
sample. Numerical tests are not perceptual listening approval; explicitly report
what was actually listened to and leave creator acceptance to the creator.

### Time and handoff

Aim for an 8–16 focused-hour implementation package. This is a planning target,
not permission to stop with missing required behavior or claim completion early.
At roughly two hours, report the chosen interfaces, baseline test results and any
cross-owner dependency. By roughly four to six hours, aim to show the first actual
finished-audio output. If that is not feasible, identify the concrete blocker and
revise the estimate rather than expand into unrelated architecture.

Finish with: baseline identity; files changed; owned patch and separate shared
integration patch; exact test commands/results including failures; retained media
paths; supported/unsupported cases; and remaining integration steps. Keep your
completion note scoped to audio. Do not mark Sniper complete or infer the overall
two-hour video-editing target from a short fixture.

## Coordination note to send to the running Codex task

I am starting a Claude Code agent on the parallel audio-finishing assignment in
`docs/producer/CLAUDE_AUDIO_PARALLEL_HANDOFF_2026-09-08.md`. Claude will work in an
isolated snapshot of the current dirty tree and own the audio implementation and
its tests. Continue HyperFrames/catalog/SDK and the main guided visual workflow.
Please avoid duplicating its cleanup/gain/SFX/shared-master work, and identify any
audio interface changes you need early. You remain the integrator for shared
command/opening/body files and final real-video qualification. Reconcile Claude's
patch against the current tree at a suitable checkpoint; do not disturb a running
catalog or creator-media job to merge it. Keep existing quality checks and source
approvals. The shared objective is one complete assisted long-form edit plus a
working revision, followed by the remaining agreed qualification.

## Scheduling expectation

The earlier 50–100 hours was a rough effort estimate, not a calibrated two-agent
schedule. This assignment may overlap roughly 8–16 hours of useful work with the
main task. Integration and final whole-video checks still take time. Do not divide
the old estimate by two or promise a deadline before the isolated audio package
and the upgraded renderer have each produced their acceptance evidence.

## Next parallel assignment: audio-only revisions reuse existing picture

Codex explicitly confirmed no ownership conflict with this conditional follow-up.
It is not editing `current_render_graph_nodes.py`, `render_stage_roots.py` or the
pending-base writer/reader. Its current changes concern SDK/CLI/linter, three
cleanup TS modules and fixtures, four route-helper moves and a historical Python
fixture. Keep the performance work as a separate baseline-bound patch after the
corrected audio package is frozen. Do not bundle it into the correctness handoff
or change the source baseline of a running test. Codex will integrate correctness
independently; the complete two-hour editing target remains unproved.

The immediate priority remains the two reproduced reuse-consistency fixes above,
fresh affected tests and a frozen correction package for Codex. Do not abandon
that package to start a broader feature. Once handed over, keep it immutable and
start this follow-up as a separate patch based on a recorded copy/branch of it.
Report the exact selected shared graph files in the coordination report; flag any
scope change beyond the confirmed split. The current visual work and final
integration remain Codex-owned.

Objective: with a valid active render graph and unchanged source/cut/picture,
changing only admitted audio finishing rebuilds the affected audio/master and
delivery without rebuilding unchanged picture. The prior review identified
gain-only changes invalidating `node-timeline.timeline.plan`, `node-base.base.plan`
and the base stage-root projection; unchanged output packets alone did not prove
that picture rendering was skipped.

- Reuse the existing graph and picture-reuse mechanisms. Trace
  `current_render_graph_nodes.py`, the `plan.timeline`/`plan.base` projection
  owners and the pending-base writers/readers that consume their digests.
  A one-line removal from `base.plan` alone is not a coherent fix.
- Keep old policy behavior and complete final/audio dependencies. Changed source,
  cuts, speed, framing or graphics must still invalidate the affected picture;
  finishing revisions must still invalidate the correct audio/master artifacts.
- Test against a real existing active graph. Use a gain-only revision, cleanup
  change, and a supported music/SFX change where their picture inputs are unchanged.
  Assert the actual reuse flag and that picture rendering/encoding is not invoked,
  alongside unchanged picture packets and correctly changed audio. An identical
  result after secretly rendering again is not proof of this optimization.
- Preserve all corrected selection, original-hold, deadline and publication
  behavior. Do not weaken a check or reuse unknown media to claim a speedup.
- Deliver a separate implementation/integration patch, exact regressions and
  bounded before/after revision evidence. Coordinate any native timing run with
  Codex; competing renders make comparative timing unreliable.

This is an optional follow-up within the existing revision-efficiency scope, not
permission to delay integrating the corrected audio package or to expand into
color, custom UI, new orchestration or another cache/approval framework. Preserve
the same workspace/baseline/report protocol as the first assignment.
