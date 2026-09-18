# Palmier source trims use a conformed timebase

## Finding

Palmier accepts source trim boundaries in seconds, then exposes those trims as
integer frames on the project timebase. When a fractional-rate source is
conformed to an integer project rate, Palmier may report the adjacent source
frame even though the output placement and duration are correct.

The live failure that exposed this used a 23.976 fps source in a 24 fps Palmier
timeline. A source start of `15.281s` mathematically rounds to frame `367`, while
Palmier read back `trimStartFrame: 366`. The generated timeline still tiled at
the expected output frames.

## Rule

Verify these concerns separately:

- Source `trimStartFrame` and `trimEndFrame`: allow at most one conformed frame.
- Output clip placement, seams, total duration, media identity, speed,
  transforms, and keyframes: retain their existing exact or explicitly bounded
  checks.

Never turn this into a general timeline tolerance. A two-frame source-trim
difference still fails closed, and a one-frame output-placement difference is
still a defect unless its own contract explicitly permits it.

## When not to use it

Do not use this tolerance to excuse a wrong source range, a stale plan, a clip
on the wrong track, a duration mismatch, or progressive drift across cuts. It
only covers the single-frame quantization ambiguity at a source-second boundary.
