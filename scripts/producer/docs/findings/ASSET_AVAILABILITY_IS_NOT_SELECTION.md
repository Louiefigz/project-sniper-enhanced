# Asset availability is not operator selection

## What failed

A one-video ingest produced a manifest with these counts:

- 1 source
- 0 b-roll assets
- 1 music asset

The music row was the repository's synthesized `default-bed.mp3`, marked
`source: "builtin"`. It was available to the renderer, but the GUI displayed it
as `1 MUSIC`, which made it look uploaded and selected. A separate sticky-preset
bug could also persist `intent.music: true` without an explicit checkbox action.

## The contract

Keep three states separate:

1. **Cataloged** — an asset exists and may be referenced by a plan.
2. **Requested** — the operator explicitly opted into that class of asset.
3. **Selected** — the edit plan references a specific catalog entry.

The manifest owns availability. `project.json` intent owns the request. The edit
plan owns selection. None of those states should be inferred from another.

For project-folder ingest, classification is explicit:

- media in the folder root is source footage;
- media under `broll/` is a cutaway candidate;
- supported audio under `music/` is project music;
- repository music remains `source: "builtin"`.

Do not classify arbitrary root audio as music. It may be dialogue, a lav track,
voice-over, room tone, or a mix stem.

## Guardrails

- Manifest summaries count project music separately from bundled availability.
- Bundled beds are labeled “available—not uploaded or selected.”
- Every preset starts with music off; only the Music checkbox opts in.
- Music-folder candidates must contain an actual audio stream.
- Tests cover project-versus-bundled counts, preset safety, and folder
  classification.

## Missing optional candidates are a capability resolution, not a failed run

A legacy Produced project requested automatic b-roll while its manifest held
zero eligible cutaways. The launch guard correctly detected the mismatch but
incorrectly stopped the saved-plan review and told the operator to ingest the
same media again. No new scan could change that fact.

The safe contract is:

1. retain the exact `requestedIntent` (`broll: auto` through the scope default);
2. derive `resolvedIntent.lanes.broll = "off"` from the manifest;
3. store an explicit capability decision explaining the fidelity reduction;
4. continue through the normal planning, render, and QC pipeline.

This applies to Produced, Full, and reference Mimic requests. A literal Mimic
without cutaways cannot match the reference's cutaway rhythm exactly, but the
missing optional pool must not make every other edit lane unusable. The UI
shows that limitation before launch without mutating state on GET; the launch
persists it when the operator continues.

Do not advertise asset generation as a connected action until a real provider
flow exists. “Generate with Higgsfield” remains visibly unavailable today;
operators may add or import generated media and rescan later.

## When not to use this split

If a format is intentionally a *timeline manifest* containing only committed
selections, cataloged and selected can be equivalent. `asset_manifest.json` is
not that format: it is a candidate pool consumed by a later edit plan.
