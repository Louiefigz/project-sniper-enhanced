# Source frame caches need a zero-based clock

## What failed

The September 15, 2026 pricing Short revision completed its picture render, but
the native reference check correctly rejected three source caches:

| Source span | Actual PNG files | Required timeline samples |
|---|---:|---:|
| `source-0-1` | 56 | 57 |
| `source-1-1` | 263 | 264 |
| `source-3-1` | 269 | 270 |

Each cache had a completion marker. That marker did not establish that its
frames covered the requested timeline. The SDK's frame lookup held the last
available frame, allowing the picture render to finish despite the shortage.

## Why it happened

The selected-source preparation retained fractional media seek times. The SDK
extracted a duration with `-ss`, `-t`, and `fps=25`, but the resulting first output
sample could begin after zero. Our cache lookup indexes samples from zero.
Those two clocks disagreed.

This was not a floating-point error in the verification assertion. Subtracting
a small tolerance from a duration calculation cannot create missing samples.

## Measured experiment

A supervised test used the same original-resolution prepared source, seeking
to `7.043333333333` seconds for a 2.28-second timeline span at 25 fps:

- Duration-based extraction produced **56 PNGs**.
- An explicit 57-frame extraction with `fps=25:start_time=0` produced **57 PNGs**.
- Every original frame `i` matched corrected frame `i + 1` byte for byte.
- Corrected frames 0 and 1 matched each other; later adjacent frames differed.
- The corrected final frame was the same genuine decoded final frame.

Anchoring the output clock fills the initial fractional-seek gap with the first
available decoded picture. It does not invent a new final picture. The experiment
took 21.35 seconds, and the shared supervisor verified child cleanup.

Evidence: `artifacts/img7138-pricing-real-first-2026-09-15/extraction-boundary-01/`.
The two commands, source hash, complete frame hashes, and owner receipt remain
available there. This small experiment alone is not full export qualification.

## Required behavior

The qualified runtime and cache validator share the same sample-count rule:

```javascript
Math.max(1, Math.ceil(duration * fps - 1e-7))
```

Validate finite positive inputs, anchor the constant-frame-rate extraction to
zero, request an exact output count, and reject a short result before publishing
the cache. Include the clock policy in cache identity so old complete-marked
entries cannot masquerade as corrected entries.

Keep the exact consecutive-frame check. Do not weaken it to accept one missing
frame, duplicate a cache file manually, or manufacture a completion marker.

## Limits

A genuine source EOF still fails if it cannot supply the requested count.
The single-final-frame path and existing variable-frame-rate policy require
their own regression coverage; the measured constant-frame-rate case does not
prove those paths. Native reference checks, encoded checks, editorial review,
and live playback remain separate obligations after a runtime change.

## Integration result

The corrected qualified SDK prepared all ten actual video entries in 33.63
seconds under the shared supervisor. The affected spans produced exactly
57, 264 and 270 consecutive frames; all ten cache identities matched the
shared reader. Cleanup was verified. Evidence is in the same revision's
`source-cache-preflight-01/` directory. Thirty-two focused regression tests and
an independent semantic/standards review also passed. Full export qualification
is recorded separately in the revision's delivery and handoff receipts.
