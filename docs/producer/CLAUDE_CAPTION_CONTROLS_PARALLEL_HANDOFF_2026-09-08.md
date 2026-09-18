# Parallel caption-controls assignment for Claude Code

Prepared for Aaron after Claude delivered the audio package and its two separate
patches. Codex explicitly confirmed this assignment is useful and non-conflicting:
Claude owns caption implementation and focused tests in an isolated snapshot.
Aaron confirmed he handed this assignment to Claude. The main Codex agent has
since read the completed caption-controls handoff and reports the package
delivered, not yet live-integrated. The coordinator has not independently rerun
the package's checks. Keep the delivered package frozen; Codex owns shared-hunk
reconciliation and live integration. No live code changes are authorized through
this handoff.

Integration coordination: Codex reserves the caption package's V9 for selected
captions. The earlier proposed post-cut audio V9 must be reconciled into a later
version by Codex, without changing the frozen caption package independently.

## Deliverable and user benefit

Connect existing caption capabilities to the guided Producer workflow so a user
can select which speech ranges receive captions and choose an existing supported
caption style for those ranges. Deliver an actual rendered example, a scoped
revision, tested implementation and the necessary caller-integration patch.

Examples: “Caption this explanation, but leave the rest without captions” and
“Use line captions here and the existing karaoke treatment for this passage.”
This removes a documented capability gap while Codex integrates audio and the
remaining visual workflow. It is not a new caption renderer or visual system.

## Existing implementation and exact gap

- `scripts/producer/captions/caption_compile.py`, `caption_grouping.py`,
  `caption_operations.py` and `caption_plan_pipeline.py` already compile explicit
  word-anchored groups, default coverage, immutable styles and corrections.
- `scripts/producer/guided_caption_profile.py::caption_preset_plan` currently
  requires all-kept line/karaoke captions, an empty groups list and no custom
  style/correction/chapter authority.
- `src/lib/producer/contracts/guided-caption-profile.ts` enforces the same limited
  profile. `src/lib/server/guided-proposal-captions.ts` emits all-kept presets only.
- Therefore another generic grouping/style helper would duplicate existing work.
  The useful deliverable is a supported, validated path through the existing
  command/proposal, compilation, rendering and revision consumers.

Read the root and Python `CLAUDE.md`, `docs/PIPELINE.md`, the current completion
checklist and command workflow, and the caption section of
`docs/producer/command-driven-editing/03_CUTS_CAPTIONS_AND_AUDIO.md` before edits.
Trace actual current callers; historical documentation does not prove execution.

## Ownership and isolation

You are not alone in this repository. Preserve every other agent's work.
Do not modify the already frozen audio packages or their test baselines.

Work from an isolated, recorded snapshot of current uncommitted project sources,
including relevant untracked files and existing required local fonts/assets and
capability artifacts. A new worktree from live HEAD alone misses ongoing work.
Record the original baseline before edits. Reuse installed tools read-only; do
not install, upgrade, download or modify shared dependencies/caches. Keep native
fixtures serial and bounded, and coordinate any substantial render with Codex.

Confirmed Claude ownership: existing `scripts/producer/captions/` implementation
and focused caption tests in the isolated snapshot. Keep ALL shared caller changes,
including Python profile/adapter and TypeScript proposal/profile/command changes,
in a separate baseline-bound integration patch. Codex owns guided-media-profile,
opening-profile, media-input, body-authority and presenter-profile activation,
including new explicit audio-finishing profile tokens. Do not rewrite those
profiles in Claude's owned patch. Codex owns reconciliation and live activation.
Caption-specific handoff documentation belongs with the isolated deliverable.

Do not change presenter/graphics placement, source color, audio, HyperFrames
dependencies or catalog templates, the shared render graph, broad worker
lifecycle code, custom dashboard UI or production approvals. If a necessary
change crosses the boundary, report the exact file/interface and continue
independent caption work until its owner resolves the overlap.

## First package scope

1. Explicit selected word ranges with captioning off outside those ranges, or
   selected groups overriding an explicitly selected default policy. Reuse the
   existing stable source-word/occurrence identities and edited timeline mapping.
2. Existing supported line/karaoke styles per selected group. Preserve existing
   type validation, installed font identity, aspect geometry and text fitting.
3. Revise a chosen group's coverage or supported style through the existing
   revision mechanisms. Preserve unchanged cut/audio and valid unaffected caption
   assets; do not claim reuse without evidence from the actual caller.
4. Supply matching Python AND TypeScript integration changes and caller-shaped
   tests in the separate shared patch. State the minimal caller contract needed
   to admit selected caption groups/styles, compiled outputs and their original
   source/word/timing bindings. Coordinate with Codex's audio-finishing activation;
   do not independently rewrite profile tokens to combine features. A Python-only
   feature still rejected by TypeScript is not a complete live workflow.

Keep novel font/style families, arbitrary placement, automatic scene suppression,
new correction/split/merge semantics, chapter editing and multi-speaker heuristics
outside this first package. Do not silently strip such existing intent or resolve
it with a default; retain existing explicit rejection/unsupported behavior.

## Correctness and acceptance

- Preserve historical profile meaning. Use the existing extension/versioning
  mechanism for newly admitted behavior rather than relabeling old approvals.
- Requested caption words appear exactly once; words explicitly outside selected
  coverage stay absent. Missing, duplicate, non-kept or wrong-occurrence IDs reject.
  Selecting one repeated passage must not caption another matching-text passage.
- A removed middle source passage must not shift selected groups onto wrong words.
  Reuse the existing exact source/output frame and sample mapping.
- Use actual existing compiler/render outputs for 16:9 and 9:16 examples. Inspect
  the resulting frames for clipping, timing and complete text. Overflow must
  explicitly request a complete-copy repair or reject; never truncate requested
  words or silently suppress them to pass fitting. Use existing
  placement/screening owners without weakening their checks. If a combined
  presenter/graphics case needs an owner change, retain the blocker explicitly.
- A group/style revision must update the actual compiled/rendered result while
  preserving unrelated picture/audio. Check invalidation and actual reused work;
  equal output bytes alone do not prove a stage was skipped.
- Preserve deadlines, failure cleanup, original input ownership and accepted
  parent behavior. No new approval framework, synthetic human approval or paid
  fallback. Small synthetic media proves the tested mechanism, not creator-video
  acceptance or the full two-hour editing target.
- Run focused existing caption tests and meaningful regressions for these cases;
  preserve failures and distinguish inherited failures from changes you introduce.
  Do not run another full project suite concurrently with the integrator's run.

## Early report and final handoff

Write `/private/tmp/sniper-claude-caption-handoff.md` with the absolute workspace
path, original baseline manifest/hash, selected owned files, intended shared
interface/version changes and dependencies on Codex. If that report belongs to
another run, preserve it and report a unique replacement path.

At the first short checkpoint, demonstrate the existing compiler behavior and
identify the exact guided admission/caller changes. Proceed to one actual selected-
range render before expanding the supported combinations. Do not spend the task
on broad research, rewriting doctrine or duplicating an existing caption engine.

Deliver a frozen source manifest, owned patch, separate integration patch, exact
fresh tests/results, retained rendered examples, supported/unsupported cases and
remaining integration steps. Record original files and patch hashes so the
integrator can combine work without resetting the dirty live tree. Package
delivery is distinct from live guided-workflow acceptance.
