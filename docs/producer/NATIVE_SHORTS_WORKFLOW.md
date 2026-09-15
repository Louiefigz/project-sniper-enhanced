# Requesting and producing native Shorts

Ask the editing agent in normal language. Supply footage or an existing project
and the outcome you want the viewer to understand. Either name a reference or
let the agent choose after inspecting the message, footage and reference library.

- “Make a Nate Herk-style Short from this recording. Show one offer improving
  step by step. Find useful supporting shots in my footage.”
- “Choose the best Short treatment from this recording automatically. Find a
  standalone lesson and show the example wherever possible.”
- “Make this presenter-led, with a close portrait crop, a benefit-focused title
  above, and centered high-contrast karaoke captions.”
- “Show the formula developing, then hold the completed result long enough to
  read it. Use the presenter when the explanation needs their gesture.”
- “When I mention a product, find its real website and scroll to the relevant
  feature. For a GitHub repository, show the actual README example.”

For real site/repository inserts, follow [the web B-roll workflow](WEB_BROLL_WORKFLOW.md).
The agent chooses the source and section; the shared recorder freezes verified
local footage for the same native supporting-video path.

The [organic B-roll edge-case audit](ORGANIC_BROLL_EDGE_CASES_2026-09-12.md)
separates current checks from the remaining brand/creator sourcing work and
defines the proposed finished-Short acceptance cases.

These are creative requests, separate from editing intensity. A named creator
does not select a fixed whole-video layout. Automatic selection is an editorial
decision made by the agent; there is no keyword-to-template substitute for it.

The optional app offers **What kind of Short? → Choose for me / I have a style
in mind**, a free-text request and suggestions. Supporting visuals have one source choice:
only supplied files, supplied files plus the existing local library, or those
sources plus public websites. Turning supporting visuals off also disables photo
and logo cutaways. Source choice survives switching between automatic and named
styles. Older requests keep their stored identity and default to local sources. **Prepare Short brief** freezes
the stored request and source inventory locally. Copy the resulting brief into
the editing task. This button prepares the handoff; it does not independently
run a model, produce a finished Short or approve the result.

To supply B-roll through the app, use **Add supporting image or video** before
accepting the guided cut. Choose a PNG/JPEG/WebP image or an MP4/MOV clip, up to
1 GiB. The control copies and checks the file while preserving the current
transcript, then tells you to prepare a new Short brief. Wait for **Supporting
media prepared** before using it in the brief. If media admission fails, the app
keeps the staged file and explains the incomplete state; the prior manifest and
verified transcript remain authoritative. The agent still inspects relevance,
speech, framing and any claims before choosing to display the asset. See
[tested formats and limits](SUPPLIED_MEDIA_FORMATS_2026-09-13.md).

## Before assembly

First establish whether the user wants an excerpt, cleanup/segmentation, or a
standalone story assembled from the recording. Follow the
[edit-scope guidance](SHORTS_JOURNEY_SELECTION_PLAYBOOK.md#establish-the-edit-the-user-wants)
and ask once if the request and saved brief leave this unclear. The story
assembly guidance below applies to standalone Shorts; a requested podcast
section keeps its agreed boundaries and order, with cleanup only as requested.
Good hooks must match the retained material in either case. Visual intensity
does not establish permission to restructure the speech. Use the execution
route that supports the requested edit; this guidance adds no runtime modes
and does not bypass native admission or Director contracts.

For a conversation or journey recording, first apply the
[journey selection and assembly playbook](SHORTS_JOURNEY_SELECTION_PLAYBOOK.md).
Its source-wide paper edit can connect distant passages into one story. Lessons,
realizations, decisions, progress and current experiments with a reason can all
supply a payoff; a completed business result is not required. Select visuals
for important explanatory moments, including a temporary presenter/board split
when simultaneous viewing helps. This is editorial guidance, not a new automatic
ranking feature or a claim that export checks assess narrative quality.

1. Read the actual transcript and inspect source footage and individual library
   frames. Select a self-contained message with a supported payoff. For a Nate
   treatment, inspect setup, development and payoff plus a contrasting example.
   Establish the whole-Short rhythm from the retained script and actual delivery
   before assigning shot lengths; follow the pacing step below.
2. Record the requested or chosen treatment and why it fits. Explain the rejected
   alternative. Choose each scene's framing from its viewing need; justify both
   panes when simultaneous viewing helps. Preserve useful expression and gestures.
3. Use the Script Director's canonical hook catalog through
   `native-director-library.ts` and `fillLocalHookTemplate`. Select the formula
   before filling it. Compare supported fills for a reason to watch: the benefit
   or question that matters to the viewer. Template validity alone does not make
   a strong hook. Put the backed title above, separate from the speech lane;
   verify contrast, lifetime and phone-size fit against the selected reference.
4. Choose each beat's teaching purpose and visual representation before sourcing:
   conceptual metaphor/diagram, real procedure, evidence, or presenter performance.
   Follow the visual-storytelling step below. A familiar cartoon object can make
   a high-level relationship clearer than technical text or a website screen.
5. Scout the entire available source, including outside the dialogue cut, then
   the project's local media pool. Record candidate ranges, what is visible,
   selection/rejection and claim limits. A dog shot can illustrate the offer; it
   cannot establish a health transformation. External searches or generation
   depend on the user's current authorization. A missing asset must be reported.
6. Plan an actual before state, visible action and readable result when the
   lesson benefits from demonstration. Supporting footage should explain or
   substantiate that development. Preserve a presenter hold when that is enough.
7. Write the strategy and exact source/word/frame bindings before HTML. Inspect
   the intended crop, title and caption positions. Review the plan under current
   permissions, recording whether this was local editorial review or a separate
   critic run. A local-only request does not authorize a remote Director/critic.

Treat the review deliverable as one complete source-supported answer: viewer
question → development → payoff, using the same identifiable example. Component,
logo, capture, codec and export tests establish their recorded technical scope
only. Before calling the example finished, review the complete encoded Short
with sound and check that its title promise is answered, the example develops
coherently, and identity/page-context inserts are not presented as demonstrated
operations or achieved results. Record missing listening, playback or source
evidence as unfinished review.

### Visual storytelling: choose how concrete each beat should be

Aaron's direction: a physical/cartoon key can explain an API key in a high-level
overview. A tutorial can show the actual credentials field. Select the visual
from the teaching moment, audience and complete spoken point. This decision
belongs between understanding the script and choosing assets or captures; it
can change within a Short as an overview becomes a practical demonstration.

| Teaching purpose | Candidate representation | Example |
|---|---|---|
| Explain a concept | Familiar physical object, cartoon metaphor or simple diagram | A key unlocks access to the service as the speaker explains API access |
| Teach a procedure | Relevant real interface and visible action | Find the credentials field and enter a masked/example key; retain the actual recorded result when claiming success |
| Support a factual claim | Appropriate observed evidence | Show a source-supported error or successful response, with its actual context |
| Continue the explanation | Presenter or small supporting cue | A passing API-key mention may not need a separate scene |

The cartoon key is one possible analogy, not a rule triggered by the words
“API key.” Explain the relationship through an action the viewer recognizes.
Keep the same key/service identifiable while developing the idea, and explicitly
connect that key to the real field if the next beat becomes a tutorial. Budget
time to recognize the object, understand its action and read the result using
the existing speech-bound pacing record. Select reference mechanics that fit
the chosen representation and the user's requested style.

Record this decision in the existing strategy fields:

- `scenes[].viewingNeed`: teaching purpose and why this representation helps.
- `scenes[].paneJobs`: chosen representation, object-to-concept mapping and its
  limits. A key can explain access without proving security or real authentication.
- `before` / `action` / `result`: how the same object develops the spoken idea.
- `visibleIds`, `story.beats[].visualJobs` and pacing holds: bind the actual
  graphic/media, its purpose and sufficient time to understand it.

A locally authored metaphor/diagram uses the existing `explanatory-comparison`
story job in a `diagram`, `comparison` or `demonstration` scene. That job already
accepts authored graphics; its name does not require a two-column comparison.
Use `assetDecisionId: null` for a locally authored graphic with no acquired media.
An acquired illustration instead retains its real asset/origin decision and
illustrative purpose. A metaphor cannot fulfill a `real-artifact` or
`real-operation` obligation. It does not authorize generation, external calls
or disabled visual lanes.

At editorial review, check that the metaphor clarifies the relationship, keeps
continuity and introduces no false inference. Structural checks establish target
and timing bindings, not whether the metaphor is understandable or appropriate.
The shared `shortDirectionInstructions` supplies this planning step to saved
request packets, local briefs, the Director/critic and Short authoring prompts.
New request packets name `choose-visual-representation` before scene assembly
and supporting-shot scouting. Existing frozen requests and exports stay intact.

### Script and delivery set the rhythm

Aaron's September 12 direction: pace the whole Short coherently. A faster script
and delivery need quicker visual development, caption phrasing and motion;
a calmer performance needs more sustained, restrained treatment. The reference
informs the visual mechanics, adapted to that performance. Do not choose B-roll
durations independently or reduce this decision to words per minute.

After selecting the retained passage, read it in full, listen to the source and
inspect word timing, phrase lengths, pauses, emphasis, idea density and the
setup-to-payoff arc. In the existing strategy rationale, record overall rhythm,
speech-bound local changes and purposeful pauses. For each scene, connect that
rhythm to its spoken cue, attention target, entrance/action/result, readable hold
and exit. A cut, an internal reveal and a camera move are different ways to
develop a beat; every word does not require another cut.

Coordinate the enabled cuts, captions, title, supporting shots and motion.
Caption word highlights follow actual speech; phrase grouping follows meaning
and readability. Respect disabled/operator-owned lanes. Music/SFX follow this
rhythm only when requested and supported; this step does not authorize adding
audio or accelerating dialogue. If the point does not fit a fast visual beat,
crop, simplify or split the information first, then plan a deliberate longer
beat when necessary. Revisit dependent timing after any retained-speech change.

The earlier one-to-five-second examples are candidate shot lengths, not defaults
independent of the script. Capture length is source inventory, not screen time.
Review the entire encoded Short with sound at normal speed for coherent rhythm,
local handoffs and readable payoffs. Still frames alone cannot establish pacing.
The shared brief and strategy version 3 carry this planning obligation. The
local measurement command derives phrase windows, speech coverage, gaps and
rates from the retained-word clock. New builds require an overall rhythm,
complete speech-bound beats, lane decisions and explicit viewing budgets. The
writer and cold reader check these against the exact clock and timed visuals.
Semantic pace, adequacy of the editor's budgets and custom animation visibility
still require playback review. Numerical checks do not qualify comprehension.

### Author the pacing record

Once the native canvas and intended visuals are specified, run:

```sh
node --import tsx scripts/producer/native-short.ts measure /absolute/plan.json
```

This runs locally without ASR, a provider call or rendering. It returns timing
observations, `timingHash`, `visualHash` and executable visual windows. It does
not label delivery energy from words per minute or silently choose shot lengths.
Use the observations to revise the planned visuals before final assembly.

Set `strategy.schemaVersion` to **3** and author `strategy.pacing` using the
`NativeShortPacing` type in `src/lib/server/native-short-pacing.ts`:

- Bind the measured `timingHash` and `visualHash` after editorial planning.
- Explain `overallRhythm`, its rationale and decisions for cuts, captions,
  title, supporting visuals, motion and audio. These notes do not enable lanes.
- Record `deliveryReview` truthfully as `source-listening` or
  `timing-and-transcript-only`; observations do not count as listening.
- Partition every output frame into `beats`. Each beat cites exactly the kept
  occurrences overlapping its window, its local rhythm, attention target and
  reason for continuing or changing pace. Silent-only beats need a pause decision.
- Add `holds` for the title, each authored text cue and every timed custom
  insert. Name the target, actual readable window, `minimumFrames` and reason.
  Choose the required budget from the visual's job; do not copy whatever time
  happens to be available. Known native entrances must finish before the hold.
  Custom GSAP/CSS may hide a timed target internally; inspect its actual state.

All frame windows are integer, start-inclusive/end-exclusive. A hold may cross
editorial beats when the same information remains useful and visible. Source
cuts, transcript words, caption groups, visual scenes or asset revisions stale
the pacing record. Reassess the dependent decisions rather than merely updating
hashes. Existing version 1 and 2 projects can still be opened and checked; new direct
and guided native builds require version 3 with pacing and asset-use decisions. Legacy status is reported explicitly.

The writer freezes `PACING-REPORT.json` alongside the project. The cold reader
recomputes it, so changing and rehashing reported measurements does not pass.
The supervised exporter pins this report with the rest of the project. Read
the [implementation and real-source cases](SHORTS_PACING_IMPLEMENTATION_2026-09-12.md)
for measured coverage and outstanding review.

When moving a reveal, carry its labels and supporting cues with the actual
payload. Add native `expectations` immediately before/after the state handoff.
For example, CURRENT WORDING must not become PROPOSED WORDING while the old
offer still occupies the reading area. A longer viewing budget alone cannot
detect this semantic state mismatch.

For custom supporting video, make its containing element the sole owner of
timed visibility masks. Keep those masks off the `<video>` itself: the exact-frame
renderer displays a sibling image and can copy the video's previous mask before
the current seek finishes. Duplicating the mask on both elements can therefore
break reverse entry. Assert the container's state and inspect actual pixels on
both sides of entry and exit, in forward and reverse order, including a
transition within a capture batch. An original media element's expected style
does not establish its displayed replacement's visibility.

### Bind the authored story to executable visuals

For an explicitly authored integrated example, add the optional `strategy.story`
record using `NativeShortStory` in `src/lib/server/native-short-story.ts`. It
connects the whole-story planning above to the existing scene, pacing and
asset-use contracts. It does not select a story or replace editorial review.

Author `viewerQuestion`, the exact selected `strategy.payoff`, and a stable
`continuity: {id, subject}` identifying the same subject or developing example.
Then author `beats` in the exact order of the existing `strategy.pacing.beats`.
Every pacing beat needs one story row with its zero-based `pacingBeatIndex`,
containing `sceneIndex`, `phase`, matching `continuityId` and `visualJobs`.
The phases move from `setup` through optional `development` to `payoff`; setup
and payoff are required. Several beats may share a scene. These are references
to retained speech and the existing frame clock, not another set of word timings.

Each visual job records `kind`, `targetId`, `assetDecisionId` and `holdIndex`:

| Job kind | Required executable binding |
| --- | --- |
| `presenter-performance` | An actual primary source view covering the beat. Its decision is an existing `no-insert` decision or `null`; `holdIndex: null` is allowed because performance does not need an artificial reading hold. |
| `explanatory-comparison` | An authored graphic or selected media target in a comparison, diagram or demonstration scene. A title card or primary presenter target cannot substitute for the graphic. |
| `real-artifact` | An existing selected real image/video/web asset and its matching asset-use decision. A logo, missing decision or `no-insert` cannot satisfy this obligation. A real page scroll may serve this contextual job. |
| `real-operation` | An existing `demonstrate` decision selecting `video` or `web`, plus authored action/result checkpoints. A still image or product identity does not demonstrate a performed operation. |

The target must appear in the scene's `visibleIds` and cover the complete pacing
beat. Referenced decisions must overlap that beat's retained speech. For every
job except a presenter performance with a null hold, `holdIndex` selects an
existing pacing hold for that same target, wholly inside the beat. General
pacing holds may cross beats; add a suitable per-beat hold when a story job needs
one. Reuse the shared executable-window, motion, minimum-hold, source, origin
and media-policy checks rather than introducing a second admission path.

A `real-operation` job additionally records:

```ts
operation: {
  actionFrame: 120,
  resultFrame: 150,
  actionObserved: "Describe the actual action visible in the selected recording",
  resultObserved: "Describe the actual resulting state visible in that recording",
}
```

Those frame numbers illustrate the shape; choose actual frames from the selected
recording and output clock. The action must precede the result in that beat, and
the result must retain at least the hold's `minimumFrames` before the hold ends.
The descriptions and frame references are authored review checkpoints, not
automated proof that the action occurred or caused the result. Use `real-artifact`
for a homepage/article/README shown as context. Do not call a page scroll a
demonstrated product workflow or an executed repository example.

After completing the canvas, scenes, pacing and asset-use decisions, bind
`story.revisionHash` with `nativeStoryRevisionHash(input)`. The local `measure`
command also returns `storyRevisionHash` for the exact plan it reads. A later
source, scene, beat, hold, decision, payoff or checkpoint revision invalidates
that binding; reconsider the affected story jobs before recomputing it.

The shared assembler checks the story after the existing strategy, pacing and
asset-use gates. With a story present, the writer freezes `STORY-REPORT.json`
and the cold reader recomputes it. The report includes the actual speech for each
referenced beat and explicitly leaves narrative quality, source truth and
finished playback review unresolved. Structural success does not establish
source identity, audience comprehension, coherent storytelling or publication
approval. Complete source inspection and encoded playback with sound still apply.

Compatibility is deliberate: version 1, 2 and existing version 3 projects without
`story` remain readable, keep their original required file sets, and report story
status as `unplanned`. A story record requires strategy version 3 with pacing and
asset use. Its absence is not a structural build failure and must never be
reported as a finished-story pass. The CLI `check` status for an authored record
is `authored-obligations-checked-awaiting-whole-story-review`.

The focused verification passed **45 tests: 14 new story cases and 31 existing
native project, pacing and asset-use cases**, plus the full TypeScript check and
targeted lint. These use synthetic local fixtures and exercise the actual
writer, cold reader and CLI check; they do not qualify a real edited video or a
live website recording. See [why story jobs must bind to real visuals](../findings/STORY_JOBS_MUST_BIND_TO_REAL_VISUALS.md).

## Shared local execution

### One asset decision across images and video

Strategy v3 also requires `assetUse`. `native-short.ts measure` returns
`assetUseRevisionHash`; bind it after inspecting the selected speech and visuals.
Revisions to the source, script, treatment, request or origin records invalidate
the decision. Do not refresh a hash without reconsidering its affected choices.

Each insert or deliberate no-insert decision records its spoken window and exact
words, entity role, purpose, context, rejected alternative and claim limit. An
insert additionally binds the real local asset, target element, source/output
window, source identity, essential pixel region and audio/attribution policy.
The essential region is a review target, not an automated visibility guarantee.
A creator named only as a style reference cannot become the depicted person.
Primary performance remains on the shared source path; other images and videos
need their own decision. CSS backgrounds/posters cannot evade that inventory.

Every production asset binds a local immutable origin receipt with the existing
`AssetRecordV1`. Preserve original acquisition kind even when bytes are cached.
Public captures require the acquisition and supervision receipts as well. Their
metadata cannot be removed to pass the asset through a weaker local-file branch.
The prepared brief hashes supplied B-roll too; a supplied-file classification
must match that frozen inventory. Shared image/video source restrictions are
checked on construction and reopening.

Use `native-short.ts origin ORIGIN-INPUT.json NEW-RECEIPT.json` to freeze an
editor-authored `{asset, record, acquisition}` input. For an existing successful
public capture, use `origin-web ASSET.json NEW-RECEIPT.json`; new web acquisitions
emit the origin binding automatically. The automatic capture-to-origin wrapper
has not yet had a fresh live capture integration run; see the coverage note in
[the web B-roll workflow](WEB_BROLL_WORKFLOW.md#origin-receipts-for-new-and-existing-captures).
These commands preserve provenance and publication uncertainty. They do not
grant rights or establish editorial fit.
The project writer checks the complete policy/use contract and emits
`ASSET-USE-REPORT.json`; reopening recomputes it and export pins all evidence.

Logos must retain the real source's mark, aspect ratio and intended color variant.
The older icon library's default blue recolor and product aliases are unsuitable
as automatic identity evidence. Verify an official source and inspect final size
and contrast. A recognizable homepage can identify a product; it cannot stand
in for the operation being explained. Missing, ambiguous or unsupported sources
remain explicit gaps with a justified alternative or presenter hold.

Native review exports preserve `needs-review` publication disposition rather than
inventing approval. Audible external quotations currently require another audio
handoff path and are rejected here; silently muting the quote is not a fallback.
The [remaining work plan](SHORTS_REMAINING_WORK_PLAN_2026-09-12.md) records cohort
acceptance separately from these structural checks.

From PROJECT_SNIPER, prepare an already ingested project's stored request:

```sh
node --import tsx scripts/producer/native-short.ts prepare /absolute/project/producer
```

The app and CLI call the same local packet writer. It freezes source and
transcript hashes, admitted-source receipt, library provenance and starting
reference documents. Its inspection statuses are pending until the agent does
the work. Bind `SHORT-REQUEST.json`'s path/hash to `requestPacket` in the plan.

For an ordinary app request, save the intent through `POST /api/producer/intent`
and prepare with `POST /api/producer/native-short`, whose body contains only
`{dir}`. Preparation reads the stored resolved intent; passing a replacement
intent in that request is rejected. Native Shorts with an explicit direction
and automatic supporting placement retain scouting when the separate B-roll
inventory is empty. The agent may find useful footage inside the admitted main
source. Source restrictions, scope limits and off/operator lanes remain binding.

An older saved request may already contain a capability-resolved `broll: off`.
The fix does not silently migrate that authority. Re-save the intended native
direction through the normal intent route, then prepare a fresh brief. The real
offer-project check on September 13 exercised that recovery, exact HTTP/CLI
packet equality and rejection of an inline override. See
`artifacts/shorts-workflow-completion-2026-09-13/saved-app-01/`. That evidence
qualifies persistence and preparation; the request-bound export is separate.

### Prepare a stored guided proposal

For a reconstructed native V9 or V10 guided proposal eligible for preparation, use the guided entry
point instead of assuming its manifest lives in the default source directory:

```sh
node --import tsx scripts/producer/native-short.ts prepare-guided /absolute/guided-project/producer
```

This reads the existing proposal's `job.ctx.intent` and `job.ctx.manifestPath`
and calls the same packet writer. Bootstrap manifests outside the project's
`source/` folder remain supported. The command returns the prepared directory,
request hash and proposal hash. Bind that directory's `SHORT-REQUEST.json` and
its hash as the native plan's `requestPacket`; preparation does not build or
approve the Short.

The app's native preparation endpoint also supports this stored guided path.
It accepts only `{dir}`, derives the checkpoint from the saved journal and
uses the controller's mutation lease. Malformed journals, stale checkpoints,
changed inventory and client-supplied policy replacements fail explicitly.
This prepares the actual brief; V9 still blocks execution of required external
assets. V10 can prepare typed pending supplied-raster requirements. Project
assembly still requires every required scene/asset pair to resolve through an
existing v3 asset-use decision. Unsupported requirements remain blockers.

The guided writer requires the packet before caption preparation. It compares
its complete normalized intent, frozen manifest, admitted sources, transcripts,
supplied B-roll and source-set receipt with the stored guided authority. The
native request must preserve the requested style and sourcing restrictions;
legacy requests retain the local-only default. Shared checks enforce disabled
or operator-owned lanes and requested audio work. A replacement packet cannot
authorize public sourcing or change an operator-owned B-roll lane to automatic.

Authority is checked again before and after writing the local project. If the
actual guided request or inventory changes, prepare and reassess the affected plan from that
new authority. Removing `requestPacket` or editing only its declared hashes
does not repair a mismatch. Preparation and contract checks remain separate
from semantic, listening and publishing review.

### Assemble a stored guided proposal

After preparing and inspecting the brief, save a `GuidedNativeVisualPlan` JSON
object with `candidateHash`, the full native `project`, and (for V10 requirements)
`assetResolutions` containing `{sceneId, assetId, decisionId}` entries. Each entry
must resolve to the same existing strategy v3 asset-use decision and current
admitted supplied raster. A no-insert decision cannot satisfy a required insert.

```sh
node --import tsx scripts/producer/native-short.ts build-guided /absolute/guided-project/producer /absolute/visual-plan.json
```

This local command reconstructs the current saved proposal, acquires its exact
checkpoint mutation lease, uses the original generation deadline with a bounded
120-second assembly attempt, and records attempt start/result files under
`producer/native-build-attempts/`. It cannot choose a provider, change a deadline
or invent an accepted cut. Its success status is `ready-for-native-qc`; it does
not render or grant editorial, delivery or publication approval.

The shared native writer retains `GUIDED-PROPOSAL.json` among hashed inputs and
a guided binding in the request. Cold reads reconstruct the current proposal,
request and admitted inventory, then replay scene/asset resolutions. The reserved
`native-development/<proposalHash>` destination also requires that binding when
optional metadata is stripped, including access through a symlink alias. This is
an integrity check for the canonical guided project, not a global project registry.

The entry and shared writer/reader have structural test coverage. No finished
service-backed guided Short has been qualified under the current local-only
choice. Existing test-only cut/admission fixtures are never production authority.

### Add supplied B-roll before cut acceptance

Use **Add supporting image or video** on the project card for PNG/JPEG/WebP or
MP4/MOV, up to 1 GiB. The control stages a stable copy and runs existing sandbox
admission. Its additive rescan preserves verified source transcript bytes and
existing supporting assets, including recordings referenced outside the source
folder. It never starts ASR. Changed or missing originals fail explicitly.

The control is disabled after guided cut acceptance or while another writer owns
the project. After successful admission, prepare a new Short brief to freeze the
expanded inventory. The existing brief is deliberately unchanged. SVG and other
unsupported native selections need an independently admitted local derivative.
See [supplied formats](SUPPLIED_MEDIA_FORMATS_2026-09-13.md) for the full boundary.

### Build and export

Author `NativeShortProjectInput` using the shared types in
`src/lib/server/native-short-project.ts` and `native-short-strategy.ts`. It
contains request, source-bound strategy, explicit canvas, frozen asset bindings,
optional project-owned native mechanisms and visible-state checkpoints.
Use existing transcript and caption-grouping code; do not rerun ASR for a title
or layout revision. Native authoring supports the chosen composition directly.
The obsolete contained-landscape development fallback is removed.

For a confirmed caption spelling correction, `canvas.captionCorrections` accepts
an ordered list of `{occurrenceId, expectedSourceText, displayText, reason}`.
Each entry binds one existing occurrence and its exact original ASR spelling.
Use the actual user's correction as the reason; retain the original transcript,
occurrence identity, cuts and word windows. Multiword display text such as
`level is` shares the original `levels` occurrence's highlight window. This is
a caption display correction, not source retokenization or new acoustic alignment.

The shared caption text limits apply. Duplicate/out-of-order/stale targets,
unchanged or malformed text, controls and missing reasons fail explicitly.
Corrections change the visual binding and require a new native build/picture
export; the source timing hash stays unchanged. Pacing observations show corrected
display text with original `sourceText` beside it. Reassess phrase fit at phone
size, and retain current audio reuse only when its independent policy passes.
Native capture checks the actual span text as well as its timing, color and fit.
See [the confirmed C0679 case](../findings/CAPTION_DISPLAY_CORRECTIONS_KEEP_SOURCE_CLOCK.md).

For an inspected source with existing burned-in captions, declare
`canvas.captionMode: "source-burned"` with empty `captionViews` and no display
corrections. Its source picture must cover the entire timeline. The shared
validator rejects duplicate caption views and missing source intervals; overlapping
source panes may jointly cover the clock. Original words/groups remain speech
evidence. The pacing report explicitly does not measure burned-caption timing.
Shared scene extensions use an explicit mount without creating dummy captions.
Review real pixels for crop/overlay clearance and legibility; this mode cannot
remove or edit text already burned into source footage. See
[caption ownership](../findings/BURNED_CAPTIONS_NEED_EXPLICIT_OWNERSHIP.md).

For progressive native reveals, initialize every future term's visibility
explicitly. A future GSAP `fromTo` with `immediateRender:false` does not hide the
element before its tween starts. Add visible-state checkpoints before each reveal
as well as after it settles. The offer qualification caught future formula terms
appearing before their spoken cue despite a technically valid export.

```sh
node --import tsx scripts/producer/native-short.ts build /absolute/plan.json /absolute/new-project
node --import tsx scripts/producer/native-short.ts check /absolute/new-project
.venv/bin/python scripts/producer/studio/native_short_export.py /absolute/new-project /absolute/new-export
```

The export directory must be new and its parent must exist. An optional
`--audio-donor /absolute/prior-export/audio/receipt.json` reuses qualified audio
only when its source-derived premaster and delivery policy match. The explicit
native profile is `native-short-v1`: shared mastering with −2.5 dBTP internal
headroom, at most six static-gain dry runs and 320k AAC. Native encoding explicitly
disables AAC perceptual noise substitution and records the consumed arguments
in `aacEncodingPolicy`; all final delivery and signal thresholds remain unchanged.
Reusing an eligible default-profile receipt also requires explicit
`--audio-profile default-v3`; the native default does not silently adopt it.
Historical donors missing the current AAC encoding policy require fresh audio
encoding under either profile. Do not backfill their old receipts. Profile
selection does not change long-form defaults or skip current audio qualification.

`--cached-native-batches` opts into native sessions of at most 48 frames. The
shared source-pixel budget selects smaller sessions for larger inputs; the
tested four-4K-view plus page composition uses eight. It requires the exact SDK
source-frame cache and does not migrate keys, resize source pixels or change
final encoding quality. Add `--acquire-source-cache` to populate missing supported
SDR entries sequentially through the pinned SDK, with original geometry, exact
frame inventories and normal playback speed. Unsupported or incomplete sources
fail explicitly. This is an opt-in path, not a fallback after a failed render. Use
`--picture-donor /absolute/prior-export` with that mode to reuse a verified,
completed batch picture after a later-stage failure. All current final checks
still run. A missing cache without acquisition enabled, or changed donor
evidence, is an explicit failure.

The explicit
`--unused-ram-advisory` option requires the operator's low-unused-RAM exception;
it retains owned-tree, per-process, pressure, swap and cleanup checks.

The exporter runs three sequential supervised owners: media generation, native
reference capture, and encoded-picture/full-decode verification. Each retains
the existing 600-second owner budget, shared heavy-work lease, continuous
resource controls and mandatory cleanup. Only one owner runs at a time. The
streaming capture CLI runs directly under its capture owner, preserving the
original single-session forward/reverse sequence without the old generic
180-second subprocess wrapper. Batch capture retains its phased coordinator.
The pinned adapted SDK, file-backed source frames, one render worker, shared
exact frame/sample timing, float mastering and AAC verification remain. It
checks actual native captures at word
and scene boundaries, reverse seeks, title/caption state, encoded-picture
comparisons and full audio/video decode. Failed attempts remain on disk.

`delivery.json` is the final result for the whole export invocation, with
preparation time, per-owner elapsed time, all failure states and reuse status.
`pipeline.render.json` now describes the media owner only and can report
`native-short-rendered-awaiting-qc`; that is never final delivery approval.
Only `delivery.json` status `native-short-checked-for-review` qualifies the
technical handoff after capture, encoded checks and every owner's cleanup pass.
Editorial authoring time belongs to the separate continuous production clock.

### Resume verification without repeating media generation

The default command runs all three stages. To explicitly stop after media
generation, use `--render-only`. A successful media owner publishes an immutable
`render-stage.json` binding the original request, project/source/tool/code pins,
owner completion/cleanup, picture, final MP4, audio receipt and media result.
After a later verification failure, start a fresh verification attempt:

```sh
.venv/bin/python scripts/producer/studio/native_short_export.py /absolute/project /absolute/new-verification --verify-from /absolute/original-export/render-stage.json
```

This preserves the sealed route/cache/audio policy, copies the exact final MP4
and repeats current native/encoded verification with no picture or audio encode.
Do not combine it with render/donor/cache overrides. Use a new directory outside
the project and original attempt. Changed dependencies, linked/substituted files,
incomplete media/audio/color proof or unverified owner cleanup reject before
verification. A collection of MP4s or partial receipts is not a reusable stage.
Historical failures without a stage seal remain failures; never backfill them.
If new code or source changes invalidate a seal, produce a separate authorized
candidate through the normal path; do not silently rerender during verification.

Keep the default streaming render route unless measured project evidence
justifies explicit cached batches. Repeated browser startup can dominate short
timelines; additional agent processes do not accelerate that capture loop.

Batch-mode reference/seek QC runs sequential phases when a verified retained
forward inventory is available. The original point planner still defines every
occurrence; each child handles at most 48 complete fresh-session groups, with
the same reverse seed, source payload, typography, scene-state and disposal
checks. The parent retains each child receipt's returned digest and verifies
the schedule, receipts and source/code pins between phases. Only a complete,
ordered, byte-verified aggregate can publish `native-frames.json`; encoded
picture comparisons and full A/V decoding still follow. No failed attempt's
partial JPEG directory counts as a completed phase. Each child retains the
180-second timeout inside their single 600-second capture owner and
unchanged memory/worker limits. The streaming route keeps its original capture
path. Valid batch projects with one-frame session capacity or no retained forward
evidence also keep full replay; invalid evidence fails instead of selecting a
fallback. Repeated cache admission retains stable source identity independently
of observed extraction timings. Eligible phases share one actual compilation
from their current run: its complete result, mutated render configuration and
compiled files are preserved and hash-bound to the parent. Every phase checks
the full project/dependency inventory and copied compiler files before and after
capture. This avoids repeated advisory keyframe scans without changing source
admission or any capture check. No prior run's compiler result is adopted.
See `docs/findings/NATIVE_QC_SESSION_COUNT.md` for the motivating case and
verification scope.

Live resource collection uses public macOS physical-footprint and host VM
counters through the shared owner. The bounded retry and original deadline,
process-identity checks, host pressure, swap, disk and memory caps still apply.
Per-process compressed bytes are an explicitly uncollected/null diagnostic;
host compressor bytes remain measured and required. Historical `top` receipts
retain their numeric diagnostics. Permission failures and malformed measurements
stop immediately. The direct sampler passed eight actual codec regressions and
a supervised native export; see the implementation receipt for scope and timings.

Deliver `review.mp4`, the editable project and receipts. A technical pass is
**ready for review**, with human editorial/listening approval still outstanding.
Report actual source/output durations, planning and execution time separately,
cache reuse, measured memory and the specific cases tested. Three examples do
not qualify every creator style or establish raw-footage-to-finished-edit time.

Native delivery shares dialogue cleanup, ramped gain, mastering and final audio
QC with long form. Before export, write a source-specific `audioFinishing`
decision in `SHORT-PROJECT.json` when processing is needed:

```json
{
  "schemaVersion": 1,
  "rationale": "Reduce this recording's steady fan noise; lift the quieter second clip.",
  "audioEnhance": { "preset": "voice" },
  "audioGain": [{ "outStart": 12, "outEnd": 18, "dB": 3 }]
}
```

The available installed presets are `voice`, `voice-strong` and `voice-rnn`.
An enhancement requested through the app must match the assembled decision;
missing or substituted processing fails assembly. Gain windows use final output
seconds, remain inside the actual duration, cannot overlap and are bounded to
±12 dB. Existing 50 ms ramps avoid abrupt gain steps. Omitted processing leaves
the normalized dialogue unchanged. Keep original source audio for comparison.

The sequence is observed channel normalization → shared cleanup with measured
latency removal and tail flushing → authored gain → shared loudness/peak master
→ one AAC delivery → actual final-output checks. Do not master each clip
independently or apply gain after the master. Model bytes, settings, output clocks
and results are retained; the raw source is never overwritten.

Final QC checks channel balance across the piece and in 100 ms windows, including
the last partial window. An alternating left/right fault must not cancel in a
whole-piece average. Exact native cut intervals also receive active speech-band
energy measurements; adjacent changes of 6 dB or more require listening review.
These measurements are not LUFS, semantic speech detection, or proof of an
unwanted level change. Preserve deliberate emphasis, whispers and pauses. Music
and noise in the speech band can affect the measurement. Long-form Audit B uses
the same checks with declared picture-cut intervals; those are not a guarantee
of spoken boundaries, especially with J-cuts or frame quantization.

Fresh and reused AAC must pass current audio QC. Severe channel faults, invalid
review clocks and failed delivery targets block export. Review warnings and
`humanListeningApproved: false` remain visible in the receipt. Noise reduction
does not establish room-echo removal; dereverberation remains a separately
evaluated processor, with matched-level A/B listening before adoption.

Background music in native Shorts remains unsupported and is rejected when
requested. Disabled or operator-owned visual lanes remain authoritative.
