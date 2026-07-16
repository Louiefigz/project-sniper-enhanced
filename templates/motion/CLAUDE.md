# templates/motion — PROJECT_SNIPER HyperFrames compositions

This directory holds the **hand-authored HyperFrames compositions** the PRODUCER
pipeline renders. It is NOT an upstream HeyGen `hyperframes init` project: there is
no `npm run check`/`publish`, no `hyperframes.heygen.com/llms.txt`, no `meta.json`
workflow here. Ignore any of that — the code below is the whole contract.

- **What renders these:** `scripts/producer/graphics/graphics_render.py` (read it +
  `scripts/producer/CLAUDE.md` → Graphics before authoring). Each `graphicsTrack`
  entry (`docs/producer/PRODUCER_MOTION_GRAPHICS_PLAN.md` §3.1) selects a comp by `kind` →
  `compositions/<kind>.html`.
- **Layout:** `compositions/*.html` (the comps, ~46), `tokens.css`,
  `motion-tokens.js`, `icons/`, `renders/cache/` (content-hash render cache).

## The one render invocation (pinned)

`graphics_render._render_to` spawns exactly this — nothing else calls hyperframes:

```bash
npx --yes hyperframes@0.7.33 render <this-dir> -c compositions/<comp>.html \
    --format {mov|mp4} --variables <json> -o <out>
```

`hyperframes@0.7.33` is pinned (`HYPERFRAMES_PACKAGE`). The pipeline renders a
throwaway `_gs-<hash>.html` copy of the target comp (never edits your file).

## Anchor → format (alpha rule)

- **own-screen** takeover → opaque **`.mp4`**.
- **every overlay anchor** (free-band / focus-shift / headroom / chest / beside-face)
  → **ProRes 4444 alpha `.mov`** (`graphics_render._FORMAT_BY_ANCHOR`).
- **Never `webm`** — it drops the alpha channel (proven, edge G2). `.mov` is the
  only alpha-preserving product here.

## Authoring contract (every comp MUST follow)

1. **Declare params** as JSON on `<html data-composition-variables='[…]'>`, and
   **READ them at runtime** via `window.__hyperframes.getVariables()` (merge over
   your own defaults). `--variables` fills these; it can NOT set render length.
2. **One timeline**, paused, registered by composition id:
   ```js
   window.__timelines = window.__timelines || {};
   window.__timelines["<composition-id>"] = gsap.timeline({ paused: true });
   ```
3. **`data-duration` on the root element IS the render length** — hyperframes fixes
   it at compile time and IGNORES `--variables` for it. Do not try to parametrize
   duration; the pipeline rewrites the root attr per window via
   `graphics_render._set_root_duration`. (Child `.clip` elements keep their own.)
4. **Determinism only** — no `Date.now()`, no `Math.random()`, no `repeat: -1`,
   no network fetches in comp logic. Renders must be byte-reproducible for the cache.
5. **GSAP core loads from a CDN** (`cdn.jsdelivr.net/npm/gsap@…`) at render time, so
   the render host needs network. Comp assets are otherwise self-contained.

## Verification (NOT `npm run check`)

A comp/entry is validated by `template_contract.validate_entry` (schema + declared
variables) and the rendered file is proven by `asset_proof.prove_rendered_asset`
(format/alpha/dimensions/duration). Run the producer selftest, not any `npm run`
target: `cd scripts/producer && PYTHONPATH=.:tests ../../.venv/bin/python3 selftest.py`.
