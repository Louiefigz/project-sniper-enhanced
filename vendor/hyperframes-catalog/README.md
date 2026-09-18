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
