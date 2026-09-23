# Opening server handoff — September 6, 2026

Implementation paused at the user's request for a handoff. Do not start jobs merely by reading this document. This is application-development state, not a video-editing instruction or approval.

Repository: `/Users/maintainer/ProjectSniperSource`. The worktree contains substantial user and other-agent changes. Preserve them; do not reset, overwrite, or assume these new files are committed.

## Outcome and current limits

The server-side private opening chain is implemented through real owned-process invocation, durable stopped-outcome activation, exact Docker cleanup/CAS, and an actual read-only media-verification consumer. The last of these has NOT yet run against a successful whole opening. No whole opening media worker has completed in the retained integration fixtures: setup was blocked by the genuinely stale graphics capability catalog, before opening input/claim/worker creation.

There is NO committed playback-selection receipt, no ready server status, no opening media GET, no opening approval, no body continuation, and no public guided-v2 workflow launch. `prepareGuidedOpening` still deliberately retains an unsupported-before-render receipt. Do not turn that old receipt into a media success. The private development fixture directly uses the production lower-level runner/claim/cleanup/readback functions; it does not use a fake renderer or test-local process runner.

Existing exact-v1 guided cut acceptance and the v2 cut → raw treatment → proposal/readiness work remain separate established slices. Preserve their full original hashes, accepted cut authority, request lineage and independent reviews. The v2 root remains PICTURE_LOCKED; the isolated TREATMENT_DRAFT is not an approved body or final. Do not change ACTIVE_HEAD or fabricate template/QC receipts to connect opening rendering.

## Live resources at this handoff

- No process, media/model job, running tool session, or Docker container was started and remains active by the opening-server owner. All its type/lint/test sessions were polled to completion.
- Its two attempted whole-fixture setups stopped before an opening claim or Docker graphics launch. The diagnosed second child returned `groupStopped:true`, `timedOut:false`.
- At the final handoff boundary the capability owner reported genuine current53-probe rebuild AND independent full readback PASS. Published artifact SHA256 `e65e1e6d45d809446ed7b7b4670355aa7f941d0600450aadd73afd18736e98ce`; independent evidence `/private/tmp/sniper-capability-final-readback-lh1r_clp/result.json`. Render cohort40m22.224s from the ORIGINAL kickoff, including failures/debug; independent readback another66.660s. Earlier25/35-minute misses remain retained; final authorized envelope was45 minutes. Owner reports all exact owned containers REMOVED, no active catalog process, source freeze released. This owner did not independently rerun those observations.
- That artifact qualifies only default/probe-spec30fps physical capabilities, NOT424 rates or per-input quality. The prior stale-catalog setup blocker is now reported resolved, but the user-requested handoff pause remains: no fixture/job starts until handoff is accepted. Reobserve exact current artifact/source before the next capture; never patch an old matrix digest to bypass rejection.

## Exact file ownership and implemented seams

Paths below are repository-relative.

### Contracts and input

- `src/lib/producer/contracts/guided-opening-v1.ts`: existing closed preparation request/unsupported receipt and exact frame-range contract. Old proposals remain readable but non-executable when their schema lacks explicit presentation.
- `src/lib/producer/contracts/guided-opening-media-v1.ts`: closed actual worker envelope and schema2 media authority, distinct from unsupported metadata. Top JSON ≤128KiB; each of 14 exact document refs ≤16MiB and aggregate ≤64MiB. Source/tool paths are server-derived.
- `src/lib/server/guided-opening-media-input.ts`: new-only input construction under the real caller lease and original remaining budget. The observer explicitly proves only held document bytes/relationships, NOT fresh source media bytes, current journal authority, or successful rendering.
- Exact document names: `authority`, `acceptedPlan`, `cutRequest`, `pictureLock`, `cutProjection`, `timelineMap`, `readinessReceipt`, `readinessPacket`, `readinessBundle`, `treatmentDraft`, `candidatePlan`, `manifest`, `frameBindings`, `occurrences`.
- `src/lib/server/guided-opening-authority.ts`, `guided-opening.ts`, `guided-opening-store.ts`: strong readiness and unsupported preparation path. Known-unavailable preparation does NOT waste a full source-byte rehash or claim freshness. It remains unavailable pending real vertical qualification.
- `src/lib/server/guided-proposal-history-snapshot.ts`: explicitly historical, bounded pinned-source observation. Do not replace strong current==pinned execution readers with it. Historical display cannot become current execution/approval.

### Durable ownership and actual process outcome

- `src/lib/producer/contracts/guided-opening-claim-v1.ts`: closed exact execution/runtime claim. Binds request/execution UUID, prior journal, input path/raw SHA/semantic hash, private output root, original clock/admission and sorted graphic orders, plus exact observed Docker binary/socket/image/user/approval/runtime-root controls.
- `src/lib/server/guided-opening-runtime-control.ts`: explicit trusted runtime selection. No ambient image/tag/daemon fallback or guessed paths.
- `src/lib/server/guided-opening-claim.ts`: `claimGuidedOpeningExecution`, `readGuidedOpeningExecutionClaim`, `readRetainedOpeningExecutionClaim`. Writes immutable claim and durable `openingExecutionClaimHash` BEFORE any child. Strong historical binding checks original prepare submission/start/intake, prior token/journal/readiness/draft/cut activation and original raw generation clock. This is ownership, not absence/media approval.
- `src/lib/server/guided-opening-process-activation.ts`: creates exact known-byte records and reads independently journal-held actual process activation. A freshly computed sidecar hash is never stop authority.
- `src/lib/server/guided-opening-process.ts`: `runClaimedOpeningMedia`, `readStoppedOpeningProcess`, `openingChildTools`, `invokeOpeningChild`, `openingPythonIdentity`. Actual media runner commits independently held intent/outcome hashes in an immutable activation referenced by `openingProcessOutcomeHash`. Crash before that pointer remains explicitly unknown; no guessed PID kill, auto retry or claim clearance.
- Shared `src/lib/producer/contracts/guided-workflow-v2.ts` pointer fields: pending `openingExecutionClaimHash`; `openingProcessOutcomeHash` requires that pending claim; historical resource-only `openingCleanupHash`; all require an actual draft. No opening selection field exists yet.
- `src/app/api/producer/auto-edit/cut-preview-process.ts`: real owned POSIX process group, bounded output, timeout/termination and group-stop check. Explicit `purpose:'guided-opening'` allows ≤1,500,000ms; omitted/explicit cut-preview remains ≤900,000ms. Cleanup uses its protected remaining cap; media/read use guided-opening. Unknown purposes fail. This does not control Docker resources by itself.

IMPORTANT fixed integration bug: execute the project venv invocation path from `pythonInterpreter()`, NOT its realpath-resolved Homebrew base Python. The resolved base lacked cv2/numpy/scipy. The actual invocation path is retained; resolved executable bytes and `pyvenv.cfg` are separately bound. `PYTHONHOME` is unset, user site disabled, Python path is the pinned producer snapshot.

### Cleanup and failure retention

- `src/lib/producer/contracts/guided-opening-cleanup-v1.ts`: closed exactly-one-stdout-object parser; ≤128KiB. Exact per-order rows are not-initialized, initialized-unarmed, or reconciled-absence. Armed missing/malformed ledger is UNKNOWN, never empty success. Explicitly does not grant process-stop/media/approval authority.
- `src/lib/server/guided-opening-cleanup.ts`: `reconcileGuidedOpeningExecution({dir,expectedToken,expectedJournalHash,claimHash})` is dedicated exact-checkpoint recovery. `reconcileClaimedOpeningUnderLease({dir,lease,expectedClaimHash})` retains a real existing lease across media → cleanup. Both reobserve exact independently durable stop first.
- Exact checkpoint capability `reconcile-guided-opening` was added to `src/app/api/_lib/project-mutation.ts`; it is token/status/journal/version bound and preserves reconciliation/default mutation denials. No generic recovery bypass.
- Cleanup gets a separate protected 300-second local cap, NOT new render credit. It may attempt exact resource removal on invalid clock, but may not clear the claim without valid original clock authority.
- Every cleanup attempt has a new UUID and immutable `start.json`, actual owned `output.json`, and, on failure, `failure.json`. Start/output raw hashes are held before publication/at actual return. Final synchronous CAS rechecks exact held bytes, failure-marker absence, actual stopped outcome, lease/current journal and original-clock high-water in both guards.
- Successful cleanup removes BOTH transient claim/process-outcome pointers and commits historical `openingCleanupHash`; it never selects or approves media.
- `src/lib/server/guided-opening-cleanup-store.ts`: `readCommittedOpeningCleanup` validates exact original job/claim/stop/start/output/result lineage. It is historical resource-only evidence, not fresh source/Docker/media observation. A new pending claim must always take priority over this historical cleanup.

### Actual completion and current media readback

- `src/lib/producer/contracts/guided-opening-result-v1.ts`: strict closed media-completion/readback stdout parsers. Reject extra NDJSON, unknown fields, unbound hashes, missing/reordered stages and approval/lease/cleanup authority upgrades.
- `src/lib/server/guided-opening-result.ts`: `readHeldOpeningResult` binds actual stopped worker stdout to fixed `OUT/media-result.json` raw SHA and canonical receipt hash. It checks media/audio failure markers and explicitly returns `sourceBytesObserved:false`, `mediaBytesObserved:false`, `mediaSelected:false`. It is an input to the strong verifier, not a replacement for it.
- `src/lib/server/guided-opening-readback.ts`: `verifyCleanedOpeningMediaUnderLease({dir,lease,expectedCleanupHash,remainingMs})`. Requires exact committed cleanup/no newer claim, current readiness/current==pinned code, actual held completion, same current journal and real lease. Invokes the actual read-only Python CLI, retains actual output, validates its closed identity, rechecks tools/result/cleanup/journal and original budget. Writes only private non-selectable readback evidence. Failed post-write checks retain a failure marker; no success-selection reader exists yet. This newest consumer and its real fault fixture await independent final review and actual integration execution.

### Status and parent-owned browser

- `src/lib/producer/contracts/guided-opening-status-v1.ts`: minimal honest DTO. States unavailable, pending-owned-execution, pending-cleanup, failed, ready-for-review; current server NEVER emits ready. Completed engine elapsed means a recorded stopped interval, not liveness, finality, all engine work, or listening. Coverage explicitly excludes earlier proposal/preview work.
- Ready-only agreed additions are already in the contract: `selectionQualifiedAt:string` and `sourceFreshness:'not-rechecked-by-status'`. These will come from an actual strong selection commit, not current wall time at GET. Main updated browser parsing/copy separately.
- `src/lib/server/guided-opening-status.ts`: `readGuidedOpeningStatus(dir)` observes exact before/after journal and claim priority. Unknown stop stays pending-owned without claiming a live worker. Historical cleanup cannot hide a new claim. No source/Python rehash on status polling.
- `src/app/api/producer/guided-opening/status/route.ts`: read-only `/api/producer/guided-opening/status?dir=...`, local-origin policy, exact bounded canonical dir query, no-store, safe errors. No start/cleanup/approval side effects.
- Parent owns `src/lib/producer/guided-opening-client.ts`, `guided-opening-media-client.ts`, `src/components/producer/guided-opening-panel.tsx`, `guided-opening-player.tsx`, and editor-view mounting. Its display/browser tests use explicitly TEST-only DTO/media; they are not authentic opening authority evidence.
- Intended future media URL: `/api/producer/guided-opening/media?dir=...&selectionHash=...&mediaSha256=...&range=core|review`. No implementation yet. Derive path from exact selected receipt and hash through the same FD before/range streaming. Core/review may intentionally refer to the SAME `core.mp4` when ranges are identical; never require a nonexistent review file by convention.

## Python boundary (quality-agent owned)

Do not edit its files without coordinating ownership. It reports 32 readback/control/decoded-submodule tests passed in39.93s; full actual input+OCI integration remains pending. Detailed note: `/private/tmp/sniper-opening-media-readback-20260906.md`.

Actual commands, all input/claim/receipt hashes from separately held real invocation:

```text
guided_opening_media.py INPUT EMPTY_PRIVATE_OUT --input-sha256 SHA --execution-claim PATH --execution-claim-sha256 SHA --timeout-seconds REMAINING
guided_opening_cleanup.py INPUT OUT --input-sha256 SHA --execution-claim PATH --execution-claim-sha256 SHA --timeout-seconds PROTECTED_REMAINING
guided_opening_read.py INPUT OUT --input-sha256 SHA --execution-claim PATH --execution-claim-sha256 SHA --receipt-sha256 ACTUAL_RAW_SHA --receipt-hash ACTUAL_CANONICAL_HASH --timeout-seconds ORIGINAL_REMAINING
```

Media OUT must already exist0700 and be empty; claim file is outside it. Worker stdout is one closed completion; ordinary internal progress is redirected to stderr only in this private CLI. `media-failed.json` and `audio/audio-failed.json` override orphan success records. Server must independently prove group stop, exact Docker cleanup, journal/lease and original deadline.

First executable development class is unity speed, no J-cut, source-float-v2, explicit own-screen/full-canvas/normal/preserve graphics. Active captions/title/PiP/grade/SFX/gain/enhancement/unqualified free-band are explicit blockers, not silently dropped. This is not the final product scope. Actual source canvas must match accepted destination; no silent upscale or FPS rewrite.

The worker reuses ordinary full-base rendering in a private root, builds/strongly holds ONE full-program mastered float bus, derives exact absolute ties-even48k PCM samples for the opening, renders selected intersecting graphics at their ORIGINAL full durations, globally composites with exact half-open frame gates, then trims and encodes AAC once. Do not normalize the excerpt separately. Master selection comes from the actual returned master selection event and held raw hash, never a pointer/directory scan. No legacy template approval is fabricated.

## Original budget and next-step prerequisites

Parent-owned `opening-deadline.ts`, `generation-deadline.ts`, `generation-clock-watermark.ts` must remain authoritative. Capture opening attempt time immediately after closed parse, BEFORE readiness/lease preparation. Same original120-minute generation origin/high-water; whole25-minute opening attempt preserves80 minutes downstream (plan15 + body assets25 + assembly15 + full A/V QC15 + promotion5 + variance5). Phase ends original+40 minutes, so a full25-minute attempt must start by original+15 minutes. No free asset credit, quality waiver, renewed repair pool, or measured p95 claim. Cleanup protected time does not reset the original render remainder; later readback/selection still must fit it.

1. Check the capability owner's completed all53-current readback/absence evidence above and that the published artifact remains current. Request a shared source-stable window before capturing the next fixture; compiler/readiness bind a broad source closure. Do not renew a failed request's budget. A fresh explicitly requested fixture is a new synthetic request, and earlier failures stay retained.
2. Run the real1080p synthetic fixture below through production runner/activation/cleanup/readback. No live creative models. Retain any first failure; diagnose before retry. This is mechanical synthetic evidence, not creator quality or ten-minute performance.
3. Run approved actual cleanup-CAS fault cohort on that SAME successful stopped media claim: three distinct real cleanup attempts mutate held start, mutate held output, and inject backward wall time at the SECOND final CAS guard. Each keeps original journal/claim and failed/mutated artifacts. Fourth actual cleanup succeeds last, without another media render. Do not reinsert a cleared claim or delete failure markers.
4. After a successful actual whole chain, implement a separately immutable `openingMediaSelectionHash` pointer/fact binding actual completion, known readback start/output/receipt hashes, cleanup, original admission/precommit budget, exact media ranges and selectionQualifiedAt. No approval/head/final/body authority. Add actual corruption/source drift/journal race/deadline/failure-marker tests before exposing ready.
5. Cheap ready status then validates current journal/claim priority and exact selected receipt lineage, explicitly last-qualified snapshot/not-source-rechecked. Media GET must hash exact selected media bytes before same-FD streaming; do not rerun full source/Python hashing on every seek. Full source/current pipeline/context/output requalification is required at selection AND future opening approval.
6. A new claim/treatment journal invalidates old ready. Historical cleanup reader will need narrowly handling the new selection pointer; do not broadly ignore draft/context changes. Human/independent visual/listening approval and body generation remain separate unfinished work.

## Reproducible real fixture and runtime controls

Driver: `src/lib/server/__tests__/_guided-opening-media-fixture.ts`. Shared TEST helpers: `_guided-proposal-fixture.ts`, `_human-cut-fixture.ts`, `tests/_cut_preview_fixture.py`. Actual1080p testsrc2 and tone impulses; transcript, compiler, critic and human decisions are explicitly TEST-only. There is no spoken-source or creative listening qualification. Measured `statement-card` is1920×1080, dark/hold, no icon asset; exact short test copy. Actual FPS30000/1001 is preserved, even if target metadata says30.

Reobserve these controls; they were valid previously, not assumed forever. Docker/loopback/process visibility needs scoped sandbox escalation. The command accesses only the explicit local Docker daemon/image and synthetic workspace:

```sh
env SNIPER_DOCKER_PATH=/usr/local/bin/docker \
  SNIPER_DOCKER_SOCKET=/Users/maintainer/.docker/run/docker.sock \
  SNIPER_RENDER_IMAGE_ID=sha256:bc56d3860d2ec1c843f7184bcecd21137aa79fe9fe19c90a67136d3052222ba8 \
  SNIPER_RENDER_UID_GID=501:20 \
  SNIPER_RUNTIME_REPO_ROOT=/Users/maintainer/ProjectSniperSource \
  /usr/bin/time -p node --import tsx src/lib/server/__tests__/_guided-opening-media-fixture.ts --run-worker --cleanup-cas-faults
```

Working directory is the repository above. For one ordinary actual cleanup rather than fault qualification, omit `--cleanup-cas-faults`. Do not run while the source/catalog is known stale. Optional isolated workspace is a positional driver argument; never import into the user's personal registry implicitly.

Prior canonical Docker path: `/Applications/Docker.app/Contents/Resources/bin/docker`; prior SHA `d65cbcacef3db7341341eaf4d367a27dd026b90f671bdd1aa1fedf0dde7ed8b3`. Prior ffmpeg `/opt/homebrew/Cellar/ffmpeg/8.0_1/bin/ffmpeg`, SHA `d94d8e7af675f813e0a0faf036ff936d334ceb18daaec3a10a355679994e0311`; ffprobe adjacent, SHA `96f53c2099a3f59fc20efb424dd36d5510373f735cf9af50479c2f4d458695af`. Socket device/inode must be observed anew. Runtime image approval must be the exact pinned snapshot's `scripts/producer/headless/render_image_approval.json`.

## Tests and failures: exact scope

Most recent opening-server command:

```sh
/usr/bin/time -p node --import tsx --test src/lib/server/__tests__/guided-opening-result.test.ts src/lib/server/__tests__/guided-opening-process.test.ts src/lib/server/__tests__/guided-opening-cleanup.test.ts src/lib/server/__tests__/guided-opening-status.test.ts src/lib/server/__tests__/guided-opening-claim.test.ts
```

- 18/18PASS,0.76s wall, including actual venv prefix/cv2/numpy/scipy imports206ms. Other tests are protocol/status/schema evidence, NOT real media/Docker/cleanup-CAS.
- Added the explicit newer-claim-over-historical-cleanup regression afterward: status4/4PASS0.35s. No old media consulted.
- Whole typecheckPASS2.28s and focused new process/readback/cleanup/fixture ESLintPASS1.98s. These precede the later ready-only type fields, parent browser edits, small TEST-only failed-worker cleanup branch and new status test. The last tree is coherent by inspection, but no final integrated-tree type/suite was rerun after the user requested pause.
- Prior actual owned POSIX timeout/descendant/reaping/output-bound cohort4/4PASS2.19s. This did not simulate every detached nested probe; see caveat below.
- Claim/cleanup/checkpoint cohort38/38PASS2.47s. Independent quality re-review of durable stop/cleanup fixes13/13PASS0.60s. Original mutual-sidecar forgery accepted0.63s; fixed same repro rejected0.18s. Initial attack and rejection are both retained in `/private/tmp/sniper-stopped-process-forgery*`.
- `src/lib/server/__tests__/_guided-opening-cleanup-faults.ts` and the actual `guided-opening-readback.ts` consumer are implemented but their real integration cohort has NOT run. No claim that their positive paths passed.

Retained fixture failures:

1. First whole setup failed10.83s with `cut preview exited1`, before opening creation. An old TEST helper deleted its fixture. This is LOST fixture evidence; only terminal error/time remains. Do not invent its cause.
2. Approved TEST-only retainFailure/early root/bounded error serialization added; NEW request failed11.98s with `graphics.comp_capability_artifact.load_artifact: matrix is stale: motion source digest changed`. Retained root `/private/var/folders/3m/8rxbwgds5z7c3r72ccfqb9280000gn/T/sniper-human-cut-rJjmn3/test-only-cut-review-07df4ff4`, with `TEST-SETUP-FAILURE.json`. Actual cut preview/v2cut/raw intake/failed compiler are retained, but no opening claim or Docker graphics.
3. Earlier input-only11.49s failure rejected mandatory `iconFile:""` via field-name asset rule. Narrow schema3 exact-empty-value AND exact-empty-measured-default correction landed; schema2 and nonempty assets stay blocked. Its160×90 fixture is negative own-screen evidence, not1080p success: `/private/var/folders/3m/8rxbwgds5z7c3r72ccfqb9280000gn/T/sniper-human-cut-e1q2qp/test-only-cut-review-d955c3b0`.

Detailed incremental note: `/private/tmp/sniper-opening-slice-a-qualification-20260906.md`.

## Newly found detached-probe hard-kill caveat — unresolved

`scripts/producer/headless/process_runner.py:89` launches a new session. `headless/media_probe.py` uses it for ffprobe (and separate media checks also use this runner). Normal return/interruption through Python reaps that subgroup. But a hard outer Python SIGKILL can bypass its cleanup, leaving a detached local probe outside the TS-owned negative-PGID observation. Therefore outer `groupStopped:true` plus Docker absence is NOT proof that every detached local probe is gone.

The actual ordinary OCI Docker client in `headless/container_renderer.py::_run` inherits the outer group, so this finding does not show its late-create client surviving. It does not invalidate normal successful returns whose nested `run_text` calls reaped their groups. No actual leaked process was created or observed in this audit; this is a concrete code-path qualification gap, reported to main/quality without changing frozen renderer files.

Before claiming automatic hard-kill recovery, choose and prove a bounded policy: durably capture exact nested subgroup ownership and reobserve/reap it, or conservatively retain unresolved claim for forced outer-kill outcomes while still attempting exact Docker cleanup. Never guess PIDs or claim full descendant absence from the outer group alone. Existing fake-stop prevention does not solve this distinct nested-group issue. Keep the captured101 render-build source/catalog stable until the capability owner's run ends; a core helper change may invalidate that qualification.

## Creator source and final claim boundary

Main reported the user's reattached `C0679.MP4` is now readable: approximately10.28GB,834.335s,4K23.976 h264/yuv420p, stereo48k pcm_s16be, transfer `iec61966-2-4` (not default BT709 gamma). This owner has NOT hashed, decoded or edited it. Treat those as main's probe observations, not this slice's source qualification. Before actual creator/provider work, the next owner must read the canonical Producer SKILL and PIPELINE completely and apply real admission/color/audio requirements. Never reinterpret the synthetic fixtures as creator quality, a ten-minute full workflow, or proof of the two-hour target.
