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

Stage local assets and the complete intended stereo, 48 kHz float WAV. Preserve
source dialogue, pauses and its exact sample clock. Diagnose hum on the source
and apply an appropriate shared audio treatment before this stage; a 53 Hz notch
from one recording is not a universal voice preset. Do not infer a new treatment
because picture rendering failed. The WAV is the premixed program authority;
HTML audio fades, gains, groups and multiple tracks are outside this adapter.

Add `LONG-PROJECT.json` beside `index.html`:

```json
{
  "schemaVersion": 1,
  "canvas": {"width": 1920, "height": 1080, "frameRate": "30/1", "totalFrames": 120},
  "audio": {"file": "assets/dialogue.wav"},
  "scenes": [
    {"startFrame": 0, "endFrame": 60, "mediaIds": ["presenter"]},
    {"startFrame": 60, "endFrame": 120, "mediaIds": ["supporting-footage"]}
  ]
}
```

Scenes are contiguous integer half-open frame ranges. `mediaIds` names the
root-timeline videos expected to be visible in that scene; use an empty list for
a graphics/still-only scene. Include boundaries when simultaneous media changes.
The HTML must have the matching explicit landscape canvas and duration, muted
normal-speed videos with stable IDs, and one complete-program WAV at time zero.
Current bounds are 1–60 fps, 15 minutes, up to 3840×2160 and 256 scenes/media.
Nested/dynamic media and intentional invisible-video intervals require explicit
adaptation; the scene check refuses mismatches rather than inventing intent.

Use [selected-source preparation](NATIVE_LONG_SELECTED_SOURCES.md) when an edit
uses small portions of long originals. Preparation preserves source provenance;
it does not replace source review. Ensure the output manifest describes the
prepared HTML's IDs and clocks.

```sh
.venv/bin/python scripts/producer/studio/native_export.py \
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
.venv/bin/python scripts/producer/studio/native_export.py review-input /absolute/project
```

This command returns a digest and complete file pins; it does not create a pass.
The review uses the existing native prebuild schema: `schemaVersion: 1`,
`scope: "native-long-full-project"`, the returned `planHash`, declared separate
reviewer/planner session IDs and `independent: true`, seven nonempty `coverage`
assessments (`briefAndRetainedMessage`, `assetsAndSourceEvidence`,
`cuesAndSceneCoverage`, `layoutCropAndText`, `motionAndTransitions`,
`pacingAndAudio`, `feasibility`), nonempty hash-bound `evidence` references,
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
5. Run the unchanged high-quality/CRF 15, one-worker SDK picture render. Source
   frames remain PNG. No resolution, frame rate or quality gate is lowered.
6. Seal the completed picture under its own verified owner. Then run shared AAC,
   mux, sRGB metadata/payload checks, encoded/native comparisons and full decode.

All expensive stages retain the shared heavy-work lease, current memory/disk
limits and verified descendant cleanup. Long owners can wait up to 600 seconds
for temporary contention/pressure, recording `waiting-for-capacity` with no
launched child. Missing telemetry and unverified cleanup still fail explicitly.
The owner records `running` only after the child exists.

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
The shared `native_review_bundle.py prepare` now accepts this exact long status,
including recovered exports, and prepares both an unchanged local MP4 and an
editable Studio fork with the final AAC copied without re-encoding. Open and
actually review both surfaces before making playback or handoff claims.

## Qualification and limits

See [the implementation evidence](NATIVE_LONG_RELIABILITY_2026-09-16.md) for actual
runs and remaining limits, and the [enforcement audit](WORKFLOW_ENFORCEMENT_AUDIT_2026-09-16.md)
for the later mandatory wiring and recovery checks. The 15-minute stress fixture deliberately uses simple
picture and deterministic broadband test audio. It can qualify clock, stage, deadline, cache
and cleanup behavior; it cannot establish throughput for an arbitrary 15-minute
4K-source edit, editorial turnaround or the 120-minute full-edit target.
