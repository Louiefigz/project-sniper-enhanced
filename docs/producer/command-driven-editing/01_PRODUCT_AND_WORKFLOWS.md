# Product contract and workflows

> **Status:** Proposed target architecture, not a current capability claim.
>
> [Previous: current-system inventory](00_CURRENT_SYSTEM_INVENTORY.md) ·
> [Back to the plan index](../COMMAND_DRIVEN_EDITING_EXECUTION_PLAN.md) ·
> [Next: authority and command contracts](02_AUTHORITY_COMMANDS_AND_TIMING.md)

## Decision

Project Sniper becomes one command-driven editing system with two approval
policies:

1. **Cut-first (default):** create and review a cut-only draft, correct it,
   approve picture lock, then build captions, graphics, b-roll, music, and
   finishing.
2. **Autopilot:** use the same stages, artifacts, gates, renderer, and QC, but
   independent system reviewers grant the cut and treatment approvals.

These are not separate pipelines. Workflow changes who approves checkpoints,
not the quality or preservation contract.

The motion-graphics answer is:

- HyperFrames can render bespoke browser motion using CSS, SVG, canvas,
  seek-safe GSAP, masks, paths, particles, and 2D/2.5D animation.
- The current Ask Editor/Auto Edit plan can only select registered composition
  kinds and fill declared values.
- Governed project-scoped composition authoring now exists as the direct P4
  Codex/Claude Code → CLI lane: it builds, proves, caches, binds, revises, and
  exports one-off scenes without silently installing them globally. The
  missing layer is one-shot Ask Editor/Auto Edit orchestration through the
  complete project and final delivery.
- This is not universal After Effects parity. Tracking-intensive composites,
  rotoscoping, advanced 3D/plugins, and proprietary effects need a prepared
  asset, an approved approximation, or an honest `unsupported` result.

## User-visible workflow

```text
raw footage
  → immutable ingest + word transcript
  → cut-only draft
  → review on the selected surface (Sniper or Palmier)
  → word-safe corrections
  → picture lock
  → captions + motion scenes + b-roll + music + finish
  → incremental revisions with preservation proof
  → operator or system approval
  → one complete final render + full QC
  → approved master + optional editable Palmier build/exact mirror
```

Required examples:

- “At 45 seconds, put a blue card with fire on the left and a text card with
  sparkles on the right.”
- “Make this range karaoke captions, but leave the rest alone.”
- “You stepped on ‘automation’ the second time I said it. Extend it without
  moving anything else.”
- “Change only the right card copy.”
- “Use the pacing, caption grammar, camera motion, and graphic rhythm from this
  reference on my raw short.”
- “Take care of all the decisions” and “stop after the cut” use the same engine.

For each command, the receipt says:

- what Sniper understood;
- which exact revision, ranges, words, and elements it resolved;
- whether the change is local or requires a ripple/broad rebuild;
- what changed and what was proved unchanged;
- what rendered and, when selected, what changed in Palmier;
- which clauses were deferred, ambiguous, unsupported, conflicted, or not
  promoted.

No clause may silently disappear.

## Definition of complete

| Requirement | Release evidence |
|---|---|
| Cut-first | Cut-only candidate reaches the selected review surface before treatment; two clean hash-bound cut reviews pass, then the selected approval policy approves that exact cut |
| Autopilot | Same checkpoints and quality gates, with independent system approval |
| Granular instructions | A 20-clause request has one durable disposition per clause across stage batches |
| Word repair | Exact word/source handles, seam evidence, and unchanged-state proof |
| Custom motion | New project-scoped HyperFrames scene authored and rendered offline from one request |
| Local scene repair | Owning render unit only, with one bound Palmier replacement when selected |
| Karaoke | Enable, style, correct, or suppress selected transcript ranges |
| Reference mimic | Versioned style pack, supported-mechanics disclosure, unseen-target test, and matched-window QC |
| Short/long | Independent policies and release matrices on one engine |
| Palmier | Stable bindings at the finest proved granularity; rich scene internals may remain baked-regenerable |
| Preservation | Actual changes stay inside the authorized closure and every required invalidation is rebuilt or revalidated |
| Final quality | One complete final export receives deterministic, composition, editorial, and authority-bound QC |
| Performance | Frozen `LF-14-A` pilot and untouched confirmation pass before a bounded 90-minute claim |

“Only rerender the changed piece” applies to iteration. A normal H.264
publishing master still receives one complete final export after approval.

## Current truth versus target

| Area | Current foundation | Gap to close |
|---|---|---|
| Cut | Transcript-bound candidate/review plus a bounded exact-parent post-lock repair lifecycle | General layered, multi-lane, native-editor repair remains blocked |
| Authority | `edit_plan.json`, deterministic cut receipt, two-clean-review receipt, gates, immutable review/QC evidence | Natural-language edits still permit broad model rewrites |
| Timing | Exact rational frame/sample authority and stable anchors in released P1/P2/P3 lanes | Legacy/general operations still expose floating output-time seams |
| Graphics | Registered comps plus the governed P4 direct-CLI project-bundle lane and unit cache | `graphicsTrack`/one-shot autopilot cannot describe arbitrary motion paths or author the bundle itself |
| Presenter | Static presenter-hole takeover | Animated PIP and continuous subject tracking are not released |
| Incremental | Base/graphics/audio fingerprints, caption-free composite cache, and cue-local alpha shards | Several non-caption lanes are still too coarse |
| Captions | Released range-level `CaptionTrackV1`, stable-word corrections, SRT, semantic chapters, bounded alpha media, and regenerated Palmier bindings | Native Palmier-caption fidelity remains separately gated; exact delivery uses bound alpha clips |
| Reference | Deep study and reference-inspired guidance | Verified style-pack execution remains 0-of-7 qualified |
| Palmier | Exact one-clip mirror and candidate primitives | Editable cuts/captions/audio/ripple lack full live long-form proof |
| QC | Gates, Audit B, critics, isolated promotion | Dirty-window preservation is not generalized |
| Performance | Fresh 45-second and 839.964125-second current-render baselines plus bounded cached repairs | No complete accepted-request-to-approved-output `LF-14-A` cohort proves the 90-minute goal |

Graphic-over-b-roll layering is now a released legacy mechanism gate.
`test_graphics_broll_layering.py` pins `render.py` to b-roll-before-graphics,
then decodes a real alpha graphic over active opaque b-roll. Its visibility
oracle rejects both a missing graphic and the reversed order. This proves the
generic compositor order; it does not prove every authored comp or a complete
10–14-minute delivery.

## Independent product axes

| Axis | Values | Meaning |
|---|---|---|
| Workflow | `cut-first`, `autopilot` | Who approves checkpoints |
| Story form | `short`, `longform` | Editorial duration and pacing grammar |
| Canvas | `source`, `16:9`, `9:16`, `1:1`, supported custom | Raster geometry and reframe policy |
| Destination | One or more platform profiles | Safe zones, UI occlusion, codec/file/duration rules, covers |
| Finish | `trim`, `light`, `produced`, `full` | Which treatment lanes Sniper owns |
| Style | House, closed style, inspired, verified mimic, custom brief | Visual/editorial grammar |
| Delivery | Sniper, Palmier editable, exact mirror, both | Review/publication surfaces |

Finish levels:

| Finish | Required behavior |
|---|---|
| `trim` | Editorial cut, canvas conversion, dialogue normalization; no automatic title, captions, motion, b-roll, transitions, or music |
| `light` | Trim plus requested captions and subtle footage motion |
| `produced` | Full engagement stack using available approved assets |
| `full` | Produced plus project-scoped comp authoring and governed asset sourcing/generation |

`Full` stays unavailable until asset acquisition, licensing/consent,
provenance, approval, and generation gates pass.

## Short, long, canvas, and destination rules

| Policy | Short default | Long-form default |
|---|---|---|
| Canvas | 9:16 | 16:9 |
| Duration | Content-earned, commonly 15–90s | Content-earned; initial corpus 10–14m |
| Cut | Tight, hook-first, word-safe | Remove retakes/tighten pauses while preserving clean takes |
| Pacing | Higher change density unless style says otherwise | Front-loaded hook and sustainable body cadence |
| Reframe | Face-aware/manual shot framing where proved | Source-preserving unless a layout changes it |
| Captions | Burned karaoke/whisper often default | SRT/CC default; burned bursts opt-in |
| Graphics | Safe-zone-aware and overlay-led | Sparse purposeful scenes/cutaways |
| Extras | Cover/loop and platform geometry | Chapters and real thumbnail when released/requested |

Story form does not dictate canvas. A 16:9 short or vertical long is valid only
when the selected canvas and destination profile support it. Assets may be
reused across destinations only when the profile hash matches.

Release matrix:

| Lane | Required proof |
|---|---|
| Short | Post-graphics karaoke suppression, destination safe zones/UI occlusion, cover/loop regeneration, pacing and codec/file/duration gates |
| Long | SRT/CC and chapter parity, sustainable motion grammar, thumbnail deliverable, 10–14-minute endurance/final QC |
| Canvas/FPS | Reframe, type, masks, b-roll, scene geometry, and caption occupancy at each released pair |
| Multi-destination | Independent exports/profile hashes and no invalid cross-profile cache reuse |

## Workflow state machine

```text
INGESTED
  → CUT_DRAFT
  → CUT_REVIEW
  → PICTURE_LOCKED
  → TREATMENT_DRAFT
  → TREATMENT_REVIEW
  → READY_TO_FINALIZE
  → QC_APPROVED
```

Rules:

- Treatment stays empty until picture lock.
- Both approval policies require deterministic cut gates and two independent,
  hash-bound clean reviews. Operator approval does not waive them.
- Spoken-timing source/transcript changes invalidate cut approval.
- A valid non-ripple repair creates a
  `PictureLockSupersessionReceiptV1`: old lock → child lock plus exact
  unchanged mapping evidence.
- Deferred or compiled treatment bound to the old lock becomes `superseded` and
  must be recompiled/revalidated against the child; it is never silently reused.
- Previously committed treatment remains immutable history but receives
  child-lock successor revalidation, including graphics, captions, music,
  audio, and Palmier bindings.
- A ripple repair reopens picture lock and re-resolves dependents.
- Approved finals are immutable; later edits create child revisions.
- Opening Palmier is non-mutating.
- Palmier work is skipped when not selected.
- Manual Palmier drift becomes the working head and blocks automation. Current
  Sniper cannot reverse-import it or silently reclaim authority.

One request may contain cuts and treatment. The request ledger persists every
clause, compiles a cut batch first, and resolves deferred treatment against the
approved child timeline. Atomicity is stage-scoped, never falsely claimed
across two timelines and an approval checkpoint.
