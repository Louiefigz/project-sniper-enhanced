# templates/motion/icons/lucide — vendored Lucide glyph subset

- Source: `lucide-static@0.525.0` (pinned) fetched from
  `https://unpkg.com/lucide-static@0.525.0/icons/<name>.svg` on 2026-07-11 by
  `scripts/producer/planner/icon_lucide.py vendor` (55 curated icons; the
  catalog is `icon_lucide.LUCIDE_NAMES`).
- License: **ISC** — "Copyright (c) for portions of Lucide are held by Cole
  Bemis 2013-2022 as part of Feather (MIT). All other copyright (c) for Lucide
  are held by Lucide Contributors 2022." Each vendored file keeps upstream's
  `<!-- @license lucide-static v0.525.0 - ISC -->` header; per-icon records
  (source URL, fetch date, baked color) live in `manifest.json` beside this
  file. ISC permits use/copy/modify/distribute with the notice retained —
  this file and the in-file headers are that notice.
- Modification: the only change from upstream is `stroke="currentColor"` →
  the brand accent (`#054BC9`, `icon_library.ACCENT`) baked at vendor time so
  `<img src="/icons/lucide/<name>.svg">` renders the exact hex (same posture
  as the Simple Icons fill-rewrite in `planner/icon_library.py`).
- Consumption: comps resolve `iconFile: "lucide/<name>"` to
  `/icons/lucide/<name>.svg` via their existing bare-name rule. Combined
  resolution order (dedupe) is `icon_library.resolve_name`: a Simple Icons
  BRAND mark wins for names in both vocabularies (e.g. `github`); the glyph
  stays reachable as `lucide/github`.
- Re-vendor / extend: add the name to `LUCIDE_NAMES` (must exist in the pinned
  version — a 404 fails loudly), then run
  `scripts/producer/planner/icon_lucide.py vendor <name>`.
