# Visual source policy

New work is HyperFrames upstream catalog first. Search the complete catalog,
inspect the closest sources, then configure or compose them for the actual shot.
A missing local installation or incompatible compatibility-renderer slot is not
a reason to resurrect a Sniper template or call the catalog inadequate.

The authority is `schemas/producer/visual-source-policy-v1.json`. Its seven
registered entries are verified upstream ports with both upstream and adapted
source hashes. The 46 old house HTML templates have been deleted. A file dropped
into `templates/motion/compositions` does not register it. New catalog items use
the native project workflow; the compatibility menu is not the full catalog.
Global house-style selection, the three old transition
presets and Pillow hook cards are retired. Pacing observations and historical
studies are evidence, not permission to select their old designs.

## Native source decisions

Every authored visual must have a current source decision. Native Shorts embed
`visualSources` in `SHORT-PROJECT.json`; native Long projects place the same
receipt in `VISUAL-SOURCES.json`. Project scene packages carry `visualSources`.
Receipts identify the current request by canonical absolute path and SHA-256.
Shorts prepared with a request packet must bind that exact packet.

`schemaVersion` is 1 and `policyVersion` is `hyperframes-catalog-first-v1`.
`subjectSha256` binds the exact authored subject. Use the TypeScript
`nativeVisualSourceSubject`/`nativeVisualSourceTargets` helpers before Short
assembly, or this command for an existing Short/Long project:

```bash
./sniper python3 -B scripts/producer/studio/native_export.py source-input /absolute/project
```

The command prints the hash and targets; it does not choose or approve a design.
Each decision has unique `targets`, a specific `reason`, and one route:

- `catalog`: `catalog: [{id, sourceSha256}]` names authentic upstream sources;
  `configuration` explains how those sources are used and adapted.
- `reference`: `reference: {path, sha256}` pins a reference explicitly present
  in the request's `selectedReferences`; `adaptation` explains the current use.
  A general reference library or creator name does not qualify by itself.
- `custom`: `gapType` is `missing-capability` or `quality-failure`, with
  `query`, `gap`, and bounded `scope`. `inspected` contains the closest authentic
  catalog sources (`id`, `sourceSha256`, `limitation`). A search miss, setup
  failure or unavailable mirror file is not an accepted gap.

Decisions cover every declared target exactly once. Editing the design, source,
request, or policy invalidates its receipt. Titles, caption presentation, native
text/shapes and scene extensions are included; calling code "native" does not
exempt it. Source evidence is not visual-quality approval. Independent plan
review requires explicit `visualSourceSelection` coverage; real Studio/export checks still judge whether the claimed reuse,
configuration or gap is honest and produces the requested result.

## Staging catalog components in a native Short

Both Short and Long request packets include complete `CATALOG-INDEX.json`.
Inspect actual source files; do not restrict selection to the seven ports.
Stage any needed dependencies as local assets. `catalogFiles` entries bind an
adapted source file with `{file, path, sha256, catalogId, sourceSha256}`:

- `file` is `compositions/<name>.html` in the new project.
- `path` is the canonical absolute path to the adapted HTML.
- `sha256` binds those adapted bytes; `sourceSha256` binds the upstream snapshot.
- Mount each file with `data-composition-src="compositions/<name>.html"` in the
  scene extension and the normal HyperFrames timing/track contract.

The builder verifies and stages these files; the project manifest covers them.
Use `catalogTitle: {file, copy}` for an opening implemented by a mounted catalog
component. The existing Director copy contract still applies. The older built-in
`canvas.titleCard` requires an explicit reference/custom decision and cannot be
claimed as an upstream catalog component. Supply visible timing checkpoints for
new title components and review their actual complete playback.

The renderer validates component dependencies, timing and output separately.
Neither a catalog match nor a source receipt proves portrait fit or playback.
Native Long projects author and stage components using the normal HyperFrames
workflow and bind all executable HTML/CSS/JS files in the subject hash.

## Existing jobs and compatibility execution

Old jobs are not silently rewritten or visually substituted. They fail with a
migration message if they request a retired kind, title-card/transition preset,
creator style or stale source receipt. Preserve their prior evidence, prepare a
new native request, select current sources, rebuild and review. Old pipeline
snapshots also fail admission under the current policy; frozen old code cannot
restore deleted templates. Historical output copies are not production inputs.

The compatibility renderer can still use the seven verified ports. Produced
long-form beats with no compatible port explicitly need native catalog work.
Never use a numeric counter or chart as filler to satisfy an unrelated beat.

The supported release uses the native renderer through `./sniper` on macOS or
`sniper.cmd` on Windows; it does not require a Docker image or image approval
from another machine.

Scoped scene text/timing operations recheck their current source evidence and
preserve the same selected source through the exact authorized edit. They cannot
change the executable bundle, element membership or source rationale. The new
subject changes plan and review hashes; this does not carry quality approval.
