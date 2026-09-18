# Map a requested reference shot to reusable components

## When to use this

Use this workflow when the operator explicitly targets a particular reference
shot or style, for either a Short or a long-form project. Consulting the visual
library for inspiration or choosing a treatment automatically does not activate
reference matching. Keep ordinary catalog-first authoring available without a map.

The editing agent first inspects the reference and writes the detailed shot
plan: source/time/frame evidence, what appears and changes, spoken cue, layout,
motion, readable hold and exit. Keep observed behavior separate from the inferred
reason it works. The mapper searches the existing shared catalog; it does not
watch videos, infer editorial intent or automatically author that shot plan.

## Choose the smallest implementation that meets the target

| Route | Use when | Record |
| --- | --- | --- |
| `reuse` | One inspected component already supplies the behavior | Exact component and role; no changes |
| `configure` | One component needs supported timing, type, color or layout changes | Specific changes |
| `compose` | Existing components together supply the target behavior | At least two inspected pieces and their jobs |
| `custom` | Inspected candidates have a concrete capability or visual-quality gap | Closest alternatives, unmet behavior, bounded custom scope and retained pieces |
| `blocked` | Required source, asset or execution support is missing/unverified | Concrete prerequisites |

A custom addition can retain the same component whose missing feature it fills.
For example, keep a working comparison-card layout and add only the unsupported
per-digit reveal. Explicitly compare that component's limitation and explain the
retained portion. Do not replace the whole composition to solve one missing action.
Equally, do not force a poor fit to avoid custom work: the requested hierarchy,
readability and motion remain the target.

A failed search is not evidence that the catalog cannot do the job. Broaden the
query or add exact known candidates, inspect their actual source and document the
gap. Missing media or an unimplemented execution adapter is a prerequisite, not
proof that custom graphics are necessary. Catalog dimensions and legacy integration
status are discovery facts, not automatic native eligibility or quality approval.

## Prepare the map

Write an explicit request JSON with this shape. Paths must be canonical absolute
paths; hashes must be SHA-256 of the current files. The project may be planned but
its parent must already exist. Use durable reference evidence and shot-plan files,
not temporary screenshots that will disappear.

```json
{
  "scope": "reference-match",
  "format": "short",
  "project": "/absolute/project",
  "references": [{"id": "reference-1", "path": "/absolute/reference-evidence.json", "sha256": "ACTUAL_SHA256"}],
  "shotPlan": {"path": "/absolute/SHOT-PLAN.md", "sha256": "ACTUAL_SHA256"},
  "shots": [{
    "id": "shot-01",
    "referenceId": "reference-1",
    "referenceBeat": "beat-03",
    "cue": "the spoken result",
    "visualNeed": "make the improvement readable",
    "requiredBehavior": "show the count changing, then hold the result",
    "query": "number pop",
    "additionalCandidates": ["mirror:number-pop-in"]
  }]
}
```

`format` is `short` or `longform`. Additional candidates are optional and must
resolve to exact shared-catalog IDs (`mirror:name` or `local:kind`). Do not put a
self-referential `request` pin inside the request file; the CLI supplies it.
Evidence files are limited to 2 GiB each; use a provenance manifest plus the
specific reviewed frames/notes for a large source video. Pin each directly
consumed evidence file in `references`; a manifest's prose is not a recursive
content hash of its referenced files.

From the repository root:

```bash
.venv/bin/python scripts/producer/graphics/reference_reuse_cli.py prepare \
  /absolute/REFERENCE-REQUEST.json --output /absolute/REFERENCE-REUSE.json
```

Preparation searches the recorded catalog once per shot and saves candidate
records, source hashes and input evidence. No download, installation, model call
or rendering occurs. Every decision starts `pending`; search results do not count
as an inspection. Existing output files are never overwritten.

## Inspect and complete decisions

Edit only each shot's `inspections` and `decision`. An inspection names `ref`,
`candidateSha256`, the observed source behavior and a `fit` of `usable`, `gap` or
`prerequisite`. A gap records `gapType` (`missing-capability` or `quality-failure`)
and `limitations`. Prerequisites use `{kind, detail}`, where kind is `source`,
`asset`, `adapter` or `other`.

Each decision contains `route`, `reason`, `pieces` (`ref`, `role`, `changes`),
`prerequisites`, and `execution` (`adapter`, `status`). Adapter status is an
authored planning assessment: `available`, `unavailable` or `unverified`.
Unavailable/unverified execution remains blocked with an adapter prerequisite.
Selected pieces must be inspected and cannot have unresolved prerequisites.

Custom decisions additionally contain `custom` with `gapType`, `gap`, `scope`,
`closest` comparisons (`ref`, `reason`), `retainedRefs` matching the selected
pieces, and `retainedPiecesRationale` explaining what is kept, including why
nothing can be retained when appropriate. Retained components with a gap need
explicit changes and must also appear in the closest comparisons.

```bash
.venv/bin/python scripts/producer/graphics/reference_reuse_cli.py check \
  /absolute/REFERENCE-REUSE.json --output /absolute/REFERENCE-REUSE-CHECK.json
```

Exit status is 0 for a complete unblocked plan, 1 for a complete blocked plan,
and 2 for pending, malformed or stale evidence. A ready plan still reports
`styleApproved`, `qualityApproved`, `renderApproved` and `executionAdmitted` as
false. Actual visual comparison, native execution qualification and final
whole-output review remain separate.

## Consume it in native work

Both formats use the same optional static-preflight argument:

```bash
.venv/bin/python scripts/producer/studio/native_preflight.py \
  /absolute/project --output-dir /absolute/new-preflight \
  --reference-map /absolute/REFERENCE-REUSE.json
```

The preflight checks the project binding and planning evidence before the SDK
and again before completion. Pending, stale or blocked maps fail before rendering.
For native Short export, pass the same `--reference-map` to
`studio/native_short_export.py`. It pins the map and its inputs into the existing
export dependency inventory and passes the map to static preflight. A later
`--verify-from` retains and revalidates the original map; it cannot take a replacement
`--reference-map`. The shared Long integration is the explicit preflight command;
there is no new automatic Long builder or app selection behavior in this increment.

Keep the completed map for later checks of this request. Changes to the requested
shots, evidence or relevant catalog candidates require fresh inspection/planning.
Reusing this planning evidence avoids rebuilding the search and decision record;
it does not by itself prove an end-to-end production-time saving.

## Reusable study mappings and experimental items

Accepted operator direction, September 16, 2026: save inspected catalog matches
while studying the reference, before a new production project needs them. This
applies to Shorts and long-form, including vlog and other non-educational styles.
Extend the existing reference library and shared catalog; preserve the existing
project-bound map for each requested application.

The shared CLI now saves and checks reusable study bindings. The local long-form
request command supplies the complete saved reference inventory and current
catalog index to the strategy session. Automatic visual matching, experimental
component promotion, and reproduction qualification remain separate work; none
is inferred from an inventory or saved inspection. Existing catalog integration
labels retain their current meaning and do not prove native playback quality.

### Prepare a 16:9 long-form strategy session

From the repository root, after normal source ingest and stored long-form intent:

```sh
node --import tsx scripts/producer/native-short.ts prepare-longform /absolute/project/producer
node --import tsx scripts/producer/native-short.ts check-longform /absolute/request/directory
```

These operations extend the existing command entry point and source/reference
contracts. They do not call a provider or render. Preparation writes an immutable,
content-addressed packet under `producer/native-longform/requests/`, containing:

- `LONG-REQUEST.json`: original intent and lane choices, admitted footage,
  transcript/supporting-asset pins, and the default 1920×1080 target.
- `REFERENCE-LIBRARY.json` and complete per-reference JSON: all three Shorts
  collections and the long-form collection, with saved beat-to-catalog candidate
  links. The current inventory has 39 references and 194 groups of saved catalog candidates. These remain
  research, not verified landscape adaptations.
- `CATALOG-INDEX.json`: every item returned by the shared recorded catalog,
  without the search result limit. The current inventory has 418 items, including
  source hashes, historical mechanism/variable annotations, declared aspects,
  current integration evidence and limitations. Missing sources remain visible.
- For a selected reference, the full interpreted deep study (all events), profile,
  selection record and available style pack. Raw per-frame signal arrays stay in
  the pinned original study. Representative images remain pinned file references;
  they do not substitute for a chronological visual study.
- `SELECTED-REFERENCE-MATCHES.json` when the selected study has a valid sibling
  `reference_catalog_matches.json` bound to its profile or deep study.
- `AGENT-BRIEF.md`: whole-video structure, sections, shot planning, genre-specific
  decisions, reuse/configure/compose priority, 16:9 adaptation, and playback review.

The reasoning session reads the complete indexes, follows relevant detail and
image/source links, and writes the strategy and shot plan. Large indexes may be
read in recorded batches. Do not send all raw measurements, implementation code
and frames in a single prompt. Every selected shot still needs its source/output
timing, framing, viewer purpose, graphic choice, motion/hold/exit and neighboring
shot handoff. A vlog is not automatically assigned educational or Shorts pacing.

The cold check rejects changed intent, source/transcript bytes, study/library
documents or catalog inventory. It reports `inputs-current`, never approval of
an authored strategy. This path is available through the local command/agent
workflow; it does not add a new Producer UI control.

### Retain an inspected study match across projects

After completing the existing reference map's inspections and decisions (including explicit blocked decisions):

```sh
.venv/bin/python3 scripts/producer/graphics/reference_reuse_cli.py save-study /absolute/reference-map.json --output /absolute/study/reference_catalog_matches.json
.venv/bin/python3 scripts/producer/graphics/reference_reuse_cli.py check-study /absolute/study/reference_catalog_matches.json
```

For automatic inclusion with a selected long-form reference, use the selected
reference's ID and pin its `style_profile.json` or `deep_study.json` in the map's
`references`. The saved binding retains source format, reference pins, exact
catalog candidates, inspection observations, configuration and decision reasons.
The original project/request/map is provenance, not a future dependency. Completed
blocked research may be saved: `check-study` lists `blockedMatches`, and adopting
those decisions into a new map still blocks production. Pending or malformed
assessments cannot be saved. Up to 1,000 directly consumed reference evidence
files may be pinned, so a long-form study can retain its reviewed frame set.

A new map request adds `studyBindings: [{id, path, sha256}]`, then each adopting
shot adds `studyMatch: {libraryId, matchId}`. Preserve the reference ID, reference
beat, required behavior and evidence pin. `prepare` retrieves the saved choices
without searching again, retaining `savedInspections` and `savedDecision` while
leaving the new shot's decision pending. Reuse the unchanged source inspection
within its limits; record the new content, layout and timing decision explicitly.
Changed reference/component bytes invalidate the binding. A changed behavior
needs a new inspection. New searches still use the existing shared catalog path.

This is durable reuse of agent-inspected matches. It is not an automatic
frame-similarity model or permission to inherit portrait geometry/playback approval.

### Save the match during the study

Each reusable reference shot or treatment should retain its stable reference and
beat IDs, timestamps, full frames, motion examples, spoken context, and observed
behavior. Attach the exact inspected catalog item IDs and source versions/hashes,
their roles, required configuration, fit limitations, and any missing assets.
Tag both storytelling purpose and visible behavior so another study or strategy
can retrieve the match. Distinguish a possible visual resemblance, an inspected
functional match, and a rendered/verified adaptation. A still frame cannot prove
easing or transition smoothness. A footage-only shot can explicitly require no
catalog graphic rather than receive an unnecessary effect.

Use the saved match first when planning a new edit. Reuse valid inspection and
execution evidence within its recorded limits; search again for a changed need,
stale component/dependency version, missing behavior, or unsuitable result. Bind
the adopted choices into the new project's reference map. A different title,
color or shadow alone does not justify rewriting working motion or keyframes.
Prefer reuse, configuration, and composition; record a concrete capability or
quality gap before bounded custom work.

### Give strategy complete catalog visibility

Provide the complete current catalog index, including reusable local additions,
alongside the complete interpreted study of the selected reference. Each index
entry should expose its stable ID, purpose, tags, preview/evidence location,
supported variables, format/runtime limits, lifecycle status, and saved reference
matches. Detailed source and motion evidence remain available for inspection as
needed. Index completeness does not require embedding all implementation code,
every frame, or raw per-frame measurements into one prompt. Large indexes can be
read in recorded batches without silently excluding items from discovery.

Strategy should identify what already exists before proposing research or a new
build. Catalog visibility and permission to use an item are separate: experimental
and failing items stay visible with their limitations and are excluded from
ordinary production selection until qualified for the intended use.

### Keep new components experimental until reviewed

Save useful new components in a separate experimental library with their source,
configurable content/timing, dependencies, reference evidence, preview, known
defects, and validation status. Search this library before building another
version of the same behavior. For example, first check for an existing glass
container with configurable text and shadow; build only the missing capability.
New work must not overwrite or silently replace a working catalog item.

User acceptance records whether the design is wanted. Technical qualification
separately records whether it behaves correctly. Promotion to the reusable
production catalog requires both, with the verified component/dependency version
and supported aspect, runtime, frame rate, duration and content limits retained.
Failed items remain experimental with a specific repair need; changes invalidate
affected checks rather than inheriting approval from an older version.

Verify actual playback and encoded output: entrance, complete reveal, readable
hold, exit, and the preceding/following shot boundaries. Check unintended snaps,
flashes, clipping, easing discontinuities, overlapping animations and readability.
Exercise seeking, restart, reload, and multiple instances with realistic text and
timing. Preserve an intentional hard cut when the reference/story calls for one.
Component qualification does not waive review of the assembled scene or video.

### Acceptance and current evidence

| Operator requirement | Existing evidence | Remaining acceptance check |
| --- | --- | --- |
| Save shot-to-catalog matches during study | `save-study` / `check-study`; cross-project Short → long-form test forbids new discovery | The packaged long-form case LF01 is an original illustration (see below), not a retained study of a real video; each new project's saved matches and adaptation still need review |
| Reuse working animation before custom work | Existing route/gap checks plus retained saved inspections and decisions | New content/layout/timing still needs a source-bound strategy decision |
| Give strategy the entire available library | Complete 39-reference/418-item local packet; no ranked-result limit; hashes checked on reuse | New experimental-item indexing/promotion remains separate; absent sources stay explicit |
| Preserve a complete long-form study and 16:9 intent | Synthetic 900-second fixture retains 1,500 events, original lane choices, selected study and saved matches | A real 10–15-minute source/reference has not been reproduced in this implementation pass |
| Keep new work separate until accepted and reliable | Current measured/unmeasured integration evidence is narrower than this lifecycle | Experimental storage, production exclusion, user acceptance and technical promotion operate together |
| Keep motion and transitions smooth | Current map explicitly grants no visual or render approval | Actual component and neighboring-shot playback/export pass for the intended use |

Implementation tests use inert source bytes and explicitly synthetic inspection
text; they verify orchestration and freshness, not visual quality. No new custom
component, experimental promotion, paid strategy session or rendered reproduction
is claimed by those tests. A real source/reference pair is needed for that review.

The packaged long-form library starts with [LF01: chapter a long explanation into steps](../../resources/references/longform/cases/LF01.json), an original case with frames rendered from Sniper's own pipeline template. It illustrates a mechanism; it is not a reviewed real-source reproduction.
