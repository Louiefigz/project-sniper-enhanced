# HyperFrames Catalog Study — mechanism-level map of all 372 items

**Studied 2026-08-28** by reading every item's source in `vendor/hyperframes-catalog/`
(4 parallel readers, one record per item). Machine-readable records:
`slice-1..4.json`, merged in `catalog-study.json` — fields: mechanism, variables,
scrubSafe, selfContained, fit, quality, aspectFlex, port priority. Two files missing
upstream: `lt-neon-border` (registry add error), `texture-mask-text` (absent from
mirror). Operator directive behind this study: **prefer the catalog's tried-and-true
graphics over our hand-built comps** (memory: feedback_prefer_catalog_graphics).

## Inventory verdict

| | count |
|---|---|
| Total studied | 372 (370 sources read) |
| **P0 — port-worthy now** | **34** |
| P1 — worthy, second wave | 95 |
| P2 — niche/later | 121 |
| skip | 122 |
| New capabilities we lack | 146 |
| Upgrades of existing comps | 100 |
| Transitions | 39 |
| Unfit (product demos, dev showcases, art pieces) | 87 |

## The P0 list by role in our grammar

**Hand-drawn emphasis family (most brand-native — cream/paper/marker, fonts bundled
in the mirror):** `hw-boil` (the family's runtime: one onUpdate dispatcher + seeded
boil — port once, unlocks the family), `marker-highlight`, `hw-callout-circle`,
`hw-arrow`, `vox-annotate`, `whiteboard-ink`, `marker-checklist-card`,
`freeze-frame-dressing`.

**Data/evidence beats:** `chart-story` (one comp, 4 chart forms landing exact values
— fills the trend hole ledger/scoreboard can't), `count-up` (stat-card upgrade),
`decline-chart`, `mk-line-graph`, `bar-chart-race` (16:9), `telemetry-hud`.

**Hooks & text kinetics:** `line-swap` (setup-then-subvert masked line replacement),
`per-word-rise` (VO-cue-timed word landings), `ticker-takeover`,
`mk-callout-highlight` (speech-synced emphasis sweep), `testimonial-proof-card`.

**Story/scene cutaways:** `chat-thread` (iMessage DSL), `notes-typing`,
`notification-stack`, `native-notification-pop`, `yt-comment-card` (needs
CONFIG→variables port).

**Screen/tutorial cutaways:** `ui-focus-zoom` (camera punch-in on screenshots),
`browser-device-stage` (device chrome around a screen slot), `code-terminal-run`,
`typed-prompt`, `toggle-flip` (exact fit for the ads-toggles doctrine),
`yt-feather-highlight` (spotlight-dim attention direction over recordings),
`split-tilt-cards`, `before-after-wipe`.

**Transitions:** `hw-scribble-transition` (alpha scribble bands with a solid
backstop covering the cut 0.85–1.35s — textbook EXIT-LAW-compatible stinger) and
`whip-pan-cut` (one strip carries both scenes, seam velocity exact by construction).
NOTE: the 13 `transitions-*` files and all WebGL "shader transitions" are 1920×1080
showcase/spec-sheet pages registered as `"main"` — recipe mines, NOT mountable comps.

**The single most portable idea:** a recurring `cues` variable (comma-separated
seconds clamped into the hold) across notification-stack, per-word-rise,
radial-surround, screen-flow-carousel, scroll-feed, spring-stack-shuffle — it maps
1:1 onto our VO-timed beat placement. Adopt `cues` as a standard slot in ported
comps so the planner can land reveals on transcript words.

## The catalog's house style — adopt as OUR porting/authoring doctrine

These patterns recur across the good 250+ items and exist because the render engine
seeks arbitrarily (`tl.seek()` suppresses events). Codify them:

1. **Paused registered timeline; `fromTo` with BOTH endpoints explicit +
   `immediateRender:false`; `gsap.set` for initial state; never `gsap.from`.**
2. **Property-setter drivers** (get/set on a tweened object) instead of
   timeline-level `onUpdate` — which does NOT fire on seek. Tween-level `onUpdate`
   is narrower than it looks: callbacks fire only on event-firing seeks, and only
   the RENDERER seeks that way (`tl.seek(t)` with `suppressEvents=false`).
   HyperFrames Studio and the editor preview shim both seek with events
   SUPPRESSED, so a tween-level-`onUpdate` comp renders perfectly and then sits
   frozen on every review surface (proven on ui-focus-zoom, review F4 2026-08-28;
   converted to the setter driver). The setter driver is the only pattern safe on
   every surface — prefer it for anything that must preview in Studio.
3. **Painter pattern** for canvas: one inert anchor tween spans [0,D]; every frame
   repaints from scratch as a pure function of `tl.time()`.
4. **Seeded determinism only**: mulberry32 / `Math.imul` LCG / sin-fold hash, built
   once synchronously before registration. `Math.random`/`Date.now` never appear in
   the good half (every grep hit was a comment asserting their absence).
5. **Typed/ticking text = precomputed text-at-time tables** applied via `tl.set`,
   never incremental state or innerHTML callbacks (those don't rewind).
6. **SVG stroke draws set `stroke-dashoffset` as an ATTRIBUTE** from
   `getTotalLength` — never the CSS property (Chrome under-invalidates reverse
   seeks) and never `pathLength`.
7. **Envelope law**: fixed IN/OUT (compressed together when short), only HOLD is
   elastic, never `timeScale`; hold breathing = finite floor-computed repeats;
   ambient sine drift ends phase-exact at zero.
8. **State machines = `tl.set` attribute flips** (GSAP records prior values →
   backward seeks restore exactly).
9. **Transforms only, never left/top** (layout props snap to device pixels under
   frame capture); container-query units measured to px once at mount.
10. Closed-form physics (analytic springs, sampled from linear drivers), not
    simulation. `exit:"none"` hold-to-cut is their default too — same as THE EXIT LAW.

## Trap list (verified in code — check before trusting any item)

- **Registration-key mismatches**: all shader/spec-sheet demos + `swirl-vortex`,
  `thermal-distortion`, `whip-pan` register `"main"`; the `vfx-*` family and the 14
  `code-snippet-*` themes register under different ids than their catalog names.
- **CONFIG-not-variables families**: all `mk-*`, `yt-comment-card`,
  `beat-freeze-cut` (its beat params are hardcoded despite a variables schema).
- **Network at runtime**: `spain-map`, `us-map*`, `world-map` fetch topojson from a
  CDN; `us-map-flow` also has a wallclock `onComplete` tween (stale dots on reverse).
- **Baked demo copy**: the entire caption family (15 files, Google-Fonts-dependent,
  demo transcript baked), the `lt-*` lower-thirds ("Maya Chen" hardcoded, fonts
  never loaded, one has a width hardcoded to the demo name), `notes-reveal`.
- **Missing assets**: `tiktok-follow`, `yt-lower-third`, `vpn-youtube-spot`
  reference files absent from the mirror; `touch-indicator` assumes a host GSAP.
- **Outright scrub-unsafe**: `grain-overlay` (infinite wall-clock CSS animation);
  `motion-blur` (frame-order-dependent); `reddit-post` (onStart text mutation);
  `flowchart*` (innerHTML callbacks); `morph-text` (reduced-motion branch registers
  no timeline); the 12 `apple-terminal` themes (callback typing).
- `terminal-simulator` does not type (static skeleton); `matrix-decode` has no
  decode; `apple-money-count` has no sound despite descriptions.

## Port contract (unchanged; how an item enters the vocabulary)

Mirror → `templates/motion/compositions/<kind>.html` rewritten to our conventions
(tokens.css brand vars, local gsap, `getVariables()`, `__timelines[kind]`,
`data-start="0"`) → typed `data-composition-variables` (+ `cues` where applicable)
→ `template_contract` slot schema → capability probe (EXIT-LAW measurement; never
run concurrently with test suites) → CLI + Studio session lint clean → determinism
double-render check → planner eligibility wiring. First wave in progress; per-item
detail for everything else lives in `catalog-study.json`.
