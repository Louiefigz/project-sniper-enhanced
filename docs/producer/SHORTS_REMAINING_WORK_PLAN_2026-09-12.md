# Native Shorts — remaining implementation and acceptance plan

September 12, 2026. Authorized: plan the remaining work and begin implementation,
using subagents. Preserve the three review exports. Existing permission for local
work and public source research/capture remains; do not send private footage,
transcripts or editing context to a remote Director/model or add generated media.

## Outcome

A conversational request can name a style or leave selection to the editor,
supply B-roll, restrict sources, and request real product/person evidence. The
editor chooses an insert only when it helps the spoken point. Script delivery,
reference mechanics and readable development govern timing across every lane.
Acquisition success must not masquerade as identity, editorial or publication
approval. Every claim of readiness names the cases actually exercised.

## First implementation batch and ownership

1. **Shared asset-use contract — contract worker, root integration.** Extend the
   existing strategy and AssetRecordV1 provenance with one speech-bound decision
   for images, logos, web footage and creator excerpts. Include justified no-insert
   decisions, entity role, purpose, exact target/window, essential visible region,
   claim limit and audio policy. Pin origin/source receipts so deleting web-specific
   metadata cannot downgrade a capture into unverified local footage. New strategy
   v3 requires the contract; existing v1/v2 projects remain readable.
2. **Request and source restrictions — root.** Preserve requested style and auto
   selection. Carry provided-only/local-only/public-web and insert-off policy
   through UI, intent, prepared brief, writer and cold reader. Freeze supplied
   B-roll alongside primary sources. Use the same policy for stills and video;
   a local cached download does not become operator-supplied footage.
3. **Acquisition and visual decisions — root after contract.** Adapt existing
   local inventory and public capture receipts. Keep real brand colors/aspect
   ratio and attributable identity; do not promote a generic icon or recolored
   legacy cache into an official product asset. Resolve ambiguity before selecting
   the source. Missing demonstrations, blocked sources and unsupported audible
   quotations produce explicit gaps rather than a misleading substitute.
4. **Cold-start reliability — reliability worker.** Diagnose saved failures,
   retain rejected measurements, and add only bounded recovery consistent with
   existing resource limits and deadlines. Treat shared source-frame cache reuse
   as a separate investigation. Verify behavior with focused failure tests and
   one coordinated supervised real run; do not run competing media jobs.
5. **Qualification — audit worker maps evidence, root executes.** Reuse actual
   admitted footage, transcripts and captures when suitable. Each case begins
   with its decision and expected failure, then exercises build, cold read,
   native/encoded review and documented source limitations. Unit fixtures and
   acquisition-only recordings are separate from finished-Short qualification.
6. **Handoff — root.** Update the workflow, optimization map, findings and a
   reproducible review index. Record successful and failed stage times, observed
   memory, cache/audio reuse, source scope and remaining listening/editorial review.

## Remaining implementation sequence

This batch's two real exports and current audio/native/encoded QC are complete.
Retain picture-only completion, failed attempts and human listening as separate
states. Continue through these independently reviewable slices:

1. **Guided app preparation — implemented and reviewed.** Connect the app endpoint to the existing
   `prepare-guided` authority checks under the controller's exact checkpoint
   and mutation lease. Test default and nondefault bootstrap manifests, stale
   checkpoints, concurrent mutations, changed inventory and attempted source-policy
   widening. Return the actual prepared brief; submitted packets are not authority.
2. **Guided external assets — V10 bridge implemented and structurally reviewed.** Keep V9's presenter/message semantics
   and its blocked external IDs intact. Add an explicit supporting-asset view
   with frozen supplied inventory and effective source policy. Bind each required
   scene/asset pair to one existing v3 asset-use decision, including speech,
   purpose, display window, essential region and audio. Persist the proposal,
   evidence and candidate hashes plus the resolution in the native project;
   replay this binding on cold read. Preserve unresolved requirements as typed
   blockers. Start with supplied raster images, then qualify video and official
   identities through finished encoded review. See the concrete slice below.
3. **Supporting-media intake — implemented; real admission/rescan checks passed.** The supporting-image/video picker uses existing
   admission and immutable snapshots, then rescans into the inventory without ASR.
   Explicitly admit or reject formats rather than silently omit them; conversion
   remains a separate, independently admitted derivative.
   Keep long-form format support intact. Test a transparent logo, supported video,
   changed files and restricted sources through actual picker/folder-to-request paths.
4. **Creator decisions.** Qualify identity, style-only reference, illustrative
   excerpt and audible quotation separately. Use attributable inspected sources;
   a creator's style alone does not justify depicting them. Audible quotation
   stays blocked until its source transcript, narrator handoff, mix and caption
   ownership work. Include ambiguity, repost and misleading-proof negatives.
5. **Website/repository demonstrations.** Record the relevant operation, code or
   result, preserving URL/time/origin and a readable region in the portrait frame.
   Plan movement and holds against speech. Test a real product operation and repo
   example, loading/consent/error states, occlusion and an appropriate no-insert
   case. A moving homepage does not establish an operation demonstration.
6. **Whole-Short pacing.** Watch and listen to complete fast, measured and
   changing-delivery cases at phone size. Coordinate title, captions, supporting
   visuals and motion using speech-bound beats. Include a readable formula/UI
   result, intentional hold and a speech revision that invalidates the old plan.
   Word rate or fixed one-second cuts alone cannot establish comprehension.
7. **Handoff.** Preserve the original three review exports and add new qualified
   cases with receipts, stage/end-to-end times and remaining review. Distinguish
   conversational editing, folder ingestion, guided preparation and full app
   execution when describing what is ready.

## Shared implementation to reuse

- Source/cut/transcript authority: guided proposal input/speech/frame-range
  modules, `guided-native-authority.ts`, immutable records and checkpoint leases.
- Exact timing and caption grouping: `edit/exact_timing.py`, existing Whisper
  caption grouping and `studio/native_caption_groups.py`; portrait placement
  stays an adapter, with no second ASR or grouping implementation.
- Work ownership and timing: generation deadlines, `stage_timing.py`,
  `native_work_lease.py`, native resource measurement and bounded recovery.
- Audio: `audio/float_master.py`, shared delivery-signal checks and
  `audio/native_dialogue_delivery.py`. Explicit native delivery profiles reuse
  the algorithm without silently changing long-form defaults.
- Picture: pinned source extraction/cache, file-backed transport, shared native
  capture context, frame inventories and one selected-frame decode. Completed
  picture/audio reuse still runs current final QC.
- Invalidation: existing fingerprints and render-graph dependencies. General
  incremental app export remains separate from the qualified stage-reuse case.

Shorts retain their own inspected references, portrait composition and
script-led pacing while sharing processing and authority mechanisms.

## Acceptance matrix

| Case | Required behavior | Negative or revision check |
| --- | --- | --- |
| Incidental/repeated brand mention | Verified identity insert or an explained presenter hold | Repeated noun does not force another logo flash |
| Real product or repository page | Relevant section readable at the spoken cue; original appearance retained | Homepage cannot be counted as showing an operation/result |
| Creator identity | Attributable original profile/image, correct person and useful crop | Display-name match or repost is insufficient source evidence |
| Style-only creator request | Uses inspected editing mechanics | Cannot depict the creator solely because their style was requested |
| Existing source B-roll | Uses the supplied range with an explicit illustrative/evidentiary job | Illustration cannot become proof of a result or transformation |
| Restricted sources | Same policy across photos, logos and videos, including cached assets | Removing provenance or changing speech makes the previous decision invalid |
| Fast/measured/varied delivery | Caption phrasing, visual development and holds follow the retained script | A fast numerical rate alone cannot establish pacing quality |
| Audible quotation | Explicit supported audio/transcript/caption handoff, or a truthful unsupported gap | Never silently mute an intended audible quotation |
| Runtime cold start | Bounded attempts require a real fresh measurement before continuing | Missing measurement, deadline exhaustion or unsafe pressure still stops |

## Completion evidence

Contract acceptance requires meaningful positive/negative tests plus the actual
writer/reader path. A finished-case pass additionally needs source evidence,
local export receipts, relevant forward/reverse checkpoints and encoded-frame
inspection. Full listening and phone-size editorial review retain their own
status. Preserve approved visual choices unless a tested defect requires revision.

The first implementation batch covers the shared contract, request integration,
local/public origin adapters and bounded runtime recovery. The cohort expands
only when its required source and audio path exist. The broader eight-case audit
is tracked in `ORGANIC_BROLL_EDGE_CASES_2026-09-12.md`; do not mark unsupported
creator/audio sourcing ready because a structural test passes.

## Implementation progress

- Shared contract and request/source restrictions are implemented. New v3
  writer/cold-reader and guided-authority tests pass. Structural coverage includes
  supplied-image restrictions, source origin stripping, changed speech, CSS
  resource escapes, source timing aliases, forged reports and changed export pins.
- Local/public origin adapters are connected, including exact public web capture
  binding and refusal to publish incomplete adapter output. Existing actual Claude
  and GitHub recordings passed the adapter; a fresh automatic capture-to-origin
  acquisition run remains separate qualification.
- The shared live/prelaunch measurement retry is implemented. The empty-cache
  offer export passed in 86.880 owner seconds. Repeated whole-host telemetry
  failures remain retained. A direct public-API sampler now passes the actual
  eight-codec workload and a native browser export, including observed turnover
  recovery under the existing limits. The final sampler suite passes 107 tests,
  with 16 additional owner-baseline tests. This qualifies the exercised workloads.
  Browser rotation completed both 4K pictures; strict picture-stage reuse let
  both cases complete current final QC without another picture encode. This is
  specific qualified reuse, not a universal cold-start reliability claim.
- Two real v3 plans are built and cold-readable: official Claude/Gemini identity
  inserts with a documented ChatGPT acquisition gap, and the same speech with
  provided-only/placement-off restrictions. Both finished exports and encoded
  sample review now pass. Final CLI attempts took 63.72 and 60.95 seconds, excluding
  planning/acquisition and the retained earlier failures. The final sampler
  acceptance reused both stages, passed in 52.56 CLI seconds and produced the
  exact reviewed official MP4 bytes. Human playback/listening
  remains separate. See the implementation receipt and local review page on port 3996.
- Creator identity/opening/audible-quote cases, changing-delivery pacing and
  comprehensive acquisition selection remain on the acceptance matrix. Source
  contracts and fields alone cannot qualify those editorial behaviors.
- App ingest now has a separate supporting-media picker for PNG/JPEG/WebP and
  MP4/MOV (up to 1 GiB). It stages a stable, hashed local copy, then uses the
  existing sandbox admission through an explicit transcript-preserving rescan.
  The rescan retains unchanged original recordings, including external referenced
  recordings, source-bound transcript bytes and the complete previous admitted
  B-roll/music inventory. Changed or missing originals fail without publishing
  a new manifest. The control is unavailable after guided cut acceptance.
  Intake/stream/request checks, 31 Python regressions and three real Docker
  admission/rescan cases pass. The media suite took 11.137s, with the complete
  owner and exact container cleanup finishing in 58.967s. Two additional real
  `ingest.main` publication tests passed in 5.608s (24.908s full owner).
  A subsequent actual Next HTTP/SSE run passed four tests, including seven
  separately spawned CLI processes and verified cleanup of ten containers.
  Full owner time was 49.854s. Coverage and its remaining limits are in the
  [integration receipt](SUPPORTING_MEDIA_AND_GUIDED_BUILD_2026-09-13.md). SVG/SVGZ still
  require a supported local derivative. Folder ingestion retains long-form formats.
- Guided app preparation now uses the actual saved manifest and intent under
  the checkpoint mutation lease. POST accepts only the project directory;
  stale or malformed journals, concurrent writers, changed inventory and
  submitted policy overrides fail explicitly. The ordinary default-manifest
  path remains supported. The route/service slice passed 58 focused tests
  (nine new), full TypeScript and lint checks, and independent review. These
  use real request/lease/file paths with proposal reconstruction stubbed;
  they are not finished guided media-export qualification.
- The V10 compiler now freezes supplied supporting inventory and source policy,
  produces typed pending requirements, and supports explicit supplied-raster
  resolution. V9 keeps its previous external-asset blocker. Shared v3 validation
  checks each scene/asset/decision binding. The guided proposal binding is saved
  with hashed project inputs and reconstructed on cold read; stripping metadata
  or using a symlink alias cannot bypass the reserved guided project path.
  This is contract and writer/reader coverage, not finished guided-media acceptance.
- The `build-guided` CLI/service connection is implemented under the real
  checkpoint mutation lease and original generation clock. Its 120-second local
  assembly attempt retains start/result evidence and returns a native QC candidate.
  Combined structural/entry checks pass 64 tests. A production guided
  acceptance case requires actual accepted cut/admission lineage; synthetic test
  journals and manual fixtures cannot supply that authority. Existing private
  material remains local, so no service-backed Director/critic run has occurred.

## V10 compiler slice: implemented contract and remaining acceptance

The September 13 read-only mapping found and this slice addressed two gaps. V9's `requiredAssetIds` lack
the supporting inventory and decision mapping needed to execute them. Its two
mechanisms describe a presenter hold or an original message illustration, so
silently treating an arbitrary photograph as either would change the contract.
Previously, `buildNativeShortProjectFiles` returned `GUIDED-PROPOSAL.json`, but the
guided writer discarded that return while saving `visual.project` through the
shared writer. The new persistent binding now survives publication and is checked
again on cold read.

The following narrow V10 contract is implemented and reviewed:

1. Add the V10 contract/schema and supporting-asset view. Extend evidence with
   exact admitted supporting inventory and the stored effective media policy.
   Required IDs must be unique and resolve to that inventory; style references
   remain separate. Initially admit only the supplied-raster execution case.
2. Represent pending asset requirements explicitly in compilation. Local brief
   preparation can accept that specific planning state, while publication still
   requires every insertion to resolve. Unsupported clauses, unknown IDs and
   unrelated blockers stay blocked; never match eligibility by error text.
3. Add a focused `guided-native-assets.ts` resolution validator. Each
   `(sceneId, requiredAssetId)` maps to exactly one existing asset-use decision.
   Verify source path/hash, origin, retained occurrences, scene bounds, target,
   essential region, claim limits and audio through the existing v3 checks.
   A no-insert decision cannot fulfill a required insertion.
4. Persist a versioned guided binding among the shared native project's hashed
   inputs and replay it on cold read. Retain proposal/evidence/candidate hashes
   and scene-to-decision mapping, along with the saved intent/inventory checks.
5. Register V10 in proposal dispatch, compiler history and schema/prompt loading.
   Keep old V9 reading and its unsupported-external-asset regression unchanged.

The first positive fixture is an admitted PNG under provided-only policy, with
an inspected illustrative purpose and exact scene/word/display binding, passing
the shared writer and cold reader. Negatives include duplicate/unknown IDs,
missing or wrong-scene decisions, no-insert substitution, changed or stripped
origin/evidence, public-source substitution, disabled/operator B-roll, depicting
a style-only reference, changed speech/crop/audio and a stripped guided binding.
Structural fixtures validate the contract and real shared writer/cold reader without
rendering or accepted production lineage; a finished guided Short is still required before declaring this execution route qualified.

Reuse strategy v3 and `NativeShortAssetUsePlan` v1. Do not create another source
policy, rights interpretation, caption engine, media executor or rendering path.

## September 13 continuation — actual app ingress

The completed local slice qualifies the supporting-media flow through actual HTTP
and a spawned Python CLI, using an isolated Next.js app/workspace/cache. Before
that run, the route now binds all destination forms to the actual managed
project's checkpoint and rejects ambiguous, nested or redirected destinations.
The held lease and ownership are rechecked after placement and before result
readback. Referenced directory input cannot write another managed project's
B-roll catalog under this project's lease. Seven new regression cases and 43
existing checks pass. Four actual app/media cases also pass in 11.120s, covering
copied/referenced input, invalid-image stream rejection and mutation/checkpoint
fences before child launch. All ten requested containers and the isolated server
were cleaned up; the owner finished in 49.854s with unchanged source/runtime
pins. The five previous media checks remain valid evidence for their scoped
helpers and main-entry publication. One additional four-format HTTP case now
passes for real H.264/AAC MP4/MOV and JPEG/WebP supporting media: 4.946s test
time, 28.404s complete owner, six exact containers cleaned up. Its failed first
attempt remains recorded. It exposed immediate telemetry retries exhausting
during child-process bursts; a bounded 0.1/0.2/0.4-second backoff in the shared
monitor retains the same sample count, clocks and caps. All 87 focused monitoring
tests pass, and the successful rerun exercised recovery after a measured wait.
No blanket codec, native picker, editorial or completed guided-export claim follows.

## September 13 visual review checkpoint

The existing 24.52-second `offer-story-07/review.mp4` and all eight final encoded
stills still match their recorded hashes. A manual still review reconfirmed
formula contrast, current/proposed label alignment, distinct outcome/time fields,
caption separation and the dog-to-still handoff. The existing follow-up and
member-math exports are unchanged. No encode or source acquisition was needed.

This is deliberately not normal-speed playback or listening qualification.
The three clips total 45.80 seconds and remain ready on the existing pacing
review page. Listen for whole-Short rhythm and the formula's reading hold;
perceived pacing cannot be certified from word timing or isolated frames.
The [scoped still-review receipt](../../artifacts/native-short-pacing-2026-09-12/visual-review-2026-09-13.json)
does not modify the projects' `timing-and-transcript-only` delivery review.
Creator quotations, an actually executed repo operation and legitimate V10
guided-export acceptance remain separate cases; existing unrelated footage
cannot supply that evidence.
