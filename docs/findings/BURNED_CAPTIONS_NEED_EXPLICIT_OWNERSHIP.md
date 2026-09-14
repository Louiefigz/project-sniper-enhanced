# Imported captions need explicit ownership

A real source import on September 14 exposed a mismatch: the native Shorts
renderer could preserve a creator's complete picture, but validation required
native caption views across the whole timeline. A source with its own burned-in
captions would therefore receive a second caption layer or fail assembly.

Use `canvas.captionMode: "source-burned"` for a continuously displayed source
whose existing captions have been visually inspected. Keep `captionViews: []`.
The shared validator rejects added native views, nonempty caption corrections,
and gaps in source-picture coverage. It permits overlapping source panes whose
combined intervals cover the complete frame clock. Cropping or overlaying the
actual burned text still requires pixel review; temporal coverage alone cannot
prove that text remains visible.

Source occurrences and phrase groups remain unchanged for speech and pacing
evidence. The mode changes the visual binding, not the source timing hash. Pacing
reports identify phrase measurements as transcript-group observations and leave
burned-caption timing unmeasured. A transcript cannot prove the spelling or
highlight timing of text embedded in video pixels. Native display corrections
cannot edit those pixels and must not be silently accepted.

The renderer provides an explicit comment mount for shared custom scene markup,
so importing source captions does not require a hidden dummy caption element.
Absent mode and explicit `native` retain historical HTML, bindings and report
behavior. Writer/cold-reader roundtrips and failure tests cover the new mode.

Do not use this mode to turn captions off, to conceal native caption errors, or
when replacement B-roll removes the source captions. Such edits need an authored
caption treatment that remains visible in the actual output.
