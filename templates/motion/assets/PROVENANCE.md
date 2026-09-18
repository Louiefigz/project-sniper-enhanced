# templates/motion/assets — variable-referenced comp assets

Image files that comps reference **through a spec variable** (the `image`
asset slot — see `graphics/template_catalog_contract.py`). Selectors are
motion-web-root-relative (`assets/<file>`); `template_contract.resolved_assets`
returns each resolved file so the render cache hashes its bytes. Brain-supplied
screenshots for `ui-focus-zoom` are copied here at plan time.

- `sample-screen.png` — deterministic token-styled dashboard mock, generated
  locally with Pillow (no network, no real product's UI); the registered
  preview/probe screenshot for `ui-focus-zoom` (`_PROBE_OVERRIDES`).
