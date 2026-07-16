# An editable NLE handoff is a parity contract, not an export

## The failure pattern

A pipeline can create a real NLE project and still lose the edit. “Sent through
MCP” proves transport; it does not prove that every decision remained editable.

The audited Sniper project had:

- 10 cuts that mapped to native clips;
- 14 motion graphics that mapped to separate clips but baked their internal
  copy, shapes, icons, and animation;
- 3 zooms with approximate easing;
- 12 ramp/aliveness moves with no translation;
- captions and dialogue enhancement that were absent as native lanes.

The old binary preflight could therefore confuse “the translator produced some
steps” with “the destination contains the edit.” Those are different claims.

## The better model

Inventory every content-affecting element and classify it:

```text
exact | approximate | baked | unsupported
```

Only `exact` earns an editable handoff. Then read the destination back and
compare expected versus actual ids, counts, ranges, trims, speed, transforms,
text/media identity, and keyframes. Persist that proof next to the output.

This catches two distinct failure classes:

1. **translation loss** — an element was never expressed natively;
2. **execution drift** — the intended native element was expressed, but landed
   on the wrong track, frame range, media, or property value.

## Why fail-closed matters

Future plan vocabulary is especially dangerous. If a new `reframe`, graphic
treatment, or audio lane is added and the handoff ignores unknown fields, old
code can keep reporting success while silently deleting new creative work.
Unknown content lanes must therefore become unsupported findings by default.

## When not to use this rule

Do not require native parity for a delivery-only export where the user wants a
finished MP4 and explicitly does not intend to edit it. Baked graphics and a
mastered audio bus are often preferable there.

Do require it whenever the product promises “open this in the editor and keep
working.” In that workflow, visual similarity is insufficient; editability is
the deliverable.
