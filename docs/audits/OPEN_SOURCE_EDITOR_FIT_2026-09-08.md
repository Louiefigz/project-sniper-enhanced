# Repository fit audit: HyperFrames, Vex, and Podframes

Evidence date: September 8, 2026. This is a source-level comparison with focused
local experiments, not a real-footage production benchmark or an implementation
approval. The recommended direction is **selective HyperFrames reuse inside
Sniper**. Vex is the closest creative analogue, but its licensing and execution
model make it a poor replacement. Podframes solves a different primary problem.

**What was inspected**

| Repository | Frozen revision | Evidence inspected |
|---|---|---|
| heygen-com/hyperframes | `v0.8.31`, `30d6f43bdb669af14be894d12985e9924db4a01a` | SDK source, published package, mutation/read APIs, tests, Studio documentation, check command |
| AKMessi/vex | `5789b687ab1b054afb5c54a2f5b231ce02d86029`, July 29, 2026 | Visual planning/authoring/verification, state, replay, export, provider selection, selected tests, CI, license |
| Jellypod-Inc/podframes | `b7afdf241f218e7fd2be0bf65fc486cf70fec947`, July 10, 2026 | Pipeline, composition/timing, edit invalidation, render completion, web run lifetime, tests, CI, license |

Upstream clones and experiments were isolated under
`/private/tmp/sniper-repo-audit-20260908.cQAf0x/`. Sniper's application, dependency
pins, production projects, and source footage were not changed. HyperFrames SDK
0.8.31 was installed only in that temporary directory, with install scripts
disabled. Node was `v23.10.0`. Vex was inspected but not executed. No paid model
calls, generated avatar calls, external uploads, or complete video renders ran.

**The actual Sniper target**

The comparison follows [PIPELINE.md](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/docs/PIPELINE.md:1)
and the September 6 [executable workflow matrix](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/docs/producer/command-driven-editing/12_SHORT_LONG_EXECUTABLE_MATRIX.md:1).
It does not treat every aspiration in older plans as shipped behavior.

Sniper is intended to take real recordings through editorial decisions, clean
cuts, useful graphics, captions, audio treatment, revisions, independent review,
and an approved final MP4. Short-form has measured style policies; long-form has
operator-selected treatment lanes. The main interaction is a local skill/CLI;
the custom web UI is optional. HyperFrames handles graphics, while FFmpeg owns
the footage/final assembly boundary. Revision accuracy, source fidelity, and
whole-output QC matter alongside appearance and speed.

Several useful mechanisms already exist: project-specific HyperFrames scenes,
independently cached scene units, caption shards, and bounded scene repair. The
matrix still marks complete-build performance and the embedded Studio review
routes unqualified. The historical standalone Studio success does not establish
creator-footage qualification for every current GUI route. A replacement must
be compared with this mixed state, not with either an imaginary finished Sniper
or an empty project.

| Requirement | HyperFrames | Vex | Podframes |
|---|---|---|---|
| Edit original talking-head/tutorial recordings | A composition toolchain; Sniper still supplies the editorial workflow | Directly aligned: real media, transcripts, cuts, effects, shorts | Primary flow generates dialogue and avatar clips |
| Produce explanatory HyperFrames visuals | Strong direct foundation | Strong conceptual match, with semantic planning and candidate repair | Fixed podcast-oriented composition treatments |
| Precisely revise existing graphics | Structured SDK mutations and history; adapter required | Operation history and generated-visual repair; different project model | Turn/clip edits and treatment changes |
| Reuse only affected render work | Helps edit compositions; does not schedule Sniper's final render graph | Replay and caches exist; general local-only revision equivalence not established | Reuses paid turns, then recomposes/renders the episode |
| Preserve Sniper's independent approval requirements | Host responsibility | Some local visual QC aligns; default degradation policy differs | Render completion has substantially lighter checks |
| Work through existing local/subscription agent path | Compatible as a tool used by our agent | Main/vision provider plumbing requires adaptation | Core generated-media workflow depends on API services |
| Reusable open-source foundation | Apache-2.0 | PolyForm Noncommercial; not a business-compatible open-source foundation | Apache-2.0 |

**HyperFrames: strongest direct reuse, especially the SDK**

The more valuable discovery is `@hyperframes/sdk`, not simply the Studio UI.
It opens HTML without a browser, queries elements, performs text/style/timing/
variable/animation changes, emits patches, and supports undo/redo and batching.
It can keep overrides separate from the source template. These are existing
implementations we could wrap behind Sniper's approved scene-edit commands.
[SDK overview](https://hyperframes.heygen.com/packages/sdk),
[frozen session implementation](https://github.com/heygen-com/hyperframes/blob/30d6f43bdb669af14be894d12985e9924db4a01a/packages/sdk/src/session.ts).

This could remove some custom HTML editing and history plumbing from future
work. It does not replace our scene bundle, asset admission, exact frame/sample
timing, dependency invalidation, or final promotion rules. Its element IDs must
be bound to Sniper scene/unit identities. An SDK patch is an input to a governed
revision, not proof that the revision was approved or rendered correctly.

I ran eight checks against the published SDK: seven passed and one exposed a
readback inconsistency. Passing checks covered an edit batch surviving reopen
while preserving an unrelated element's state, undo/redo, rollback after an
exception, unknown-target rejection, GSAP tween serialization, an in-memory
variable edit in Sniper's actual `fire-sparkles` fixture, and the expected absence
of runtime-generated elements from the static document model.

The failed check is concrete: after `setTiming(..., {start: 2, duration: 2})`,
the serialized HTML contains the right duration and `getElementTimings()` returns
the correct interval, but `getElement(...).duration` returns `null`. The generic
snapshot reader derives duration from `data-end`; the writer uses
`data-duration`. Both the frozen source and installed package contain that
behavior. This is a query inconsistency, not evidence of a bad MP4 render.
[Snapshot reader](https://github.com/heygen-com/hyperframes/blob/30d6f43bdb669af14be894d12985e9924db4a01a/packages/sdk/src/document.ts#L185),
[canonical timing reader](https://github.com/heygen-com/hyperframes/blob/30d6f43bdb669af14be894d12985e9924db4a01a/packages/sdk/src/session.ts#L345).

For our existing scene fixture, changing the declared `rightTitle` variable
survived serialization/reopen and left the source file untouched. The SDK did
not materialize the `right-copy` element built later by JavaScript. We should
start with declared variables and explicit supported elements; arbitrary
runtime-generated scenes still need their own authoring contracts. This test
did not render the modified fixture or prove compatibility with runtime 0.7.33.

The newer `hyperframes check` command also combines lint, runtime, layout,
motion, and contrast checks in one browser session. Transition-boundary sampling
and machine-readable results make it a useful candidate for earlier scene
feedback. It can help catch geometry and motion problems before final assembly;
it cannot judge our whole edit's narrative, audio, or claim grounding.
[Check command](https://github.com/heygen-com/hyperframes/blob/30d6f43bdb669af14be894d12985e9924db4a01a/packages/cli/src/commands/check.ts).

Studio remains useful for manual review, but its components require project
state and contexts; they are not a drop-in editor. The SDK fits our primary
headless workflow more directly. [Studio integration documentation](https://hyperframes.heygen.com/packages/studio).

A runtime upgrade is more than an npm version edit. Sniper's
[scene bundle schema](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/schemas/producer/scene-bundle-v1.schema.json:60),
[TypeScript validator](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/src/lib/producer/contracts/scene-bundle.ts:144),
and Python bundle validator explicitly require 0.7.33. Newer SDK-generated HTML
must be checked against the intended renderer, and a runtime migration must
renew the applicable capability/render evidence and invalidate affected caches.

There is also no undiscovered catalog windfall: Sniper already has a substantial
[read-only upstream catalog mirror](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/vendor/hyperframes-catalog/README.md:1).
The remaining work is selecting, adapting, and qualifying components for our
plan vocabulary and geometry. Catalog availability alone does not close it.

Decision: **evaluate the SDK and diagnostic tools first; expand Studio where
operator needs justify it.** Reusing these components could reduce development
work. No measured integrated speedup is established yet.

**Vex: genuinely aligned creatively, unsuitable as a direct foundation**

Vex's alignment is substantive. Its code includes transcript-derived visual
opportunities, typed scene primitives, grounded copy constraints, explanatory
relationships, rendered candidate evaluation, and bounded repair. The visual
director selects among publishable candidates and records verification state.
That is closer to our aim of graphics that explain the spoken point than a
generic automatic B-roll editor.
[Scene authoring](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/vex_hyperframes/authoring.py),
[communication contracts](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/vex_visuals/communication_contract.py),
[visual director](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/vex_visuals/director.py#L115).

The useful design question is: can a viewer recover the intended relationship
from the visual, and does the visual improve understanding? We could add that
question to our independent composition review, using our own implementation.
It would complement checks for text overflow, timing, and spelling.

Direct adoption has four material obstacles:

1. **License.** The frozen package declares PolyForm Noncommercial. The project's
   README explicitly excludes internal business tooling and revenue-generating
   workflows without a commercial license. A free Sniper giveaway is not, by
   itself, evidence that the intended use meets those terms. It does not meet
   the requested freely reusable open-source foundation criterion.
   [License](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/LICENSE),
   [package metadata](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/pyproject.toml#L11).
2. **Different revision model.** Vex maintains a working media file and an
   operation history. Its general rebuild starts from source and replays
   operations. That is useful undo/reconstruction behavior, but does not
   establish Sniper's desired unchanged-outside-window proof or general
   one-unit dirty rendering. Its edit-plan object is a sequence of tool steps,
   not a compatible Sniper edit plan.
   [Replay](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/tools/undo.py#L194),
   [edit-plan type](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/edit_plan.py).
3. **Different approval policy.** Balanced verification is the default. On a
   vision-provider outage, a candidate passing the local threshold can be
   marked degraded and publishable; strict mode is available. Sniper requires
   the configured independent evidence to be present before final approval.
   Vex's per-visual verification and validated export are useful, but the
   inspected export path does not implement our complete plan/manifest/final
   approval chain.
   [Verifier outage path](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/vex_visuals/verifier.py#L645),
   [export implementation](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/engine.py#L1609).
4. **Integration and execution cost.** The independent vision path selects
   API-key-backed Gemini/Claude providers. It would need a bridge to our
   existing agent execution model. Visual generation is spread across a large
   coupled pipeline; `tools/auto_visuals.py` alone is 6,513 lines in this
   revision. Candidate tournaments and repair rounds also spend compute/time.
   Neither code presence nor a fast CLI proves a faster complete Sniper job.
   [Provider selection](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/vex_visuals/verifier.py#L561).

The selected tests support real control-flow intent, including strict renderer
selection and degraded-verification behavior. Several render/vision tests use
mocks, so they do not establish visual quality on our recordings. No Vex
creator-footage benchmark was performed here. No equivalent verified reference
style-replication or exact non-ripple workflow was established in this review.

Decision: **use as a conceptual comparison, especially for semantic visual
review. Do not plan a fork or code transplant under the current license.**
Even if commercial licensing were resolved, project-model and approval-policy
adaptation would remain.

**Podframes: good narrow workflow ideas, weak overall fit**

Its actual pipeline is script → speech → stills → avatar video → B-roll →
composition → render. Its clip model and composition builder center on host
turns and generated avatar segments. It is not an existing raw-footage editor
waiting for a Sniper skin.
[Pipeline stages](https://github.com/Jellypod-Inc/podframes/blob/b7afdf241f218e7fd2be0bf65fc486cf70fec947/packages/core/src/pipeline.ts#L30),
[composition model](https://github.com/Jellypod-Inc/podframes/blob/b7afdf241f218e7fd2be0bf65fc486cf70fec947/packages/core/src/compose/builder.ts).

There are worthwhile ideas: a shared edit-invalidation map used by browser and
server, selective speech/clip regeneration, explicit stage status, and previews
of the work a change will invalidate. These make update costs understandable.
We could adopt the interaction pattern while retaining Sniper's finer scene
and caption dependencies.
[Shared invalidation map](https://github.com/Jellypod-Inc/podframes/blob/b7afdf241f218e7fd2be0bf65fc486cf70fec947/packages/core/src/shared.ts#L133),
[selective speech invalidation](https://github.com/Jellypod-Inc/podframes/blob/b7afdf241f218e7fd2be0bf65fc486cf70fec947/packages/core/src/editing.ts#L91).

I ran its timing and composition-builder tests: **16 passed**. Those prove
bounded trim/timeline math and generated HTML behavior, not paid-media output
quality. A separate helper probe returned no invalidated stages for changed
`fps` or `renderQuality`, while a changed visual treatment correctly returned
`compose, render`. This demonstrates incomplete option coverage in the helper;
the full live CLI path was not exercised. Do not import the map as a complete
dependency model without covering every render-affecting field.

Its render stage treats lint errors as nonfatal, skips lint for draft renders,
uses one capture worker for a documented older-runtime issue, then normalizes
the MP4 and marks completion using file size/duration. That is a different
quality boundary from Sniper. Its declared HyperFrames dependency is
`^0.6.110`, so its renderer workaround is not evidence about our 0.7.33 or the
newer 0.8.31 runtime.
[Render stage](https://github.com/Jellypod-Inc/podframes/blob/b7afdf241f218e7fd2be0bf65fc486cf70fec947/packages/core/src/stages/render.ts#L53),
[package dependencies](https://github.com/Jellypod-Inc/podframes/blob/b7afdf241f218e7fd2be0bf65fc486cf70fec947/packages/core/package.json).

The web run manager survives browser disconnects and stores its registry on
`globalThis`; execution still lives in the server process. This does not prove
survival across server-process termination. Sniper should retain its detached
worker design. Podcast timing also rounds selected mappings to hundredths of
a second; that is not a replacement for our rational-frame/sample contracts.
[Run lifetime](https://github.com/Jellypod-Inc/podframes/blob/b7afdf241f218e7fd2be0bf65fc486cf70fec947/apps/web/lib/runs.ts#L51),
[trim timing](https://github.com/Jellypod-Inc/podframes/blob/b7afdf241f218e7fd2be0bf65fc486cf70fec947/packages/core/src/compose/trim.ts#L3).

Decision: **borrow the change-impact preview and selective-regeneration UX if
needed; do not adopt its pipeline as Sniper's base.** The Apache-2.0 software
license does not make its generated-media API calls free.

**Where development time could actually be saved**

| Candidate | Potential saved work | Work still required | Priority |
|---|---|---|---|
| HyperFrames SDK behind scene commands | HTML mutation, supported animation edits, local history, patch generation | Sniper ID mapping, variable/bundle binding, version compatibility, gates and readback | First experiment |
| HyperFrames check/keyframe diagnostics | Some custom early geometry/motion diagnostics | Normalize reports; preserve final independent QC; measure overlap and latency | Evaluate alongside SDK |
| Existing upstream catalog | Reauthoring suitable visual mechanisms | Selective porting, brand/geometry adaptation, runtime qualification | Target named missing visuals |
| Vex semantic visual-review ideas | Design exploration for explanatory graphics | Original implementation, reviewer calibration, measured quality/cost | Small independent experiment |
| Podframes change-impact UX | UI design for explaining regeneration | Bind to Sniper's actual graph and cache state | Later, if operator friction warrants |
| Whole-editor replacement | No defensible saving established | Source/project migration, fidelity, reviews, licensing, regressions | Do not start |

Development effort, initial-build runtime, and revision runtime are separate
measurements. SDK reuse can reduce engineering work without accelerating video
encoding. A better critic can improve visuals while increasing first-build
time. Neither should be advertised as a percentage saving without measurement.

**Concrete next experiment**

Build one disposable adapter for declared scene variables and supported text/
timing edits, leaving the renderer migration a separate decision. Bind every
target to an existing Sniper scene/unit and run SDK edits on a private candidate.
Use the canonical timing query, preserve project-controlled IDs, and reject
unsupported runtime-generated element edits rather than guessing.

Exercise one representative short and one 10–14 minute talking-head/screen-share
project. For each: change one card's wording, change its supported styling, move
its timing, adjust one caption, then add/remove one governed scene. Record the
existing path and proposed path from the same starting project. Check retained
plan fields, affected unit/cache counts, decoded picture/audio outside the
requested changes, final QC, total wall time, model/tool calls, and operator
interventions. Add a failed-edit rollback and a missing/stale review case.

Proceed only if this reduces adapter/custom-code work and measured revision
effort while preserving the existing requirements. A failure should remain a
small adapter finding, not trigger a wholesale pipeline rewrite. This audit
does not establish the full-project 90-minute target or authorize a production
dependency upgrade.
