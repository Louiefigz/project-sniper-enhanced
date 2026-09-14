# Short exports need the same delivery gates as long videos

Short duration reduces media volume. It does not eliminate frame-boundary errors,
moving subjects, audio generations or color metadata. Three portrait Shorts
(8.24s, 13.04s and 23.32s) exposed all four after earlier static/preview checks.

The offer's outgoing portrait leaked at frame 90. Members showed two presenter
crops at frame 12. Explicit seek-safe timeline exits clip outgoing elements at
their output clock:

```javascript
timeline.set(element, {clipPath: 'inset(100%)'}, endFrame / frameRate);
```

The shared helper defines the initial unclipped state for reverse seeks too.
Check actual frames before, on and after the boundary. Snapshot and export APIs
can disagree at an exact boundary; a snapshot alone is not proof of the export.

Raw AAC clocks passed, but decoded local checks failed in one, one and sixteen
windows. Sharing long-form float mastering then encoding AAC once at 256 kb/s
passed every window at roughly −14.1 LUFS / −2 dBTP. Visual revisions retained
that AAC unchanged. Keep mastering separate from a source-unity comparison:
purposeful gain/limiting changes belong in the intended reference signal.

The native renderer's sRGB behavior was mislabeled BT.709 transfer. A measured
metadata correction preserved picture payloads and AAC; all 23 sampled reference
comparisons then passed MAE ≤ 2 / PSNR ≥ 40 dB. Do not retag arbitrary footage to
make it look better. This repair follows exact renderer evidence. Match opaque
capture settings too: transparent PNG is not equivalent to opaque JPEG output.

Reuse execution mechanisms, then compare unchanged output. One matched warm
export went from 49.962s / 3.825 GiB to 34.733s / 2.174 GiB using long-form
file-backed frame transport. All 326 decoded frames and audio were identical.
This is one pair, not a general speed guarantee. A copied project unexpectedly
missed cache because absolute path and mtime were part of identity. Report hits,
not an assumption that any second run is warm.

See the [qualification report](../producer/SHORTS_REAL_EXPORT_QUALIFICATION_2026-09-10.md)
for evidence and application connections still needed. Technical passes cannot
establish a persuasive hook, complete story or coverage of every studied style.
