# Native Shorts production integration

The September 11 request authorizes finishing local integration, explicit or
automatic creative direction, supporting-footage discovery, and real workflow
testing. The earlier local-only restriction still applies to model/provider
calls. Existing three-case exports remain review evidence for their exact bytes.

## Work and acceptance checks

- [x] Persist a Short direction request independently of editing intensity. Allow
  automatic selection, a named reference, or a described treatment; preserve it
  through UI, stored intent, request construction and planning read paths.
- [x] Make the strategy packet source-first: viewing need, contrasted reference,
  benefit-based canonical title, inspected supporting assets, demonstrable
  before/action/result and explicit claim limits. Automatic choice belongs to the
  edit brain; a preset or keyword matcher must not impersonate that judgment.
- [x] Replace the obsolete native development writer with the shared native
  canvas and explicit inspected geometry. No contained landscape/caption panel
  fallback. Support project-owned native mechanisms with frozen dependencies.
- [x] Promote the qualified file-transport runtime and bounded local render/QC
  adapters into configurable production modules. Share ownership, source clock,
  caption grouping, audio finishing and caches with the existing route.
- [x] Provide a repeatable local entry point from request/strategy through
  editable project, rendered review and receipts, with no remote calls.
- [x] Exercise the actual entry point on the three contrasting Shorts, verify
  edited titles/captions, supporting video, timing, audio and source currentness;
  retain stage timings, failures and cache reuse. Test requested/automatic
  direction and missing/stale-input failures. Keep listening/editorial approval
  distinct from deterministic checks.

## Completed local verification

All three requests were frozen with the real admitted source and transcript
inventory, bound into the authored strategy, assembled with the production CLI,
and exported through the production supervisor. These tests reuse the earlier
selected cuts, transcripts and editorial strategies; they do not measure a fresh
raw-footage-to-finished creative edit or an autonomous provider session.

| Case | Duration | Export + checks | Encoded frames checked | Reverse frames | Peak measured owned memory |
| --- | ---: | ---: | ---: | ---: | ---: |
| Presenter follow-up, automatic treatment | 13.04 s | 67.840 s | 149 | 16 | 2.23 GiB |
| Nate offer story, requested treatment | 24.52 s | 85.673 s | 237 | 25 | 2.71 GiB |
| Developing math, automatic treatment | 8.24 s | 48.617 s | 64 | 8 | 2.12 GiB |

Total: 450 distinct encoded-frame comparisons and 49 reverse-frame comparisons.
All outputs are 1080×1920, 25 fps, decode completely and pass shared audio clock,
packet and signal checks. Integrated dialogue levels are −14.06, −14.05 and
−14.07 LUFS respectively. Each final attempt reused qualified audio with **zero
additional AAC encodes**. Owned-process cleanup and before/after input pins pass.

Evidence is under `artifacts/native-shorts-integration-2026-09-11/`:

- `request-workspace/*/producer/native-shorts/requests/`: real local request packets.
- `projects/*-requested/`: editable native projects and complete file manifests.
- `exports/*-final-01/`: final media, stage timings, resource samples, native frames,
  pixel metrics, audio receipts and supervisor results.
- `ui-smoke-03/`: actual React intent/launch components and production HTTP handler
  tested together in an isolated local harness; all three review videos advance
  and seek successfully. This is not a full Next navigation test. Earlier harness
  failures (working directory, serialized callback helper) are retained.
- `review.html`, `review-manifest.json`: the three actual final exports, served at
  `http://127.0.0.1:3994/` for the user's editorial/listening review.

Focused verification passes: 27 core native/Director/request tests, seven guided
native proposal tests with synthetic provider replies, four existing intent and
pipeline-resume suites, 69 Python intent/resource/ownership tests, and two new
runtime/picture regression tests. Type checking and targeted ESLint pass. The
new Python/TS logic modules meet the 300-line file and 50-line function bounds.
No remote model/provider or generated-media calls occurred.

## Reuse, corrections and boundaries

The same follow-up MP4 and all 149 picture metrics are exactly equal before and
after the raw-RGB QC optimization; picture/decode time fell from 62.099 to 5.989
seconds. Excluding generated caches from code snapshots restored a failing
98.110-second history test to a passing 10.704 seconds. Details, retained failures
and reverse-seek tolerances are in
[the finding](../findings/NATIVE_SHORT_QC_CAN_BE_FAST_WITHOUT_CHANGING_PIXELS.md).

The new request field is independent of editing intensity. Choosing a saved
creator style updates the request; a subsequent custom/automatic choice clears
conflicting legacy style/pace values. The app prepares a brief for the editing
agent; it does not claim one-click autonomous production. The production writer
requires inspected geometry and rejects the obsolete contained-landscape fallback.
Source-first scouting and show-the-change planning are obligations recorded by
the agent; a list of available assets is not proof of visual inspection.

This qualifies the shared local route on these three treatments. It does not
qualify every library style, new media inputs, automated external acquisition,
general scene-level incremental encoding or fresh remote Director/critic execution.
Native dialogue delivery rejects requested music/optional enhancement it cannot
perform, and preserves disabled/operator lane ownership. Human editorial and
listening approval remain open. See [how to request the next Short](NATIVE_SHORTS_WORKFLOW.md).
