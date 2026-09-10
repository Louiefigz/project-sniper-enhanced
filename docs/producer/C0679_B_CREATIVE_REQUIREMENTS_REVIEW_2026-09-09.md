# C0679 B creative requirements review

## Subsequent operator feedback

Aaron reviewed B and requested a full-frame presenter opening shot, plus
substantially more visual variety throughout the video. He explicitly clarified
that the opening shot need not remain full frame for 15 seconds or throughout
the hook; the editor should choose composition changes from the story. He preferred the
first successful run's range of information formats and presenter placements.
Different text inside the same recurring sheet does not meet this brief.
The full revision requirements are in the [latest native direction](C0679_NATIVE_HYPERFRAMES_DIRECTION_2026-09-09.md#latest-review-full-frame-opening-and-whole-video-visual-variety)
and the canonical Producer skill's **Visual storytelling** section.

The three repairs below are initial ingredients, not the complete revision.
Production owns the separate new creative batch and must open its next ready
review visibly in Chrome. This feedback does not change the sealed B file/QC
evidence or establish approval of the revised visuals.

## Scope and result

This is a source review of sealed B and two existing Studio stills, using the
episode-package-review checkpoint. It is not a new render, whole-video visual
review, audible listening, or user approval. No source, working project or
archive was changed. Production owns the separate revision/export work.

The archive is `artifacts/c0679-fresh-native-b-2026-09-09/`, with manifest SHA
`d83b8ff08a1175679a6fdfa60b64203643f54c0e32771f9fc152ce9b667357db`.
This review verified 62 selected source/still files against that manifest,
including all 53 authored child HTML files. The provisional title, Four Cs,
builder narrative and promise-to-example mapping remain as recorded in the
archived `EPISODE_PACKAGE_REVIEW.md`; publication title, thumbnail and resource
availability remain separate and unapproved. No new script or speech is proposed.

The source supports progress on the brief, but not full creative completion:

| Requirement | Evidence | Judgment |
|---|---|---|
| Presenter stays part of the explanation | Persistent presenter video; 15 full, 27 split and 11 bubble scenes; sampled panels 35/42 show a clear face | Present in source and selected stills; whole-video face visibility remains separate |
| Padded, rounded presenter | Root geometry and both inspected stills have visible margins and rounded/circular crops | Established for inspected poses |
| Presenter on both sides | `build_native_project.py` defines only full, right split and lower-right bubble poses | Left-presenter variant missing |
| Varied graphic formats | 12 content types, but every child has identical shared CSS and the same outer sheet anatomy | Content diversity exceeds presentation diversity; strengthen the most useful contrasts |
| Meaningful motion | Authored presenter pose transitions, item reveal times, and two sheet entrance recipes | Motion exists; source review does not prove every movement works or earns its place |
| Quantities explained visually | Numeric ranges and quantities appear as ordinary item text | A quantity-specific treatment would improve the package-building lesson |
| HyperFrames catalog first | Generator describes catalog-adapted slam/reveal; asset copier references catalog fonts and GSAP | Named transition/component selection and lineage are not established by these files; do not claim verified catalog-first coverage |

The two inspected stills are `animated-stock-v6-frames/panel-35.png` and
`panel-42.png`. They show readable text and unobstructed faces in those states.
They also show the repeated notebook shell. This is not a retention score or a
claim that all 53 scenes look identical. Their timed reveals are deliberately
staggered; no claim of long motionless video is made from settled screenshots.

## Three focused repairs for the next creative batch

### 1. Make topic versus pain a visual comparison, with Aaron on the left

**Scene:** panel-30, output **247.205292–266.933333s**, source
**301.96–321.69s**. Source transcript:

> Our workflow is scattered across five tools.

The following passage names Notion, Drive, Slack, Frame.io and the scheduler,
contrasts moving a client video with editing it, then mentions the wrong cut.
Use the original audio for that sentence; the ASR's final verb is uncertain.
Current concise on-screen copy is “Our workflow is scattered.” versus
“We move one video through five tools—and still send the wrong cut.”

**Catalog source:**
`vendor/hyperframes-catalog/compositions/components/comparison-split.html`.
Its documented mechanism is a before/after wipe with a persistent divider,
`split`, `orientation`, `labelA` and `labelB` variables. Adapt that comparison
mechanism to the existing two statements. Begin with the vague topic, reveal
the specific pain on its spoken cue, then hold both readable. Preserve the
distinction between an illustrative statement and a demonstrated app result.

**Left-presenter placement:** keep the source video orientation unchanged.
For the existing 1920×1080 wrapper with scale 0.8 and 480px side crops,
`x=-288, y=110` yields a visible presenter rectangle **x=96–864, y=110–974**.
Place the comparison graphic **x=974–1824, y=92–976**. This leaves a 110px gap,
96px outer horizontal margins, and rounded geometry. These are calculated
proposed bounds, not visually tested bounds. Verify the moving face/hands and
both transition endpoints before acceptance; do not mirror the recorded studio.

### 2. Turn the quality gate into four quick annotations over the presenter

**Scene:** panel-46, output **557.723833–582.915667s**, source
**630.68–655.85s**. Actual transcript questions are:

- “does this serve the right client?” (641.50–645.80s source)
- “Does it plant the right flag?” (645.80–647.52s)
- “Does it match our current goal?” (647.52–650.08s)
- “can we execute this in a month?” (within 650.08–655.88s)

**Catalog source:**
`vendor/hyperframes-catalog/compositions/components/marker-checklist-card.html`.
Use its drawn-marker/checklist reveal language as four concise criterion
annotations alongside a larger presenter. Remove the large opaque notebook
sheet for this beat. Highlight each criterion as it is discussed; no fabricated
angle score or claim that an unseen example passed. The catalog original has
three rows: a four-row adaptation is required, and the fourth criterion must
not be dropped to fit a template. Retain the current spoken-question cadence
and leave a short readable hold, rather than adding continuous decoration.

### 3. Show how one pain becomes a content package, preserving the ranges

**Scene:** panel-48, output **590.006083–610.651708s**, source
**662.96–683.59s**. The source says:

> one flagship long form video three to five shorts and clips, and maybe even
> two to three written posts.

**Catalog source:**
`vendor/hyperframes-catalog/compositions/components/number-pop-in.html`.
This primitive accepts string `value` and `unit` fields and reveals characters
with a deterministic GSAP recipe. Use exact strings **1**, **3–5**, **2–3**
with the existing content-type labels. Connect them to one shared pain/input,
revealing the branches as the narrator names them. Keep Aaron in an inset
alongside the diagram. The quantity animation explains the package structure;
it is not an arbitrary counting effect. Preserve “maybe” for written posts.
Do not convert a range into a count-up ending at its maximum or imply those
assets have already been generated. Existing reveal cues 2s/5s/8s are starting
points only; actual narration must confirm final timing.

## Implementation and verification boundary

These are concrete catalog choices for adaptation, not already-qualified
renderable Sniper templates. The local mirror's lock records registry provenance,
372 listed items, 371 installed items, and a 0.7.33-era mirror; the runtime tested
in B is 0.8.31. Keep sources local and pin the chosen files. Localize any CDN
dependencies, preserve native paused timelines and independent composition IDs,
and run the applicable contract, lint and seek/export checks. Do not substitute
the old portrait/white-card port merely because it has the same component name.

Inspected catalog file SHA-256 values:

- `comparison-split.html`: `2637b4dd260eb9ef272fad2f3b3921fe8f282cb498b8de112ec6faa76d5ef3b8`
- `marker-checklist-card.html`: `c99d951e0f361447109f50b5301cbbd8bcfed621cd7a66d92d9c5a65ec1614f0`
- `number-pop-in.html`: `25bb2a0a3e2dc9a067cfb016d7d8a971b70774652a0a4dca200c9173a1fc4e48`

Batch these approved-scope creative repairs in a separate working revision.
Inspect the affected states and transitions, then export the complete revised
master through the owned resource guard and existing delivery/audio checks.
Count all work and failures. Neither these proposed repairs nor a four-second
child export qualify the complete revised delivery. B's first benchmark stays
sealed with its failed playback and missed deadline.
