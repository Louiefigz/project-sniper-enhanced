# Native edits need a directing plan before assembly

Aaron rejected the first native Shorts preview on September 10: the full
landscape source occupied a small part of a portrait canvas, captions sat in
empty space underneath, and the proposed split had no demonstrated story need.
This was a planning failure, not a memory or rendering failure.

## What the long-form paths actually provide

The current C0679 native project's
[brief](/private/tmp/sniper-c0679-produced-review-20260909.FCYcRv/native-presenter-v1/BRIEF.md)
defines the viewer, their problem, Aaron's role, the visual idea, rhythm,
palette/type hierarchy, a timed editorial scene plan, source-word cues,
catalog adaptations, rejected alternatives and verification requirements.
Its extension notes develop those decisions across the programme. This is a
concrete structure to reuse; the current revised document alone does not prove
every decision was recorded before its first implementation.

The [automated route](AUTO_EDIT_LANE.md) separately implements author →
deterministic gates → fresh strategy critic → bounded revision → current-plan
review checkpoint → render. See
[planning-loop.ts](../../src/app/api/producer/auto-edit/planning-loop.ts),
[planning-review-batch.ts](../../src/app/api/producer/auto-edit/planning-review-batch.ts),
[authoring-prompt-inputs.ts](../../src/app/api/producer/auto-edit/authoring-prompt-inputs.ts)
and [review-contract.ts](../../src/app/api/producer/auto-edit/review-contract.ts).
Those checks bind the actual reviewed inputs and invalidate review after a change.
They are not automatically connected to the native development writer.

## Why this Short bypassed the useful structure

The real-source development `build.mts` hand-authored its proposal, called the
native materializer, and wrote a one-paragraph BRIEF after the HTML. It made
zero provider calls. The generated STORYBOARD described already-selected scenes.
Neither artifact was an independently reviewed creative strategy before assembly.

V9 binds exact words, scene windows, selected reference images, actions and holds.
It does not express an overall audience/promise, alternative treatment selection,
source crop, caption hierarchy, two-pane purpose, or a strategy-critic verdict.
The writer fixes footage to a 1080 × 660 contain box and captions to y=1460.
Thus reference IDs and valid timing could pass while the picture was wrong.
A reference beat that stages a full-screen analogy, for example, does not
justify a presenter-plus-message split just because its persistent container
was transferred.

## Shared planning sequence

Use the existing BRIEF and STORYBOARD as the working documents. Do not generate
them retrospectively from HTML or add a new human permission round in an
autonomous edit. The directing agent is the creative brain; another model call
without this responsibility and evidence would not solve the failure.

| Stage | Required decision/evidence | Completion condition |
| --- | --- | --- |
| Brief | Viewer, problem, source-supported takeaway, actual opening and payoff, output, requested lanes, preserved decisions | An editor can explain why this clip should exist without naming a template |
| Strategy | Read the complete retained speech and inspect the actual footage; compare relevant reference images and at least one alternative; select edit intensity separately from layout | Chosen treatment serves this message and its source, with rejected alternatives explained |
| Shot plan | Every important beat through the ending: exact cue, purpose, selected asset and original range/handles, attention target, what changes or deliberately holds, layout, crop/subject clearance, text jobs and lifetimes, transition start/destination/duration/ease, reading hold and exit | Another editor can build the planned scene without inventing its explanation or transition |
| Feasibility | Actual inspected local media with provenance, selected registry source/configuration, fonts, supported geometry and timing; resolve missing assets and capability gaps before building affected scenes | The chosen scene can execute without replacing it with an easier template; a search result or desired asset is not a fulfilled dependency |
| Independent critique | A fresh critic sees the complete plan, actual source/reference images, exact speech and feasibility findings | Material issues are resolved against the current plan before assembly; no self-issued approval |
| Representative preview | Check the selected composition at phone size and through its meaningful changes | Actual output matches the plan before scaling; final audiovisual QA still follows |

### Resolve decisions upstream; delegate bounded execution

The September 16 follow-up explicitly asks for a strong brief and complete plan
to prevent avoidable revisions and full rerenders. Treat the sequence above as
a dependency order: source/reference inspection and asset discovery inform the
plan; feasibility and an independent critique precede dependent assembly. A
changed source, claim, timing, crop or transition reopens the affected decisions.
Keep the record in the existing brief, storyboard and asset/usage map; do not add
a second planning system or a blanket human approval round.

Use parallel agents only when their work is independent and reduces the critical
path. Source scouting can run beside reference/strategy research. After the plan
passes, a graphics worker can own a self-contained scene with frozen cue words,
input assets and hashes, frame window, start/end state, geometry, type/motion
tokens, text, reading hold and output contract. Assign disjoint files; one lead
owns dialogue, global timing, presenter continuity and scene seams. Workers must
report a missing capability or asset instead of changing the treatment. Small
scenes with shared geometry may be faster for the lead to build together.

Review each returned scene against its assignment and check its integration with
adjacent scenes before one coordinated full export. Use a targeted preview for
uncertain crop/motion/readability, not a complete encode as the discovery loop.
Final full-program audiovisual review still follows; planning cannot catch every
implementation or playback fault. Measure actual planning, assembly, review and
render timings and classify rerender causes before claiming a speed improvement.

For split screen, name what each pane teaches, why simultaneous viewing is
useful, each subject/detail's required size, and the condition that ends the
split. A second pane that paraphrases captions is not sufficient. For a
presenter hold, identify why expression or explanation carries the passage and
keep the person prominent. Neither split nor full presenter is a universal rule.

## Standing directing requirements — September 16, 2026

Aaron's review of IMG_7446 rejected abrupt layout cuts, repeated Joker grooming,
unexplained chicken/beef images, an omitted Facebook-advertising beat and a brief,
unreadable supplier view. His subsequent clarification makes this a standing
standard for all future Shorts and long-form work, not just this source or
presenter. Apply it before assembly within the requested treatment; respect a
simple edit, a different current brief and disabled visual lanes. The examples
below illustrate the explanatory jobs, not mandatory dog imagery or layouts.

- **Source coverage before shot assignment.** Inspect the available catalog
  broadly, then transcript-match and visually inspect relevant footage. Record
  distinct subjects, actions, locations, exact ranges and handles. Review the
  usage map for repeated source ranges and near-identical action. A callback
  needs a new explanatory job; convenience is not a reason to repeat footage.
- **Problem → explanation → visible example.** Record what a viewer should
  understand from each insert and why those pixels explain the spoken point.
  Give protein/product examples their feeding or allergy context. Never imply
  an ingredient cures a condition merely by juxtaposition. Verify the actual
  speech instead of converting a user's shorthand or ASR error into advice.
- **Smooth presenter continuity.** Plan the start pose, destination pose, motion
  duration/ease and reading hold. Use the same continuous source clock through
  a layout move. Consider pictures on either side, a temporary circular presenter
  at bottom left, and a return to full presenter. Inspect face/hand clearance
  during the motion; an endpoint screenshot cannot establish a smooth handoff.
- **Give B-roll the space its job needs.** Deliberately remove the presenter
  when an action, product or explanation needs the full frame. Consider three
  distinct videos together when viewers benefit from seeing related examples
  simultaneously. Stage attention and labels so they understand the relationship;
  do not turn variety into unrelated motion or a compulsory template rotation.
- **Complete semantic coverage.** Check all important spoken problems, actions,
  companies and business arguments against the shot plan, including the ending.
  Paying Facebook is a visualizable advertising-cost point. Use real platform
  identity and an honest explanatory illustration; do not fabricate spending,
  performance metrics or a personal account dashboard.
- **Recognizable products and destinations.** Establish the official website,
  focus the logo/product, and hold the settled target and readable destination
  long enough to recognize and act on it. Specify the crop/zoom and reading hold
  in the strategy; confirm them at delivery size during playback.
- **Catalog breadth with editorial purpose.** Inspect the full current registry
  index and search by each viewing need. Inspect selected mechanism source before
  choosing reuse/configuration/composition. Vary visual form, scale, placement and
  development while retaining a coherent motion language. Record why an effect
  helps comprehension or attention; a catalog count is not creative quality.

The independent prebuild critic must see actual assets and reject unexplained
repetition, missing important beats, context-free products, unreadable brand
holds and unspecified transitions. Final review watches entrances, movement,
holds and exits continuously, with a semantic pass across the whole programme.
Technical checks and still-frame approval do not satisfy that review. High
retention is the objective; no measured retention gain follows from these rules.
The shared implementation is `src/lib/producer/visual-storytelling.ts`, consumed
by automatic short/long authoring, plan review, rendered review and revision,
and by the supported native Director/guided proposal paths. Existing automated
review contracts route material issues to revision or block; they do not
automatically measure taste, understanding or retention. Native Director and
guided proposal stages retain their narrower supported scope and asset grammar.

For native agent-led assembly, record the exact candidate hash, review evidence,
each applicable criterion, unresolved issues and the independent verdict in the
existing task review notes. Review the complete retained message for coverage
and explanation, and use actual playback for transition/pacing conclusions.
Missing required evidence or a known material defect prevents a ready/complete
claim and final handoff; repair and review the changed candidate. Do not reuse
approval from a previous encode. This is an agent-owned completion requirement,
not an editorial gate implemented inside the native rendering CLI.

## DRY implementation boundary

Reuse the existing author/critic process runners, strict review result contract,
immutable evidence/authority bindings, bounded revision/no-progress rules and
stage timing. Adapt the planning controller's packet and gates for native
direction. The current controller is coupled to `edit_plan.json` and legacy
graphics gates; calling it unchanged would not validate a native scene plan.
Do not copy its graph-count floors, two-chassis grammar or local kind eligibility
into Shorts. Native construction uses the primary HyperFrames registry and
source-appropriate portrait composition.

The intended native execution boundary must consume the reviewed strategy and
scene plan, including explicit geometry/style decisions, and verify their current
hashes before materialization. An unsupported crop or asset is a capability gap
to implement or resolve, not permission to substitute contain or a label list.
Assembly must not generate a missing strategy, select a different layout, or
turn technical-test success into creative approval.

The native Short build boundary now uses
`src/lib/server/native-short-prebuild-review.ts`: direct, guided and writer
entry points require a separate current full-plan `ProducerReview` pass before
dependent assembly/preparation. The record includes seven coverage assessments,
pinned evidence and declared independent reviewer provenance. Its digest binds
all authored fields, excluding only the review reference and generated
`guidedBinding`/`preparedSources`; existing proposal and media validators still
check those generated transports. Changed assets, cues, crops or transitions
invalidate the pass. No provider call or automatic pass is created by this gate.

New projects preserve the review sidecar in their exact manifest. Historical
projects remain readable with explicit legacy/unreviewed status; reading one
does not supply a pass for a new build or new export. Reviewer identity is declared, not
cryptographically authenticated, and these records do not prove actual pixel
inspection or editorial quality. Independent source and final playback review
remain required.

New native long exports require a complete-project review through
`studio/native_long_prebuild.py`, reusing the same coverage, reviewer/evidence
and `ProducerReview` validation with scope `native-long-full-project`. Project
HTML, timing declarations and media bytes participate in that binding. See
[the long export contract](NATIVE_LONG_EXPORT.md#required-current-review).
This enforces the recorded pass at export; it does not implement a native
creative controller. Those edits still require the agent-owned prebuild and
current-candidate completion sequence above. The current V9 writer remains a
bounded development seam, not a complete creative director; do not resume the
rejected fixture as a creative candidate.

## This example's recovery

The [revised brief and shot plan](../../artifacts/native-short-development-2026-09-10/STRATEGY.md)
precedes the next build. The proposed treatment is a source-inspected portrait
presenter with captions over the footage. The exchange graphic is rejected for
this passage because it repeats the narration without demonstrating anything
the viewer needs to inspect. The first fresh critic rejected a crop that cut the
outward hand and an unspecified title position. Both were corrected in the plan;
a second fresh critic passed that exact revision for strategy only. Receipts are
saved beside the strategy. Actual continuous crop/font/preview checks remain;
this is not a delivered or quality-approved Short.
