# HyperFrames Catalog Mirror (read-only reference)

Full local mirror of the upstream HyperFrames registry — 371/372 items (154 blocks,
218 components; see `hyperframes-catalog-lock.json` for provenance and the one
registry-side failure). `catalog-index.json` is the searchable metadata index
(names, titles, descriptions, tags); the source of each item lives under
`compositions/` (blocks) and `compositions/components/`.

**Why it exists:** so the agent can READ the actual code of every catalog item when
the operator asks for a look ("a subtle glitch transition") — selection by mechanism,
not by title — and so porting decisions are grounded in source.

**Boundary (same doctrine as `vendor/hyperframes-skills/`):** this is NOT a Project
Sniper capability surface. Nothing here is plannable or renderable. An item enters
the working vocabulary ONLY by being ported into `templates/motion/compositions/`
through the template contract: typed variable slots, brand tokens, capability probe
(THE EXIT LAW measurement), and Studio session lint. Do not reference these files
from plans, comps, or the Studio generator. Do not install catalog items inside a
Studio review project (they will not sync to the plan and will not survive re-render
— ask for a port instead).

Refresh: rerun the mirror script pattern (catalog --json, then `add <name> --dir`)
against the pinned CLI and update the lock file.

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
