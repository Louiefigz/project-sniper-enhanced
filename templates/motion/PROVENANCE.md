# templates/motion — vendored asset provenance

## vendor/gsap/SplitText.min.js + vendor/gsap/DrawSVGPlugin.min.js (GSAP 3.14.2)

- Source: the official npm `gsap` package, v3.14.2, via jsDelivr
  (`https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/SplitText.min.js` and
  `.../dist/DrawSVGPlugin.min.js`, vendored 2026-07-11; SplitText 7,779 bytes,
  DrawSVGPlugin 4,351 bytes). Since GSAP 3.13 the formerly members-only bonus
  plugins ship in the public npm package — these ARE the official free builds.
- Version: 3.14.2 (matches the pinned local `vendor/gsap/gsap.min.js` core every
  registered comp loads — plugin and core versions MUST stay in lockstep when
  either is bumped).
- Licensing: GSAP standard "no charge" license —
  https://gsap.com/standard-license (per each file's `@license` header:
  "Copyright 2025, GreenSock. All rights reserved. Subject to the terms at
  https://gsap.com/standard-license"). As of GSAP 3.13+ (post-Webflow), the
  standard license covers ALL uses including commercial, for the whole toolkit
  including these plugins. The npm package ships no LICENSE file;
  `vendor/gsap/README.upstream.md` is the verbatim upstream README kept
  alongside as the record ("Standard 'no charge' license:
  https://gsap.com/standard-license").
- Consumed by (opt-in only; comps that don't load them are unaffected):
  - `compositions/punch-shout-lockup.html` — `splitText:true` per-word staged
    reveals (SplitText; pop timing stays under the ≤2-frame law).
  - `compositions/statement-card.html` — `splitText:true` per-char staged
    word-rise in the classic build (SplitText).
  - `compositions/stroke-draw-badge.html` — DrawSVG stroke-draw → flood-fill
    icon badge (the Punch save-CTA move).
- Serving: hyperframes serves the project dir as the web root, so comps load
  them as `<script src="/vendor/gsap/SplitText.min.js">` — local files, no
  extra CDN fetch at render time.
