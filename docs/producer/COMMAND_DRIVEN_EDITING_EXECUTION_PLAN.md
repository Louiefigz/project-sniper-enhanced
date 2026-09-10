# Project Sniper command-driven editing plan

> **Status: target implementation plan with complete defined P0, P1, bounded
> P2, P3, and P4 exits; P5 is at 6 PASS / 5 BLOCKED; P5 hybrid delivery,
> P6 verified mimic, P7/P8 qualification, and the complete product remain
> blocked**
>
> **Date:** 2026-07-30
>
> [`../PIPELINE.md`](../PIPELINE.md) remains the authority for what is wired
> today. These chapters describe the target architecture and stop-gated rollout.

The original 2,000-line plan is now split into focused chapters. Start with the
audited current-system inventory, read the product decision, then jump to the
area you are working on.

## Reading order

0. [Current-system inventory and extension map](command-driven-editing/00_CURRENT_SYSTEM_INVENTORY.md)
   Existing authorities, cut/refit/speed/cache/capability/headless primitives,
   baseline telemetry, and the reuse/extend/replace decision.

1. [Product contract and workflows](command-driven-editing/01_PRODUCT_AND_WORKFLOWS.md)
   What the product promises, cut-first versus autopilot, current gaps,
   short/long/canvas/destination policy, and the workflow state machine.

2. [Authority, commands, and timing](command-driven-editing/02_AUTHORITY_COMMANDS_AND_TIMING.md)
   Immutable revisions, typed stage batches, clause states, stable IDs,
   projection receipts, Palmier commit saga, and timing anchors.

3. [Cut repair, captions, and audio](command-driven-editing/03_CUTS_CAPTIONS_AND_AUDIO.md)
   Non-ripple word repair, L/J cuts, alignment evidence, range karaoke,
   caption-shard migration, and audio/mastering behavior.

4. [Motion scenes, assets, and reference styles](command-driven-editing/04_MOTION_ASSETS_AND_REFERENCES.md)
   Project-scoped HyperFrames, render units, fire/sparkles example, asset
   governance, creative/delight proposals, tracking boundaries, and verified
   style mimicry.

5. [Render graph, Palmier delivery, and QC](command-driven-editing/05_RENDER_PALMIER_AND_QC.md)
   Content-addressed invalidation, dirty-window rendering, hybrid editable
   delivery, exact master, full readback, and preservation proofs.

6. [Edge-case and recovery matrix](command-driven-editing/06_EDGE_CASES.md)
   Fail-closed behavior for commands, cuts, captions, motion, references,
   audio, rendering, durability, Palmier, assets, and destinations.

7. [Stop-gated implementation roadmap](command-driven-editing/07_IMPLEMENTATION_ROADMAP.md)
   P0 through P8, deliverables, exit gates, phase demos, pilot, and untouched
   confirmation.

8. [Performance qualification and testing](command-driven-editing/08_PERFORMANCE_AND_TESTING.md)
   The bounded `LF-14-A` workload, 90-minute hypothesis, incremental targets,
   golden scenarios, fault injection, and measurement rules.

9. [Implementation map and immediate next steps](command-driven-editing/09_IMPLEMENTATION_MAP_AND_NEXT_STEPS.md)
   Proposed module boundaries, the implemented P0–P4 bounded checkpoints, and
   remaining cross-phase work.

10. [Legacy regression gates and traceability](command-driven-editing/10_LEGACY_REGRESSION_GATES.md)
    Existing geometry, contrast, capability, duration, audio, refit, caption,
    and authority lessons that the new architecture must preserve.

11. [P0 exit audit](command-driven-editing/11_P0_EXIT_AUDIT.md)
    Exact passing evidence for all 15 defined P0 roadmap exits and the retained
    parity-refresh procedure.

12. [Short-form versus long-form executable matrix](command-driven-editing/12_SHORT_LONG_EXECUTABLE_MATRIX.md)
    Generated workflow and complete production-route dispositions for both
    story forms, including incremental-render and Palmier boundaries.

13. [P3 exit audit](command-driven-editing/13_P3_EXIT_AUDIT.md)
    Bounded first-class caption and karaoke evidence plus explicit native and
    creator-project limits.

14. [P4 exit audit](command-driven-editing/14_P4_EXIT_AUDIT.md)
    Governed custom HyperFrames motion/assets, local repair evidence, and
    unsupported tracking/style-mimic boundaries.

15. [P1 exit audit](command-driven-editing/15_P1_EXIT_AUDIT.md)
    Exact 13-of-13 compatibility authority, anchor, graph, durability, and
    production-saga protocol evidence plus the open live Palmier gate.

16. [P2 exit audit](command-driven-editing/16_P2_EXIT_AUDIT.md)
    Exact 12-of-12 bounded picture-lock and non-ripple speech-repair result,
    including the 24-cell media cohort, governed alternate selection,
    controlled visual A/V evidence, and surgical-picture limits.

17. [P5 exit audit](command-driven-editing/17_P5_EXIT_AUDIT.md)
    Exact 6-of-11 optimized-render/hybrid-delivery result, including the
    14-minute one-unit repair, one-pass compositor, and fault cohort, plus the
    five remaining connected Palmier blockers.

18. [P6 exit audit](command-driven-editing/18_P6_EXIT_AUDIT.md)
    Exact 0-of-7 verified-mimic verdict, the released reference-inspired
    boundary, offline V1 preparation machinery, and the required real-evidence
    closure sequence.

19. [P7/P8 qualification audit](command-driven-editing/19_P7_P8_QUALIFICATION_AUDIT.md)
    Exact six-project, pilot-protocol, go/no-go, and untouched-confirmation
    dispositions without promoting the LF-14 renderer baseline into an SLA.

## Bottom line

- HyperFrames plus the P4 direct agent/CLI lane can author governed
  project-scoped browser motion. The closed `graphicsTrack` vocabulary and
  one-shot autopilot still cannot express or integrate arbitrary keyframes,
  paths, and easing by themselves.
- Extend the current cut/refit/render/durability seams behind adapters; do not
  build a competing authority.
- Build one typed revision engine with cut-first and autopilot approval
  policies, using both current cut authorities during migration.
- Persist mixed one-shot requests across cut and treatment stages; never drop
  a clause.
- Make captions, scenes, audio, and base segments separate dependency-graph
  nodes so eligible edits rerender locally.
- Deliver a governed Palmier hybrid plus exact master; do not claim native
  parity where it is unproved.
- Treat the legacy reference strategy ID `mimic` as reference-inspired
  guidance until all seven P6 qualification exits have retained evidence.
- Treat the 90-minute long-form goal as a bounded, confirmatory performance
  gate—not a current promise.
- The passing P0, P1, bounded P2, P3, and P4 scopes now have
  correctness cleanup, measured
  offline comp capability, an intent-bound compatibility picture lock,
  lease-serialized expected-parent promotion/recovery, transactional sidecar
  rollback, one typed graphics-text operation, content-addressed revision
  shadow authority, durable request/idempotency recovery, a minimum render DAG
  with forced-full oracle, a closed current render-effect registry, a retained
  final-tree short/LF-14 dirty-versus-forced-full replay, strict timing-anchor
  re-resolution, and a durable Palmier saga used by governed production native
  candidate promotion.
  P2 additionally has a retained all-rate early/middle/late repair cohort,
  controller-derived alternate-take authority, controlled caller-ROI A/V
  temporal mapping, and an exact-parent surgical picture path. That picture
  path rejects pre-rendered captions/graphics/b-roll/title cards/transitions,
  reframe/punch-ins, music, gain/enhancement, and other unsupported lanes; it
  is not universal layered repair or native/connected Palmier editability.
  Continue canonical-reader migration and connected Palmier/P5–P8
  qualification before any complete-product or performance claim. External
  ingress and the retained adversarial sandbox corpus are now passing P0
  evidence; Palmier live-build ingress and descriptor-to-subprocess host
  intervals remain explicitly limited.
