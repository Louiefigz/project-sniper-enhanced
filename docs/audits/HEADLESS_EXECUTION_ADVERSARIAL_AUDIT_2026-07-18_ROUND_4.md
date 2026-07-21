# Headless execution adversarial audit — 2026-07-18, round 4

> **STATUS: FROZEN AUDIT SNAPSHOT.** This records the fourth adversarial wave and its cross-examination. Corrections belong in the living [headless optimization dossier](../producer/HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md), not by rewriting this record.

## Scope and method

Reviewed only headless Claude Code/Codex planning and execution into Palmier, plus approved-plan realization into MP4. GUI work remained excluded.

Three independent attacks tried to disprove the round-three plan from different directions:

1. Product economics and latency evidence, including every retained failed attempt rather than only the successful specimen.
2. State-machine, fencing, commit, stop/resume, and reader/garbage-collection interleavings.
3. Operational, filesystem, export, concurrency, disk, and model-tool security failure modes.

The agents then cross-examined the prior internal-canary decision. That cross-examination changed the decision: offline Palmier compiler/manifest/diff work remains useful, but another live Palmier mutation is temporarily blocked. No production code or tests changed in this round. The earlier complete TypeScript and 1,559-test Python baseline remains the latest test evidence; this round inspected code and retained artifacts and changed documentation only.

## Round-four verdict

The deterministic MP4 direction survives, but its implementation order changes. The fastest safe hypothesis to test is **MP4-only with dependency-scoped repair**. Production Palmier investment is not justified by the retained timing evidence.

The current implementation is not production-ready and the greater-than-95% product-direction claim is not supported. The new hard blockers are:

- A stop can be reported before the old process group is dead, allowing overlapping writers.
- Desktop Palmier Pre/Post reservations are not atomic and can misattribute concurrent same-tool operations.
- Local MP4 promotion and Palmier delivery are multi-file or remote side effects without one authoritative commit.
- Parsed inputs can differ from the bytes later hashed and approved.
- Palmier export completion can be inferred from a parseable but incomplete file.
- The current machine is 98% full, while retention and space reservation are undefined.
- Model subprocesses can read repository-root files even though their process environments are allowlisted.

## Decisions overturned

### The 40-second Palmier repair is selected warm-retry evidence

The first retained card-repair attempt was not a success. It spent 33.356 seconds preparing the changed asset and 113.248 seconds in the Claude/Palmier turn. A stale positional `trackIndex: 0` pointed at the caption lane after graphics had moved to track 3. The attempt removed four captions, trimmed two more, left the original graphic in place, could not undo or reconcile, and required cleanup. The failure is recorded in the first [card-repair runtime](../../artifacts/palmier-card-repair-acceptance-20260716/producer/.live-card-repair-runtime.json) and [first-60 runtime](../../artifacts/palmier-card-repair-acceptance-20260716/producer/.live-first60-runtime.json).

The later r2 acceptance script explicitly seeds its assets from that failed r1 run in [live_desktop_palmier_card_repair_acceptance.py](../../scripts/producer/tests/live_desktop_palmier_card_repair_acceptance.py). Its 0.492-second preparation and 40.413-second mutation are therefore a warm recovery specimen, not an independent cold success. Including the failed preparation/mutation and the retained r2 cut, visual build, preparation, and repair gives a 733.093-second lower bound—12m13s—before export, final QC, operator setup, and recovery labor.

The r2 [candidate record](../../artifacts/palmier-card-repair-acceptance-20260716-r2/producer/palmier.timeline-candidate.json) remains unapproved and QC-pending. It is 3840×2160 and 43.792 seconds long, not a retained accepted 45–60-second 9:16 short.

This evidence proves only that one warm, bounded mutation can work after a prior destructive attempt and a targeting fix. It does not prove a 40-second quality pass, publish-ready quality, cold reliability, or favorable product economics.

### Maintaining an editable Palmier realization has an unpriced setup cost

A flat MP4 delivery has no separately replaceable cards. Card-local Palmier repair requires building and maintaining a second `palmier-editable` realization.

The retained r2 editable setup took 82.832 seconds for cut execution plus 462.752 seconds for visual execution: 545.584 seconds before planning, assets, export, or final QC. Compared with MP4 composites around 70–86 seconds recorded in the [latency punch list](../producer/PRODUCER_LATENCY_OPTIMIZATION_PUNCHLIST.md), the optimistic warm Palmier mutation saves only about 30–46 executor seconds per eligible repair. Amortizing the extra editable build would require roughly 12–19 eligible card repairs per short, before failures and Palmier export/QC. A normal single extra quality pass does not support that economics.

The canary also excludes cut, caption timing, audio, presenter recomposition, global look/reframe, and transition changes. No retained field data establishes what share of real feedback is eligible. Without GUI value in scope, editability has no demonstrated benefit over changing the declarative plan and reusing isolated assets in the MP4 pipeline.

### Correctness architecture cannot be sold as the near-term speed win

Round three placed the direct latency work after several migration and authority phases. That sequence would spend substantial engineering effort before testing the likeliest speed lever.

The current code also explains why a second pass can cost nearly the first pass. After QC changes the plan, [quality-loop.ts](../../src/app/api/producer/auto-edit/quality-loop.ts) invalidates back to `plan_authored` and explicitly reruns every planning review and gate. [pipeline.ts](../../src/app/api/producer/auto-edit/pipeline.ts) then renders and performs QC again.

Model work is heavily provisioned without stage-specific evidence: Claude defaults to `opus`; both authoring stages use `xhigh`; several Claude review/revision paths also use the default model at `xhigh`. Codex already caps short/light authoring at `high` and uses lower reviewer reasoning in some paths. Current JSONL handling records elapsed time but drops token, cache, cost, and immutable resolved-model data.

The speed work therefore moves forward:

1. Instrument request-to-approved-output time, active operator time, model/tool identity, tokens, cache state, retries, recovery, and disposition.
2. Restore disk headroom and establish attempt reservation before benchmark work.
3. Implement and benchmark MP4 dependency-scoped repair plus same-input per-critic receipt reuse.
4. Test stage-specific model/effort settings behind blinded noninferiority gates.
5. Continue authority and migration work because it is required for correctness, but do not count it as a measured speed improvement.
6. Reconsider live Palmier only if MP4 repair fails the preregistered kill test or field feedback shows enough Palmier-eligible changes to cross the measured break-even.

## Concrete state-machine counterexamples

### `interrupted` does not mean quiescent

[auto-edit-stop.ts](../../src/lib/server/auto-edit-stop.ts) writes the job and producer run as interrupted before sending `SIGTERM`, and schedules `SIGKILL` asynchronously. [project-mutation.ts](../../src/app/api/_lib/project-mutation.ts) admits a new mutation whenever the producer run is not `running`.

Counterexample:

1. Worker A or one of its ffmpeg/Palmier descendants is still mutating.
2. Stop writes `interrupted`.
3. Worker B sees a non-running producer status and acquires a mutation lease.
4. A and B overlap until termination is proved, or indefinitely if an untracked descendant survives.

The corrected transition is `running -> stopping -> interrupted-quiescent`. `stopping`, a live orphan, or ambiguous process identity remains mutually exclusive with every writer. The full-lifetime arbiter is released only after the exact process group is dead and reaped. A stale process may continue computing, but its fencing token must be unable to commit locally or remotely.

### Recovery can overwrite a newly live worker

[auto-edit-job-store.ts](../../src/lib/server/auto-edit-job-store.ts) decides liveness outside the job lock, then its terminal write checks only token and status. A heartbeat can occur between those steps and still be overwritten as interrupted. [job-stream.ts](../../src/app/api/producer/auto-edit/job-stream.ts) invokes recovery on its polling path, making this race recurrent rather than theoretical.

Recovery must compare the exact observed revision/heartbeat/worker identity under the lock. Terminal transitions are conditional on that observed state still being current.

### Outer status can manufacture approval

[job-stream.ts](../../src/app/api/producer/auto-edit/job-stream.ts) synthesizes `outputs: approved:true` from a completed journal when it did not observe an output event. [producer-run-registry.ts](../../src/lib/server/producer-run-registry.ts) clears active state on outer completion. Neither action proves a committed sink.

The direct [render route](../../src/app/api/producer/render/route.ts) can also emit an output path before Audit B finishes. A headless consumer can therefore act on candidate availability that later fails QC.

Completion and approval must derive from a verified immutable generation selected by `CURRENT`, not from the job projection.

### Live locks can be stolen by age

[auto-edit-job-lock.ts](../../src/lib/server/auto-edit-job-lock.ts) removes a lock older than 120 seconds even if its PID is alive. The launch lock has the same class of failure, while the project lease relies on PID-only identity. A slow critical section or PID reuse can create split brain.

Never time-break a demonstrably live owner. Use kernel exclusion, process start/boot identity, heartbeat where needed, and a monotonically unique fencing epoch. Reject symlink or nonregular lock paths.

Auto Edit lint/base/assemble stages and many Python ffmpeg calls also lack uniform deadlines, closed stdin, and durable process-tree supervision. Every external process needs one supervisor with bounded output, TERM/grace/KILL/reap semantics; no lock, staging cleanup, or replacement writer proceeds while a descendant may still be alive.

## Corrected commit and side-effect protocols

### Local immutable generation

1. Acquire the common project writer arbiter and a never-reused fencing epoch.
2. Resolve the expected parent `CURRENT` commit digest while holding it.
3. Create a unique sibling staging directory on the same filesystem.
4. Write and verify every media/evidence/receipt file; fsync every authoritative file.
5. Write `commit.json` last; fsync it and the staging directory.
6. Rename staging to a unique immutable generation and fsync the generations parent.
7. Revalidate the expected parent, attempt, and fencing epoch under the arbiter; update `CURRENT`; fsync the pointer and parent directory.
8. Emit approved output only from the selected, closed generation. Materialize root `final.mp4` afterward as non-authoritative compatibility data.

A rename alone is not compare-and-swap. Process-crash atomicity and power-loss durability are distinct claims: current job writers do not fsync, while the shared atomic helper fsyncs the temporary file but not the containing directory after rename.

Readers must resolve `CURRENT` first before a V2 writer exists. Garbage collection is disabled initially. Later GC must retain `CURRENT`, approvals, deliveries, live/ambiguous attempts, quarantines, and pins, and must prevent a generation from being deleted between resolution and open. The CAS compares a never-reused commit digest/epoch, not a reusable name, to avoid ABA.

### Remote Palmier mutation or delivery

`palmier-flat` remains a delivery of already approved MP4 bytes; its failure never invalidates that local realization. It is not, however, safe to retry blindly.

[sync.py](../../scripts/producer/palmier/sync.py) creates a shadow, performs operations, activates the generated timeline, and only then writes the local sidecar. [shadow.py](../../scripts/producer/palmier/shadow.py) performs `create_timeline` before a durable local result exists. A timeout or crash after a remote effect but before the receipt can cause a retry to create or activate a duplicate timeline.

Every remote effect, including flat delivery, needs a durable pre-send intent containing operation ID/idempotency key, expected parent, exact bytes/authority, capability identity, attempt, and fence. Classify failures as pre-send safe, definitive rejection, or ambiguous post-send. Only the first two classes may be retried automatically. Ambiguous effects are queried by operation ID, exactly read back, reconciled, or quarantined. If the server cannot support this identity, automated promotion remains unproved.

### Desktop hook reservation

[desktop_hook.py](../../scripts/producer/palmier/desktop_hook.py) currently performs load/check/set/save without an atomic lock. Two agents can both read `pendingOperation:null`, overwrite one another's reservation, and both mutate. PostToolUse matches only the tool name, so one agent's result can be attributed to the other's arguments.

Pre and Post must run under the same cross-family arbiter and an atomic state CAS. The pending record binds operation ID, session/attempt, arguments hash, tool, exact parent fingerprint, and fence. A second Pre rejects while one is pending. Post must match every bound field and the current fence; a stale or ambiguous result quarantines the candidate.

## Input, export, disk, cache, and security attacks

### Parsed bytes are not necessarily approved bytes

[checkpoint_inputs.py](../../scripts/producer/palmier/checkpoint_inputs.py) parses manifest A, then separately opens the path to hash it. A replacement with manifest B can make translation use A while authority binds B; later `authority_current` can validate B. [render.py](../../scripts/producer/render.py) similarly parses plan/manifest before an approval routine reopens their paths, then renders the earlier in-memory values.

Open each input once with safe directory-relative semantics, validate the descriptor as a regular allowlisted file, copy and hash from that same descriptor, and parse only the frozen snapshot. Rewrite media references to snapshot-local logical asset IDs. Reject URLs/protocols, devices, FIFOs, sockets, symlinks, and paths outside configured roots.

[assemble.py](../../scripts/producer/assemble.py) can refit a stale base and replace the plan path. An executor must never mutate its approval artifact: refit only a writable execution copy, and require a new realization approval for any semantic change.

### Export completion can false-pass

[export.py](../../scripts/producer/palmier/export.py) treats two equal-size polls as completion and verifies only a declared video duration. [native_qc_export.py](../../scripts/producer/palmier/native_qc_export.py) can then hash and promote the file. An encoder pause, early valid metadata, fragmented MP4, or truncated tail can satisfy that contract.

Require explicit Palmier completion when available, then fully decode video and audio with fail-on-error semantics. Verify decoded frame/packet counts, audio duration/presence, canvas, FPS, and expected end before hashing. Use attempt-unique staging paths and test pauses, partial/truncated media, delayed metadata, stale files, and exporter crashes.

### Disk reservation is a precondition, not an open cleanup question

At final verification the data volume was 1.8 TiB total with about 49 GiB free and 98% used. `artifacts/` occupied about 4.5 GiB; one retained Palmier specimen occupied 2.9 GiB. Only about 17 specimen-sized directories fit in the remaining space before snapshots, caches, rollback margin, or other workloads.

Before expensive work, reserve pessimistic peak space for source closure, p99 intermediates, export, rollback, and at least the agreed concurrent-generation footprint. Use global and project quotas and same-filesystem staging. Initially keep GC off; later use lease-aware mark/sweep. Inject `ENOSPC` at every write and rename and prove the prior `CURRENT` remains valid.

### A shared graphics cache needs its own atomic protocol

[graphics_render.py](../../scripts/producer/graphics/graphics_render.py) checks for a content-key output, writes the same `_gs-<key>.html`, and renders directly to the same output without shared locking or attempt staging. A project-level arbiter does not prevent two projects from racing the shared cache.

Use a per-key kernel lock, attempt-unique input/output staging, verified receipt, atomic publish, and safe loser reuse. Never expose an incomplete cache object as a hit.

### Environment allowlisting does not constrain model file reads

[ai-provider.ts](../../src/app/api/_lib/ai-provider.ts) removes most application credentials from Claude/Codex process environments. However, authoring and review grant broad `Read` and sometimes `Glob`/`Grep`, while rendered critic directories include the repository root. `.env` and `.env.local` exist beneath that root.

Treat transcripts, OCR, media metadata, and filenames as untrusted prompt input. Give models a sanitized, immutable per-run evidence jail with only allowlisted files and brokered commands; do not add the repository root. Add seeded fake-secret/prompt-injection tests and redact logical paths, prompts, and logs.

Palmier authority/Desktop records include full timelines and local paths but are created under the ambient umask. Authority directories/files must be 0700/0600, reject symlink/nonregular targets, use exclusive attempt staging, and fsync the file and parent directory. These controls address crashes and cooperative races, not a fully hostile process under the same OS identity.

## Minimum must-pass adversarial matrix

| Attack | Required invariant |
|---|---|
| Two writers at launch, Pre/Post, generation commit, `CURRENT`, and Palmier promotion | Exactly one fence can mutate and commit; the loser cannot publish |
| Stop at every stage, including descendant ffmpeg and remote mutation | No new writer until the old group is dead; stale fence cannot commit |
| Crash/power loss before and after every authoritative write, rename, commit, and pointer update | Prior `CURRENT` or the complete new generation is selected; never a mixture |
| Manifest/plan A→B swap, same-size rewrite, parent swap, symlink/hard-link substitution | Parsed, hashed, approved, and executed bytes are identical and allowlisted |
| Remote timeout before send, after effect, before response, and during activation | No blind retry; exact reconciliation or quarantine; no duplicate promotion |
| Export pause, partial/truncated MP4, delayed metadata, stale temp | No approval until complete decode and exact media facts pass |
| `ENOSPC` at each boundary plus GC/read/write races | Prior commit remains usable; reachable or pinned data is never collected |
| Shared-cache same-key concurrent render | One verified object is published; no partial hit or staging collision |
| Model prompt injection with seeded fake secret | Secret is inaccessible and absent from provider/log artifacts |
| Model/CLI/MCP/Palmier/ffmpeg drift on resume | Exact supported identity is bound or the run fails closed and requalifies |

## Minimum unbiased speed experiment

Use six 45–60-second vertical projects: two light, two produced, and two full. Randomize three routes per project:

1. MP4-only with dependency-scoped repair.
2. Palmier-editable-only, exported through final approval.
3. Hybrid MP4 plus a maintained Palmier-editable realization.

All routes start from the same immutable source, intent, and approved cut—not the MP4-specific plan. Give each route one preregistered eligible card change and one noneligible change rotating among cuts, captions, audio, motion, and global reframe. Isolate sessions and caches. Run cold first; a warm run may use only cache created by that same route. Count all failures, rebuilds, interventions, recovery time, and storage.

Execute the MP4 scoped-repair versus full-replay arm first. The Palmier arms remain preregistered but blocked until the live-canary safety gates pass, and may be canceled entirely if MP4 meets the kill threshold.

Primary endpoint: command submission to exact approved final MP4 after the second revision. Also record active operator seconds, provider/model tokens and cost, p50/p95, and three-rater blinded quality.

Kill the hybrid hypothesis if it is not at least 20% faster than MP4-only on paired median complete time, or if p95/operator intervention is worse. Six projects can reject a clearly inferior direction; they cannot establish 95% reliability. If no route is eliminated, power an untouched confirmatory holdout from the pilot's paired differences.

## Round-four go/no-go

| Path | Decision after this round |
|---|---|
| Complete observability and unbiased paired benchmark | Go first |
| Disk headroom/reservation and full-lifetime writer fencing | Go first; production blocker |
| MP4 dependency-scoped repair under existing V1 routing | Go after immediate input/commit safety containment |
| Reader-first V1/V2 fencing and immutable authority | Go for correctness; not counted as a speed result |
| Offline Palmier compiler/manifest/path-diff work | Go |
| Another live Palmier mutation canary | Temporary no-go until MP4 kill test, quiescence, common lease/CAS, remote reconciliation, and disk gates |
| Palmier-flat automated delivery retry | No-go until remote intent/idempotency/reconciliation exists |
| External Palmier repair beta or native publishing | No-go |
| Rich Claude/Codex direct-MCP production | No-go |
| Greater-than-95% product-direction claim | Not supported |

The revised direction is intentionally falsifiable: make the local MP4 second pass cheap, measure the complete accepted-output economics, and force Palmier to earn further investment after its isolation and recovery contracts are real.
