# templates/motion/icons — provenance and licences

## Brand marks (this folder) — Simple Icons, CC0 1.0

The 14 `*.svg` marks recorded in `manifest.json` (anthropic, claude, codex, cursor,
figma, gemini, github, instagram, notion, openai, perplexity, tiktok, x, youtube)
come from Simple Icons (<https://simpleicons.org>, served by
`https://cdn.simpleicons.org/<slug>`), whose icon data is dedicated to the public
domain under CC0 1.0 Universal. `manifest.json` records each file's slug, source URL
and fetch date (2026-07-05 or 2026-07-23). `scripts/producer/planner/icon_library.py`
fetched them and rewrote the fill to the Sniper accent `#054BC9`; the glyph paths
are unchanged.

### The three colour variants

`claude-color.svg`, `openai-color.svg` and `gemini-color.svg` are not in
`manifest.json`. In the maintainer's repository history they first appear in the
2026-07-16 anonymized snapshot commit, which carries no fetch record for them. On 2026-09-18 their `<path d="…">` data
and `<title>` were compared with the manifest-recorded files: each is identical to
`claude.svg`, `openai.svg` (= `codex.svg`) and `gemini.svg` respectively. The only
difference is the fill colour: `#D97757`, `#10A37F` and `#4285F4` instead of
`#054BC9`. They are therefore the same CC0 Simple Icons glyphs, recoloured.

They are recorded here rather than in `manifest.json` because `icon_library.py`
rewrites the manifest on every fetch and treats each manifest key as a resolvable
icon name. They are used by the `icon-badge-wide` Elements defaults
(`src/lib/producer/comps-catalog.ts`), `graphics/intro_semantic_cues.py`,
`graphics/template_visual_contract.py` and the capability probe
(`graphics/comp_catalog_probe.py`), so they ship with the package.

Simple Icons notes that its CC0 dedication does not imply that every icon is CC0 and
records per-icon licences where they apply. In the `simple-icons` 16.31.0 data file
(checked 2026-09-18) none of the marks used here carries a separate licence entry. The
OpenAI mark is absent from that data: Simple Icons removed it in 16.0.0 (November 2025)
after a public call to seek OpenAI's agreement to keep it went unanswered. `openai.svg`,
`codex.svg` and `openai-color.svg` use the Simple Icons 15.0.0 drawing (path data
identical). Whether to keep shipping that mark is an open owner decision.

## Trademarks

CC0 covers the drawing data only. Every brand mark in this folder is a trademark of
its owner. Project Sniper uses a mark only to identify the product a speaker is
talking about (nominative, editorial use). This use implies no endorsement,
sponsorship or affiliation. Buyers who publish videos containing these marks are
responsible for their own use, including each owner's brand guidelines.

## Generic glyphs (`lucide/`) — ISC

See `lucide/PROVENANCE.md`: 55 Lucide glyphs from `lucide-static@0.525.0`, ISC licence
(portions MIT, from Feather). Each file keeps its `@license` header. The ISC licence
text ships in the package's THIRD-PARTY-NOTICES.md.
