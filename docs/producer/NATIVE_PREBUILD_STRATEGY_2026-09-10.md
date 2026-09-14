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
N26-B05 demonstrates a full-screen taxi analogy; transferring its persistent
container does not justify a presenter-plus-message split.

## Shared planning sequence

Use the existing BRIEF and STORYBOARD as the working documents. Do not generate
them retrospectively from HTML or add a new human permission round in an
autonomous edit. The directing agent is the creative brain; another model call
without this responsibility and evidence would not solve the failure.

| Stage | Required decision/evidence | Completion condition |
| --- | --- | --- |
| Brief | Viewer, problem, source-supported takeaway, actual opening and payoff, output, requested lanes, preserved decisions | An editor can explain why this clip should exist without naming a template |
| Strategy | Read the complete retained speech and inspect the actual footage; compare relevant reference images and at least one alternative; select edit intensity separately from layout | Chosen treatment serves this message and its source, with rejected alternatives explained |
| Shot plan | Per beat: exact cue, attention target, what changes or deliberately holds, layout, crop/subject clearance, caption/title jobs and lifetimes, transition reason and exit condition | No creative choice remains hidden in a renderer default |
| Feasibility | Actual local media, inspected registry source/configuration where needed, fonts, supported geometry and timing, unresolved dependencies | The chosen scene can execute without replacing it with an easier template |
| Independent critique | A fresh critic sees the complete plan, actual source/reference images, exact speech and feasibility findings | Material issues are resolved against the current plan before assembly; no self-issued approval |
| Representative preview | Check the selected composition at phone size and through its meaningful changes | Actual output matches the plan before scaling; final audiovisual QA still follows |

For split screen, name what each pane teaches, why simultaneous viewing is
useful, each subject/detail's required size, and the condition that ends the
split. A second pane that paraphrases captions is not sufficient. For a
presenter hold, identify why expression or explanation carries the passage and
keep the person prominent. Neither split nor full presenter is a universal rule.

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

This document and the Producer instruction update establish the immediate agent
workflow. The native controller adapter and executable review boundary remain
implementation work; documentation is not proof that they are wired. The
current V9 writer remains a technical development seam, not a finished Shorts
director. Do not resume the rejected fixture as a creative candidate.

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
