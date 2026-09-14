# Port the Director's decision process with its templates

A template ID written after a hook has already been drafted does not establish
that the template shaped the decision. Sniper's native Shorts strategy must
choose a format and hook template before scene assembly.

The Script Director's Shorts lane provides the sequence: identify the actual
payoff and viewer, choose a format, choose one named hook anchor and its reference
example, fill that same template two or three ways, audit each opening, then
independently review the selected result. The YouTube publishing-title workflow
is a separate decision and cannot substitute for this screen-hook process.

## Reuse the source libraries

On 2026-09-10, the shared library contains 11 formats, 190 named anchors, and
326 reference/training examples. The older formula index covers only 234
examples. Loading that index alone would omit 92 solution-aware training
examples. Sniper now reads all six canonical documents and preserves their
exact bytes with each planning attempt.

```ts
const catalog = loadDirectorCatalog();
const plan = validateDirectorPlan(authorOutput, catalog, source);
// A separate invocation critiques this exact plan before scene planning.
```

The retained record identifies the selected and rejected alternatives, filled
slots and source quotes, hook variants, condition evidence, and critique. Stored
decisions use their frozen library snapshot during reconstruction, so later
library edits do not silently change old work.

## What the checks establish

Executable checks can reject nonexistent anchors, missing slots, invented source
quotes, failed conditions, and a critic verdict bound to another plan. They
cannot prove that a truthful hook is compelling. That remains editorial judgment.
Likewise, a contrast plan in text is not a pixel measurement, and a passing
strategy critique does not qualify a render.

Do not use this recorded-footage adapter as a scriptwriting interview for a new
recording. It preserves the accepted spoken words and cut. Do not use its test
fixtures as proof of creative quality: author and critic replies in those tests
are explicitly simulated.
