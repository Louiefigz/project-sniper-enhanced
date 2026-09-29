# HyperFrames Catalog Mirror (read-only reference)

Full local mirror of the upstream HyperFrames registry — 371/372 items (154 blocks,
218 components; see `hyperframes-catalog-lock.json` for provenance and the one
registry-side failure). `catalog-index.json` is the searchable metadata index
(names, titles, descriptions, tags); the source of each item lives under
`compositions/` (blocks) and `compositions/components/`.

**Why it exists:** so the agent can READ the actual code of every catalog item when
the operator asks for a look ("a subtle glitch transition") — selection by mechanism,
not by title — and so porting decisions are grounded in source.

**Boundary (same doctrine as `vendor/hyperframes-skills/`):** this mirror is
discovery evidence, never automatic execution approval. The ordinary compatibility
renderer can use only an integrated, measured port in
`templates/motion/compositions/`. A native Short or Long may select a reference and
adapt its exact pinned source into a project-owned composition, but that adaptation
still needs local dependency closure, typed inputs, a guarded capability probe and
Studio lint. Plans and renderers must never execute these mirror files directly.

`catalog-snapshots-v1.json` pins the current metadata/resource sidecars by digest.
Historical roots stay in place so an explicit old snapshot ID remains readable.
`catalog-resource-index-v1.json` contains static, unmeasured resource signals used
to decide which finalists need a guarded probe; it contains no source or preview
bytes and grants no capability. A refresh is prepared in a new snapshot directory,
then checked by `graphics/catalog_snapshot_admission.py` against the exact expected
upstream commit before its registry row can be promoted. Never overwrite an admitted
root. The documented September 16 399-item audit cannot be promoted from the current
checkout because its exact generated index/source bundle is not present here.

## Licence, notices and what ships

The mirrored registry items are part of HyperFrames
(<https://github.com/heygen-com/hyperframes>), Copyright 2026 HeyGen, Inc., licensed
under the Apache License, Version 2.0. The full licence text ships with Project Sniper
as `licenses/Apache-2.0-hyperframes.txt`. HyperFrames publishes no NOTICE file
(checked 2026-09-18). The
files here are kept as the CLI 0.7.33 `add` command wrote them on 2026-08-28; Project
Sniper does not edit them. That was not re-verified against upstream bytes for rc4,
because the lock records counts, not per-file hashes. Individual items were not
reviewed for third-party material embedded in their source text.

What the buyer package contains (`release/package_spec.py`): this README, the index,
the lock, and the composition **HTML sources** under `compositions/` — the only item
files that `scripts/producer/graphics/catalog_discovery_sources.py` reads. These are
withheld because discovery never reads them and their individual terms were not
verified: `assets/` (sound effects, wallpapers, textures, fonts, icons),
`compositions/assets/` (fonts and the HyperFrames logo), `compositions/lib/`
(a script library) and the `compositions/components/*.png` textures. They stay in the
source tree.

Seven items were ported into `templates/motion/compositions/` and modified by Project
Sniper (chart-story, count-up, hw-callout-circle, hw-scribble-transition, line-swap,
marker-highlight, ui-focus-zoom). Each ported file carries its own Apache-2.0
attribution and modification notice.
