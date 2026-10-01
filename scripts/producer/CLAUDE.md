# CLAUDE.md — PRODUCER (`scripts/producer/`)

September 27 timing lineage (A6 timing): `studio/native_run.py` launches every native
child with `native_run_config.launch_environment` — the closed environment plus only the
allowlisted `SNIPER_TIMING_*` lineage (`stage_timing_context.LINEAGE_ENV`), so worker spans
link to their owner span; nothing else from the supervisor environment is copied.
Version-2 rows carry optional `taskId`/`claimEpoch`/`hostTurnId` (`task_scope`, env, or TS
`withStageTimingContext`; an epoch/turn needs its task) and a closed `metadata.activity`
(model, tool, host-slot-wait, native-queue-wait, pressure-wait). Malformed lineage is
dropped and named in `lineageRejected`, never thrown: timing never fails work. TS reads
inherited env lineage only inside `withInheritedStageTimingLineage` (a command launched by
a timed parent; no current command calls it), never implicitly in a long-lived server.
`native_run_admission.py` records queue/pressure admission as `child_span`s under a
journaling owner. `stage_timing.record_handoff` / TS `journalHandoffEvent` append the task
handoff vocabulary (dependencies satisfied → ready → claim requested → host accepted →
execution started → artifact published → consumer accepted → terminal settlement); a
malformed event writes nothing and returns `{recorded: false, reason}`, never throws (the
CLI still exits 1 with that reason).
`stage_timing.py DIR STAGE start|end|handoff` (`stage_timing_markers.py`) writes linked
wall-clock v2 markers in an explicit run (`--run-id`/env/`--parent-span-id`), serialized by
a lock beside the journal; `start --handover LABEL=SHA256` notes the handed-over title/script
identities (diagnostic only; the budget authority owns the batch start and its binding).
`stage_timing_report.py [--run-id]` + `stage_timing_attribution.py` scope the window to the
run's descendant spans, from its earliest (even crashed) production_total start; foreign,
unparented and unknown-lineage spans are reported apart (a legacy run-less window counts
only legacy spans). They separate model, tool, host-slot, native queue, pressure and
publication-to-acceptance time as inclusive, innermost-exclusive and summed-outermost
unions (absent = unknown). Journals stay diagnostics; no
safety decision reads them. Tests: `test_stage_timing*.py`, `test_production_timing_coverage.py`,
`stage-timing-{v2,propagation,fallback}.test.ts`.

September 27 reasoned caption suppression: `canvas.captionSuppressions` (`{startFrame, endFrame,
reason}` rows) is validated in `src/lib/server/native-caption-display.ts` (views and suppressions
partition the Short; each window hides a phrase, never all, and never the whole phrase of a word
spoken wholly outside every window; reasons must be readable text). The compositor emits no caption
in a window, highlights only rendered spans, and an explicit `<!--native-caption-mount-->` that
`native-short-project.ts` mounts extension markup before (`nativeExtensionMount`), since
`caption-0-0` may not exist. Windows and reasons enter the pacing visual hash
(`native-short-pacing-observations.ts`, which also reports visible frames, uncaptioned words and
fragments under the 0.25 s readable minimum), never the timing hash or the audio contract. `studio/native_preview_events.py` names the edges (`native_preview_schedule.py` priority),
`studio/native_review_html.frame_points` adds review stills, and `native_short_capture_checks.mjs`
captures both sides forward and backward and asserts no caption is in or painted inside a window.
Tests: `native-short-{composition,project,pacing}.test.ts`, `native_capture_frame_state` and
`native_short_capture_points` (`scripts/tests`), `test_native_short_regions.py`,
`test_native_review_html.py`, `test_native_capture_reuse.py`.

September 27 host capability gate (maintainer tooling, withheld from the buyer package):
`studio/production/host_conformance/` measures whether Claude Code or Codex can meet the §6
host contract of the orchestration review (identity, idempotent launch, exact handles, replay,
interrupt, tool cleanup, coordinator death, usage). `run_gate.py` runs named scenarios into
path-neutral evidence JSON; Claude mechanics use the loopback `stub_model.py`, Codex scenarios
spend real subscription turns on probe-owned app-servers (`codex_rpc.py`, `ws_unix.py` for
`--listen unix://`). It is not a host adapter and no runtime imports it. The 2026-09-27 run did
not pass for either host; report and evidence are HOST_CAPABILITY_GATE.md and
host-capability-gate/ under docs/producer. Test: `test_host_conformance.py`.

September 27 host work pool: `native_work_pool.py` replaces the single heavy
mutex. `NativeWorkLease.acquire(lane, project)` keeps its API: 'heavy'/'audio'
return a pool member (`native_work_pool_lease.PoolLease`), 'preview-control' stays
the exclusive lease. Members reserve memory/disk against one host budget
(`native_work_pool_policy.py` holds the derivation); FIFO tickets, quarantine and
legacy interop live in `native_work_pool_state.py`/`_observe.py`; state is
`<state_root>/pool-v1`. Without the host record written by `studio/pool_qualification.py`
(`native_work_qualification.py`, `native_work_session.py`) the pool is exclusive.
Qualification profiles (E, September 27): each request's mode comes from the profile
covering its workload. `native_work_workload.py` describes the request from files it already
binds (plan format, receipt stage, canvas duration/pixels, frozen engine identity);
`native_work_profiles.py` validates schema-2 profiles (per-format bounds re-derived from
per-job evidence; a 'mixed' claim needs the jobs' own audio-stage owners overlapping heavy
owners) and selects one. The schema-1 record keeps serving, as `legacy-v1`, whatever no
schema-2 profile covers: Shorts until a Short profile exists, unbound supporting owners and
older clients' unrecorded owners, never Longs. `native_work_pool_mix.py` decides mixes before
capacity: uncovered work starts only on an idle pool (since M-057 it waits as a ticket for the live members;
see the Phase 1 line); profile-admitted
work is refused the same way beside a live exclusive or out-of-profile member, and
terminally beside such a member with unverified cleanup. `native_work_pool_fence.py` is the
one compatibility fence for older pool clients (E3 exclusive members, schema-2 members,
E2 off-root disk and any admission whose disk space is an APFS container, which older
clients key per volume — `native_work_pool_disk.fence_reasons`): while a valid schema-1
record makes older clients run qualified, such a member holds one fence ticket per class
with sequence 0 (`native_work_pool_lease.FENCE_SEQUENCE`), which every older request counts
as ahead of it; while any fence is held (or the request takes one), no request of this
engine counts older requests in its FIFO (`native_work_pool_mix.competing`; counting them
would deadlock, test `test_native_work_pool_liveness.py`).
`native_work_pool_expand.off_root_fence` calls `fence_member()` before a running member
reserves disk on another device. Records carry `poolClient` 2. Rollout rule and trade-off:
older clients never join fenced work (on APFS: any member of this engine) and wait while
new fenced work keeps overlapping; every exclusive or fenced member's record charges the
whole memory budget (`reservationBytes`, raised by `fence_member` via `PoolLease.adopt_charge`
at an off-root expansion) while this engine charges `guardReservationBytes`, so older
clients stay out even after its supervisor dies, until recovery.
The batch forecast (`native_budget_forecast.heavy_lane_capacity(seconds)`) uses the
batch's longest known output. The harness (`run --class-mix`) writes profiles via
`studio/pool_qualification_profile.py` from `studio/pool_qualification_evidence.py`
(nested owners, per-owner summed memory, class and own-audio-stage overlap,
cold/warm/partial cache, admission load and owner CPU receipts, disk, throughput, failures,
cleanup, managed Studio views at start/end). Tests: `test_native_work_profiles.py`,
`test_native_work_committed.py`, `test_native_work_pool_fence.py` and
`test_native_work_pool_mixed_engine.py` (real base-engine client from
`tests/fixtures/base_pool_4a15560/` via `base_pool_driver.py`, both launch orders:
exclusive member, off-root disk, sibling-APFS root), `test_pool_qualification*.py`, `test_native_run_pool_receipt_evidence.py`.
`NativeRunConfig.lane`/`disk_reservation_bytes` select class and disk; `studio/native_run_admission.py`
queues within the owner deadline and records `queueSeconds` (top level, read by
`pool_qualification_evidence`, and in `queue`: ticket, attempts, admitted); `studio/native_owner_queue.py`
gives immediate-refusal owners the bounded queue. Recover one quarantined member or a
legacy marker with `native_work_recovery.py <nonce>`. Disk is charged per shared space
(APFS container or single HFS+/exFAT/FAT filesystem; versioned records;
`native_work_pool_disk.py`). `native_work_pool_storage.py` refuses what cannot be charged
exactly (`DiskUnaccountable`): non-`MNT_LOCAL`, types outside apfs/hfs/exfat/msdos, and
volumes whose IOKit ancestry is not a real Internal/External disk (disk images report
"Virtual Interface"; read in-process, never cached). Earlier engines' member roots are
classified before the ledger lock (`native_work_pool_roots.prescan`: one reused thread per
root, all roots concurrently, bounded by the caller's deadline or expansion tick; timeout,
crash, no root or a late member → charged in every space, named in
`diskChargedInEverySpace`), never inside it. An unreadable member record is waited for while its lock is held and
refuses all disk admission once quarantined; recovery removes it only on a present, free
lock file (`native_work_pool_recovery.py`). A running member
grows its reservation with `native_work_pool_expand.expand_disk` (adds to the admitted
bytes; not queued; child-supplied directories are resolved, opened and classified before
the ledger lock, then re-checked by one lstat each inside): an owner with
`NativeRunConfig.disk_expansion` serves its child's one `<label>.disk-request.json`
(`studio/native_run_disk.py`), retries waitable refusals and sysctl timeouts for 45 s and
records `diskGrant` only after the grown record is durable; a final refusal aborts the
owner (`disk-space`, `disk-unaccountable`, `pool-unsupported-mix` or
`disk-reservation-error`; admission refusals record `disk-unaccountable` and
`pool-unsupported-mix` as well). Admission
retries a sysctl/ps timeout at most twice with deadline-clamped backoff, starts no retry once
the admission deadline is reached, then fails as `host-inspection-timeout` (`studio/native_run_admission.py`); every receipt has
`leaseCleanupVerified` (with `leaseCleanupReason` when false; `studio/native_run_lease.py`). Tests: `test_native_work_pool.py`,
`_interop.py`, `_storage.py` (real APFS/HFS sparse images), `_unknown.py`,
`test_native_work_recovery.py`, `test_native_run_pool_admission.py`.
Long extraction asks for the cache share; Long `capture` binds its samples and
`picture`/`pipeline` their output from `diskProjection` at admission.
Limits: `docs/producer/NATIVE_LONG_EXPORT.md` → "Disk accounting spaces and limits".

September 27 owner reliability (R1): a recorded identity is PID + start time. In
`native_render_processes._anchors`, a recorded process whose PID now shows another
start has exited and is retired (`recycled` in `process_selection`,
`ResourceSnapshot.recycled_registered_pids`): not an anchor, not a violation; the new
holder is owned only through an owned parent. Same PID and start in another group, or a
root whose start changed, is still a violation (`reused_registered_pids`, unverified,
stop). `native_render_process_table.recorded_row` reads a recorded PID that another
user's process now holds through `kinfo_proc` (`public_row`; libproc returns EPERM);
the same start or an unbound identity still fails closed, and the root is always read
through libproc; `process_bindings` refuses unless this process's own `kinfo_proc` and
libproc rows agree. `add_children` re-reads each parent after listing its children and
refuses the sample (`parent-changed-during-child-discovery`, retried) if that PID changed.
Remembered rows at the root PID are judged as the root. `OwnedRegistry.remember_measured`
replaces a retired record with the measured new process and refuses only a group change.
After each verified sample `studio/native_run_lease.py` (`retire_exited`) forgets exited
and reassigned non-root identities (`OwnedRegistry.retire`) and calls the lease's
`retire_processes`, which drops rows only after its own `ps` read shows them absent;
`record_lease_processes`/`release_lease` live there too. At most
`native_work_lease.MAX_RECORDED_IDENTITIES` (4,096) identities are recorded at once;
`ProcessRegistryOverflow` stops the owner as `process-registry-overflow`, and a verified
cleanup still completes the lease. Receipt counters: `identityRetirement`. `ResourceSnapshot` and
`ResourcePolicy` live in `native_render_snapshot.py` (re-exported by
`native_render_resources`). Owner receipts: `cut_preview_io.read_bytes` raises
`ArtifactReplaced` only when the opened file was unlinked and its path names another
regular file; `native_export.active_owner_snapshot` (export, audio, inspection and
capability workers) reopens only on that, at most `OWNER_READ_ATTEMPTS` (5) reads,
never returning replaced bytes. Tests: `test_native_pid_recycling.py`,
`test_native_owner_snapshot_race.py`, `test_native_identity_retirement.py`. See
`docs/findings/EXITED_PROCESS_PIDS_ARE_REASSIGNED_DURING_LONG_OWNERS.md`.

September 27 CPU attribution (evidence only): the direct sampler (`native_render_macos.py`,
payload schema 2) keeps each owned process's rusage user/system CPU, converted from Mach
ticks with the call's own `mach_timebase_info`, and reads fresh per-processor ticks with
`host_processor_info` (`host_statistics` CPU load is rate limited and cached across
processes). The helper emits only CPU readings that pass `cpu_problem` (the parser's own
rule) and reports Rosetta translation or any invalid value as CPU unavailable, so CPU
never withholds the memory reading. `ResourceSnapshot.host_cpu`
(`native_render_measurements.HostCpuSample`) and `ProcessFootprint.cpu_user_ns`/`cpu_system_ns`
carry them; `top` readings have none. `native_render_cpu.CpuTracker` derives deltas bound
to PID + kernel start time: reuse is exit plus birth, a falling counter is excluded, stale
or duplicate readings give no utilization, every processor must advance 0.8-1.2x its tick
rate, 32-bit tick wraps count only when they fit, and intervals over 15 s count only when
every owned identity continued. Each owner writes the interval as `cpu` in
`<label>.resources.jsonl` (raw processor ticks only in the receipt) and the stage summary
(`cpu`), admission reading (`cpuAtAdmission`) and per-poll `cpuLaunchDeferral` in
`<label>.render.json`. No stop, admission or reservation reads CPU.
`native_render_deferral.py` is the launch-deferral hook: admission passes no profile
because no measured profile has shown a throughput or deadline benefit, so every decision
is `launch`. A future `CpuDeferralProfile` must name the qualified pool record and its
evidence; it holds only on a measured busy interval, its hold is bounded, counted in
`cpuDeferralSeconds` (not `pressureWaitSeconds`) and never becomes a refusal. Tests:
`test_native_render_cpu.py`. See
`docs/findings/MACOS_CPU_COUNTERS_NEED_TIMEBASE_AND_FRESH_HOST_TICKS.md`.

September 27 audio owner (C1): only the audio stage's live, admitted owner runs its worker.
`native_export.launch_binding` closes the audio command/request/pins
before admission and `worker_environment` binds `SNIPER_NATIVE_AUDIO_REQUEST`;
`studio/native_audio_owner.py` is the worker side. `require_owned_audio_worker` refuses
(`NativeOwnerRefused`, CLI exit 2, nothing written) before any DSP unless the owner
receipt pinned the exact request, is active, admitted, in time and the worker's
parent; `require_live_supervisor` repeats the parent check before DSP and before
the result, so an orphan never publishes. The stage failure record reads the logged
refusal (`worker_refusal`) and keeps its category (`audio-owner-refused`, or
`budget-exhausted` for a spent deadline). NativeRun records
`supervisorPid`/`productionAllocation` for this. Tests: `test_native_audio_owner.py`,
`test_native_audio_owner_lifecycle.py`.

September 22 ordinary render admission: `render_readiness.py` calls the shared
TypeScript `plan-readiness.ts` validator before `render.py` or `assemble.py`
starts media work. `readiness_preview.py` uses the existing native full-decode
admission and retained receipt reader for bounded early preview evidence. Final
and watermarked draft readiness are separate. No scope/graphics/resume exception.
See `docs/producer/RENDER_READINESS.md` for the agent-authored review bundle.
`ordinary_previews.py` generates/registers bounded ordinary context clips after
deterministic draft admission. `ordinary_preview_media.py` reuses the real
graphics-free base, ordinary compositor and whole-program master; cold base
preparation remains full-program work. `ordinary_preview_windows.py` binds local
reuse and context coverage. `studio/owned_inspection.py` owns each preparation or
window with the shared native resource/cleanup supervisor. None grants a review
or final delivery approval.
Native Short now captures before full render, sharing `check_samples` from
`studio/native_picture_references.py` with Long. SDK source-cache acquisition
precedes capture; final output QC still follows encoding. `native_motion_previews.py`
and `.mjs` automatically generate continuous moving windows and exact whole-master
audio excerpts. `native_review_regions.py` binds their dependencies;
`native_preview_history.py` checks completed owners and the complete retained chain.
`native_motion_review.py` and the shared TS validator require current recorded
independent preview reviews before full picture work. With no `--preview-reviews`,
the export stops at previews and records editorial review as pending.

Preview memory recovery: `native_preview_sections.py` supervises and seals each
window's picture and audio package independently. `native_preview_recovery.py`
discovers exact-input seals and independently validates restored copies in each
worker. Cleanup and existing capacity admission separate successive owners.
`native_render_sampling.py` brackets footprint reads inside one helper;
`native_render_process_table.py` reads SDK-declared libproc identities without
spawning `ps` between samples. Live missing measurements still fail closed under
the existing retry ceiling. See `docs/findings/NATIVE_PROCESS_CHURN_AND_PREVIEW_CHECKPOINTS.md`.


September 16 enforced native export: `studio/native_export.py` is the public
Short/Long selector and common owner admission boundary. The installed native
SDK CLI and capture workers require a live shared owner. `native_long_prebuild.py`
uses the existing TS prebuild validator for complete-project review; Short new
exports call strict `check-export`, while historical reads remain available.
`native_export_history.py` serializes immutable per-project discovery;
`native_long_autoresume.py` and `native_short_autoresume.py` select exact terminal
stages without a resume flag, through their format-specific proof readers.
Short discovery also retains qualified partial picture and float/AAC audio;
the ordinary worker consumes these bindings before any new picture work.
The shared review reader/bundle supports the actual long export protocol.
Compatibility HTTP render/assemble routes delegate to the existing saved-plan
review/QC controller. See `docs/producer/WORKFLOW_ENFORCEMENT_AUDIT_2026-09-16.md`.
`npm test` now includes `npm run test:native` so the native Node guard, clock,
cache and QC regressions run with the ordinary repository checks.

September 16 native long reliability: `studio/native_long_export.py` is the
landscape adapter over `native_short_pipeline.py`'s shared lifecycle.
`native_long_contract.py` validates exact scenes/audio; `native_long_worker.py`
orchestrates phases and reuses shared float/AAC gates; `native_long_capture.mjs` checks full-context
seams and reverse seeks before master; `native_long_sources.mjs` admits projected
allocations and observes real source-frame publication. `native_long_recovery.py` seals picture separately and
resumes exact completed stages. `native_workload.py` and `native_run_admission.py`
add bounded long-job deadlines/progress and capacity waits without weakening the
existing resource owner. The SDK CLI/capture-library patch makes video windows
half-open on both forward and reverse seeks and bounds source-task concurrency.
See `docs/producer/NATIVE_LONG_EXPORT.md`
and its implementation evidence for commands, supported scope and qualification.

September 15 review handoff: Shorts and long-form require both the local checked
MP4 review and a live editable HyperFrames Studio view by default. The owning
interactive task follows `docs/producer/STUDIO_REVIEW_LANE.md` → "Required review
handoff: local playback and Studio"; an export receipt or project file link alone
does not complete that handoff; `studio/native_handoff.py` records it (the September 27 visible
hand-off record below).

September 11 native Shorts entry points: `native-short.ts` prepares local request
packets, builds explicit native strategies and cold-checks projects.
`studio/native_short_export.py` owns local export, shared dialogue delivery and
native/encoded picture checks. It delegates to `native_run.py` with the existing
work lease and resource/ownership utilities. Runtime patches and file transport
live in `studio/runtime/`; generated `.sniper-native-runtime` caches are excluded
from code snapshots. See `docs/producer/NATIVE_SHORTS_WORKFLOW.md` and the
September 11 integration report for the measured three-case scope and limitations.

September 16 upstream review: `src/lib/producer/visual-storytelling.ts` supplies
the shared short/long author and critic criteria. Native Short builds use
`src/lib/server/native-short-prebuild-review.ts` before direct/guided dependent
assembly: strict existing plan-review pass, full authored-input digest, seven
coverage assessments and pinned evidence. `native-short-project.ts` retains and
cold-checks `PREBUILD-REVIEW.json`; historical projects remain explicitly
unreviewed. Only the review reference and generated transport bindings are
excluded from the creative digest; proposal/media checks remain independent.
This verifies a recorded review, not reviewer identity or actual pixel quality.
New native long exports now require the equivalent complete-project review
through `native_long_prebuild.py`; this does not implement a creative controller.
Follow
`docs/producer/NATIVE_PREBUILD_STRATEGY_2026-09-10.md` for the complete brief,
asset/transition plan, independent critique and conditional worker assignments.

September 26 related Short groups: `native-short.ts prepare-related-group`
accepts one bounded draft for two to four producer targets, freezes one shared
allocation and prepares every request with its current-output projection.
`native-related-style-group.ts` owns orchestration;
`native-style-executable-signature.ts` derives completed sibling usage from
staged catalog bytes and mounted HTML instead of accepting variation prose as
execution evidence. See `docs/producer/NATIVE_SHORTS_WORKFLOW.md`.

September 15 export recovery: `native_short_pipeline.py` coordinates sequential
render, native-capture and encoded-verification owners. Each retains the existing
600-second owner limit and shared heavy lane. `native_short_resume.py` admits an
exact completed render for a fresh `--verify-from .../render-stage.json` attempt;
`native_stage_evidence.py` supplies reusable hash-bound stage/cleanup evidence for
native adapters. Final export status is `delivery.json`; a sealed render alone
is still awaiting QC. The generic `native_run_lifecycle.py` restores owned signal
handlers between stages. Reuse shared audio, exact clocks, resource ownership and
these evidence helpers; keep format-specific picture checks in their adapters.

September 15 optimization: `native_short_capture_resume.py` supplies automatic
capture sealing/reuse to the standard exporter and the thin `resume_final_qc.py`
compatibility command. `--resume-from <attempt>` retains later successful capture;
invalid present seals fail explicitly. `audio/native_master_preparation.py` and
`native_audio_donor.py` check the exact reusable audio before picture; shared
final AAC/AV checks remain. `native_short_dialogue.py` owns source/clock assembly.
`native_selected_frames.py` streams all selected RGB through the shared bounded
pipe reader; `native_picture_references.py` keeps unchanged pixel/reverse checks;
`native_render_storage.py` admits planned allocation plus the existing reserve.
`native_review_{bundle,contract,html,media,recognition}.py` replaces dated review
builders with manifest-driven preparation and separates raw ASR diagnostics from
timing approval. Long-form geometry/clock helpers are shared; actual checked
delivery admission currently uses the native Short receipt protocol. Production
timings use the existing journal and union coverage report, never a quality gate.
See `docs/producer/SHORTS_OPTIMIZATION_IMPLEMENTATION_PLAN_2026-09-15.md` for the
target operating schedule and measured qualification limits.

September 15 selected media: `edit/selected_sources.py` supervises and seals
reusable source ranges; `selected_sources_contract.py` merges bounded handles and
`selected_sources_media.py` preserves picture packets and extracts float audio.
`src/lib/server/native-selected-sources.ts` binds the small assets and executable
offsets while retaining original editorial clocks. Direct `native-short.ts build`
prepares missing media; `prepare-media` allows explicit preparation/reuse first.
`studio/native_selected_sources.py` shares receipt admission and selected-audio
inputs with export. Legacy projects remain readable. Do not substitute prepared
bytes for original source evidence or bypass the shared native work owner.

September 15 native long-form preparation: `studio/long_sources.py` adds explicit
prepare/check/managed-preview commands for separate selected-media projects.
`long_sources_html.py` translates only media URLs/source offsets;
`long_sources_project.py` preserves the original inventory and complete-program
WAV, binds the shared source package, and cold-verifies the new project. See
`docs/producer/NATIVE_LONG_SELECTED_SOURCES.md`. Working cut-base pipelines and
qualified archived long-form exports remain on their existing paths.

September 9 native-work resource rule: use `studio/managed_preview.py open`
for authored HyperFrames projects, or the existing Studio open command which
now delegates to it. It reuses one current preview across draft folders and
verifies retained descendant cleanup before replacement. Managed preview uses
the existing qualified `studio/native_runtime.py` adaptation, with exact-runtime
identity checks before server reuse. Stock Studio can skip HTML/media handling
in embedded browsers; export and preview must share these compatibility fixes.
Do not start raw SDK
preview daemons. Native rendering and browser/media QC must acquire the shared
`native_work_lease.NativeWorkLease` heavy lane and use resource admission plus
continuous owned-tree monitoring; release only after verified cleanup. These
controls are independent of the legacy renderer described below. See
`docs/producer/C0679_END_TO_END_OPTIMIZATION_AUDIT_2026-09-09.md` for the failed
attempts, tested controls, current native direction and remaining limitations.

For explicitly selected native-project work, the conservative static preflight
is `studio/native_preflight.py <canonical-staged-project> --output-dir <new-evidence-dir>`.
Use the installed `SNIPER_NODE_PATH`. It reuses official SDK project lint and
path resolution without network, probes, rendering or project edits. Run it
after asset staging and before guarded sample/master work; its pass is never
render/quality admission. Animated sample and full-output QC remain required.
See `docs/producer/NATIVE_PREFLIGHT.md` for scope, bounds and failure semantics.

The AI video editor: raw footage + a brain-authored `edit_plan.json` → a finished
short/long via a deterministic Python + ffmpeg/hyperframes renderer, then Audit B.

**Destination (canonical: `docs/PIPELINE.md`):** footage is uploaded into
PRODUCER (intent card: Short w/ style · Long w/ lane checklist), the gated plan
is authored here, and the in-house `render.py`/`assemble.py` + ffmpeg bus is the
**primary, canonical renderer** — it produces the controller-approved `final.mp4`.
**Palmier Pro is an OPTIONAL, post-approval, one-way exact-master MIRROR**, not a
native-translation destination: the wired push (`palmier/sync.py` →
`palmier/mirror.py`) delivers ONE byte-identical clip of the approved `final.mp4`
(it requires a `mirror` lane and rejects a `cuts` lane — `sync.py`). Don't add NEW
composite capability (timeline assembly, color, export) that PIPELINE.md assigns
downstream without checking there first.

`palmier/` (~57 files) is the Stage-4 mirror + native-candidate + authority
subsystem — far more than the original translator. Entry points: `push.py`
(executor CLI), `translate.py` (PURE plan→steps math, loud errors on
untranslatable vocabulary), `mcp_client.py` (HTTP JSON-RPC session,
`127.0.0.1:19789`). Mirror/authority core: `mirror.py`, `shadow.py`, `sync.py`,
`parity.py`, `ownership.py`, `preflight.py`, `native_candidate_lifecycle.py`,
`native_qc*.py`, `timeline_authority.py`, `candidate_qc_contract.py`,
`checkpoint*.py`, `verify*.py`. Wired contract: `docs/palmier/PALMIER_PARITY_CONTRACT.md`
+ `docs/palmier/PALMIER_MIRROR_HANDOFF.md`; what is/isn't wired yet:
`docs/palmier/PALMIER_CANONICAL_IMPLEMENTATION_STATE.md`.

**How these CLIs are driven (GUI):** a detached auto-edit worker
(`src/app/api/producer/auto-edit/worker.ts`; `docs/producer/AUTO_EDIT_LANE.md`) spawns the
`claude`/`codex` CLI to author the plan, runs a bounded plan-review loop (a fresh
independent critic each round) + the deterministic gate bundle, renders isolated
candidates under `.sniper-qc/<token>/round-N/`, and promotes a passing one via
`.sniper-qc-approved.json`. Hand-running the CLIs below reproduces the same stages
without the controller.

**Gate/contract modules (top-level, run each plan-review round):**
`operator_intent_contract.py`, `plan_lint.py` (+ `plan_lint_motion` / `_audio` /
`_reframe` / `_smooth`, `plan_lint_broll.py`, `plan_lint_overlays.py` —
title-card + b-roll window checks called from `lint`), `hook_contract.py`,
`claims_contract.py`, `reference_profile_lint.py`, `transcript_cut_contract.py`
(+ `_evidence` / `_quality`), `template_usage_contract.py` (+ `_approval`),
`intro_transition_contract.py`, `brand_lint.py`; `assemble_lock.py` guards
concurrent assembles.

**READ THIS BEFORE WRITING A NEW FILE.** This is the module index so a session
reuses what's built instead of reinventing it. The brain (you, in the skill) makes
the editorial decisions; these modules PROPOSE (measure/detect) and EXECUTE
(render). If a capability below already exists, extend it — don't clone it.

Operational how-to lives in `.claude/skills/producer/SKILL.md`; the design record
in `docs/producer/PRODUCER_PLAN.md`. This file is the code map.

## The pipeline (what `render.py` orchestrates, in order)

1. **cut+speed** → `cut_speed.py` — trims the cutTrack's ranges, applies per-seg
   `speed`, concatenates to a mezzanine. Executes the cutTrack; does NOT detect
   silence (that's the edit brain, below). `cut_encode_plan.py` owns typed jobs
   and filter planning. `cut_reframe.py` fuses known center/portrait crops before
   scaling for eligible large sources; tracked/manual/split/protected cases keep
   the existing reframe pass. `cut_decode.py` selects qualified native HEVC decode
   and records explicit software fallback; libx264 remains the encoder.
   `cut_execution.py` writes full argv, frame-clock, source/tool/code identities
   and completed part observations in `cut_execution.json`.
2. **channels / baseline** → `motion/baseline_look.py` — chest-up recrop + warm grade.
3. **face_track → reframe** → `motion/face_track.py`, `motion/reframe.py` — 9:16
   face-aware vertical cut (shorts).
4. **overlays** → `captions/overlays.py` — hook title cards.
5. **graphics** → `graphics/graphics_stage.py` — composites MG entries (renders each
   comp via `graphics/graphics_render.py`; per-entry offset resolution —
   explicit pin / rail / own-screen / Placement v2 — lives in
   `graphics/stage_placement.py`, which places via `planner/graphics_anchors.py`;
   the plan-time comp-size gate's geometry rules live in
   `graphics/comp_measure_rules.py`, orchestrated by `graphics/comp_measure.py`).
6. **punch-ins / motion** → `motion/punch_in.py` — zooms, ramps, brackets, aliveness.
7. **enhance → transitions → gain / master** → `audio/audio_enhance.py`
   (plan.audioEnhance dialogue cleanup, pre-gain) runs FIRST, on the pure
   dialogue bus — BEFORE `motion/transitions.py` amixes the whoosh SFX, so
   `separate` (Demucs, residual −60dB) / voice-rnn can never delete authored
   transition sound; then transitions (seam covers), `audio/audio_gain.py`,
   `audio/master.py` — −14 LUFS master + cover frame. Music (plan.music) is
   NOT a base stage — it's applied at ASSEMBLE time (`audio/music_stage.py`,
   below). A monolithic render with plan.music.enabled emits a loud
   `music_not_applied` warning (assemble applies it).
8. **captions** → `captions/captions_ass.py` — burned karaoke/line captions.
9. **audit** → `audit/audit_render.py` (Audit B) — post-render QC.

`compile_timeline.py` is the **source↔output time map** — the correctness keystone
every planner/caption/graphic depends on to convert a source second to an output
second through the cutTrack. Reuse it for any time mapping; never hand-roll.

## Edit brain — deciding WHAT to cut (`edit/`)

The renderer executes a cutTrack; these BUILD one from a raw take. Silence removal
happens HERE, upstream — not in the renderer.

- `edit/pause_scan.py` — **PROPOSES** which inter-sentence gaps to tighten (raw take
  → trims, each down to a kept breath; protects emphasis pauses). Primary length
  lever for longform (62% of reduction is silence).
- `edit/apply_pauses.py` — **APPLIES** the edit-brain proposals: folds `pause_scan`
  trims AND (via `--retakes`) `retake_scan` cut spans into a clean cutTrack
  (`cut_track_from_pauses`), also dropping an abandoned cold-open fragment. This is
  the wire between propose and execute. Use it to build the cutTrack; don't
  hand-author a single raw segment (leaves dead air + false starts in).
- `edit/retake_scan.py` (top-level `retake_scan.py`) — PROPOSES retake/false-start
  drops from one raw take.
- `edit/speech_cleanup.py` — ONE-SHOT wire (the UI's Speech-cleanup button):
  `speech_cleanup.py <manifest.json> [--source-id ID] [--out f.json]` runs
  pause_scan + retake_scan on the source's transcript and folds both through
  `cut_track_from_pauses` (incl. the cold-open drop). NDJSON events, final line
  `{"status":"done","cutTrack":[...],"segments":N,"removedS":X}`. Doctrine:
  `needsOperator` retakes are SKIPPED unless `--all-retakes` (never auto-cut a
  minute of footage on fuzzy evidence). Wraps the brains above — reimplement
  nothing here.
- `edit/render_cut.py` — standalone CLIPPER-ranges → finished master (quick win; no
  reframe/captions). Consumes ALREADY-decided keep ranges.
- `edit/cut_repair.py` + `target_resolver.py` + `non_ripple.py` — P2
  occurrence-aware `cut.restoreSpeech` analysis. They enumerate bounded
  duration-neutral candidates or return `NON_RIPPLE_IMPOSSIBLE`; they never
  mutate the current picture lock.
- `edit/repair_fragment.py` + `repair_composite.py` — P2 media executor. The
  first renders one exact dirty frame/sample unit; the second must rebuild and
  fully decode the complete candidate, enforce terminal pre-AAC `B(F)`, and
  prove decoded picture/PCM outside the authorized closure before the
  controller can call the candidate proved.
  Ask Editor promotion uses a separate durable
  `PICTURE_LOCKED → CUT_REVIEW → PICTURE_LOCKED` TypeScript transition. It
  accepts only a content-addressed execution package containing the exact
  Python candidate plus real QC/operator receipts. The Python repair action
  stays bound to its original parent; never rebase it onto the review child or
  manufacture the missing acoustic/audition package.
- `edit/study_edit_diff.py` — learns the editor's cut policy by diffing RAW vs EDITED.
- `edit/cover_select.py` — LL-008 slip-cover window scoring (operator review
  2026-07-10: the v2 45.3-47.8s wide cover read as an OUTTAKE — silent,
  mouth-closed, motionless). `score_cover_windows(manifest, span)` scores
  candidate source windows by MEDIAN motion energy (frame-diff) + lower-half
  gesture presence, hard-excludes retake_scan spans ±2s and silent+static
  windows; nothing above the floor → cover the seam with a graphic takeover
  (LESSON-008). Pure scorer (`score_windows`) split from the ffmpeg probe
  (`motion_profile`); knobs in `producer_config.COVER_SELECT`.

## Graphics — the auto-graphics system (`planner/` + `graphics/`)

The brain says WHAT a graphic is; code owns WHERE/WHEN. **`graphics_planner.py` is
the PROPOSER hub** — add a new graphic lane as a `planner/graphics_planner_*.py`
module and wire it into the hub, mirroring the existing lanes. The hub is
**scope-aware**: `_apply_scope` (via `edit_scope`) emits only the lanes the
operator's `target.scope`/`target.lanes` activated — `trim` proposes nothing,
`light` keeps the aliveness creep only, `produced`/`full` are unchanged. A new lane
should slot into the same gate (graphics / broll / motion family).

- `planner/motion_triggers.py` — deterministic candidate detector (the shared
  trigger vocabulary all lanes read).
- `planner/visual_plan_contract.py` / `visual_plan_fields.py` /
  `visual_plan_validation.py` — bounded route-neutral `VISUAL-PLAN.json`
  authority. `visual_plan_allocator.py` allocates the whole program with hard
  density/repetition constraints and source identity tracking;
  `visual_plan_layering.py` validates explicit concurrent pairs and preserves
  every active visual window without relaxing density or repetition caps;
  `visual_plan_allocator_ranking.py` applies 0.05 quality-equivalence bands so
  variation beats noise but not materially better candidates.
  `visual_plan_media_authority.py` grounds eligible source/B-roll/external
  path+hash identities in a bounded controller-verified source-set receipt and
  controller-frozen manifest metadata without reading media;
  `visual_plan_cli.py` is the buyer-agent
  validate/allocate/fingerprint boundary. It is planning-only and never opens
  media, executes catalog HTML or launches render workers. Tests:
  `test_visual_plan.py` and `test_visual_plan_layering.py`.
  The manifest `externalMedia` projection and Native Short request inventory
  preserve exact external-lane path/hash/admission identities, but those rows
  remain prerequisites until canonical ingest deeply validates a sibling
  `ASSET.json`/`ASSET-ORIGIN.json` and seals that origin pin in the hashed
  source-set entry. Admission is not publication permission. Public-web
  discovery has no automatic bridge: identify the need, capture with origin
  evidence inside `external-media/<attempt>/`, re-ingest, materialize a fresh
  context, and re-plan. A preserved `needs-review` disposition permits only the
  declared local editorial review; publication clearance remains separate.
- Lanes: `graphics_planner_receipts.py` (b-roll receipts), `_sequences.py`,
  `_boundaries.py` (section markers), `_gauge.py` (milestone gauges),
  `_illustration.py` (concept b-roll), `_zoom.py` (punch/aliveness carpet),
  `graphics_reference.py` (deixis → placed comp, cross-format), `_density.py`
  (trim to budget), `_items.py`/`_style.py`/`_rules.py` (shared helpers).
- `graphics_copy.py` — deterministic converge points: brain-written copy + code
  timing → a placed candidate (`fill_list_spec`, `fill_illustration_spec`). The
  `fill_*_spec` seam is where brain copy meets code timing. No LLM calls here.
- `graphics/catalog_discovery.py` (+ `_sources`, `_records`, `_cli`) — READ-ONLY
  discovery over the WHOLE recorded catalog: the vendored mirror index/lock/
  sources (`vendor/hyperframes-catalog/`), the mechanism study
  (`docs/producer/catalog-study/`) and the integrated registry, joined to the
  MEASURED matrix through the existing `comp_capability_artifact` reader (never
  a second validator, never the probe). `catalog_discovery_cli.py search
  "<need>" [--type --declared-aspect --status --tag --limit]` / `lookup <name>`
  → JSON or text with per-item status (`reference` / `reference-missing-source`
  / `integrated-measured` / `integrated-unmeasured`), source path + existence,
  declared vs measured canvas kept separate, evidence-backed adaptation notes,
  loaded provenance + lock/study/disk disagreements. The explicit
  `PORTED_KINDS` mapping joins a local kind to its upstream item only when the
  template declares its provenance; same-named items never share capability.
  Evidence, not admission — the plan/scene adapters and gates still decide.
  Tests: `test_catalog_discovery.py`, `test_catalog_discovery_fixtures.py`.
  `inventory` returns the entire recorded inventory with source hashes and full
  annotations for strategy, without ranking/limit or native execution approval.
  `test_catalog_inventory.py` covers completeness and source drift.
- `graphics/catalog_semantic_search.py` — bounded 1–4-intent retrieval over
  every catalog metadata row. Direct language ranks above controlled
  job/family synonym expansion; a 1–20 result cap never truncates the rows
  considered. It returns paths, hashes and metadata only, never source/preview
  bytes or execution approval. `catalog_resource_index.py` supplies the
  digest-bound static DOM/canvas/WebGL/video-texture/media/dependency/repeat
  signals used to require guarded probes. `catalog_snapshot_registry.py` keeps
  current and historical metadata roots immutable; prepared future snapshots
  must pass `catalog_snapshot_admission.py` against an exact upstream commit.
  Tests: `test_catalog_semantic_foundation.py`.
- `graphics/reference_reuse_map.py` / `reference_reuse_validation.py` — explicit
  reference-shot/style planning shared by Short and Long. Existing catalog search
  freezes shot candidates and source bytes; authored inspections choose reuse,
  configure, compose, bounded custom or blocked. Supports retaining a component
  while filling its specific gap. No visual/execution approval or model calls.
  `reference_reuse_cli.py prepare <request> --output <map>` / `check <map>`.
  `studio/native_reference_reuse.py` binds optional `--reference-map` evidence to
  shared native preflight and Short export/resume; absent maps load no catalog.
  See [workflow and schema](../../docs/producer/REFERENCE_SHOT_REUSE.md).
  Tests: `test_reference_reuse_map.py`, `test_reference_reuse_cli.py`,
  `test_native_reference_reuse.py`.
- `graphics/reference_study_bindings.py` — `reference_reuse_cli.py save-study`
  retains inspected matches beyond their original project; `check-study` verifies
  exact reference/candidate bytes without discovery. New requests opt in with
  `studyBindings` and per-shot `studyMatch`, retaining previous inspections and
  decisions as evidence while requiring a new adaptation decision. Tested across
  Short → long-form in `test_reference_study_bindings.py`.
- `native-short.ts prepare-longform` / `check-longform` reuse existing ingest,
  intent, reference selection and shared catalog through server helpers
  `native-longform-request`, `reference-strategy-library`,
  `longform-reference-inputs` and `longform-strategy-packet`. They freeze the full
  research/catalog indexes and complete selected event sequence into a local
  1920×1080 strategy request; no provider, automatic style qualification or render.
  See `REFERENCE_SHOT_REUSE.md`; TS test `native-longform-request.test.ts`.
- Placement: `planner/free_space.py` (absolute free-space map, SAFE_BOX-clamped) +
  `planner/graphics_anchors.py` (`resolve_offset_v2` measures + places into the
  emptiest legal region; v1 fallback). Reuse for any placement — it already clamps
  to safe margins.
- `planner/icon_library.py` — fetch/cache brand icons (chip-row / icon-badge
  marks) + `resolve_name` (the COMBINED icon order: Simple Icons brand mark
  wins, vendored Lucide glyph falls back as `"lucide/<name>"`, unknown fails
  loudly). `planner/icon_lucide.py` — the vendored Lucide glyph subset (~55
  generic marks: check/arrow/database/cpu/globe/lock/chart…, ISC, pinned
  `lucide-static@0.525.0`) at `templates/motion/icons/lucide/` (+ manifest +
  PROVENANCE.md); comps take `iconFile: "lucide/check"` with zero changes.
- Render: `graphics/graphics_render.py` (hyperframes + content-hash cache),
  `graphics/graphics_stage.py` (compositing; an entry may carry
  `"takeoverBase": "blur-desat"` — G5 punch treatment: the FOOTAGE gaussian-
  blurs + desaturates under the window, 1-frame apply/restore via enable
  gating), `graphics/exit_on_cut.py` (G4 THE EXIT LAW: `"exitOnCut": true`
  clamps an entry's outEnd to the next cutTrack seam — shared by lint,
  render.py and assemble.py so they can't drift), `graphics/pip_takeover.py`
  (longform glass takeover move). Comps are HTML under
  `templates/motion/compositions/` (punch pack: `punch-shout-lockup` +
  tokens.css `--lemon`/`--font-serif-display`/pop tokens + `motion-tokens.js`).

## Incremental graphics — the render → lock → composite loop (`assemble.py`)

For iterating graphics WITHOUT a full re-render each tweak (ported from the
video-editor's `workflows/incremental-graphics.md`). Because punch-in runs BEFORE
graphics, our graphics are output-space overlays → the base cleanly separates:

1. **BASE** — `render.py --skip-graphics <plan> <manifest> <base_dir>` masters the
   whole pipeline EXCEPT the graphics composite → `base_dir/final.mp4` +
   `base.fingerprint.json` (base-shaping plan digests plus full source/transcript
   and completed-base byte identities, checked by `base_reuse.py`). Rendered once.
2. **ASSEMBLE** — `assemble.py <base.mp4> <plan> <out.mp4> [--fingerprint …]`
   defaults `--fingerprint` beside the selected base. It renders each
   `graphicsTrack` entry (content-hash cached) and overlays them onto
   the base in ONE ffmpeg pass (audio stream-copied from the mastered base). An
   ordinary graphic edit rerenders only that clip and the composite; graphics that
   change long-form recomposition or legacy-caption suppression correctly rebuild
   the base.

**Fingerprints are SPLIT** (`fingerprints.py`, shared by render + assemble):
`base_fingerprint` (legacy full print — graphics/planVersion/music excluded via
`_NON_BASE_KEYS`), `videoFingerprint` (base fields EXCEPT audioEnhance/audioGain;
transitions stay video-side — their flash frames are baked into the picture) and
`audioFingerprint` ({audioEnhance, audioGain}). `base.fingerprint.json` records
all three; when the `base_plan.json` snapshot sits beside it (every writer
stores both), `recorded_fingerprints` RECOMPUTES the prints from the snapshot,
for diagnostic plan compatibility. A snapshot cannot upgrade an old base into
byte-bound authority: missing/stale `baseReuse` evidence requires a rebuild, and
`--resume` cannot bless unproven intermediates. Hashing goes through `json_canon` (integral floats → ints, bools kept):
the editor's save-plan writes via JS `JSON.stringify`, which collapses `30.0`
→ `30` — without canonicalization a zero-change UI save flipped the base
fingerprint into a spurious ~3 min rebuild (fixed 2026-07-09; the graphics
`content_hash` cache key canonicalizes the spec the same way). Guards ported
from the reference: `eof_action=pass` on every overlay
(the 1-in-4 duplicate-frame stutter) + the YDIF dup-ratio FAIL ≥ 8% — the probe
now rides INSIDE the composite pass (a signalstats `metadata=print` tap on a
split of the final label; PRE-encode frames, same 0.08 threshold;
`_ydif_dup_ratio` remains for the passthrough/standalone paths). Perf notes
(2026-07-09): `graphics_stage._probe_frames` counts PACKETS, not decoded frames
(identical 2598 on our H.264 MP4s, 0.085s vs 16.5s), and the composite encodes
with `ENCODE["composite_preset"]` = veryfast (16.9s→9.4s; CRF 12 still governs
quality — the rejected VideoToolbox path was ENCODING, which loses CRF;
qualified native DECODING is separate and keeps the libx264 encode).

**Execution and review observations** (2026-09-22): `audio/mastering_filter.py`
records the selected branch, exact applied gain/filter, measured dry runs and
whether that selected filter converged, exhausted its budget or was unmeasured.
Program-master receipts use schema 3; source-float base authority is unchanged.
`revision_ledger.py` writes immutable output-bound render and deterministic-audit
observations beside ordinary outputs. These never grant or inherit editorial
approval; every changed output still requires full review. Keep these hooks at
publication boundaries, outside the shared fingerprint primitives and frozen
headless build catalogs.

**The graphics/base boundary is explicit, not mode-wide.**
`graphics_base_effects.py` projects only long-form rail/recompose geometry and
legacy-caption suppression windows into the base/video fingerprints. In a
`--skip-graphics` render, those windows remove legacy ASS cues before the base
encode; explicit `CaptionTrackV1` captions remain post-base shards. Ordinary
scene copy and `presenterFrame` alpha/format changes retain the base in both
short and long-form workflows.

**The render-effect vocabulary is closed.**
`render-effect-registry-v1.json` owns every released public plan/manifest root;
`render_effect_registry.py` rejects unknown or unreleased roots and
`render_effect_discovery.py` scans the current renderer import closure for
unregistered literal readers. `render_stage_roots.py` compiles domain-separated
timeline, base, per-scene, composite, final, and manifest roots into the current
`RenderGraphV1` bridge. Generated registry mutations are the authority for which
roots move and whether base reuse is legal; add a registry row and mutation
before teaching the renderer a new public field.

**`--auto-base` is the smart re-render dispatch** (the editor's one button):
`assemble.py <base> <plan> <out> --fingerprint base.fingerprint.json --auto-base`
checks the base state — `current` composites fast; `audio_stale` (video print
matches, audio print changed) takes the **AUDIO-ONLY fast path**
(`audio/base_audio.py`): the base keeps its video stream and only the audio bus
is rebuilt — enhance → gain → two-pass loudnorm re-master (via `master.py`'s
public `build_pass2_afilter` seam), `-c:v copy` at every step — then, when the
existing final.mp4's `.assembled.json` sidecar proves its composite is current
(same videoFingerprint + graphicsTrack), the new audio is MUXED onto it (no
recomposite; music still applies after). HONEST fallbacks (loud
`audio_fast_path_skipped` → full rebuild): audio fields already baked into the
base (can't un-bake — a SECOND tweak of the same field costs a full rebuild),
and audioEnhance on plans with sfx transitions (enhance runs BEFORE the whoosh
amix in the pipeline, but the whooshes are baked into the base audio; gain-only
stays fast — gain runs AFTER the amix, so the mastered bus reproduces the order
exactly). `stale`/`missing` first refits the plan's output-time windows to the
edited cutTrack via `edit/plan_refit.py` (old timebase from the
`base_plan.json` snapshot; pure arithmetic through the source↔output map,
dropped windows reported loudly). The refit is TRANSACTIONAL: staged to
`<plan>.refit.json` and promoted over the operator's plan only after the
rebuild succeeds — a failed rebuild leaves the plan untouched so a retry
re-runs the identical refit (no double shift). Then it re-runs
`render.py --skip-graphics` (~3 min, manifest from `--manifest` or the
`manifestPath` recorded in the fingerprint file) and composites. Measured on
the 108s e2e longform (2026-07-09): graphics-only fast path **19.9s** incl. the
3.0s proxy (was 60.9s); audioGain tweak **11.7s** end-to-end (was ~158s); full
base rebuild still ~190s.

**Preview proxy** — after every successful assemble, `preview_proxy.py` writes
`final.proxy.mp4` next to the output: short side 480 (even dims), x264 CRF 28
veryfast, keyframe every 24 frames (scrub-dense), AAC 96k, faststart. Measured
2.7-3.0s / ~27x smaller on the 108s final; 0.25s on a 5s short. Emits
`{status:"proxy", path, ms, bytes}`; failure is the ONE documented
warn-and-continue exception (`proxy_failed`) — the deliverable already
succeeded, a broken preview must not fail the render.

**Draft mode** — `draft_render.py <plan> <manifest> <producer_dir>` = the
pre-review-wall WATCHABLE candidate (geometry-contract v3 item #8): subprocesses
`render.py` into `<producer_dir>/draft/` with `--approval-dir <producer_dir>`
(same delivery-approval receipt the final render enforces; Audit B skipped by
default, `--audit` opts in), then one fast drawtext pass (veryfast, `-c:a copy`,
knobs in `producer_config.DRAFT`) burns a center + corner DRAFT watermark into
`draft/draft.mp4` and deletes the unwatermarked `final.mp4` + its
`.assembled.json`. A draft can never ship: wrong name/dir for
`palmier/master.py`'s `final.mp4` path key, no provenance, and it never writes
`.sniper-qc-approved.json` (refuses to run if one appears in `draft/`).

**Music at assemble** — after the composite + YDIF check, `plan.music =
{enabled, path|assetId, duck (default true), gapDb}` is applied by
`audio/music_stage.py`: resolve the track (`path` absolute, or `assetId` via an
explicit `--manifest` (wins) or the fingerprint's recorded manifest — music
manifest entries carry file paths; any miss fails loudly), then `audio/audio_mix.py` lays the bed (pre-norm to dialogue−gapDb,
mandatory sidechain duck whenever dialogue exists, re-master to −14 LUFS) audio-only over the
assembled output — the video stream is copied. Music edits never rebuild the base.
At Palmier handoff this mastered bus replaces the NLE's raw linked audio; see
`docs/findings/AUDIO_AUTHORITY_AT_NLE_HANDOFF.md`.

## Motion, audio, captions, b-roll

- `motion/` — `reframe`, `reframe_split`, `face_track`, `punch_in` (zoom engine),
  `baseline_look`, `transitions` (seam covers: flash/leak ONLY — the stock
  ffmpeg-xfade family was operator-rejected and REMOVED 2026-07-11
  (FAILURE_LEDGER LL-014); longform seams use Sniper's seam grammar
  (`docs/studies/MODULE_STUDY.md` §2, `EDITCRAFT_LESSONS.md` §2.7):
  panel sweeps, face-bridged recompose, under-panel cuts, blur-recede,
  seam-role zoom-pulls — `plan_lint_motion` hard-ERRORs any `xfade:*` kind in
  every mode; the SFX slot takes `true|false|"<pack-name>"` resolved
  through `audio/sfx_library`), `visual_state`, `recompose`
  (FACE-ANCHORED RECOMPOSE, defect report 2026-07-10 §1: a rail/panel entry
  declares `recompose: {clearX: [x0,x1]}` → a synced `role:"recompose"`
  punchIns push window that scales+pans the footage, eased 0.4s with a 0.12s
  lead, so the face lands at the clear-region midpoint; both edges eased via
  punch_in's `releaseS`; `motion/recompose.py <plan>` stamps rail kinds on
  longform + rebuilds the windows idempotently — run it in SKILL step 4a).
- **Reframe layouts** (`plan.reframe.layout`, 2026-07-09): `"fill"` (default,
  layout absent = today's strategy path) or `"split"`. `split` = Opus-Clip
  "Layout: Split" for StreamYard-style screen-share sources (webcam inset +
  shared screen baked into one 16:9 frame): TWO normalized `[x,y,w,h]` crops of
  the same source — `reframe.split.top/bottom.crop`, `top.frac` (0.3–0.7, default
  0.5) = top cell's share of output height — each scaled to COVER its cell
  (center-crop, never letterbox), vstacked to 1080x1920. 9:16 shorts ONLY.
  Sibling: fill-mode `reframe.crop` manual override — wins over the automatic
  face crop, scale-to-cover the full canvas. Both dispatch in `render.py`'s
  `reframe_stage` to `motion/reframe_split.py` (face_track skipped; geometry is
  denorm + even-snap + fail-loud on out-of-frame rects — never clamp; rects
  denorm against DISPLAY dims — `cut_speed.display_dims`, edge I9: rotation
  side data swaps the canvas and ffmpeg autorotates). Bounds
  live in `producer_config.REFRAME_SPLIT`; lint = `plan_lint_reframe.py`.
  Manual crop/split + `plan.baselineLook` is a lint ERROR (v1): crops are drawn
  on the raw source frame but baseline_stage recrops BEFORE reframe — no
  coordinate transform yet, fail loud.
  `reframe.track` is reserved (only `false` accepted — tracker not yet wired).
  reframe is BASE-side: any layout/crop edit flips the base fingerprint.
- `audio/program_finish_contract.py` + `audio/program_finish_bus.py` — **source-float-v2
  audio finishing** (2026-09-08). On the v2 path `audioEnhance`, `audioGain` and
  `transitions[].sfx` are NOT base stages: `render.py` skips the legacy enhance/gain
  stages and strips seam SFX from the transitions stage once the source-float
  admission holds, and assemble applies them on the retained float dialogue bus at
  program-master time (`program_mix_bus.build_program_mix` → `render_finishing`):
  cleanup (catalog ffmpeg chain; `separate` is refused, it needs a downloaded
  Demucs runtime) → measured-latency removal (afftdn/arnndn are not latency-free
  and do not flush their tail; the chain input is padded by the measured delay +
  100 ms guard, then the delay is trimmed) → the existing trapezoid gain windows
  (`audio_gain.build_filter`, evaluated every 256 samples) → authored SFX summed
  sample-exactly (engine whoosh via `motion.transitions.synth_whoosh`, pack items
  via `sfx_library.resolve`; hit lands on the seam) → music bed ducked by the
  finished dialogue WITHOUT SFX → the single whole-program master. Everything stays
  pcm_f32le at the bus clock. `audio_policy_reason(plan, "source-float-v2")` now
  validates finishing (`finishing_reason`) instead of refusing it; v1 still refuses.
  The program-master receipt carries `finishing` (settings, filters, measured delay,
  model/SFX sha256s, finished stem identities) and `audioProgramInputHash` digests
  it, so a finishing revision invalidates excerpts/pointers/graph node-final while
  the raw bus (cutTrack+target domain) and the base stay current
  (`assemble._finishing_invariant_current`, `cut_delivery_authority.base_plan_lineage_digest`,
  `assemble_picture_reuse` use `finishing_free_plan`). `assemble_source_audio` reuses
  the retained program master for non-audio revisions after `load_program_master`
  re-proves it (`programMasterReused`). Tests: `test_program_finish_contract.py`,
  `test_program_finish_media.py`, `test_assemble_finishing_media.py`.
- `audio/` — `master` (encode + loudnorm + cover), `audio_enhance` (plan.audioEnhance
  dialogue cleanup — the SINGLE entry point the renderer calls; presets in
  `producer_config.AUDIO_ENHANCE`: `voice`/`voice-strong` (afftdn — steady noise
  only), `voice-rnn` (RNNoise `arnndn`, model vendored `audio/models/bd.rnnn`,
  `{models}` token substituted by `build_filter`), `separate` (dispatch sentinel →
  `audio_separate`)), `audio_separate` (Demucs two-stem: extract 48k wav → demucs
  → remix vocals + residual at `--residual-db`, default −60 ≈ mute; needs
  `pip install demucs torchcodec`, first run downloads weights), `audio_gain`
  (per-section bus; its `parse_windows` is also the lint validator — see
  `plan_lint_audio`), `audio_mix`/`audio_mix_bed` (music bed + ducking; `MixSpec`
  carries the plan.music `duck`/`gap_db` knobs; `--no-duck` is music-only,
  `--gap-db` controls the voice-priority rest margin),
  `music_stage` (assemble-time plan.music application — see assemble section),
  `base_audio` (the AUDIO-ONLY base fast path: eligibility + bus rebuild + mux —
  see the `--auto-base` section; reuses enhance/gain/master, duplicates none),
  `sfx_library` (the starter SFX pack: catalog + resolve + deterministic
  `build` — seeded ffmpeg synthesis into `assets/sfx/` with PROVENANCE.md;
  each name carries a `lead_s` so the renderer lands the HIT on the seam).
- `captions/` — `captions_ass` (burned karaoke; aspect-aware geometry via
  `caption_cfg_for_aspect`), `captions_minimal`, `captions_whisper` (the punch
  base layer, `captions.style: "whisper"` — 1-3 word sentence-case replace
  cues, no karaoke, inline amber tier-A emphasis; `CAPTIONS["WHISPER"]`),
  `overlays` (hook cards),
  `caption_corrections`, `bake_emoji`, `longform_outputs` (SRT + chapters — WIRED
  into `render.py` `longform_sidecar_stage`; longform ships the SRT even when not
  burning, so a longform is never caption-less). Explicit `CaptionTrackV1`
  authority uses `caption_plan_pipeline` → `caption_shards` (cue-local,
  font-byte-bound RGBA clips) → `caption_shard_composite`; the same compilation
  writes SRT, semantic chapters, regenerable Palmier bindings, authority, and
  Audit B evidence. Caption-only changes restore the proved caption-free
  composite and rebuild only dirty shard keys.
- **`graphics/pip_takeover.py` is UNWIRED** (the ANIMATED shrink-to-PIP,
  MODULE §5 item 10) — `render.py` never calls it; `plan_lint_motion` still
  HARD-REJECTS `needsPip`/`canvas-pip-list` entries. BUT the STATIC
  face-in-PIP takeover IS wired (§5 item 9, operator-adjudicated legal for
  longform 2026-07-10, banned for shorts): hole-comps
  (`graphics/pip_hole.py` registry — `module-takeover`) render the frame
  around a transparent face hole with alpha forced by
  `graphics_render.format_for`, and `graphics_stage` scales the base footage
  into the hole at composite time (`pipHole` branch). Gates in
  `plan_lint_module.py` (longform-only + own-screen; also lints the
  `glass-rail` `spec.entrance: "rail-push"` move, §5 item 8).
- `broll/` — `broll_pool` (operator's pool: vision cataloging + resolve),
  `broll_insert` (receipts ride on top, never touch audio).

## Gates & QC — mode-aware, run for shorts AND longs

- `plan_lint.py` — editorial gate between brain and renderer (both modes).
- `plan_lint_reframe.py` — reframe-section lint (called from `plan_lint`):
  strategy rules + the fill/split layout contract (layout enum, split = shorts
  only with BOTH cells, crop rects 4 numbers in [0,1] w/h ≥ 0.05 inside the
  frame, frac in [0.3,0.7], `track` only false, reframe must be an object,
  manual crop/split rejected alongside `baselineLook`).
- `plan_lint_audio.py` — audio-field lint (called from `plan_lint`, mirrors
  `_motion`): `audioEnhance.preset` must be in the AUDIO_ENHANCE catalog;
  `audioGain` validated through `audio_gain.parse_windows` (the executor's own
  validator — lint and renderer can't drift) + bounds/overlap; `music.path`
  (absolute existing file) accepted as the assetId alternative, plus
  `duck`/`gapDb` sanity; `gapDb` must keep voice at least 3 dB above the bed.
- `hook_contract.py` — the **Hook Contract**: content-derived, scope-aware HARD
  gate that FAILS a plan whose intro is MISSING an owed element (named tool→graphic,
  credibility claim→PIP/card, strong beat→push, captions). Derives obligations from
  the transcript so a forgetful brain gets caught; run in the skill's planning-
  convergence loop (SKILL step 4) alongside `plan_lint`. Reads `edit_scope`.
- `claims_contract.py` — the **Claims Contract** (truth gate, MODULE_STUDY
  §5.6): pre-render, every NUMERIC token in card copy (`graphicsTrack[].spec`
  strings + `titleCards[].text`) must be SPOKEN in the card's window —
  arithmetic string/number match (K/M/B scales, spelled cardinals via lookup),
  never regex semantics; `evidence*`/`icon*` slots exempt. The brain owns
  paraphrase faithfulness (SKILL step 4b). Same CLI shape as `hook_contract`.
- `planner/word_lock.py` — word-locked seams (MODULE_STUDY T-G):
  `snap_to_word_boundary` / `snap_plan_seams` move `transitions[].outTime` and
  translate `graphicsTrack[]` windows onto kept-word boundaries at plan time;
  `plan_lint_motion.check_word_lock` WARNs on seams >150ms off-boundary
  (runs when `plan_lint.py` gets the optional `[transcripts_dir]` arg).
- Narration-paced module builds (MODULE_STUDY §5.4): the brain picks WHICH
  kept words a card's modules land on, `graphics_copy.fill_module_lands`
  converts them to comp-relative `spec.moduleLands` (the comp schedules its
  builds off it); `plan_lint_motion` validates lands (increasing, ≥0.25s
  apart — `MOTION["module_lands"]` — inside the hold).
- `review_packet.py` — the skill review wall's hash-bound critic evidence
  packet (SKILL step 4): plan + manifest byte hashes, the cut-segment table
  with rationales, kept words remapped via `compile_timeline`, cut-boundary
  neighbor words, the plan_lint/hook_contract/claims_contract verdicts +
  `gateDigest`, and the pacing report, sealed under a deterministic
  `contentDigest` (same inputs → same digest). Build ONCE per review round;
  round-1 concurrent critics all read the SAME packet instead of re-deriving
  the transcript (mirrors the GUI's `plan-review-packet.ts`). CLI:
  `review_packet.py <plan> <transcripts_dir> <manifest> --out packet.json`.
- `edit_scope.py` — resolves the operator's `target.scope` (trim/light/produced/
  full) + `target.lanes` per-lane directives into the active-lane map. Single source
  of truth for "what did the operator ask for"; the contract + planners key on
  `lane_required()`. Back-compat: `treatment` maps onto a scope.
- `plan_lint_motion.py` — MG-track lint (graphics/treatment/audio/zoom cadence);
  `if mode == "longform"` branches, shorts get a uniform cut-driven budget.
- `plan_lint_smooth.py` — SMOOTH LONGFORM grammar (defect report 2026-07-10,
  called from `check_motion`, longform only): every punchIns boundary whose
  scale steps discontinuously (computed from punch_in's own pure mirrors)
  must land ON a cut seam — off-seam pops are shorts grammar (ERROR); pushes
  ease ≥0.25s in AND out; footage never punches under a live non-own-screen
  panel (ERROR, defect 4); rail windows without a synced recompose, >3 layout
  families (`MOTION["layout_families"]`), and flash/leak transitions WARN.
  Plus LL-007 (operator, v2 showpiece): an in→out zoom pair resolving within
  `gap_pair_max_s` (4s) that overlaps NO graphic and carries NO emphasis
  trigger/evidence WARNs — zooms are not gap-fillers; `pacing.suggest_fills`
  longform fills now propose graphic/panel-extension, never a punch.
  Knobs in `producer_config.MOTION["longform_smooth"]` / `["recompose"]`.
- `plan_lint_visual.py` — LEARNING-LOOP visual lint (showpiece QC 2026-07-10,
  called from `check_motion`; each rule names its `docs/findings/
  FAILURE_LEDGER.md` row): first DECLARED content land (moduleLands[0]/min
  atN) within `MOTION["first_land"]` of outStart (own-screen ERROR 0.6s,
  panel WARN 0.9s — empty-chrome staging, LL-002); WCAG accent-vs-bg
  contrast ≥3:1 for cataloged kinds (`MOTION["contrast"]["kind_bg"]`,
  LL-004); left-column own-screen holds >5s WARN (LL-005); FORM SELECTION +
  VARIETY (MODULE_CARDS §1.4/§2, LL-015/LL-016): `check_form_shape`
  (transcript-armed path only — comparison-shaped info, ≥2 numeric spec
  tokens + a spoken comparative marker, on a kind outside
  `MOTION["card_form_map"]["comparison"]` WARNs) and `check_variety`
  (consecutive same-kind WARN, caption layers + statements[] chains exempt;
  produced/full longform ≥6 windows below the `MOTION["variety"]`
  distinct-kind floor WARNs). Sibling LL-001
  (blur-recede seam runway) lives in `graphics/exit_on_cut.py`
  (`EXIT_RUNWAY_S`); LL-003 (unspoken >2-word phrases) in `claims_contract`
  phrase grounding + `STRUCTURAL_LABELS`.
- `ledger_lessons.py` + `docs/findings/FAILURE_LEDGER.md` — the LEARNING
  LOOP's memory: append-only defect ledger (id/defect/root cause/caught-by/
  encoded-as/status) + the "## Brain lessons" section (LESSON-id lines) that
  the auto-edit authoring prompt AND SKILL step 4 are contractually bound to
  obey. `parse_lessons()`/`parse_rows()`; `sync-checklist` regenerates the
  derived failure-modes block of `docs/findings/QC_CHECKLIST.md` (the
  standing QC-panel brief — future QC panels read it first). Every new
  QC/operator defect = a ledger row + an encoding (lint rule/test/LESSON).
- `audit/audit_render.py` (Audit B) → `audit/audit_motion.py` (pacing/presence/
  smoothness, WARN-only), `audit_frames`, `audit_glitch`, `audit_probe`.
- Budgets (floors, per-mode) live in `producer_config.py` — e.g. shorts
  `pacing.min_changes_per_min: 12.0`, `max_still_gap_s: 8.0`. Change a threshold
  there, never inline. Longform still-gap is **region-aware** (`hook_still_gap_s: 4`
  vs `max_still_gap_s: 20`): the hook must stay dense, the body may breathe — the
  front-loaded envelope from `docs/studies/PRODUCTION_ENVELOPE_STUDY.md`. Don't flatten it
  back to one ceiling.

## Study — learning from reference videos (`study/`)

- `study/study_video.py` — the STUDY fingerprint (pacing / states / audio);
  submodules `study_cuts` / `study_states` / `study_audio` / `study_transcribe`.
- `study/study_deep.py` — the DETERMINISTIC deep extractor: P1 fingerprint
  (auto-runs study_video if absent) → P2 per-frame motion signals (d-metric,
  Haar face track + width zoom proxy, phaseCorrelate pan, dark/bright, YDIF==0
  freezes) → P3 unified events[] (cut/zoom/pan/panel/graphic/freeze/flash with
  bbox, transition class hard-cut/sweep/fade/flash/pop, direction+frames,
  ACTIVE-SPAN easing fit linear/power2-out/power3-out/bell) → P4 tesseract
  text (per-graphic OCR + colors + per-word timing, caption-system stats
  incl. karaoke) → P5 word-lock stats (reuses `planner/word_lock`) → P6
  OPT-IN `--semantics` agent micro-layer (schema-forced `claude -p` per
  graphic event; core runs with ZERO AI). One canonical `deep_study.json` —
  schema in `study/DEEP_SCHEMA.md`; thresholds in `study/deep_config.py`
  (never inline). The EVENT layer (rebuilt after the acid audit 2026-07-10)
  is three-tier: impulses + runs + a freeze-sided POP SCAN (`deep_pops` —
  keyword pops sit at d≈3-4 on a ≈2 talking-head floor, only a per-pixel
  freeze/extreme-luma region diff finds them); cuts are scdet-anchored with
  punch magnitude from the faceW step (`deep_face` — NEVER ORB across a cut,
  91% error); a ≤3-frame motion is a STEP (a cut), never an eased zoom; runs
  separate by region/signal family (`deep_face` glide/zoom + `deep_chrome`
  panel/rail/takeover per-region timelines + `deep_classify_motion` faceless
  probes) so a rail push never conflates with the face glide and lower-third
  out it rides with. Submodules: `deep_frames` (ffmpeg rawvideo decode),
  `deep_signals`, `deep_events` (low-percentile baseline — a rolling MEDIAN
  swallows 20-30 frame motions; scdet forcing + family dedup), `deep_classify`
  (+`_motion`), `deep_face`, `deep_chrome`, `deep_pops`,
  `deep_regions(+_inout)`, `deep_easing`, `deep_text`, `deep_captions`,
  `deep_wordlock`, `deep_semantics`. Ground-truth tests:
  `tests/test_study_deep.py` + `tests/_deep_synth.py` (constructed clip with
  known cut/pop/jump-cut/sweep/zoom/easing/OCR) + `tests/test_deep_units.py`
  (per-fix pure-function units).
- `study/study_zoom.py` (+`study_zoom_faces`/`zoom_scale`/`zoom_detect`) — the
  ZOOM MAP of an edited cut vs its cut list (punch-in cuts + animated ramps).

## Ingest & test

- `ingest.py` / `ingest_probe.py` / `ingest_scan.py` — build `asset_manifest.json`.
  Canonical Producer ingest first routes raw sources, input-project b-roll, and
  input-project music through `ingest_admission.py`; manifest executable paths
  name immutable snapshots and bind a content-addressed source-set receipt.
  `render.py`/`assemble.py` reverify that receipt when present. Every
  `broll_pool.py` command requires the manifest, rejects late additions until
  canonical re-ingest, and probes/extracts only admitted snapshots. Reference
  video intake has a separate retained admission authority, and canonical
  `music.path` is restricted to admitted manifest rows. Reference text
  sidecars, legacy no-flag CLI calls, and Palmier live-build imports remain
  separate boundaries; see
  `docs/findings/INGEST_ADMISSION_IS_NOT_ALL_INGRESS_ADMISSION.md`.
  Repo-bundled starter beds (`PROJECT_SNIPER/assets/music/*`) auto-register into
  `manifest.music` AFTER the project's own `music/` (ids continue `music-N`,
  `source: "builtin"`), so `plan.music.assetId` resolves out of the box.
- `make_test_footage.py` — synthetic clips for tests.
- `selftest.py` + `tests/` — stdlib `unittest` (no pytest). Run
  `PYTHONPATH=.:tests ../../.venv/bin/python3 selftest.py`. Shared fixtures +
  module aliases in `tests/_common.py` — add new tests there, reuse the aliases.
  `tests/_live_state_isolation.py` (imported by `selftest.py`, `_common`,
  `_budget_fixture` and the native/pool fixtures) gives every test method private
  `native_budget_store.default_root()` and `native_work_lease.state_root()` roots. Its audit
  hook (`_live_state_paths.py`: spellings, dir fds, and what it cannot see) fails any test
  that touches the operator's live budget authority, pool record or pool namespace. Class
  and module fixtures get no shared root: asking for one during a run is a class-level
  `LiveStateScopeError`. A refusal in a fixture is a class-level error. A swallowed one fails
  the run at `stopTestRun`, or the process at exit.
  `test_live_state_isolation.py` covers the runtime behavior; `test_live_state_coverage.py`
  covers the static checks (import closure, selftest order, the reviewed child launches and
  dynamic imports in `_live_state_child_allowlist.py`, and the supervised scripts).
  **Extending isolation on a merge:** after merging a branch that adds test modules
  or fixtures, run `PYTHONPATH=.:tests ../../.venv/bin/python3 -B -m unittest
  test_live_state_coverage test_live_state_isolation`.
  `test_modules_that_can_reach_the_owners_install_the_isolation` names every test module whose
  imports can reach `studio.native_budget_store`, `native_work_lease` or
  `native_work_qualification` without installing the isolation at import time. For each one, add
  `import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused`
  as its first local import, or import it in a shared fixture the module already uses.
  An import inside a function does not count. `test_dynamic_imports_and_child_launches_are_reviewed`
  names every new file that uses `sys.executable` or a dynamic import. Review it: a child that
  runs budget or pool code must assign its own roots (as
  `test_live_state_child_tripwire.test_a_child_with_its_own_private_root_is_not_refused` does). Then
  add a row with its reason. Rerun until both lists are empty.
  **Exemption, supervised real-media scripts** (`tests/*_integration.py`,
  `native_perf_fixture.py`, `native_route_canary_fixture.py`): they are not unittest modules and
  do not install the isolation. Each calls `_private_budget_root.use_private_budget_root()` first
  in `__main__`, so a live batch never refuses or charges them. They keep the real host pool
  namespace and qualification record on purpose: real renders share the host's heavy-slot limit
  with every other owner on this Mac.

  **Child tripwire.** Python children a test starts inherit `tests/_child_live_state/sitecustomize.py`
  (armed by `_live_state_children.arm`: the folder first on `PYTHONPATH`, the refused prefixes as JSON in
  `SNIPER_TEST_CHILD_REFUSED`, a reports folder and `PYTHONDONTWRITEBYTECODE=1`). It imports only the
  standard library and adds no `sys.path` entry. A refused child writes a report and exits 97, and the
  report fails the test or run even when the child's exit status is ignored; a missing or malformed
  variable also exits 97. A child started with `-I` or `-S`, or with an environment without
  `PYTHONPATH`, is not armed (`test_live_state_child_tripwire.py`).

## House rules (see repo memory / CLAUDE.md at root)

- **Skills-only.** No feature flags, no live/paid API calls in pipeline code. The
  brain does LLM work in the skill flow ($0).
- **No regex for semantics.** Deterministic code finds WHERE (beats/timing); the
  brain writes WHAT (copy). Numeric magnitude parsing is arithmetic, not semantics.
- **No fallback matching** — fix upstream, don't fuzzy-match over a data mismatch.
- Line limits (logic files): 300 lines / 50-line funcs / 4 params / 2 nesting. Data
  catalogs and comments are exempt.

Long-form research OCR: `study/study_deep.py --text-scope states` retains every motion event and transcript word-lock while reading all visual state representatives. Per-event OCR timing is explicitly unmeasured; the default full text scope is unchanged. `test_study_text_scope.py` covers this boundary. See `study/DEEP_SCHEMA.md`.

## Authorized Short orchestration (September 28 integration)

`native_batch.py` routes typed commands through `studio/production/cli.py`.
Approval files and task submissions are parsed by `inputs.py`; approval changes
and staged-start disposition live in `handover_commands.py`. `dispatch.py`
claims media tasks; `media.py`, `process_watch.py` and `process_settle.py` bind
and settle the exact supervised exporter. The coordinator remains responsible
for AI work under the existing host governance contract.

`production/queue_clock.py` owns the versioned Short counted clock;
`queue_authority.py` binds grants and commits scheduler observations.
`native_queue_accounting.py` connects `NativeRun` to the typed capacity reasons
from `native_work_pool.py`. Only settled idle render-capacity time changes
Short deadlines. Other productive tasks suppress credit. Historical Short and
Long clocks do not opt into this policy.

`context.py --role` uses `role_packet_*` to freeze exact author/critic inputs.
`native-review.ts` publishes typed reviews through `native-review-*` and
`native-final-review-*`; gate readers recheck current approved content.
`native-short-draft.ts` and `native_short_draft*` preserve pending findings,
separate draft eligibility from final eligibility, and gate exact-byte promotion.
Early static/audio checks and reusable capture evidence live in
`native_early_stage.py` and `native_capture_reuse.py`.

`native_handoff.py`/`native_handoff_*` bind the checked encoded video to its
matching live Studio view. Managed preview holds are per owner/project;
`production/handoff.py` consumes a verified visible-handoff confirmation.
The executable route and deferred qualification boundary are documented in
`docs/producer/NATIVE_SHORTS_DEADLINE_BATCH.md`.

September 27 Studio selection ids: pinned Studio stamps `data-hf-id` on any element lacking one and
writes `index.html`/`compositions/*.html` back re-serialized, which changed delivered projects at
hand-off. New native Short builds refuse such files (`src/lib/server/native-studio-host-ids.ts`,
called from `writeNativeShortProject`); `native-short.ts studio-ids` inserts the missing ids byte-
preservingly (`native-studio-host-stamp.ts`). Test: `native-studio-host-ids.test.ts`.

Scoped packets (B1): critic catalog rows may subtract sub-ranges (`except_`/`drop`,
`paragraph`) or assign a section only for a used subject feature (`when`, `FEATURES`,
computed by `role_packet_native.plan_features`); every exclusion is resolved, recorded with
its reason and content-pinned (`role_packet_sections.pinned`: text inserted into an
excluded range fails closed until reclassified), and unknown use keeps the section.
`role_packet_scope.py` classifies artifacts (inspect/entries/bound/history), narrows
CATALOG-INDEX/DIRECTOR-LIBRARY by exact id (whole index kept for custom/reference routes)
and records the packet's self-inclusive `size`. Shared evidence: `role_packet_evidence.py`
drafts/seals once-per-production `SHARED-EVIDENCE-vN.json` (`context.py --evidence-draft/
--evidence-seal`), `role_packet_evidence_schema.py` validates provenance-cited claims at
seal AND bind, `role_packet_evidence_record.py` re-observes, re-validates, checks location
and supersession (`--evidence-check`, `evidence_check` for the submission step).
Requirement revision `approved-content-production-2026-09-27`: given titles/scripts come ONLY
from the batch authority (unit A1/A2; shared evidence carries none). `role_packet_given.py`
takes `--batch/--clip`, refuses omission while a live batch claims or holds the plan's
source, reads A1/A2's `studio.production.api.read_approval` directly for the one current active
or draining batch only (the only source; unit tests patch `role_packet_given.authority.read_approval`
and `current_batches` with TEST readers) and checks the
plan's selection with the authority's `same_short`. `role_packet_approvals.py` reproduces
A1/A2's approval-v2 form byte for byte and recomputes every identity from the transcript;
`role_packet_transcript.py` refuses transcripts whose raw word numbering differs from the
writer's kept-word numbering and mirrors the writer's occurrence-frame rule. The packet's
`given` contract (other units read it; fixture `tests/fixtures/role-packet-given-contract.json`)
is {status: "not-supplied", meaning} or {status: "bound", readFrom, requirementRevision,
batchId, clipId, authorityStatus, identity, scriptSha256, titleSha256, planChecked, title:
{given, planned, status: exact|normalization-only|different, material}, selection, captionText,
timing: each {matches, details}} (`role_packet_speech.py`; display corrections listed in
captionText.details with `changesGivenSpelling`, never mismatches). Critic subjects list C3
`canvas.captionSuppressions` windows with their uncaptioned words. Tests:
`test_role_packet_scope.py`, `test_role_packet_pins.py`, `test_role_packet_evidence.py`,
`test_role_packet_approvals.py`, `test_role_packet_submission_contract.py` (real `submit-prebuild`).
Gate side: `role_packet_given_check.py` (`context.py --given-check <packet>`) re-derives a packet's
given block from the authority's current approval against the plan the packet froze, or re-runs
the omission refusal, and returns a bound packet's batch-clock resolution; `record_resolution`
writes that `packet-resolved` event before a batch-bound packet is published. A missing approved
title is a material `different` title.

Typed review evidence (B2): observations schema 2 and new records carry
`inspection` entries of three kinds — `still-frames` (exact `samples`),
`motion-playback`, `audio-listening` — each bound to the exact artifact path and
sha256 it covered, plus `approves` (picture/motion/audio), all declared, not
authenticated. Stills cover only their sampled frames (reported `sampled`, never
complete unless every frame). `native-review-submission-shared.ts` refuses
motion/audio approvals their kind does not cover on every reviewed frame (stills
never establish motion), picture approval of a rendering nobody looked at, other
bytes than the target's (stale), and notes/events/located issues at frames not
looked at (`VISUAL_KINDS`; listening supports only audio-lane claims, `claimKinds`).
`native-review-provenance.ts` records the answered packet (which must have reviewed
the plan digest, preview or MP4 the record admits), its resolution time and the
submission time. For a batch-bound packet the interval is batch-clock seconds from the
`packet-resolved` event `context.py --role` recorded (`studio/production/packets.py`); an
unbound packet's interval starts at its author-written `resolvedAt` and is labelled
`declared-not-authenticated` (it bounds nothing against a hand-edited packet). Playback
plus listening summed over artifacts must fit; the interval is a lower bound, never
proof anything was seen or heard. Every typed gate reader also re-derives the approved
content through `native-review-given-check.ts` → `context.py --given-check`
(`role_packet_given_check.py`) and admits only a record equal to it. Submission schema 1
is refused; a Short build needs a schema-2 plan review.
`native-review-approved-content.ts` (requirement
`approved-content-production-2026-09-27`) reads the packet's `given` block in B1's
contract (the TS fixture loads `tests/fixtures/role-packet-given-contract.json`:
`not-supplied` binds nothing; `bound` only from `studio.production.api.read_approval`;
title status/material, selection, caption text, timing as `{matches, details}`), records
the approval's batch, clip and identities, refuses a pass on any departure (a revise must cover it with an
`approved-content-contradiction` material issue) and records `proposed-change`
findings for the operator without withholding execution approval; an absent block
binds no approval. `native-review-shared-evidence.ts` re-runs `context.py
--evidence-check` on bound shared evidence; plan scenes then need `evidenceBasis`. Only a motion approval admits full
rendering (a picture-only pass admits nothing); only a final pass approving all
three is `editorialFinal: approved`. Records without `inspection` read as
historical untyped evidence and are never upgraded: Short (schema-2) packets
refuse them for full picture — `native_motion_review.require_typed_short_reviews`
refuses them during Short option validation, before any budget charge — and Long
(schema-1) keeps their historical admission, reported as untyped. The route
canary writes an explicit TEST fixture declaration admitted only for its own
TEST fixture project. `studio/review_player*` labels a checked MP4 CHECKED FOR
REVIEW and leaves editorial approval to `check-final`. `role_packets.retainable`
keeps only typed, non-fixture motion approvals. Tests:
`native-review-{inspection,approved-content}.test.ts`, `test_native_review_typing_gate.py`.
Gate regressions (probes p02-p09, p16, p19): `tests/test_approved_content_gates.py`. The TEST
harness `tests/_isolated_review.ts` + `_isolated_context.py` runs the real `native-review.ts` /
`native-short.ts` commands with the given check pointed at the test's private authority root;
the TS fixture `_native-review-fixture.ts` installs a TEST given check that never reads the real
authority. End-to-end approved-content chain (B1+B2+B3 over A1/A2's real authority, placeholder media, no
renders): `tests/test_approved_content_chain.py` (authorize with the approval → owner/plan-critic
packets bind `given` → `submit-prebuild` pass; changed title/order/word text refused, covered revise
recorded; shared evidence re-checked through the real `context.py --evidence-check`) and
`tests/test_approved_content_handoff.py` (motion/final packets MC-13/FC-12 and submissions; the
hand-off records the same approval identity, lists caption display corrections, keeps the neutral
CHECKED FOR REVIEW label and confirms visibility); fixture `tests/_approved_content_fixture.py`.

September 27 visible hand-off record: `studio/native_handoff.py open <attempt> --owner TAG
--record NEW.json [--review-player URL]` (`native_handoff_open.py`) writes a typed
`native-visible-handoff` record per output (`native_handoff_record.py`), after an O_EXCL intent
file: exact MP4 (review player's evaluator), the delivery-bound files plus every visible markup
file hashed no-follow before Studio opens and after it loads (`native_handoff_evidence.py`), the
live view's served check and load (`native_handoff_checks.py`), the review player's
`/inventory.json` row, server identity and per-attempt activity (`studio/review_player_activity.py`),
checked/draft label, findings, and the approved title/script read from the batch authority
(`native_handoff_approval.py`: by the export's own productionBudget batch clip via A12's
`read_approval`, confirmed by the folder binding `approval_for_project`, else
APPROVAL_BINDING_MISSING; unit tests patch both with TEST readers) and compared with the build as B1
reads a plan: source words, merged cut seconds, the admitted transcript and writer-rule timing
(`native_handoff_content.py`; caption display corrections are listed as `displayCorrections`, never
a mismatch). Status is `views-ready` or `handoff-incomplete` (exit 2; SIGTERM still writes
`handoff-interrupted`). `visibleHandoffAt` is set only by `confirm` (`native_handoff_confirm.py`): a
full re-check, the served page's own 'playing' report for the exact MP4 route from a page load after
`viewsVerifiedAt` (a bare media request, from curl or anything else, is only `mediaRequested`), and
the caller's attestation that the review page and Studio page were opened (it cannot prove anyone
watched; a local program can imitate the report). `managed_preview.open_view` takes a `ViewOwner` (tag, per-hand-off
token, evidence files); `managed_preview_holds.py` owns launcher/hold/user-hold rules, the hold cap
and `ViewOwnedElsewhere`; `managed_preview_owned.py` counts views (`views`), releases by token
(`release --handoff`) and prunes unevidenced or ended hand-offs' holds (`prune-holds`). An open
writes its binding and hold in one registry write after admission (`registry.admit_open`), so a
refusal changes nothing. The review player caches only
passing receipt admissions keyed on pinned-input and attempt-file identities; bundle forks'
inserted dialogue node carries a `data-hf-id`. Tests: `test_native_handoff.py`,
`test_native_handoff_views.py` (fixtures `tests/_handoff_fixture.py`, fake Studio
`tests/_fake_studio_server.py`), managed-preview, review-player and bundle tests.

`review-submitted` events, read-only `check-final --as-submitted` and `studio/native_handoff_verify.py`
are the unreviewed I-B123 round preserved on `p0/preserve-i-b123-wt`; review, acceptance and their
docs belong to P3b.

## Phase 1 correctness (P1; module map lines per step, completed at M-062)

- **Schema 8 (M-044, X7), the release's one schema step.** `studio/native_budget_schema.py` holds
  `SCHEMA_VERSION` 8, the readable versions 5, 6, 7 and 8, `OPTIONAL_ROWS` (optional attempt and delivery
  keys), `a5_shape`, and the release field ledger in its docstring. Its policy literals live in the data
  catalog `studio/native_budget_schema_data.py`, re-exported by name (checked with `--data-catalog`).
  `native_budget_store.BatchSession.read` lifts 5-7 to 8 (`studio/native_budget_lift.py`: the lift, and the refusal
  by name of a 5-7 record carrying content only schema 8 writes) and refuses an A5-forecast schema-5 record by name;
  the lifted versions are `native_budget_schema.LIFTED_VERSIONS`, the one place they are written.
  `production/production_optional.py` validates the optional production keys through
  `task_schema.production_problem` (`storage`; `closure` is refused until M-043 lands its validator).
  `production/queue_clock_schema.py` holds the v1 and v2 `capacityClock` shapes and validators; new Shorts get
  a v2 clock (`new_clock`, re-exported by `queue_clock.py`). `queue_clock.writable` is true for v2 only:
  `checkpoint` and `observe_worker` never advance a v1 clock, which keeps the credit it earned (delivery and
  task settlement still record on it, and `tasks.new_row` records a new task's credit origin in its `taskCredits`;
  the credit since that origin stays 0). `queue_authority.bind_allocation` binds only writable clocks.
- **One end rule (M-041, M-042; G9).** `production/task_end.py` decides every AI task end: `end_cause`,
  `end_proof` (`EndProof`: `slot_released` and `tool_cleanup` kept apart), `settle_end`, `late_cancel`, and the
  empty `HOST_END_EVIDENCE` catalog (filled at M-102). `callbacks.complete`/`fail`/`_terminated` and
  `reconcile._reconcile_one` settle through it; `task_schema.holds_slot` counts an ended task still `unresolved`.
  A launch-tool failure travels verbatim in events only (`release --launch-error`, `complete --failure
  launch-failed --launch-error`); `claims.release` refuses an AI release without it. An AI execution attaching after
  its claim's deadline is still refused, but `claims.attach` binds its handle and settles the end through the rule,
  held (P1-RP2 MA1). Section readers (`section_results.current`, `sections.require_encoded_task`) keep a completed
  result that still holds its slot current, and `section_chunk_liveness` reserves slots for early reviews whose
  authors cannot free theirs; an early review that ended without running reserves nothing, read with a chunk request
  or from the clip's family plan (`_early_task`, P1-RP2 MA2).
- **Closure and the host record (M-043; X25, X29, X37).** `lifecycle.close_or_drain(record, elapsed, observation,
  root)` drains while media work is live; otherwise it ends the enrolled director's assignment (cause `closure`),
  revokes every other live AI task, writes `production.closure` (validated by
  `production_optional.closure_problem`) and appends its rows to `production/unresolved_executions.py`'s host
  record `unresolved-executions.jsonl` inside the closing transaction. Nothing is released. `archive_refusal`
  and `native_budget_batches._archivable` need every unsettled task in both; `native_budget_batches.refuse_creation`
  refuses a new batch while the host record holds open AI rows (until M-100's admission counts them), and, while
  that record is missing, while an archived closure lists AI rows (`unresolved_executions.archived_ai_rows`, P1-RP2
  m1). `settlement._lifecycle_room` reserves room for the widest closure. `production/queue_commands.py` registers
  `settle-resource`, which records the operator's statement and releases nothing (`callbacks.settle_resource`: an
  active or draining batch's unresolved work, or revoked work not yet settled, P1-RP2 m2).
  `dependencies._dependency_outcome` reads a pre-P1 completed-after-cancel prerequisite as cancelled.
- **Which work withholds queue credit (M-045; C4, X99(2)).** `queue_clock.productive` counts an owner that is
  not waiting, another running attempt, the enrolled director while it has not declared itself idle for the Short
  (v2 clocks), and every task of the Short or run-scoped that is live, ready AI or check work, or ended unresolved
  but not completed (a completed turn only lacks slot evidence). `production/director_activity.py` records the
  director's own declaration (`director-activity --clip ID|--all --state working|idle`, in `queue_commands`;
  `api.declare_director_activity`); it is declared, never observed. Tests: `test_queue_clock_v2_b.py`.
- **Which pool waits are capacity waits (M-046; C5).** `native_work_pool.decide` groups its waitable reasons by
  source (`_reason_groups`, the order unchanged) and calls `native_work_pool_credit.classify`, which only annotates
  `decision.context` (`liveOccupied`, `liveFull`, `occupants`, `waitClass`, `capacityOnly`); no reason, refusal or
  admission changes. A heavy wait is credited only while live occupancy fills its slots, or beside a mix or legacy
  exclusive member; FIFO-only, quarantine-only and free-slot memory waits, disk and the qualification session never
  are. Until M-049 the owner loop reads only `capacityOnly` (through `native_work_pool_fence.refusal`), so those
  uncredited waits no longer extend the deadline, and a full-slot memory wait beside an audio member now does.
  Tests: `test_native_work_pool_credit.py`.
- **Credit bound to evidence (M-047; C11).** `queue_authority.record_observation(context, state, evidence, pool)`
  refuses a context whose supervisor is not this process, and records the pool's `PoolEvidence` (ticket, live
  occupants, wait class; `native_queue_accounting.pool_evidence` builds it from the refusal's `capacity_evidence`)
  on the owner row (`queue_clock.observe_worker`). A waiting row's interval is credited only when that row was a
  `verified_wait`; otherwise it is uncertain. A heartbeat that brings the credit `CHECKPOINT_SECONDS` (300) past the
  last checkpoint is written as `capacity-checkpoint` (at most 32 per Short; a `TERMINAL_EVENTS` member).
  `production/queue_audit.capacity_audit` checks each v2 Short's total against its last capacity event at or before
  the clip's observed time; `cmd_status` adds `capacityAudit` and `clip_status` its `creditVerified` (the audit is
  passed in through `native_budget_status.StatusInputs.audit`). Unkeyed: a writer who rewrites record and trail
  together is not detected. Tests: `test_queue_clock_v2_c.py`, `test_native_work_pool_credit.EvidenceTests`.
- **Orphans and dead waiters (M-048; C7, P3, P6).** `queue_authority.recovery_evidence` (in `queue_recovery.py` since
  P1-RP3, re-exported) returns `Recovery(ended,
  orphaned)`: a working row of this boot whose recorded supervisor no longer runs (PID, start and group compared)
  is orphaned; `recover_workers` moves it to a v2 clock's `orphans` (`count`, the last 16 rows with
  `orphanedElapsed`; a v1 clock keeps it) and makes the pending interval uncertain, and the observation event lists
  `orphanedWorkers`. A dead waiting row is ended even while its old process group lives (it launched nothing).
  `queue_clock.settle_task_workers` makes pending uncertain only when no waiting owner remains in the clip. Tests:
  `test_queue_clock_v2_d.py`.
- **The owner's wait extends only by settled credit (M-049; C3).** `native_run_admission.attempt_pool_admission`
  adds only `pool_observation`'s settled-credit delta to `until`; the former +4 s extension for a capacity-only
  refusal (`native_queue_accounting.waiting_for_capacity`) is gone. An uncredited wait (other work of the Short, or
  a wait that is not capacity) ends after `capacity_wait_seconds` (at most 600 s) as `capacity-timeout`. This ends
  M-046's interim reading of `capacityOnly` in the owner loop. Tests: `test_native_queue_accounting_waits.py`.
- **The named stall (M-050; C2 as X19 and G1 correct it).** `production/queue_stall.py`: `stall_seconds()` (the
  longest admissible render plus cleanup, from policy); `track`, called by `queue_clock.observe_worker` on every v2
  observation, names `capacity-stalled` once the sorted union of the verified waits' occupants has held that long
  (cut at 64 with `truncated`; a truncated stall earns nothing, `suppressed`) and clears it, occupants and
  truncation together, when the union changes or ends. Credit never stops because time passed (no `crediting`).
  `queue_authority._observe_locked` writes a stall change as a `capacity-observed` event with `capacityState`.
  `decide` records the operator's one decision, `cancel` (`capacity-stall --clip ID --decision cancel --reason`,
  `api.decide_capacity_stall`): the Short's work is frozen and it is closed out (`closed_out`: `phase_refusal`
  refuses its new work, `close_refusal` no longer waits for it). `close_refusal` refuses by name while a Short is
  stalled without a cancel. `queue_clock.status` adds `capacityState`, `stall` and `stallBoundSeconds`;
  `clip_status`'s first action names the holders and their watchdog. The stall validator (X180 m7) requires
  `cancelled` iff one cancel row, a time iff a state, and sorted, distinct occupants. Tests:
  `test_queue_clock_stall.py`.
- **Run-scoped tasks follow the Shorts' credit (M-051; C6).** `tasks.new_row` calls
  `queue_clock.record_task_origin` for every task but the director: a clip task's origin goes on its clip's clock
  (a v1 clock too), a run-scoped task's on every writable Short clock. `task_deadline` gives a run-scoped task the
  largest credit any writable Short earned since its origin there (never retroactive; a Long has no clock and adds
  nothing), so its children, bounded by `tasks._check_parent`, follow it. Tests: `test_queue_clock_v2_b.RunScopedTests`.
- **P1-RP3 fixes (X183).** `director_activity.enroll` (what `api.enroll_director` calls) resets every open v2 Short's
  `directorWorking`, so a newly enrolled director counts as working until it declares, and `enroll`'s output carries
  `declare` (`ENROLL_HINT`). `native_work_pool_credit.classify` names `LEGACY_HOLDER` as the occupant of a legacy
  exclusive wait. `claim_admission.authoring_closed` (a creative task past its output's preparation deadline, which
  never reopens for one output; the run's latest can move forward, X190 n3) is read by the claim refusal and by
  `queue_clock._task_is_work`, judged at each interval's start.
  `queue_audit._waiting_after` closes the audit window when no owner waits after the last event. A
  `capacity-checkpoint` carries only `event, clipId, worker, state, elapsed, excludedSeconds` and is written only
  within `queue_authority.CHECKPOINT_EVENT_BYTES` (512 B; 32 x 32 = 512 KiB of the terminal reserve). The lift refuses a
  5-7 record with an unresolved end outside `UNRESOLVABLE`; an archived record of another version that is malformed
  reads as `(unreadable)`. Owner recovery moved to `production/queue_recovery.py`. Tests: `test_queue_clock_v2_e.py`,
  `test_queue_clock_v2_c.CheckpointTests`, `test_budget_schema_lift`, `test_production_batch_succession`.
- **P1-RP3b fixes (X184).** `capacity-stall-decided` is a `TERMINAL_EVENTS` member (at most one per Short), so the
  cancel, and then `close`, work at a full trail. A full trail raises `native_budget_store.TrailFull`;
  `queue_authority._observe_locked` then commits a heartbeat's stall change record-only, so the waiting render never
  fails. `close_refusal` names a stalled Short before its open-clips text. `settle_task_workers` re-tracks writable
  clocks; `queue_stall.stalled` excludes handed-off Shorts; `suppressed` ends a cancelled Short's credit;
  `cancelled_refusal` names the Short. The stall validator also refuses a stall with no occupants, one dated after the
  clock's observed time, and a cancel dated before its stall. `status` audits the credit from the trail it read under
  its observation lock (`native_budget_status.audited_observation`, `queue_audit.audit_record`; X183 n3). Tests:
  `test_queue_clock_stall_b.py`, `test_queue_clock_v2_c.AuditTests.test_status_reads_the_trail_once`.
- **An added Short has its own clock; one same-job function (M-052; C8, C-2 as X144, X159 and X167 make it
  exact).** `native_budget_policy.admit_new_clip` has no minute-25 refusal: a clip added at any minute gets its own
  clock from its authorization and is admitted by the mixed forecast (`outputs.authorize_output`;
  `admit_joining_short` is gone). `production/duplication_check.py` holds the job identity: the folded title
  (`fold_title`: NFKC, casefold, drop category Cf and `DEFAULT_IGNORABLE`, then trim and collapse whitespace; the
  constant is data, 17 ranges of Unicode 16.0.0, re-read from the interpreter's Unicode version on any upgrade,
  D-P-24), the source and the ordered kept words (`kept_words`: transcript index and text). `outputs.same_job`
  refuses only an effective duplicate (the same identity, or one in the other clip's revision lineage); a rename
  goes through `change-approval`. Overlapping source seconds record `duplicationCheck` on the `clip-added` or
  `output-authorized` event (null, or one row per overlapping clip), and each non-null check owes one
  `coordination-decision` line (`coordinator-note`, `decisionId` = `duplication-check.` + 32 hex of the approval
  identity) that `add-clip`, `authorize_output` and `status` write once (`approvals.append_pending_decisions`),
  never on a closed batch. The trail cap has no exception: a line refused at a full trail, or owed when the batch
  closed, stays in `status.pendingDecisions` for good (O-11). `status` shows each added clip's recorded
  `duplicationCheck` (no key for a legacy adding event), passed with the capacity audit as one
  `native_budget_report.TrailViews` (O-4: four parameters at most); `wallBudget` and `blockers` use the output's own
  deadlines (`formats.clip_deadlines`). Known limit (O-12): a U+3164 used in place of a space, and U+2800, stay distinct; the
  fold is not a homoglyph defence. Tests: `test_production_add_clip_clock.py`, `test_production_duplication_check.py`.
- **P1 fix round (M-RPIF; X189 as X190 widens it, X190, X192).** A run-scoped task's deadline never passes the run's
  delivery deadline (`queue_clock.task_deadline`, m1). `queue_audit` checks each capacity row against its predecessor
  (`_chain_break`, m2) with `SETTLE_TOLERANCE` (the poll bound, n1), names a malformed row (`malformed-trail`, n2)
  and a lost owner no row explains (`unexplained-removal`, X192). A watchdog or reconcile settlement
  (`queue_clock.settle_task_capacity`) puts each Short's settled credit and removed owners (16-hex digests,
  `queue_audit.settlement_entry`) on its own terminal event under `capacitySettled` (F2); every other removal already
  writes a row (a `finished` observation, a recovery), and a hand-off removes none. Status, wait and archive commit
  through `native_budget_status.commit_observation`: an empty observation at a full trail is record-only
  (`observed-record-only`, `native_budget_store.RECORD_ONLY`), one that marked dead launches abandoned is always
  written (`native_budget_store._terminal`, F1). The trail's reserve was raised to 4 MiB and its bound to 19 MiB (12
  and 27 MiB since M-RP5, which counts every settling class; `test_trail_reserve_budget`). A failed checkpoint is
  written once (`_FAILED_CHECKPOINTS`, n6); status shows a handed-off Short as not stalled (`queue_stall.shown_state`,
  s1); a settlement re-track only clears a stall. Tests: `test_queue_clock_v2_f.py`, `test_queue_clock_stall_c.py`,
  `test_trail_reserve_budget.py`.
- **Lock-free credit reads (M-053; C9).** `production/queue_credit.py` reads a Short's settled credit and a task row
  without the batch lock (`snapshot`: the atomically replaced `authority.json`, checked only by
  `queue_clock_schema.problem` for the clip and by the batch status). Credit is cached per clip for
  `CREDIT_CACHE_SECONDS` (1 s); a failed read returns the last value for at most `CREDIT_READ_TOLERANCE_SECONDS`
  (15 s, the watchdog's grace), then raises `CapacityCreditUnavailable`; credit below `max(atGrant, last read)`
  raises `CapacityCreditRegressed` (never tolerated, never transient). `queue_authority.credit_delta` and
  `process_watch._task_row` read through it; `read_batch` stays only in `owner_context`, `record_observation` and
  `supporting_contexts`. The owner's monitor stops by name at once (`native_run_lifecycle.monitor_limits`;
  `production_remaining` records the category before it propagates, on the admission path too; `failure_category`
  passes both credit categories through before its text checks). The watchdog names the stop only after
  `DEADLINE_GRACE_SECONDS` past the error's `since`, as a returned reason (SIGTERM, then the cleanup grace;
  `queue_credit.watchdog_stop`), and `process_settle._name_credit_stop` gives a launch the exporter closed as
  `cancelled` the watchdog's credit category, so a regression gets no retry. `TRANSIENT` gains
  `capacity-credit-unavailable` (L-J J1): one retry. Documented limits: the watchdog's claim, cancel and ack checks
  pause at most 15 s during a credit grace (D-O10; the batch deadline never pauses since M-RP5, X218 F-m5); the task
  row's own tolerance can end one poll before the credit error, which loses the name but not the retry (D3).
  `process_watch.py` was split at M-RP5 (`OutputRelay` in `production/process_output.py`).
  Tests: `test_queue_credit_snapshot.py`, `test_queue_credit_aborts.py`, `test_queue_clock_v2_f.GrantDeltaTests`.
- **Counted time stops at delivery; the hand-off is timed (M-054; C12).** `queue_clock.status` (v2 clocks,
  `queue_handoff.frozen_times`) freezes `countedProductionSeconds` at the first delivery (`countedAtDeliverySeconds`,
  `totalAtDeliverySeconds`, from `deliveryCredits`); `countedToHandoffSeconds` runs until the visible hand-off.
  `commands.cmd_handoff` calls `queue_handoff.record_handoff` inside its lock, at the command's batch-clock `elapsed`
  (B11; the confirmation's `visibleHandoffAt` stays its own field), before the state change: the clock's `handoff`
  row (`elapsed`, `countedSeconds`, `totalSeconds`, `deadlineElapsed` with the credit held then, `onTime`) goes on
  the clip, the `clip-handed-off` event and the answer (`clock`; None for a v1 clock or a Long). After it nothing
  grows (`totalAtHandoffSeconds`, `handoffOnTime`), and `native_budget_report.sla_miss` lets the recorded hand-off
  decide `slaMiss` (minute 40 is the visible hand-off; the export time stays in `deliveries`). The hand-off timing
  lives in `production/queue_handoff.py` (split from `queue_clock` for its line budget). Tests:
  `test_production_handoff_clock.py`.
- **Bounded trail and poll bound (M-055; C13, P2).** `native_queue_accounting.pool_observation` records a pool
  refusal that is not for occupied capacity as one `unverified` observation (no `finished`-then-`working` pair):
  `queue_clock.observe_worker` makes a prior waiting row's pending interval uncertain on it (`UNCONFIRMING`),
  `productive` counts it like `working`, and its repeats are heartbeats (`queue_authority._observe_locked` compares
  state and resource), so 300 polls of a disk refusal add at most 2 events. `queue_recovery._recoverable` ends a
  dead `unverified` row like a dead waiter (`PRE_ADMISSION`: both are written only before any launch).
  `capacity-settled` stays in `TERMINAL_EVENTS` (once per owner end). `queue_clock.POLL_BOUND_SECONDS` (30 s)
  replaces the 6 s gap: the admission loop's 2 s sleep, `LEDGER_WAIT_SECONDS`, `INSPECTION_ATTEMPTS` x
  `native_work_pool_policy.HOST_IDENTITY_TIMEOUT_SECONDS` (L-I I2) plus backoff, and
  `native_budget_launch.PS_TIMEOUT_SECONDS` (L-J J2) = 27.5 s; `queue_audit.SETTLE_TOLERANCE` follows it (M-RPIF's
  n1 tolerance). Tests: `test_queue_clock_v2_c.CadenceTests`,
  `test_native_queue_accounting_waits.TrailBoundTests`, `test_queue_clock_v2_d.OrphanTests`.
- **P1 fix round (M-RP5; X217, X218).** The trail's bound, terminal reserve and settling classes live in
  `studio/native_budget_trail.py` (re-exported by the store). New work stops at 15 MiB; the reserve is 12 MiB and the
  bound 27 MiB, because `test_trail_reserve_budget` derives its classes from `TERMINAL_EVENTS` plus the abandoning
  `observed` line (a class without a worst case in `tests/_trail_budget_classes.py` fails) and counts every writer:
  about 10.6 MiB (M1). The counting basis, and its one limit (a command repeated under a persistent record replace
  failure is outside the reserve), is in `native_budget_trail`'s docstring. What keeps the count bounded:
  - an owner's end (`capacity-settled`, `queue_authority._settled_line`) names owners by 16-hex digest, which
    `queue_audit` reads beside the older form, and is a line only when it removes an owner row;
  - `commit-failed` carries `native_budget_trail.error_text` (ASCII-escaped, 96 characters); `commit-unsynced` is no
    longer a settling event (its commit stands without the line);
  - a review continuation's outcome line cuts its status and leaves the path to its start line;
  - a hand-off's evidence paths are bounded at `settlement.DELIVERY_PATH_BYTES`, its times at `handoff.TIME_CHARS`.
  `api.close` puts its reconcile's settled changes on the close or drain line (`reconciled`, M2); a close that leaves
  a draining batch draining records nothing (m2a). `api.settle_resource` takes one statement per task and phase
  (`phase`: `revocation` or `unresolved resource`, m2b), read through `approvals.committed_events`, which decodes only
  the trail lines naming the event, so it works at a full or padded trail. `queue_audit._cap`
  caps the waiting window by the checkpoint cadence (m1); `_capacity_rows` reads only the event, its `changes` and
  its `reconciled` (n1). `native_budget_status.commit_observation` writes an abandoned launch's line once per attempt
  while its record cannot be replaced (`_FAILED_ABANDONMENTS`, m3). `change-approval` refuses, by `outputs.same_job`'s
  text, a change into another clip's job (m4). Known limit (m5): a kept word is identified by its transcript index, so
  the same source seconds bound to a re-numbered transcript of that source are a new job.
  X218: the hand-off row validator refuses an `onTime` that disagrees with the row's times, times outside
  `countedSeconds <= totalSeconds <= elapsed`, and a row on a clip not handed off (F-m1); `record_handoff` refuses a
  second call by name (F-m2); `native_budget_status.SLA_BASIS` names a recorded late hand-off (F-m3); inside a credit
  grace the watchdog still stops a passed batch deadline, read without credit
  (`native_budget_clock.uncredited_remaining`, F-m5). By design (K7), a hand-off is judged with the credit settled
  when it is recorded: credit that accrued before it but settles after it (at most one poll bound, 30 s) does not
  count. Tests: `test_trail_reserve_budget.py`, `test_queue_clock_v2_g.py`, `test_production_settling_writers.py`,
  `test_production_duplication_check_b.py`, `test_production_handoff_clock_b.py`, `test_queue_credit_pins.py`.
- **A `studio` pool class (M-056; C1).** `native_work_pool_studio.py` (`MODE`, `decide`) admits Studio startups in their
  own ledger class (`native_work_pool_policy.STUDIO_CLASS`, `STUDIO_SLOTS` 2, `STUDIO_RESERVATION_BYTES` 1 GiB,
  `STUDIO_DISK_BYTES` 256 MiB: provisional, outside `policy_identity()`, so qualification records stay valid); Studio
  rows never count as render members or tickets (`native_work_pool_mix`), and every member is still charged against
  the shared memory and disk budget. `NativeWorkLease.acquire` routes every `LEDGER_CLASSES` lane to the pool;
  `native_work_pool_disk` and `native_work_pool_recovery` accept the class (a quarantined Studio member is recovered
  by nonce). `studio/managed_preview_launch.py` holds the launch path moved out of `managed_preview.py` (314 -> 189
  lines): `launch` takes a Studio slot (`acquire_until`) and completes it after a verified start, when nothing was
  attempted, and when `settle_failed_launch` verifies a failed start's cleanup, which needs the root gone and no
  live process in its group (`group_survivors`; `managed_preview_state.discharge_launch`'s "already exited" checks
  only the root); an unverified cleanup keeps the slot quarantined and the project's `launching` fence. The
  Studio-slot wait holds the registry lock (REVIEW m5). An older (`4a15560`) client refuses its own admission as
  quarantined while a Studio start is live. Tests: `test_managed_preview_studio_class.py`,
  `test_managed_preview_studio_release.py`; patch points moved to `managed_preview_launch` in the fixtures and five
  test files.
- **Mix refusal becomes a waitable ticket (M-057; P1 M1 as X97, X107, X111 and X123 amend it).**
  `native_work_pool_mix._unmatched` makes an uncovered request wait for the live members only (none live: admitted;
  a live member of its own project: unsupported at once; X242, an owner deviation: a live member of an older pool
  client, whose record `native_work_pool_fence.is_current` does not accept, makes it unsupported at once by name,
  never queued or credited, since that client predates the wait); queue order stays with `fifo_ahead`, where the pass rule
  (`may_pass`) applies only to an uncovered request's own ticket: younger requests pass it at most `PASS_LIMIT` (4)
  times (the waiter's tally, `_tally_passes`, rewritten in place by `native_work_pool_fence.rewrite_ticket`), a live
  member's own-project work always passes, and a request that passes an uncovered ticket passes the younger tickets
  it holds back (`_held`, X107 B1). A covered stage beside a live exclusive member of its own project is refused at
  once by name, never queued or credited (X107 m1). `native_work_pool.decide` reads `problems(mode, view, outside,
  request)` and may run only inside the ledger. Limits: a cross-project nested owner after 4 passes stalls; a passer
  inside one 2 s poll is not counted (X111). `native_work_pool_mix.py` 242 lines; `native_work_pool.py` 299/300 (its
  next editor extracts first). Tests: `test_native_work_pool_mix_wait.py`, `test_native_work_pool_liveness.py` (the
  480-order enumeration), `test_native_work_profiles.py`.
- **A mix refusal before any stage keeps the one retry (M-058; P1 M2).** `native_budget_launch.WAITABLE =
  {'pool-unsupported-mix'}` (L-J J3) joins `TRANSIENT`; `_retry_decision` returns no decision for a `WAITABLE` failure
  that ran no stage: the same identity relaunches fresh, its launch counter charged but not the clip's one transient
  retry (the pool frees; nothing ran). After a stage it is transient as before. Tests: `test_native_budget_mix_transient.py`.
