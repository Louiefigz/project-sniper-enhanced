# Correct logos do not establish visual storytelling

The organic-media review showed the intended brand identities, but that did not
answer the larger creative question: did the Short develop an example and pay
off its promise? A correct logo can identify a product. A real article scroll can
show relevant context. Neither establishes that the product performed the
operation discussed in the narration.

The existing native strategy already records scenes with before/action/result
descriptions, speech-bound asset decisions and pacing holds. The missing
connection was an explicit whole-story obligation tied to those executable
choices. Adding another unbound paragraph would allow a plan to say "demonstrate"
while the composition still showed only a logo.

## Bind the obligation to the existing plan

The optional version-1 `strategy.story` contract uses the current version-3 native
strategy. It records a viewer question, the selected payoff, one stable subject
or example identity, and one ordered story row for every existing pacing beat.
Each row references its containing scene and classifies its work as setup,
development or payoff. The referenced pacing beat supplies the actual retained
speech; there is no second transcript or timing system.

Each visual job points to an actual target, its existing asset decision when
needed, and an existing readable hold. The closed job kinds distinguish:

- `presenter-performance`: the retained primary source view; no artificial
  reading hold is required for ordinary performance.
- `explanatory-comparison`: a real authored graphic or selected media comparison;
  the opening title card cannot stand in for it.
- `real-artifact`: selected real media showing a source or example, including
  contextual page footage. A logo or `no-insert` fails this obligation.
- `real-operation`: a `demonstrate` decision selecting video/web recording, with
  authored action and result frames and enough time to read the result.

For example, the following is a job fragment, not a complete valid project:

```ts
{
  kind: "real-artifact",
  targetId: "workflow-page",
  assetDecisionId: "show-official-workflow-context",
  holdIndex: 3,
}
```

The target must cover its whole pacing beat and appear in the containing scene.
Decision `show-official-workflow-context` must select that target and overlap the
retained speech. Hold 3 must reference the same target and fit inside the beat.
Shared validators still check source origin, policy, executable media timing,
essential regions and the declared minimum hold. Story checks add relationships
between existing records instead of duplicating media admission.

After editorial planning, `nativeStoryRevisionHash(input)` binds the story to
the current source/visual revision, asset-use decisions, pacing, selected payoff
and authored checkpoints. A change to any of those dependencies makes the
previous story binding stale. Reconsider the changed choices before updating the
hash; a fresh hash is not an editorial review.

## Check result duration after the result appears

An operation needs more than two increasing frame numbers. Its result checkpoint
must leave at least `minimumFrames` before the readable hold ends. One synthetic
test uses a 25 fps timeline with a hold ending at frame 20 and a minimum of
5 frames. Placing the result at frame 19 leaves just 1 frame (0.04 seconds),
although the overall hold is longer. The check rejects it because the declared
result needs 5 frames (0.20 seconds) after it appears. These numbers test the
relationship; they are not recommended viewing budgets for real Shorts.

The focused suite passed **45 tests: 14 new story tests and 31 existing native
project, pacing and asset-use tests**. It covers presenter/comparison/artifact
bindings, operation checkpoints, logo/no-insert substitutions, missing decisions,
stale speech/scenes/beats/holds, changed continuity/payoff, absent targets,
fabricated review fields, report tampering and migration compatibility. The
actual local writer, cold reader and CLI check ran on synthetic fixtures. Full
TypeScript checking and targeted ESLint also passed. No provider call, browser
capture, audio listening or real-video quality claim is part of that evidence.

## Keep the review boundary explicit

Use `real-artifact` when a source page, article or README supplies context. Do
not use `real-operation` for a homepage scroll merely because something moved.
A recording of the relevant operation and its actual resulting state is needed
before authoring those checkpoints. The structural check can validate their
binding and timing; it cannot verify that the descriptions are true or that the
operation caused a claimed outcome.

Do not force extra graphics into a presenter-led story that communicates through
performance, or treat every spoken brand as a mandatory cutaway. Conversely,
correct logos and valid media files cannot substitute for a promised example.
Choose the visual job from what the viewer needs to understand, then inspect the
actual source and complete encoded Short with sound.

The story record remains optional for migration. Older version 1, 2 and 3
projects without it reopen with unchanged required files and report `unplanned`.
Newly authored story records produce a hash-bound `STORY-REPORT.json`, recomputed
on reopening. Its structural success leaves source truth, narrative quality and
finished playback review explicitly unresolved. This is traceability for an
authored plan, not an automatic storytelling score or publication approval.

See [the native Shorts workflow](../producer/NATIVE_SHORTS_WORKFLOW.md#bind-the-authored-story-to-executable-visuals)
and [the implementation](../../src/lib/server/native-short-story.ts).
