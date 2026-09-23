# templates/motion — vendored asset provenance

## vendor/gsap/ — GSAP 3.14.2 core, SplitText and DrawSVGPlugin

- Files: `gsap.min.js` (core), `SplitText.min.js` (7,779 bytes) and
  `DrawSVGPlugin.min.js` (4,351 bytes), all 3.14.2, unmodified, from the official
  npm `gsap` package (plugins via jsDelivr
  `https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/<file>`, vendored 2026-07-11).
  Since GSAP 3.13 the formerly members-only plugins ship in the public npm package.
  `README.upstream.md` is the verbatim upstream README kept as the record; its receipt
  hash matches the shipped `gsap.min.js`.
- Version: plugin and core versions MUST stay in lockstep when either is bumped.
- Licensing: GSAP Standard "No Charge" License, granted by Webflow —
  <https://gsap.com/standard-license> (redirects to
  <https://gsap.com/community/standard-license/>; the page showed "effective 30 April
  2025, last modified 30 May 2025" on 2026-09-18). Each file keeps its `@license`
  header ("Copyright 2025, GreenSock. All rights reserved. Subject to the terms at
  https://gsap.com/standard-license"); the licence forbids removing those notices.
  Since 3.13 the licence permits commercial use of the whole toolkit, including
  these plugins, at no charge. It grants rights only for its "Permitted Uses"
  (websites, web applications, digital interfaces) and, without Webflow's prior
  written consent, forbids use in no-code visual animation tools that compete with
  Webflow's visual animation building. **Not cleared for sale:** whether Project
  Sniper's editing surfaces fall under that restriction, and whether the licence
  covers shipping these files inside a paid download, awaits the publisher's written
  answer (rc4 release evidence `design/GSAP_DETERMINATION.md`). The npm package ships
  no LICENSE file.
- Consumed by: every registered composition loads the core. Opt-in plugins:
  - `compositions/punch-shout-lockup.html` — `splitText:true` per-word staged reveals
    (SplitText; pop timing stays inside the two-frame budget).
  - `compositions/statement-card.html` — `splitText:true` per-character staged
    word-rise in the classic build (SplitText).
  - `compositions/stroke-draw-badge.html` — DrawSVG stroke-draw → flood-fill icon
    badge.
- Serving: HyperFrames serves the project dir as the web root, so comps load them as
  `<script src="/vendor/gsap/<file>">` — local files, no CDN fetch at render time.

## tokens.css — embedded fonts (all SIL OFL 1.1)

Inter 400/700 and Caveat (from `assets/fonts/`, licences `Inter-OFL.txt` and
`Caveat-OFL.txt` there) and Bricolage Grotesque plus IBM Plex Mono 500/600 (from
`src/app/fonts/`, licence files beside them) are embedded unmodified as base64 data
URLs. The palette and type pairing are Project Sniper's own (see the tokens.css
header).

## compositions/ — seven ported from the HyperFrames catalog (Apache-2.0)

`chart-story`, `count-up`, `hw-callout-circle`, `hw-scribble-transition`,
`line-swap`, `marker-highlight` and `ui-focus-zoom` are derived from HyperFrames
catalog items (Copyright 2026 HeyGen, Inc., Apache License 2.0) and modified by
Project Sniper; each file's header carries its attribution and modification notice.
No other composition is recorded as derived from third-party code
(`scripts/producer/graphics/catalog_discovery_sources.py` `PORTED_KINDS` lists exactly
these seven).

## icons/ — Simple Icons (CC0) brand marks and Lucide (ISC) glyphs

See `icons/PROVENANCE.md` and `icons/lucide/PROVENANCE.md`.
