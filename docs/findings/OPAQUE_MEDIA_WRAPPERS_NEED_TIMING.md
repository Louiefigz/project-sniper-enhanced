# A hidden video can leave its wrapper visible

## What failed

The 21.4-second Trevor/Skool Short used two real supporting videos in a lower
viewport. Each video had the proper HyperFrames clip timing. Its ordinary parent
div carried the crop and camera transform. Adding a background to that untimed
parent made it paint before its child video started.

The later insert's parent was above the earlier insert in the stacking order.
It covered both the opening full presenter and the earlier real Skool video.
Native frame 0 and frames 70, 100, 146 showed the defect. The title and captions
still appeared because they used higher layers.

```css
/* The video is timed, but this background is not. */
.community-crop {
  position: absolute;
  top: 880px;
  height: 1040px;
  z-index: 4;
  background: #f2eee6;
}
```

## The correction

Use a transparent crop wrapper when the shared canvas already supplies the
background. Keep framework ownership of the actual timed video and retain the
existing deterministic exit mask. If the background itself is part of a shot,
give that visible layer explicit timing as well.

Do not assume a child's clip window hides its ancestors. This applies equally
to Short and long-form compositions, including inactive images, borders, shadows,
pseudo-elements and other visible wrapper decoration.

## Why the automated checks did not catch it

The first export's technical checks compared the encoded result with the same
authored composition. Both contained the unwanted background, so those checks
agreed. The export completed technical checking in 245.16 seconds, with 254 encoded
frame comparisons, but it was rejected by visual review. Matching output to code
does not establish that the picture satisfies the storyboard.

For real insert review, inspect an opening full-presenter frame, the first frame
and settled state of every insert, the frame immediately after its exit, and the
final full-presenter return. Verify the actual source pixels are visible, not
just that a video element exists and has valid timing. Inspect the first insert
even when a later insert uses the same asset successfully.

Evidence remains in
`artifacts/img7138-dms-community-short-2026-09-15/export-01/` and
`VISUAL-REVISION-02.json`. The original project and export remain unchanged;
the corrected build uses a new project/export path. Audio and selected media can
be reused only after their existing content and timing checks pass.

## When not to remove the background

A persistent scene background may intentionally span multiple child clips.
Keep it when that is the planned visual state. The defect is a mismatch between
the parent's visible lifetime and the shot's intended lifetime, not the mere
presence of a background color.
