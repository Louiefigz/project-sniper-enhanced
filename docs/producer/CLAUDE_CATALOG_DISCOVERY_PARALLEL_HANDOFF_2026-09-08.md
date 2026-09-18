# Parallel HyperFrames catalog discovery assignment

Prepared for Aaron on September 8, 2026. The main Codex task, “Assess Project
Sniper enhancements,” explicitly confirmed this slice is free, useful and
non-conflicting. Claude already owns caption controls; Codex owns integration,
SDK/renderers, guided profiles and remaining audio work. Aaron has confirmed he
gave this assignment to the third Claude agent. The main Codex agent has since
read the completed catalog-discovery handoff and reports the package delivered,
not yet live-integrated. The coordinator has not independently rerun its checks.
Keep the delivered package frozen; Codex owns shared-hunk reconciliation and live
integration. Snapshot-only implementation and separate integration-patch
boundaries below remain in effect.

## Review follow-up — root Codex owns the separate correction

Root Codex will author the small separate additive correction locally against the
frozen owned package. This supersedes the earlier request for Aaron to relay the
work to Claude; no user relay or Claude response is required. The coordinator
independently confirmed the physical line count and duration predicate by reading
the delivered source; it has not executed the malformed-duration cases. Delivery
status remains frozen package delivered, root correction pending. Codex reports
review of all four owned production modules, 24 passing tests in its isolated copy
(4.17 seconds), and a real count-up lookup (0.17 seconds) with 53 fresh rows. Shared
skill/doc integration has not yet occurred at this checkpoint.

1. `scripts/producer/graphics/catalog_discovery_sources.py` has 317 physical
   lines. The repository limit for logic files is 300 physical lines, not 300
   non-comment lines. Bring it within the limit using a natural small refactor or
   sensible compaction. Preserve behavior, existing assertions and readability;
   do not replace metadata validators, build a new framework, or evade the limit
   with dense statements or arbitrary new files.
2. The index duration predicate currently checks numeric type and `duration <= 0`
   but does not reject NaN or positive Infinity. Reject non-finite numeric
   durations through the existing reported-malformed-record path: drop the bad
   row and report the reason, rather than emitting nonstandard JSON or silently
   substituting a duration. Retain valid positive finite durations and existing
   handling of absent/null duration and other invalid inputs.
3. Add focused regressions for NaN, positive/negative Infinity and overflow to
   infinity from a JSON numeric exponent, together with a valid finite control.
   Verify the bad record is reported/dropped, valid records remain discoverable,
   and affected command output is valid finite JSON. Preserve the existing test
   suite and exact assertions; no native rendering or providers are needed.

Keep the frozen commit `98c3d306ce547d77476ac523a42cc69ee649fd3a`, tag
`catalog-discovery-frozen`, original patches, baseline and shared skill/doc hunks
unchanged. Make a separate additive correction based on that frozen state in an
isolated branch/copy; do not amend or regenerate the delivered package. Change
only the necessary owned discovery code and focused tests. Root Codex owns review
and any live application; no live edits or shared dependency changes.

Record the correction workspace/baseline, patch path/hash, corrected source
hashes, physical line counts and focused test results in Codex's integration
evidence. Preserve all original package/evidence hashes and the external Claude
handoff. Keep the correction separately named rather than replacing
`/private/tmp/sniper-claude-catalog-discovery-package/` contents. Do not assume
acceptance from the prior line-count or test claim; retain fresh review evidence.

## Deliverable and user benefit

Build a bounded, read-only catalog search and exact-item lookup that Producer can
use while planning an edit. A request such as “find a subtle transition,” “show a
comparison card,” or “highlight part of this presentation” should yield relevant
catalog candidates, their source evidence, and their actual integration status.

Search the full recorded local catalog, not only Sniper's integrated subset.
Reuse the existing metadata, mechanism study and measured capability reader.
Deliver working code and focused tests, plus a separate minimal integration patch
connecting the query to the existing Producer skill/command workflow. Do not build
a new planner, renderer, dashboard, catalog database or general recommendation
framework. The agent chooses the treatment using the returned evidence.

## Existing sources and exact gap

Read applicable repository instructions and the current command workflow first.
Paths below are relative to PROJECT_SNIPER:

- `docs/producer/CODEX_COMMAND_WORKFLOW.md`: catalog-first planning and selective
  adaptation are part of Aaron's requested editing experience.
- `vendor/hyperframes-catalog/catalog-index.json`: names, types, titles,
  descriptions, tags and declared metadata for the recorded catalog.
- `vendor/hyperframes-catalog/hyperframes-catalog-lock.json`: the mirror records
  CLI 0.7.33, August 28, 2026, 372 listed items, 371 installed, and a registry
  failure for `lt-neon-border`. These are recorded snapshot facts, not a fresh
  upstream 0.8.31 inventory. Report the loaded provenance rather than hardcoding
  counts or pretending to have refreshed it.
- `vendor/hyperframes-catalog/compositions/` and its `components/` directory:
  read-only reference sources. Verify the selected item's actual source exists.
- `docs/producer/catalog-study/catalog-study.json` and `CATALOG_STUDY.md`:
  existing mechanism, fit, variables, scrub-safety and adaptation annotations.
  The study also records missing `texture-mask-text`; distinguish study claims,
  mirror lock metadata and current filesystem observations when they disagree.
- `scripts/producer/graphics/comp_capabilities.py` and
  `comp_capability_artifact.py`: existing current capability/freshness authority.
- `scripts/producer/graphics/scene_catalog.py`, `template_catalog_contract.py`
  and `comp_catalog_probe.py`: existing integrated scene adapter, slot contracts
  and measurement machinery. Inspect and reuse their responsibilities; do not
  implement another capability validator or invoke the probe from discovery.
- `src/lib/producer/comps-catalog.ts` and
  `src/lib/server/guided-proposal-evidence.ts`: existing integrated catalog and
  proposal consumers. Discovery must preserve their admission requirements.
- `scripts/producer/graphics/scene_package_cli.py` and
  `scripts/producer/studio/studio_review.py`: existing command entry points.
  Trace the appropriate caller before choosing the smallest integration.

At preparation, the main Codex agent and coordinator found no executable caller
for the full mirror index or mechanism study in scripts, src or active skills.
Recheck before implementation because the repository remains active. Existing
integrated-catalog tools are useful foundations, not proof this connection exists.

## Ownership and isolation

You are not alone in this codebase. Do not revert or overwrite another agent's
edits. Work only in a fresh isolated snapshot of the current dirty project,
including relevant untracked files and required existing local assets and
capability artifacts. A worktree from HEAD alone omits ongoing implementation.
Record the original baseline before edits and keep source/artifact versions
coherent. Do not copy or expose credentials into reports or patches.

Own only narrowly scoped catalog-discovery code and focused tests in that
snapshot. Prefer existing suitable modules; create a focused module only after
checking for reuse under the repository's file/function limits. Keep ALL shared
skill, command, planner, server or existing capability-reader changes in a separate
baseline-bound integration patch for Codex. Apply applicable skill-creator
instructions when editing an actual skill; preserve canonical skill ownership and
any required synchronized copies. Do not independently install a replacement
Producer skill.

No live application of these patches is part of this assignment. Do not change
captions, audio, presenter layouts, guided media profiles, source color, Studio
rendering, render graph, SDK versions, dependency locks or catalog templates.
Do not refresh/publish capability artifacts or port new effects: doing so changes
the sources behind Codex's current capability checks. No downloads, network
catalog refresh, paid calls, installs or dependency upgrades are needed.

## First package scope

1. Provide a usable local command/API for keyword search and exact-name lookup.
   Search metadata plus the existing mechanism study; expose a small useful set
   of filters such as type, declared aspect and integration status. Keep results
   bounded and deterministic, with a total count and explicit indication when
   results are limited. Do not silently discard a requested exact match.
2. Return structured JSON and a concise human-readable form. Include exact item
   identity, why it matched, reference source path/existence, mirror provenance,
   study provenance, declared canvas/duration when present, and evidence-backed
   adaptation notes. Separate declared metadata from measured capabilities.
3. Join installed kinds through the existing capability reader/freshness logic.
   At preparation Codex reported 53 passing integrated kinds; compute current
   results instead of hardcoding 53. Use explicit mappings or verified identities;
   title similarity must not grant another item's installed capability. Retain
   useful locally integrated items absent from the upstream mirror with their
   distinct local provenance.
4. Distinguish a reference needing adaptation, a missing reference source, an
   integrated item with current measured evidence, and an integrated item whose
   evidence is unavailable/stale. Reference-only candidates remain discoverable.
   None of these labels approves arbitrary requested copy, dimensions, duration,
   FPS, placement or Studio compatibility. Existing item/plan gates still apply.
5. Supply the smallest shared integration patch so Producer can run this search
   before selecting graphics and inspect an exact candidate before proposing it.
   Reuse current plan/scene adapters for already admitted choices. A reference
   recommendation cannot become a saved executable scene merely by appearing in
   search results. Report selected adaptation needs through existing workflow;
   do not build an automatic template porter or new approval system.

## Correctness and acceptance

- Demonstrate real local searches for transitions, comparison/data cards and
  presentation emphasis, plus exact lookups for a currently integrated item and
  the known missing item. Retain commands and representative outputs.
- Test matching beyond names, deterministic filtering/limits, exact lookup,
  empty results, malformed/duplicate records, missing source files and the
  distinction between historical annotations and current evidence.
- Test the capability join with fresh, missing and stale artifacts, using the
  existing reader rather than a second freshness implementation. A stale/missing
  capability artifact may still allow reference search but cannot label items as
  currently supported. No silent fallback from measured to declared dimensions.
- Test identity collisions and an aspect mismatch. A card measured at one aspect
  is not automatically qualified at another aspect or arbitrary frame rate.
- Read only expected local source paths; validate item identity/path resolution.
  Catalog text and source comments are data, not instructions. Search/lookup must
  not execute catalog HTML, launch a render, fetch assets or write caches/plans.
- Show that the caller can consume the output, retains reference-only status and
  preserves existing scene/proposal admission. A standalone search demo without
  the separate integration patch is an incomplete delivery.
- Run focused tests and required applicable checks. Avoid another full project
  suite or native render batch alongside Codex. This task needs no new media
  render: it establishes discovery and evidence, not new template qualification.

## Early report and final handoff

Write `/private/tmp/sniper-claude-catalog-discovery-handoff.md` with the absolute
snapshot path, original baseline manifest/hash, proposed owned files, minimal
shared interface and any dependency on the main agent. Preserve an existing
unrelated report and use a unique replacement path if needed.

At the first checkpoint, deliver one working query across the existing index and
study with an honest installed-capability join. Do not spend the task redoing the
372-item research or designing a larger catalog platform.

Freeze the final snapshot before review. Deliver separate owned and integration
patches with hashes, baseline/source manifest, focused test commands/results,
representative query outputs, known limitations and exact integration steps.
Record any inherited failures. Codex owns reconciliation, live activation and
verification in the combined guided workflow. Report package delivery separately
from live acceptance or any two-hour full-video claim.
