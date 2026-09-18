# Rendered graphics require sustained visible-pixel proof

## The defect

File existence, dimensions, duration, and codec metadata cannot prove that a
viewer receives a graphic. An opaque all-black MP4 reports a fully occupied
canvas while carrying no meaningful card content. A transparent overlay with
one nonzero-alpha speck can satisfy a maximum-frame test even though it is
invisible for the rest of its duration.

Both assets are technically valid and editorially blank.

## The invariant

Proof must inspect the rendered pixels over time before handoff:

- opaque assets must contain meaningful non-flat visual content, not merely an
  opaque background;
- alpha assets must retain alpha and show meaningful nonzero-alpha area;
- meaningful occupancy must persist across a required share of sampled frames,
  rather than appear in only the peak frame;
- dimensions, duration, frame count, copy inputs, and render-input identity
  remain part of the same receipt.

The proof is generated from the final rendered asset, not inferred from the
template spec or browser DOM. A perfect authoring record cannot rescue blank
pixels.

## Why a temporal requirement matters

Entrances and exits legitimately contain low-occupancy frames, so requiring
every frame to be full would reject good animation. Using only the maximum has
the opposite failure: a corrupt or transient frame can bless an otherwise
empty clip. Sampling across the asset and enforcing a sustained threshold
preserves animated ramps while rejecting one-frame artifacts.

## Verification

`test_graphics_asset_occupancy.py` renders real FFmpeg fixtures for a visible
opaque card, a fully black opaque card, and a one-frame alpha speck. The first
produces measured content below full-canvas occupancy; the latter two fail
before delivery.

## When not to use it

Do not interpret occupancy as a taste score or demand that every layout fill
the frame. A restrained lower third can occupy a small area and still pass when
that area is meaningful and sustained. This proof answers whether content
rendered, not whether the composition is beautiful.
