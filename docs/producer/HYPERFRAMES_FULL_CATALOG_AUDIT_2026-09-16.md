# HyperFrames catalog audit: one reusable library for Short and Long

## Conclusion

The catalog contains substantially more useful mechanisms than our current edits
regularly use. The main gaps are discovery, fragmented instructions, uneven
request packets, and incomplete evidence of actual reuse. A new effect is often
unnecessary: real content plus a configured existing mechanism can do the job.
Technical limitations should be recorded per item and version; an old brand or
talking-head preference should not hide an otherwise useful mechanism.

The requested audit and indexed research artifacts are complete. Updating the
production discovery/request/assembly code is a subsequent implementation phase.
This audit does not qualify all catalog items for rendering in both formats.

## Open the results

- [Searchable library](http://127.0.0.1:4005/catalog-audit-2026-09-16/index.html): all
  399 items, 40 starting candidates, purpose filters, Short/Long placement,
  controls, source notes, historical assessments and official preview links.
- [Indexed JSON](../../artifacts/catalog-audit-2026-09-16/catalog-index.json): exact
  `itemsById` records plus nine precomputed lookup tables.
- [Complete audit records](../../artifacts/catalog-audit-2026-09-16/AUDIT.json),
  [coverage](../../artifacts/catalog-audit-2026-09-16/COVERAGE.json),
  [index checks](../../artifacts/catalog-audit-2026-09-16/INDEX-CHECKS.json), and
  [search reproductions](../../artifacts/catalog-audit-2026-09-16/SEARCH-PROBES.json).
- [Exact upstream snapshot and source hashes](../../artifacts/catalog-audit-2026-09-16/snapshot.json).

## Audit scope and evidence

Frozen official upstream commit:
[`7b5fdb1ad28347272d235edea7aa6a9c762d5e1c`](https://github.com/heygen-com/hyperframes/tree/7b5fdb1ad28347272d235edea7aa6a9c762d5e1c/registry),
committed September 16, 2026 at 15:55 UTC. All metadata and downloaded text files
come from this single revision. Catalog text is source data, not instructions.

| Coverage | Result |
| --- | ---: |
| Reusable items | 399: 180 blocks, 219 components |
| Separate example projects | 9 |
| Declared text-source files scanned | 474 |
| Text-source bytes retained | 7,332,508 |
| Items with declared variables | 212 |
| Items with explicit upstream storytelling jobs | 114 |
| Items with timing sync points | 77 |
| Items with preview metadata | 172 |
| Priority starting candidates | 40 |
| Focused source-inspection notes | 19 |

Every item has an editorial family, use guidance, Short and Long placement
recommendations, declared geometry, actual metadata, source hashes and static
review triggers. Family guidance is an editorial assessment, not proof of a
successful adaptation. The focused notes inspect specific implementation details;
they are not a claim that a human watched every frame of 399 animations.

The complete-source pass is static. Regex findings can include comments and
integration examples, so they request review rather than automatically declaring
an item broken. Remote fonts, media, models and data were inventoried; non-text
assets were not downloaded or executed. Source equality compares the main HTML,
not an entire runtime dependency closure.

Live browser spot-checks inspected the official Camera Follow Captions and Browser
Device Stage pages/previews, and the catalog overview. Other selected candidates
were assessed from current metadata and source. Some legacy CDN poster links did
not display in the local library; use the linked official live page. Preview
availability is not counted as successful playback qualification.

## Findings, ordered by impact

### 1. Shorts receive less catalog context than long-form

`native-short-request.ts:43` selects six starting reference documents. At line 84,
the output includes the request, hook-writing Director library and brief, with no
full HyperFrames catalog packet. These references are starting context, not a
hard limit, but the broader discovery work is left to the agent.

`native-longform-request.ts:17` already calls the full inventory; lines 28 and 33
require catalog reading and shot-level reuse decisions. Its packet includes
`CATALOG-INDEX.json`. Share this discovery contract across formats rather than
maintaining two different levels of context.

### 2. Our saved catalog is stale and loses useful metadata

Compared with the 372-item August 28 index:

- 27 new items: 25 carousel variants, `hw-write-title`, `kinetic-center-build`.
- 158 existing main HTML sources changed.
- 212 main HTML sources are identical.
- 2 old main files were missing locally but are present in the new snapshot:
  `lt-neon-border` and `texture-mask-text`.

The old lock reports 371 installed sources while discovery finds 370. This is an
inventory disagreement, not a reason to reject the entire catalog.

Current metadata includes `jobs`, `family`, `profile`, `syncPoints`, variable roles
and content controls. The local index/search does not preserve and search all of
these. A reproduced `prove` query returns seven items but misses
`testimonial-proof-card`, whose current upstream job is explicitly `prove`.
The new audit's `lookups.byUpstreamJob.prove` includes it.

### 3. Historical skip judgments confuse style preference with capability

The earlier study contains 122 `skip` judgments. Some are valid technical concerns;
others reflect a narrow cream/ink brand, the old compositor, or assumptions about
what a talking-head video needs. Examples worth reopening:

| Item | Historical reason | Useful Short and Long role |
| --- | --- | --- |
| `onboarding-stepper-flow` | Onboarding UI scaffold | Pending step → next action; expose truthful state and content |
| `card-resize` | Generic UI prop | Summary expands into its explanation without losing identity |
| `multi-device-splay` | No talking-head use | Explain actual mobile/desktop product context |
| `swipe-rail` | Mobile gesture scaffold | Move through real examples or screen states |
| `sticky-mock-swap` | Skeleton feature tour | Preserve a stable screen context while showing actual features |
| `transitions-*` | Footage transitions outside old compositor | Reuse the selected transition recipe in native assembly |

Do not promote these automatically. For example, onboarding-stepper-flow really
has fixed labels and example completion states. Adapt those inputs while retaining
the useful mechanism. Keep artistic suitability, technical availability and
production qualification as separate fields.

### 4. Catalog-first is documented, but generic custom-work evidence is optional

`docs/PIPELINE.md:24` already requires catalog-first graphics and transitions.
`native-short-strategy.ts:25` captures story, reference, asset and timing evidence,
but no universal catalog-candidate/source/configuration record.
`studio/native_reference_reuse.py:21` returns no reference snapshot when no map was
supplied. The strong reuse/configure/compose/custom comparison is correctly scoped
to explicitly requested reference matching, so ordinary produced work can still
reach native assembly without that comparison.

The fix should add a shared catalog decision for graphics/motion work. It should
not force exact creator-reference matching on every edit or add effects to a
deliberately simple clip. Footage-only and graphics-disabled beats need no effect.

### 5. Old port restrictions and development routes can mislead selection

`vendor/hyperframes-catalog/README.md:13` says every item must first be ported to
the legacy template registry. Current canonical pipeline direction permits native
authoring and wider catalog use; the old statement needs an explicit route scope.

The legacy registry has 53 currently measured local kinds, with seven explicitly
mapped upstream ports. That is not the full catalog's capability ceiling.

`guided-native-prompt.ts:8` describes a separate V9/V10 development route with
only two mechanisms, plus a supplied-image mechanism in V10. This is an actual
route limitation; it must not become a claim about all native HyperFrames work.

### 6. Recent work shows discovery, but not complete tracked component reuse

The remaining-Shorts `CATALOG-SEARCH.json` queried 399 current items using the word
matching tier. Its `BRIEF.md:21` records inspecting onboarding-stepper-flow and
ui-focus-zoom and adapting their mechanisms. That establishes real discovery and
some source inspection. It does not establish that every custom visual had an
inspected capability gap, or that the final HTML reuses exact component source.

Separate these outcomes in future receipts: source reused, configuration changed,
several items composed, or a new implementation inspired by the source. Do not
count an inspiration citation as maintained component reuse.

## Clean reusable mechanisms to prioritize

### Make catalog selection part of visual storytelling

The JSON does not make a good editorial choice by itself. Use this shared sequence
for both formats, with a verifiable decision before custom composition work:

1. **Read the complete beat.** State what the viewer should understand before and
   after it, and identify the useful visible change. A named tool alone does not
   decide the picture.
2. **Choose the representation.** Inspect real footage, pages, products, people,
   logos and proof first when relevant. Decide whether the beat needs evidence,
   comparison, explanation, orientation, emphasis or simply the presenter.
3. **Retrieve from the whole catalog.** Query indexed jobs, inputs and tags, then
   search descriptions/mechanics if needed. The 40 starting candidates are not a
   whitelist; keep all 399 searchable. No portrait-only prefilter should silently
   hide a useful host-sized mechanism or an adaptable landscape composition.
4. **Inspect a small visual shortlist.** A practical initial target is 3–5
   candidates per distinct job, not 399 previews per beat. Inspect real motion,
   controls and source for finalists. Expand the search when no candidate fits.
   Similar beats can share the same inspected mechanism and exact version.
5. **Bind the chosen item to the story.** Record actual content/media, source cue,
   attention target, configuration, geometry, readable hold, exit and adjacent-shot
   handoff. For custom additions, compare the closest existing candidates and keep
   reusable pieces. A different color or font is a configuration decision.
6. **Review the sequence.** A separate creative review should check that pictures
   support the actual speech, evidence is truthful, the choice is visually strong,
   and recurring layouts do not flatten the story. Then verify actual Studio and
   encoded behavior. Correct schema fields cannot establish visual quality.

The proposed completeness check is a beat-to-item coverage record for enabled
graphics/motion beats. It must accept a justified presenter/real-footage choice,
and it must reject missing candidate inspection or a generic custom justification.
This enforcement is recommended here; it has not yet been added to production.

The data retrieval cost is small: the 4,306,370-byte indexed JSON took a median
**18.74 ms** to read/parse across 15 local Python repetitions. After loading, exact
ID and bucket lookups averaged below 0.1 microsecond in 100,000-iteration loops.
The filesystem cache may be warm and the loops include overhead. These measure
only local retrieval, not agent latency, asset searches, preview review or render
time. See [lookup timings](../../artifacts/catalog-audit-2026-09-16/LOOKUP-TIMING.json).
The editorial shortlist/review needs its own real production timing measurement;
the 3–5 candidate starting target is a proposed work budget, not a quality cap.

| Visual job | Strong candidates | Short treatment | Long treatment |
| --- | --- | --- | --- |
| Real screen proof | `browser-device-stage`, `ui-focus-zoom`, `yt-feather-highlight` | Real page plus one readable detail | Real walkthrough; overview → detail → overview |
| Tools/framework | `grid-card-assemble`, `trust-strip` | Few large items on speech cues | Reusable framework developed through the section |
| Comparison | `before-after-wipe`, `split-tilt-cards` | One clear before/after relation | Hold and inspect each meaningful difference |
| Attribution | `testimonial-proof-card`, `yt-comment-card` | Real quote or question with identity | Case-study quotation with context |
| Process | `hw-pipeline`, `state-chip-rail`, `onboarding-stepper-flow` | One decision and next action | Persistent process with truthful changing states |
| Correct a belief | `line-swap`, `strikethrough-replace`, `morph-swap` | Change the relevant phrase/object | Preserve old/new relationship while explaining why |
| Screen sequence | `screen-flow-carousel`, `parallax-zoom`, `parallax-unzoom` | A few real examples | Guided tour with a return to the full system |
| Code teaching | `code-highlight`, `code-diff`, `code-terminal-run` | One readable command/change | Actual file, edits and results across a section |
| Titles | `titlecard-lockup`, `hw-write-title`, `kinetic-center-build` | Concise opener/emphasis | Chapter/definition with speech-derived hold |
| Karaoke | `caption-highlight`, `caption-pill-karaoke` | Bind actual active-word timing | Selected phrase emphasis or restrained captions |
| Transition | `fade-through`, `hw-scribble-transition`, `whip-pan-cut` | Motivated scene handoff | Chapter or related-view handoff |

The same mechanism can serve both formats. Content density, geometry, placement,
caption clearance and reading duration must be derived for the actual format.
A 16:9 demo is neither proof of portrait compatibility nor proof of incompatibility.

## Indexed JSON design

JSON stores the structured catalog; this Markdown report explains the findings.
The HTML browser and lookup JSON derive from the same `AUDIT.json` records.
Do not maintain independent hand-edited copies of item facts.

```python
import json

with open("catalog-index.json") as handle:
    catalog = json.load(handle)  # Load once per snapshot: O(n).

item = catalog["itemsById"]["ui-focus-zoom"]  # Average O(1).
proof_ids = catalog["lookups"]["byUpstreamJob"]["prove"]
cue_ids = catalog["lookups"]["byInput"]["cues"]
```

Bucket lookup is average O(1); reading k results is O(k). Combining filters or
semantic searching is not O(1). Alias buckets preserve collisions. Unknown keys
remain misses. Source IDs are exact; human alias keys use the documented Unicode
normalization. Examples live separately and cannot be mistaken for installable
blocks. A database is unnecessary for this 399-item snapshot; a cached loader and
the existing search CLI are sufficient. Add a database only if shared writes,
large-scale querying or measured load costs justify one.

## Recommended implementation, in order

1. **Shared versioned loader:** extend existing catalog discovery to retain full
   current metadata. Index by ID and job/tag/input/geometry, with provenance and
   status separate from artistic preference. Refresh explicitly; keep old project
   pins readable. Never silently replace a running project's component version.
2. **Equal request packets:** reuse one catalog/reference handoff for Short and
   Long. Retrieve relevant candidates and on-demand details instead of repeatedly
   stuffing 399 full sources into every request. Preserve full discovery access.
3. **Beat-to-item decisions:** record purpose, real asset, inspected candidates,
   chosen source/version, configured inputs/cues, format treatment and any specific
   custom gap. Use existing reference-reuse machinery where applicable without
   imposing reference matching on ordinary work.
4. **Shared native adapters:** distinguish full blocks, host snippets, CSS progress
   utilities and demo galleries. Preserve source motion; share adapter logic across
   formats. A brand/font change should not require rewriting the animation.
5. **Representative qualification:** start with frequent mechanisms above. Check
   actual 9:16 and 16:9 content, repeated instances, forward/backward seek, entry,
   readable hold, exit and final encode in the pinned runtime and Studio.
6. **Reusable fixtures and receipts:** retain tested input limits, genuine preview
   evidence and exact source/runtime hashes. Recheck affected dependencies after
   changes rather than rendering the whole catalog per video.
7. **Measure production benefit:** compare complete equivalent edits: planning,
   asset search, assembly, render, QC and repairs. Preserve resolution, codec,
   karaoke/audio checks and editorial quality. No elapsed-time savings are claimed
   from this read-only audit.

## Edge cases and acceptance checks

- **Dimensions:** components may contain fixed demo canvases despite having no
  manifest dimensions. Test actual portrait and landscape wrappers; never force a
  blanket crop/contain treatment that makes proof unreadable.
- **Inputs:** long labels, Unicode, non-Latin glyphs, empty values, comma-separated
  lists, excessive items and missing cues. Grid-card-assemble documents a 12-item
  cap and commas as separators; never silently lose required information.
- **Font metrics:** kinetic-center-build measures a system-font stack while its
  display requests Geist. Test widths and fallback behavior before trusting fit.
- **Timing:** cues outside the duration, a scene too short for entrance plus
  reading hold, paused/rewound playback, and complete final words.
- **Truth:** real logos, screenshots, customers and quotes must remain sourced.
  Template sample metrics, completed steps and avatars are not proof.
- **Instance isolation:** fixed DOM IDs, global selectors, CSS variables and
  timeline keys can collide when two instances share a project. Verify twice.
- **Runtime:** CSS infinite animation, prior-frame-dependent blur, callbacks and
  asynchronous initialization need exact seek/readiness tests. Source-pattern
  scans alone cannot pass or fail the whole item.
- **Dependencies:** missing assets, fonts, network-fetched map data, nested file
  paths, shared helpers and GPU/WebGL requirements. Record a prerequisite rather
  than treating a missing file as permission to rebuild everything.
- **Transitions:** full-screen demo galleries are not directly mountable A/B
  transitions. Bind the real two scenes and preserve timeline ownership.
- **Index correctness:** exact ID lookup, alias collisions, unknown IDs, duplicate
  IDs, stale version/hash, complete item coverage and all bucket references.
- **Style scope:** simple edits stay simple. No compulsory motion percentage or
  effect density; every chosen visual needs a teaching or storytelling purpose.

## Verification and limitations

- Existing catalog discovery/fixture/inventory suite: **33 tests passed**.
- New index checks passed: 399 unique items, 9 examples, nine lookup tables,
  complete partition coverage, valid unique sorted references, alias collision
  preservation, duplicate-ID rejection, cue/job retrieval and JSON roundtrip.
- Snapshot text files were hash-checked during audit generation.
- Browser verified the searchable library and item detail view; remaining UI
  checks are recorded in the audit artifact directory.
- Production pipeline, vendored source mirror, completed videos, render runtime
  and delivery qualification were not changed. No claim of a 399-item visual
  certification or new end-to-end performance benchmark is made.

## Requirement / source / evidence

| Requirement | Source | Evidence |
| --- | --- | --- |
| Full current catalog audit | User request | Pinned 408-record snapshot; 399 item records plus 9 examples |
| Both Short and Long use | User request | Every record has separate placement and geometry guidance |
| Reuse clean catalog mechanisms | User request; canonical pipeline | 40 candidates, source notes, prioritized shared integration plan |
| Indexed JSON | User follow-up | `catalog-index.json`, `INDEX-CHECKS.json`, documented complexity |
| Preserve quality | Standing user direction | No production weakening; explicit real-input and dual-format qualification plan |
| Preserve unrelated work | Workspace instructions | New isolated audit artifacts and documentation only |
