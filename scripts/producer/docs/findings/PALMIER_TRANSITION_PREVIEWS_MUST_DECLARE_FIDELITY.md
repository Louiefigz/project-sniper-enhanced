# Palmier transition previews must declare fidelity

## Finding

Palmier currently exposes no native transition primitive. Dropping the plan's
transition lane from a working checkpoint makes a correct plan look unfinished,
but calling an arbitrary keyframe move “the transition” is equally misleading.

The safe progressive-preview boundary is narrower:

- **White flash:** render a three-frame, full-canvas alpha overlay. Normal alpha
  composition to white is visually equivalent to the renderer's screen-to-white
  equation. The clip is still baked, not a native editable transition.
- **Light leak:** render a short orange-to-pink alpha overlay, but label it
  **approximate**. The delivery renderer uses a luma-screen blend and stronger
  chroma wash that normal Palmier alpha composition cannot reproduce exactly.
- **Zoom pull:** do not translate it yet. Its whip form needs a blur-masked peak
  across outgoing and incoming clips. Writing scale keyframes alone both loses
  the mask and risks replacing an existing punch track.
- **Transition SFX:** keep it explicit as render-only until the checkpoint owns
  a verified audio-track placement and readback contract.

## Enforcement

`palmier/transition_preview.py` content-addresses and renders supported visual
previews as alpha ProRes, then uses the same media proof gate as motion graphics.
`palmier/checkpoint_plan.py` fails the checkpoint if a supported required visual
cannot render or prove; unsupported kinds and SFX become named omissions.

The checkpoint sidecar and event stream keep `limitations` separate from
`omissions`, so “visible but baked/approximate” cannot be confused with “missing.”

## When not to use this

Do not use these overlays as proof of final transition parity, for final audio
approval, or as a substitute for the governed render/QC pass. They exist to make
plan progress visible without overstating Palmier's editing vocabulary.
