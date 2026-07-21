# Render oracles must check the last encoded frame

## Finding

A timeline ending at duration `D` does not imply the encoded file contains a
sample at `D`. At 30 fps, a 2.5-second render contains 75 frames whose timestamps
run from `0` through `74/30 = 2.4667` seconds.

The first offline `section-marker` proof faded its foreground element but left a
full-frame scrim visible. After the fade target was corrected to the complete
stage, the last encoded frame still retained 21.88% of the mid-animation alpha:
the GSAP fade ended at 2.5 seconds, a time the file never sampled.

Ending the fade at `D - 1/fps` aligned it with the last encoded timestamp. The
next oracle measured final-frame alpha as zero while preserving the requested
accent color in more than 10,000 pixels on the visible middle frame.

## Rule

For an `N`-frame constant-rate render, inspect at least:

```text
first timestamp = 0
last timestamp  = (N - 1) / fps
```

Assert decoded frame count, duration, format, dimensions, every-frame decode,
one meaningful visible-state pixel oracle, and the final encoded frame. Bind the
oracle result to the artifact hash; checking a nearby preview frame is not the
same proof.

## When not to use this approach

Do not force every animation to fade out merely to satisfy a generic test. An
own-screen takeover may intentionally remain opaque through its last frame, and
a loop may intentionally wrap. The oracle should encode the composition's
declared terminal state. Variable-frame-rate media needs decoded timestamps,
not the constant-rate formula above.
