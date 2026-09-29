# Shared visual plan

`VISUAL-PLAN.json` is the route-neutral creative-direction artifact for a new
produced/full Short or long-form edit. The buyer's Codex or Claude agent remains
the creative director. This contract gives that judgment a complete, bounded and
reviewable record before it becomes an ordinary plan or a native project.

## Workflow

1. Lock the accepted program, transcript, stored intent, duration, frame rate and
   delivery aspect. Preserve disabled or operator-owned lanes.
2. Read the complete retained program and inspect available footage. Establish
   one project-wide direction: palette, typography roles, motion and transition
   families, density, breathing room and repetition budgets.
3. Create semantic opportunities only where a viewer benefits from visual help.
   Record the viewer question, explanatory job, transcript evidence, section
   role, timing and permitted modalities. A seam opportunity records both
   adjacent scenes.
4. Search the complete pinned catalog metadata for each distinct job. Inspect
   three to five finalists when that many credible choices exist. Include
   source footage, supplied B-roll, authorized external media, text, presenter,
   custom-native and omit/restraint candidates where applicable.
5. Record exact evidence, prerequisites, exclusions, expected visible result,
   review target and scores. Keep files outside the artifact; store IDs, paths
   and SHA-256 hashes. A missing preview or motion inspection stays explicit.
6. Validate and allocate the plan. Compile only the selected decisions into the
   route-specific project. Independent review still judges the authored project
   and rendered moving result.

After the accepted cut is saved as `producer/edit_plan.json`, materialize the
trusted whole-program context. This freezes every retained transcript word, the
source-footage and supplied-B-roll path/hash inventory, the complete 372-row
catalog and validated prior visual usage without calling a provider or reading
media bytes:

```bash
./sniper node --import tsx scripts/producer/visual-plan-context.ts /absolute/project/producer
```

Write one bounded semantic query per opportunity to
`/absolute/project/producer/VISUAL-SEARCH.json`, then search all frozen catalog
metadata:

```json
{"schemaVersion":1,"scope":"ordinary-visual-semantic-queries","queries":[{"opportunityId":"opp:proof","intents":["Show credible evidence and the concrete result"]}]}
```

```bash
./sniper python3 scripts/producer/planner/ordinary_visual_plan_search.py /absolute/project/producer/CATALOG-AUTHORITY.json /absolute/project/producer/VISUAL-PLAN-CONTEXT.json /absolute/project/producer/VISUAL-SEARCH.json /absolute/project/producer/VISUAL-SEARCH-RESULTS.json
```

The command searches every frozen row, always returns at most five ranked
results per opportunity and prints an exact `authority` pin. Narrowing filters
and smaller result limits are refused because they could hide alternatives.
Each query must reuse concrete language from that opportunity's retained speech,
viewer question, explanatory job or stated requirements; validation rejects an
unrelated narrow query that could manufacture an artificially small result set.

Author `VISUAL-PLAN.pending.json` by copying `project`, `catalogPin`,
`transcriptAuthority`, `mediaAuthority`, `relatedUsageAuthority` and
`relatedUsage` exactly from
the context, then copy the printed pin to `searchAuthority`. For each opportunity,
set `searchReview.searchDigest` to that authority digest and account for every
result marked `credible`, in rank order, as either a catalog candidate bound by
its exact record ID or a rejection with a concrete reason. Weak results do not
force filler. Fewer than three credible results, including none, may pass when
all of them are accounted for; no opportunity can hide a credible alternative.
The search result is retrieval evidence, not an allowlist or execution approval.
Validate the pending artifact:

```bash
./sniper python3 scripts/producer/planner/visual_plan_cli.py validate /absolute/VISUAL-PLAN.pending.json
```

Allocate directly when no catalog source-inspection or integration planning
prerequisites remain. Allocation never claims that catalog mirror HTML is
executable:

```bash
./sniper python3 scripts/producer/planner/visual_plan_cli.py allocate /absolute/VISUAL-PLAN.pending.json
```

When a catalog candidate lacks its required static source inspection, create a
private authority parent and run the installed issuer. It derives its own
installed pipeline identity and writes an already allocated output when every
opportunity retains an eligible choice:

```bash
mkdir -p /absolute/project/producer/.visual-plan-authority
./sniper python3 scripts/producer/planner/catalog_receipt_issuer_cli.py /absolute/VISUAL-PLAN.pending.json /absolute/VISUAL-PLAN.receipted.json /absolute/project/producer/.visual-plan-authority
```

Keep the `authority.path` printed by that command. Unresolved dependency
findings remain explicit adaptation work; they are not a failed browser probe.
If the output remains pending, inspect the allocation failure and candidate
set. Do not run `allocate` again on an already allocated issuer output. Save the
successful canonical output as `VISUAL-PLAN.json`, then pass the same
out-of-band authority to every later read:

```bash
./sniper python3 scripts/producer/planner/visual_plan_cli.py validate /absolute/VISUAL-PLAN.json --receipt-authority /absolute/CATALOG-RECEIPT-AUTHORITY.json
./sniper python3 scripts/producer/planner/visual_plan_cli.py fingerprints /absolute/VISUAL-PLAN.json --receipt-authority /absolute/CATALOG-RECEIPT-AUTHORITY.json
./sniper python3 scripts/producer/planner/visual_plan_cli.py binding /absolute/VISUAL-PLAN.json --receipt-authority /absolute/CATALOG-RECEIPT-AUTHORITY.json
```

For a plan allocated without catalog receipts, omit `--receipt-authority` from
the `fingerprints` and `binding` commands.

The context command freezes the installed registry's complete unified discovery
inventory. Its `catalogPin` includes the exact registry, raw index, lock,
resource sidecar, study and current capability identities. Validation re-derives
the same inventory from those trusted installed inputs; a plan-made version,
registry or partial shortlist cannot become catalog authority.

In isolated initial authoring, the controller captures the exact staged query
and result bytes before deleting the authoring directory. It writes the query to
a content-addressed file in the producer project, regenerates the result against
the durable catalog and context, and rewrites `searchAuthority` plus every
`searchReview.searchDigest` before allocation. Promotion fails on any staged
path, byte hash, query hash or result digest mismatch. The promoted plan never
depends on disposable authoring paths.

`allocate` prints canonical allocated JSON. Save that exact object as
`VISUAL-PLAN.json`, then run `fingerprints` against the saved file. The CLI does
not edit another artifact or execute media. `binding` prints the path, exact
file-byte hash and planning fingerprints to copy into a Native Short or Long
project contract.

## Selection behavior

Eligibility is a gate. The allocator combines validity, semantic fit,
readability, feasibility and coherence into deterministic 0.05 quality bands.
Inside one band, variation and recent-use evidence decide before a tiny quality
delta; crossing a band keeps a materially stronger candidate ahead of filler.
It evaluates the whole program with bounded beam search. Different component
IDs do not count as variety when anatomy and information development are
identical.

An identical development requires an explicit, evidence-bound repeat intent.
Callbacks bind an earlier selected opportunity and candidate. Signature,
callback and necessary-repeat declarations cannot bypass the project repetition
caps. A stable sourced visual is identified by modality, controller record ID
and immutable source hash, so renaming a candidate or composition cannot hide a
repeat. A sourced callback must bind that exact prior identity. Same-family
choices are reported as varied only when their anatomy or development differs.

Every opportunity receives a decision, including presenter or omit when visual
restraint is the best choice. Candidate alternatives and exclusion reasons stay
in the allocation for review.

Concurrent visuals require an explicit opportunity-level `layering` declaration:
`{"withOpportunityIds":["body"],"reason":"The title occupies a separate region above the persistent diagram."}`.
Name 1–8 unique, existing, non-self opportunities whose actual windows overlap.
Either side may declare the pair; same-start ordering does not change the result.
Only that pair's overlap is exempt from temporal breathing room. Every active
underlying visual remains checked, each selected layer still counts toward density
and repetition caps, and sequential gaps still require the configured breathing
frames. Keep the exact full windows in native mounts and execution bindings.
The declaration records editorial intent; independent preview review must still
verify legibility, non-occlusion and meaning. It is not layout or render approval.

## Route selection

- If every selected executable candidate is compatible with the ordinary
  measured adapters, allocate the entire project to `ordinary`.
- If any selected winner requires a project-owned native adaptation, allocate
  the entire project to `native-short` or `native-long` according to the project
  mode.
- A prerequisite or blocked candidate cannot be selected. Restore or qualify it,
  choose another supported candidate, or leave the planning stage unresolved.

The route is whole-project. Do not mix renderer authorities inside one edit.

Eligible source-footage, supplied-B-roll and external-media candidates must copy
the exact record ID, canonical path and source hash from `mediaAuthority`.
Before minting or accepting that authority, the controller reopens the bounded
source-set receipt and checks its content-addressed path/hash, entry count,
ordering, digest, lanes, canonical snapshot identities and per-file admission
receipt identities against the manifest. This metadata-only check never opens
media. Invented records, stale paths, stale hashes, forged manifest rows and
eligible external-media rows absent from the controller inventory fail closed.

`external-media/` is an explicit ingest lane for custom or previously acquired
media. Its sandbox admission receipt proves technical decode/isolation facts;
it does not prove copyright, consent or publication rights. An external
candidate still needs its separate bounded `authorization` evidence, and an
agent-authored manifest pin cannot create or broaden the controller inventory.
Canonical ingest accepts only a sibling, deeply validated `ASSET.json` and
`ASSET-ORIGIN.json`, then seals the exact origin pin inside the hashed source-set
entry before mirroring it to the manifest. Plain files remain prerequisites.
Public-web capture is a two-pass workflow: create the supervised capture inside
`external-media/<attempt>/`, preserve its origin bundle, re-ingest, rematerialize
the context, then re-plan. `needs-review` with editorial/local-review rights is
eligible for that local review edit and retains its disposition; it is not
publication clearance. Blocked, expired, incomplete, moved or tampered bundles
remain prerequisites or fail closed. Native Short and Native Long requests carry
and cold-read the same pins.

Catalog, text, custom-native, transition, presenter and omit keep their existing
admission rules.

## Catalog and evidence boundaries

The production mirror remains the admitted 372-row August 28 snapshot until a
new exact snapshot passes versioned admission. The documented September 16
399-item audit is not promoted because its exact generated snapshot is absent
from this checkout. `catalog-snapshots-v1.json` preserves current and historical
metadata roots by digest. `catalog-resource-index-v1.json` provides static,
unmeasured DOM, canvas, WebGL/GPU, video-texture, media-slot, dependency and
repeat-risk signals.

Static resource evidence never grants runtime, render or quality approval. The
catalog receipt issuer performs serial, bounded source inspection and records
missing or unsupported dependencies without pretending to execute the item.
The two missing-source records remain blocked. A source-present reference may
enter allocation after static inspection even when it reports unresolved
dependencies, because its project-owned adaptation can localize or replace
them.

`sourceInspectionEvidence` points to the required closed static receipt rather
than arbitrary evidence bytes. It binds the snapshot record and source, project
and opportunity, candidate composition, resource class, tool/runtime files and
observed dependency findings. `runtimeQualificationRequired` remains true when
the staged result needs runtime proof; a planning receipt cannot clear it. The
selected reference must use a distinct project-owned implementation and pass
native static preflight, browser compilation and seek capture, animated moving
previews, full-output QC and independent review.

## Memory and recovery

Catalog search and allocation are planning work. They read bounded metadata and
never materialize the entire source/preview corpus inside a render worker. The
visual plan contains no base64 media or copied source HTML.

Native preview, probe and render work retains adaptive capacity admission, the
single heavy-work lease, the low-memory environment, bounded telemetry retries,
verified descendant cleanup, immutable picture/package seals and exact-input
recovery. A changed visual plan invalidates dependent picture/capture work.
Unchanged compatible source and audio preparation remain reusable. A catalog
refresh does not invalidate a frozen project pin.

## Enforced compilation

New produced/full ordinary edits create and allocate `VISUAL-PLAN.json` beside
`edit_plan.json` before review. The post-authoring controller resolves the saved
file again, supplies its bounded content to the independent critic, and runs the
visual-plan execution gate. `edit_plan.json.visualPlanApplication` must cover
every allocated opportunity in allocation order and bind the selected candidate,
exact output window and actual graphic, transition or restraint decision. A
missing, stale, partial, substituted or timing-inconsistent application stops
the planning bundle before render.

New produced/full Native Shorts bind the plan in
`NativeShortProjectInput.visualPlan` and record the same complete mapping in
`strategy.visualPlanApplication`. The project writer checks the mapped scene
indexes, executable HTML IDs and staged catalog source/implementation hashes,
then freezes both artifacts in the project manifest. Existing cold-readable
projects without a visual plan retain their prior behavior.

New native Long projects use `LONG-PROJECT.json` schema version 2. They bind the
prepared request, the allocated plan and `visualPlanApplication`. The cold reader
and prebuild snapshot verify complete allocation coverage, exact scene overlap,
executable IDs, mounted project-owned catalog files and their hashes. Schema
version 1 projects remain readable for legacy and bounded revision work; adding a
visual plan to one requires its matching execution application.

Compilation preserves accepted cuts, current capability gates, catalog/source
hashes, review boundaries and renderer contracts. The application receipt proves
which plan decisions the route authored; moving previews and independent review
still judge whether the result works visually.

## Cross-project usage memory

After a Native Short or Long export reaches its final
`native-short-checked-for-review` or `native-long-checked-for-review` machine-QC
status, the successful exporter automatically registers the exact checked
allocation in its source producer project. It writes an immutable
`visual-usage-registration.json` beside `delivery.json`; that sidecar binds the
delivery hash and returned receipt identity without creating a hash cycle.

If the exporter reports a `visual-usage-registration` failure, preserve the
checked export and use this command only for recovery or historical backfill:

```bash
./sniper node --import tsx scripts/producer/visual-plan-usage.ts register /absolute/source-project/producer /absolute/native-project /absolute/checked-export
```

The automatic and recovery paths record machine-checked visual usage with
`humanApprovalClaim: false`; they do not replace playback review, the Studio
handoff or human approval. The next project's `visual-plan-context.ts` run reads
the newest eight current receipts for the same mode. It revalidates their small
JSON authorities without reading video or audio bytes. Discovery streams
receipt names with bounded memory, retains
at most 128 globally newest mode-compatible candidates across sibling projects,
and revalidates those candidates before selecting eight unique projects. Current
receipt names bind machine-check time, mode and receipt digest; digest-only
legacy names remain supported inside the same bounded compatibility window.
The selected uses feed the allocator's repetition penalties and budgets. Each use retains candidate
and composition labels plus `modality`, `sourceRecordId` and `sourceSha256`, so
renaming or rewording a candidate cannot hide reuse of the same catalog or media
source. Registered native receipts from the current producer participate in the
window; the current project's legacy web approval is excluded from self-history.
