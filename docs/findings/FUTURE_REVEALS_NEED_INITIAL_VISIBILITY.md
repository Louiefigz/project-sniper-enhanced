# Test the state before a reveal

An offer Short passed frame-clock, layout and encoded-picture checks, but actual
review of output frame 384 showed “+ Timeframe” before “Specific outcome.” The
formula terms had future GSAP `fromTo` calls with `immediateRender:false`, and
their CSS left opacity at its visible default.

The first outcome fade began at frame 384, plus at 426 and timeframe at 445.
Before a future tween ran, its term was already visible. The timeframe could then
disappear at its own reveal and fade back in. A late checkpoint at frame 479
could not detect that wrong sequence.

Initialize the three terms with CSS `opacity:0` and retain the authored reveal
times. Check future terms at frame 384, the last hidden frames 425 and 444,
and settled terms at 390, 430 and 451. Retain forward and reverse captures of
these states, then inspect the encoded pixels. Matching an encoded output to
its own renderer only proves fidelity; both can faithfully reproduce a bad
story state.

This correction applies to intentionally hidden future elements. Do not hide
every scene element globally: persistent labels and already introduced objects
should remain visible for their authored reading interval.

The failed visual example remains under
`artifacts/shorts-qualification-2026-09-14/export-offer-persistent-01`, with its
decoded boundary evidence in `frames-offer-persistent-01`. Its technical pass
is preserved separately from its failed editorial review.
