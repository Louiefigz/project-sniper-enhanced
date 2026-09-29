# Native long export and recovery

New native exports enter `studio/native_export.py`, which selects exactly one
declared Short or Long adapter. Eligible landscape edits use
`studio/native_long_export.py` internally. This is
an adapter over the existing native owner, pinned SDK, audio delivery, source
cache, stage evidence and encoded picture checks. Do not write a dated per-video
export script or inherit the Short worker's 480-second child timeout.

Keep an already active edit's source/approval history. This command does not
migrate archived qualified exports or approve editorial quality. The usual
independent editorial review, listening, full playback and MP4 + live Studio
handoff still apply.

## Declare the finished composition

Stage local assets and the complete intended stereo, 48 kHz float WAV through
the owned program-audio command below. Preserve source dialogue, pauses and its
exact sample clock. Diagnose hum on the source
and apply an appropriate shared audio treatment before this stage; a 53 Hz notch
from one recording is not a universal voice preset. Do not infer a new treatment
because picture rendering failed. The WAV is the premixed program authority;
HTML audio fades, gains, groups and multiple tracks are outside this adapter.

New produced/full work starts from `native-short.ts prepare-longform`, follows
the packet's `AGENT-BRIEF.md`, and completes the generated `project/` scaffold.
Preparation writes its schema-version-2 `LONG-PROJECT.json` and
`NATIVE-LONG-POLICY.json`; do not replace that scaffold with a legacy project.
The finished project places `index.html` beside the scaffold and binds the exact `LONG-REQUEST.json`, allocated
`VISUAL-PLAN.json`, and complete `visualPlanApplication` described in
[the shared visual-plan contract](VISUAL_PLAN.md). The abbreviated shape is:

```json
{
  "schemaVersion": 2,
  "requestPacket": {"path": "/absolute/LONG-REQUEST.json", "sha256": "<sha256>"},
  "visualPlan": {"schemaVersion": 1, "path": "/absolute/VISUAL-PLAN.json", "byteHash": "<sha256>", "visualPlanSha256": "<sha256>", "pictureInputSha256": "<sha256>", "catalogPinSha256": "<sha256>", "upstreamAuthoritySha256": "<sha256>"},
  "visualPlanApplication": {"schemaVersion": 1, "route": "native-long", "visualPlanSha256": "<sha256>", "decisions": []},
  "canvas": {"width": 1920, "height": 1080, "frameRate": "30/1", "totalFrames": 120},
  "audio": {"file": "assets/program.wav"},
  "scenes": [
    {"startFrame": 0, "endFrame": 60, "mediaIds": ["presenter"], "visualIds": ["opening-proof"]},
    {"startFrame": 60, "endFrame": 120, "mediaIds": ["supporting-footage"], "visualIds": ["comparison-card"]}
  ]
}
```

The empty `decisions` array above is only a shape abbreviation; a real project
must contain one exact execution row for every allocated opportunity. Schema
version 1 remains a legacy read/revision format outside prepared requests and
does not acquire a visual-planning claim merely by adding prose or catalog IDs.

Scenes are contiguous integer half-open frame ranges. `mediaIds` names the
root-timeline videos expected to be visible in that scene; use an empty list for
a graphics/still-only scene. Schema 2 `visualIds` is the exact ordered set of
visual-plan elements active in the scene. Each ID's executable HTML element must
carry `data-start` and `data-duration` matching its allocated frame window.
Include boundaries when simultaneous media or planned visuals change.
The HTML must have the matching explicit landscape canvas and duration, muted
normal-speed videos with stable IDs, and one complete-program WAV at time zero.
Current bounds are 1–60 fps, 15 minutes, up to 3840×2160 and 256 scenes/media.
Nested/dynamic media and intentional invisible-video intervals require explicit
adaptation; the scene check refuses mismatches rather than inventing intent.

Use [selected-source preparation](NATIVE_LONG_SELECTED_SOURCES.md) when an edit
uses small portions of long originals. Preparation preserves source provenance;
it does not replace source review. Ensure the output manifest describes the
prepared HTML's IDs and clocks.

Before `review-input`, prebuild review or export, run the exact current
program-audio preparation. Use the absolute manifest path recorded in
`LONG-REQUEST.json` and a new attempt directory on the first run:

```sh
./sniper python3 scripts/producer/native_program_audio.py \
  /absolute/source-project/producer \
  /absolute/source-project/source/asset_manifest.json \
  /absolute/request-directory/project \
  /absolute/new-program-audio-attempt
```

This installs `project/assets/program.wav` and `project/PROGRAM-AUDIO.json` from
the exact accepted edit plan and manifest. Re-running the same command with the
same attempt directory revalidates and reuses the completed owner. Any plan,
manifest, WAV, clock or owner change stops admission. The receipt explicitly
withholds listening, editorial and export approval.

```sh
./sniper .venv/bin/python scripts/producer/studio/native_export.py \
  /absolute/project /absolute/new-attempt \
  --cache /absolute/cache --audio-profile default-v3
```

Always select the intended shared audio profile explicitly when transferring an
existing edit. The compatibility default is `native-short-v1`; an existing
`default-v3` result must retain `--audio-profile default-v3`.

## Required current review

Before export, an independent reviewer supplies `PREBUILD-REVIEW.json` beside
the composition. Obtain the exact input binding with:

```sh
./sniper .venv/bin/python scripts/producer/studio/native_export.py review-input /absolute/project
```

This command returns a digest and complete file pins; it does not create a pass.
The review uses the existing native prebuild schema: `schemaVersion: 1`,
`scope: "native-long-full-project"`, the returned `planHash`, declared separate
reviewer/planner session IDs and `independent: true`, eight nonempty `coverage`
assessments (`briefAndRetainedMessage`, `assetsAndSourceEvidence`,
`cuesAndSceneCoverage`, `layoutCropAndText`, `motionAndTransitions`,
`pacingAndAudio`, `feasibility`, `visualSourceSelection`), nonempty hash-bound `evidence` references,
and a passing plan-stage `ProducerReview` with no material issues. The shared
TypeScript validator checks the complete record. All project assets and HTML
participate in the hash, excluding the review sidecar and generated manifest to
avoid a circular binding. Changed evidence or composition requires a new review.

For an explicit reference match, declare `referenceMap` in `LONG-PROJECT.json`
as the canonical absolute path to the checked Long reference reuse map. Both
`review-input` and export validate its project, format, readiness and all source/
catalog/reference pins. Those bytes also participate in the review digest and
export/recovery evidence. Once declared, no additional CLI flag is needed.
Ordinary inspiration does not require a map; an unrecorded conversational intent
cannot be inferred by the standalone renderer.

The shared launch boundary rejects custom native video wrappers. The installed
native SDK render CLI and capture workers additionally require the active shared
owner. Long picture launch requires current passed encoded seam evidence.
These checks enforce recorded prerequisites; they cannot authenticate subjective
review quality or prevent an operator using a separate external renderer.

## What happens before the master

1. Validate the manifest, source paths, native static contract and current
   recorded full-project prebuild review before media work.
2. Prepare and qualify the exact audio master. A failed audio gate stops picture
   work. A reused master is still checked against current input, profile, sample
   count, section mapping and quality; human listening approval is never invented.
3. Probe source PNG sizes at three positions in each distinct used range, reject
   short ending windows there, and admit projected cache, scratch,
   sample and output allocations plus the shared 10 GiB reserve, then ask the
   pinned SDK to extract original-resolution source frames. Metadata and source
   extraction are sequential within the SDK; complete-source HDR negotiation
   remains unchanged. HDR compositions conservatively reserve cold-cache space
   because SDR-to-HDR transforms use different cache keys. The projection has
   headroom; it is not a worst-case compression guarantee. Live disk/memory
   monitoring remains mandatory. A source ending early fails here, before a full
   master. Author an explicit last-frame hold when appropriate; do not shorten
   dialogue or silently fabricate missing picture.
4. Capture full-project absolute-time samples at each cut ±2 frames, start/end,
   and every two seconds, then visit them in reverse. Check active media, exact
   scene/source state, pixel stability and a full-quality encoded sample reel.
   The reel contains selected neighborhoods, not an unbroken preview of the edit.
5. Generate continuous moving windows with the same native picture path and exact
   excerpts of the whole-program audio master. The default invocation stops here.
   An independent critic reviews picture, motion, context and audio, then supplies
   a `--preview-reviews /absolute/reviews.json` bundle for a new attempt. See
   [render readiness](RENDER_READINESS.md) for the bundle and region-map contracts.
   Unchanged dependency-bound previews and detailed reviews can be reused. A new
   full-project prebuild review remains required after editorial changes.
6. Run the unchanged high-quality/CRF 15, one-worker SDK picture render. Source
   frames remain PNG. No resolution, frame rate or quality gate is lowered.
7. Seal the completed picture under its own verified owner. Then run shared AAC,
   mux, sRGB metadata/payload checks, encoded/native comparisons and full decode.

All expensive stages retain the shared heavy-work lease, current memory/disk
limits and verified descendant cleanup. Long owners can wait up to 600 seconds
for temporary contention/pressure, recording `waiting-for-capacity` with no
launched child. Missing telemetry and unverified cleanup still fail explicitly.
The owner records `running` only after the child exists.

Moving-preview windows have separate `preview-picture-N` and
`preview-package-N` owners. Each releases its processes and heavy-work lease,
verifies cleanup and seals its output before the next capacity admission.
A new attempt automatically restores compatible sealed windows; an audio-package
failure can reuse its completed picture. Unsealed media from failed older
monolithic preview attempts is not reusable evidence. Source, runtime, tools,
media hashes and original cleanup are revalidated before reuse.

Memory telemetry brackets footprint collection with direct owned-process
identity reads inside one helper. Exited children are distinguished from newly
observed or unreadable live children; missing live measurements remain errors.
The existing four-attempt/18-second telemetry bound and memory-pressure limits
remain in force. Failure receipts distinguish `measurement-unavailable`,
`host-memory-pressure`, `render-memory-limit`, `cleanup-unverified`,
`cancelled` and `renderer-failure`.

Picture deadlines are frame-derived, with an explicit cleanup/assembly margin
and six-hour absolute configuration ceiling. At 30 fps/15 minutes the child
picture allowance is 7,350 seconds and its execution/cleanup allowance is 7,950
seconds. Each long owner additionally reserves 600 seconds for capacity waiting
(8,550 seconds total for that picture phase), so queuing does not consume the
planned work allowance.
These are failure bounds, **not predicted delivery times**. Ten minutes without
advancing SDK frames, source-frame allocation or adapter counters aborts a
stalled child through the same cleanup path. Repeated warnings do not renew it.
The inner SDK source-extraction timeout also receives the corresponding phase
budget; it does not retain the SDK's five-minute default behind a longer owner.

## Reuse completed work

Every attempt gets a fresh destination. Never overwrite a failed attempt,
manufacture a cache completion marker or retrofit a successful owner receipt.

Ordinary invocations now automatically select the most complete compatible
terminal attempt: finished media first, then picture plus audio, then qualified
audio. Discovery checks siblings and a per-project immutable history outside the
authored project, so changing output parents does not lose completed work. A
project reservation serializes discovery/publication. History and sibling scans
are bounded at 256 entries; retain a dedicated attempt directory and reconcile
history when full. Explicit donor/resume options remain available.

Exact project, implementation, runtime, tool, cache and audio-policy bindings
must match. Changed inputs start new work; a corrupt compatible seal or an active/
interrupted matching attempt stops with an actionable error instead of silently
launching a duplicate. Discovery pointers never substitute for stage proofs.

After a picture-only edit or failure, reuse checked audio:

```sh
.venv/bin/python scripts/producer/studio/native_long_export.py \
  /absolute/project /absolute/new-attempt --audio-profile default-v3 \
  --prepared-master /absolute/prior-attempt/audio-preparation/receipt.json
```

`--audio-donor /absolute/prior-attempt/audio/receipt.json` also reuses qualified
AAC through the existing shared donor contract. It retains final delivery checks.
The two audio reuse options are mutually exclusive.

After a later stage fails, resume the exact project:

```sh
.venv/bin/python scripts/producer/studio/native_long_export.py \
  /absolute/project /absolute/new-attempt --resume-from /absolute/prior-attempt
```

A complete `render-stage.json` reuses finished media and compatible capture, then
runs final verification. If only `picture-stage.json` completed, the adapter
reuses that picture and checked float master and repeats remaining gates. Source,
runtime, implementation, clock or policy changes invalidate incompatible seals.
A missing/failed picture is never treated as reusable. Preserve earlier donors.

`delivery.json` is the final status. `native-long-checked-for-review` means the
technical checks and owned cleanup passed; it does not mean a person has approved
listening, story, visual quality or the required live Studio review.
For schema-version-2 projects with a visual plan, the exporter then automatically
records the allocation and writes `visual-usage-registration.json` before
reporting workflow success. A registration failure preserves the checked render
and returns a failed workflow result; use `visual-plan-usage.ts register` only
for recovery or backfill. This machine record keeps
`humanApprovalClaim: false`.
The shared `native_review_bundle.py prepare` now accepts this exact long status,
including recovered exports, and prepares both an unchanged local MP4 and an
editable Studio fork with the final AAC copied without re-encoding. Open and
actually review both surfaces before making playback or handoff claims.

## Qualification and limits

### Guarded initial Long sections (September 28 implementation)

The public exporter has an opt-in section route:

```sh
./sniper .venv/bin/python scripts/producer/studio/native_export.py \
  /absolute/project /absolute/new-section-attempt --sections \
  --preview-reviews /absolute/current-moving-preview-reviews.json
```

Current prebuild, source, program-audio, seam-sample and independently reviewed
moving-preview requirements still apply. The request stores one shared initial
Long plan in `revision` with `mode: "initial-long"`; it has no Short ancestor.
The plan uses stable section IDs, absolute half-open frame ranges, generations
and input identities. Each render window is at most 250 frames. These technical
windows do not assign creative authors or replace a director's shared plan.

Each window runs through the existing native owner in a separate supervisor
process. Dispatch selects the host pool's capacity for the exact Long workload,
including an exact live qualification session. Without matching qualification
the capacity is one. The shared pool still owns FIFO admission, memory/disk
reservations and cleanup. More dispatcher workers do not grant more capacity.
The children share the parent phase's remaining picture deadline. Section/capture
source frames use the shared store with private worker views and reader leases.
The ordinary unsectioned SDK picture render retains its existing cache route;
its cache is not collected by the new store. Long section throughput has not
been qualified by these code checks.

A finished section publishes its picture, exact full-master PCM excerpt and
`segment-picture-N-stage.json` only after verified owner cleanup. The evidence
is immediately available while other sections are running. If a section fails,
completed seals remain available. Cancellation requests normal owned cleanup;
an unresponsive direct supervisor is stopped after a bounded wait, without
granting cleanup proof or releasing a surviving worker's pool quarantine.

Assembly stops with `failureCategory: "section-review-pending"` until independent
section reviews are supplied. Review the encoded picture and its paired PCM,
including neighboring context, then resume into a new attempt:

```sh
./sniper .venv/bin/python scripts/producer/studio/native_export.py \
  /absolute/project /absolute/new-reviewed-attempt \
  --resume-from /absolute/prior-section-attempt \
  --section-reviews /absolute/section-reviews.json
```

The explicit resume automatically selects the section route and admits donors
only from the registered named attempt. It revalidates and preserves that
attempt's admitted preview evidence/mode, cache and audio policy; there is no
need to repeat `--preview-reviews`. Conflicting preview overrides are refused.
The parent checks current moving-preview reviews before dispatching any section,
and each section's launch and worker repeat that admission.
Without `--resume-from`, `--sections`
discovers exact-plan seals through the existing immutable export history.
Original sections are never overwritten. Corrupt or changed matching seals
fail validation. Recovery here preserves technical work; it does not create an
editorial pass.

The section review bundle is `{ "schemaVersion": 1, "reviews": [...] }`, with
exactly one row for every required section. Each row records `planIdentity`,
`sectionId`, `generation`, `inputIdentity`, `frameRange`, `media: {path, sha256}`,
distinct `authorTaskId`/`reviewerTaskId`, `status: "pass"`, and hash-bound
`evidence`. `checks` must pass and `assessments` must explain all six categories:
`sourceFidelity`, `captions`, `visuals`, `motion`, `audio`, `neighboringContext`.
`observations` must contain `encoded-playback` and `audio-listening`, each with
`kind`, `path`, `sha256`, and the complete section `frameRange`; both referenced
files must appear in the pinned evidence. The playback hash must match the sealed
picture and the listening hash its sealed PCM. Task identities and observation
claims are reviewer declarations. The engine checks the records and current
bytes; it cannot authenticate identity or prove someone watched or listened.

Assembly requires every current sealed section and its current QC. It checks
coverage, stream compatibility and packet payloads, joins into a pending file,
then rechecks the frozen manifest and review identities before publishing.
The existing per-project history reservation orders section attempts; a newer
attempt supersedes an older pending join, even when the older worker finishes
late. Successful delivery rechecks the same currentness barrier under that lock.
Shared audio, encoded/native comparison and final full-decode QC still run.
`native-long-checked-for-review` still requires actual final playback/listening
and the matching live Studio handoff.

The next integration increment wires the existing format-aware production
budget into the public Long entry. A bound output retains its original clock,
attempt counters and cleanup reserve across preparation, pool waits, section
launches, repairs and review continuations. An actual section launch is charged
after pool admission and before the child starts. The original production clock
and independent stage clock are both rechecked after preparation and monitored
while the child runs. One authority-approved transient retry is possible;
deterministic failures do not acquire a fresh allowance. Final AAC candidates
also consume the same original audio counters. These are implementation checks,
not a demonstrated delivery SLA.

`--repair-from /absolute/original-attempt` selects cross-generation picture reuse
against a separate immutable project snapshot. It is mutually exclusive with
`--resume-from`. The original project and its registered request/seals must still
validate. An explicit implementation/tool partition must match, while the existing
dependency reader computes affected windows. Compatible picture copies receive
fresh current PCM and current owner seals. Shared style/clock changes widen the
closure; modified originals, missing proof or changed implementations refuse
reuse. This does not transfer editorial approval to changed inputs.

### Registered section authors and reviewers

`--section-plan /absolute/assignments.json` adds registered logical assignments
to the technical section route. It uses the existing production task table,
enrolled director, claim/attach/completion APIs and original dispatch limits.
The closed plan contract is in `studio/production/section_plan.py`: it binds the
authority/output/director, one frozen shared creative-plan receipt, absolute
logical ranges, source input pins, private task output root and authored-file
mapping. Logical boundaries split technical windows when needed. It supports
up to three logical assignments without changing the existing author limit.

Register the author tasks before integrating their private artifacts:

```sh
./sniper python3 scripts/producer/native_long_sections.py enqueue \
  --plan /absolute/assignments.json
```

The supervising host dispatches the returned tasks through the existing claim
and attach APIs. A result belongs to `<outputRoot>/<taskId>/<epoch>-<token>/`.
Completion rehashes its exact canonical result, inputs and owned artifacts.
Reviewers must have a different registered host/thread identity from the author;
recorded host identities still do not authenticate subjective observation.
Changed assignments may name a pinned `parentPlan` and exact
`priorAuthorTaskId`: a provenanced generation increment uses the existing
`repairCycle` counter, while unchanged author assignments retain their identities.

After current project/prebuild admission, a `--section-plan` preview export
creates registered early-review tasks. Each requires actual moving-preview and
listening observations plus the six section assessments. An exact resume may
advance to final sections only after those reviews pass. Completed logical groups
then expose encoded-review tasks as their windows finish, without waiting for
the other groups. Tasks can also be materialized explicitly:

```sh
./sniper python3 scripts/producer/native_long_sections.py reviews \
  --attempt /absolute/registered-attempt --stage encoded
```

Once all sections and registered encoded reviews pass, use
`--resume-from /absolute/section-attempt --review-only` with a fresh output path.
This continuation retains the original allocation and cannot render a missing
picture section. Exact resumes retain validated original review manifests and
task identities; copying a file does not require another review of identical
evidence. A changed plan or actual media breaks that compatibility. Final
publication holds the batch authority before export history, rechecks task/media
currentness and the original clock, and settles the continuation under that same
lock. A checked original attempt cannot produce duplicate free final deliveries.

Scoped immutable section admission now permits a completed assignment to render
while another creative author remains unfinished. The assignment's own authored
files and early review must already be frozen and admitted. This does not permit
rendering an unfinished private author directory or invent another per-chunk
author allowance. Synthetic three-section repair tests preserve A/C and renew B
through final assembly at the existing eight-review limit. These tests establish
authority and dependency behavior, not real editorial or media qualification.

### Long-only natural chunks and incremental review

The new opt-in `--chunks --section-plan /absolute/assignments.json` route requires
an authored `LONG-CHUNKS.json` in the project. It is under engineering
qualification. Standalone Shorts and Shorts derived from a Long keep their
existing behavior. A creative assignment can contain several review chunks;
the default target is approximately 60 seconds with a 45–90 second preference.
Natural scene boundaries and complete transition/action spans take precedence.
An inseparable longer span or short tail needs an explicit recorded reason.

The closed authored contract in `studio/native_long_chunks.py` binds the frozen
creative section plan, exact chunk/window map, chunk purposes and one versioned
transition decision per neighboring boundary. Each transition has one owner,
both affected neighbors, an absolute frame span, source/state evidence and an
absolute-clock/no-restart policy. Do not create a new intro, outro, fade or motion
restart merely because a chunk ends. The existing independent prebuild review
must explicitly include the current contract bytes; authored assessments alone
do not prove that the encoded handoff is smooth.

The same `native_long_sections.py reviews --stage encoded` command returns
`readyChunks` after the scope's sealed windows have a verified continuous review
clip. The render supervisor packages ready scopes under the original counted
family while other render workers continue. Each scope identifies its existing
assigned review task, exact frames and current media manifest. Sealed scopes
without an owned clip appear in `pendingPresentation`; a cold review command
does not start an unowned encoder.
Later chunks and internal joins use that same task. They do not receive fresh
review counters, deadlines or author assignments. The reviewer remains attached
and holds its existing AI slot while waiting; claim admission preserves capacity
for unfinished current authors and early reviewers.

The supervising host writes canonical scope judgments under the current claim's
`chunks/<scopeId>.json` and records them through
`studio.production.api.record_section_review_progress(root, batch_id, claim, pin)`.
This is a nonterminal callback: the task stays running. Final `result.json`
references every required progress pin in frozen order and any assigned explicit
`global-joins.json`. Final assembly requires every current assignment, chunk,
internal join and neighboring creative-section join. It compares reviewed
picture and PCM against the actual current assembly inputs.

For a changed-author repair, `readyChunks` can instead identify an unchanged scope
as `status: "retained-judgment"`. It includes the original reviewer task, claim and
receipt, its original continuous observations, a current raw-media manifest and
the pinned `retainedJudgment` proof. These remain original observations; do not
rewrite them as playback performed by the new reviewer. The existing task stores
bounded immutable references in `sectionCarry`, separate from `sectionProgress`.
Compatible carried clips are not regenerated merely to change their author label.

The final review object explicitly lists `retained` pins for required scopes that
have no new current progress, in frozen scope order. Its `progress` list contains
only current claim receipts, also in scope order. Every scope must be covered;
new current progress overrides retained evidence. Changed interiors and seams
still require fresh independent review, and assigned global joins remain current.
Both completion and later assembly/reuse readers revalidate selected carry against
the actual task graph and current picture/PCM/dependency evidence.

An explicit `supersede_task` on the original chunk reviewer withdraws its retained
judgments even if an author replacement already revoked that task's callbacks.
The bounded withdrawal marker does not reset counters or release unresolved work.
Subsequent dispatch offers those scopes for fresh review; a later callback or
assembly cannot use their withdrawn carry. Missing later windows remain pending;
present corrupt proofs refuse rather than being treated as missing media.

Exact recovery must preserve the same original chunk inventory, counted task
and claim, including when only part of the review is complete. Changed-generation
repair retains only compatible media and independently revalidated local
interiors. A B2 defect rerenders affected encoder windows and actual dependencies;
it does not discard compatible B1/B3, A/C or still-current compatible windows
inside B2.
Shared transition changes invalidate both sides. Continue to use the existing
registered repair and resume routes, never copy an old approval onto changed
bytes or omit required joins to fit a limit.

Each derived review clip stream-copies the sealed picture, uses an exact excerpt
of the whole-program audio master, and applies the final route's native sRGB
metadata correction. Packet, sample-clock and complete-decode checks precede
publication. Its review-only AAC is separate from final delivery, and an exact
completed package is reused rather than encoded again. Internal and global join
clips include the entire authored transition and bounded surrounding context;
the matching continuous early-preview inventory is frozen before family admission.

Focused authority/recovery tests and generated-media codec checks pass. These
fixtures do not establish editorial continuity: the encoded entrance, complete
handoff and settled continuation still require playback/listening against the
approved continuous reference. Complete joined-video QC remains mandatory.
Short isolation tests keep native-short routing and real accounting, but stub
Short preflight/media boundaries; they do not qualify actual Short preflight or
the end-to-end Short workflow.
Package forecasting currently uses the existing conservative final-processing
rate for each scope. This may refuse a job that faster measured remuxing could
fit; qualification must establish any more specific rate without enlarging the
original grant or transferring a tiny fixture's timing to a real Long.
Representative C0679 ingestion is deferred until the engineering paths and
independent checks are ready. Matched clean/repair/restart timings, one/two/three
worker capacity, defect detection, storage, coordination overhead, installation
rebuild and final MP4/live Studio qualification remain pending. No speed or
quality improvement follows merely from smaller chunks or passing fixture tests.

See [the implementation evidence](NATIVE_LONG_RELIABILITY_2026-09-16.md) for actual
runs and remaining limits, and the [enforcement audit](WORKFLOW_ENFORCEMENT_AUDIT_2026-09-16.md)
for the later mandatory wiring and recovery checks. The 15-minute stress fixture deliberately uses simple
picture and deterministic broadband test audio. It can qualify clock, stage, deadline, cache
and cleanup behavior; it cannot establish throughput for an arbitrary 15-minute
4K-source edit, editorial turnaround or the 120-minute full-edit target.
