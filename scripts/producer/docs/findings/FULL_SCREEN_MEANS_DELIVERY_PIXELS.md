# Full-screen means delivery pixels, not matching aspect ratio

## Finding

An `own-screen` graphic rendered at `1920x1080` does **not** fill a
`3840x2160` delivery merely because both are 16:9. FFmpeg's `overlay=x=0:y=0`
does not scale the overlay; it places the 1920x1080 pixels unchanged in the
top-left quarter of the 4K frame.

The same pixel rule applies to a `free-band` graphic whose transparent asset is
a full delivery-canvas composition. Alpha changes which pixels are visible; it
does not make FFmpeg scale the invisible canvas around them.

That was the exact geometry behind the bad full-screen-card failure: the card
covered 25% of the delivery pixels while its plan still truthfully said
`anchor: "own-screen"`.

## Deterministic rule

For every full-canvas graphic (opaque takeover or transparent overlay):

1. Probe the rendered comp and delivery dimensions.
2. Fail when their aspect ratios differ by more than `0.002`.
3. When the aspect matches but the pixel dimensions differ, scale the comp to
   the exact delivery width and height before overlaying it.
4. For an alpha overlay, scale its offset, explicit placement, content bbox,
   and placed bbox by the same authored-to-delivery factors. Scaling only the
   clip strands its geometry in the authored coordinate space.
5. For an own-screen takeover, persist
   `placedBBox = [0, 0, deliveryW, deliveryH]` and fail Audit B unless it exactly
   matches the recorded delivery canvas.

For example, a `1920x1080` comp on a `3840x2160` delivery now inserts:

```text
scale=3840:2160:flags=lanczos
```

before the overlay and records:

```json
{"placedBBox":[0,0,3840,2160],"canvas":[3840,2160]}
```

Hole/PIP takeover rectangles must scale by the same delivery factor. A hole at
`[1344, 60, 534, 960]` on 1080p becomes
`[2688, 120, 1068, 1920]` on 4K; scaling only the card would misalign its live
footage fill.

## When not to use this

Do not stretch a comp across a delivery with a different aspect ratio. That is
an authoring/canvas error, not a scaling opportunity. Do not blindly multiply a
face-relative auto-placement either: its region may already be expressed in
delivery pixels, and its fit must be chosen against the delivery-scaled content
footprint. Until that resolver is coordinate-aware, a resolution mismatch on a
face anchor must fail loud; explicit authored placement remains safely scalable.
