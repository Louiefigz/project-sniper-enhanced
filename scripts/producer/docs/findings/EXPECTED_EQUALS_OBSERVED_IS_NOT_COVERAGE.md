# Expected Equals Observed Is Not Coverage

## The trap

A decode receipt can look internally perfect while proving almost nothing:

```json
{"expectedPackets":1,"decodedPackets":1}
```

Equality only proves that two claims agree. It does not prove that either claim
covers the complete media. The same mistake applies to frame windows, contrast
samples, protected-region scans, and effect-color samples.

## What closed the gap for deterministic MP4 R0

The evidence validator now binds each claimed population to separate authority:

- expected video frames and packets must equal the final media's measured frame
  count;
- decoded frames and packets must equal that independently bound expectation;
- decoded audio samples must cover the final media duration within a fixed AAC
  padding tolerance;
- AAC packet count must be plausible for 1,024-sample access units;
- effect sample count must equal the complete plan-derived frame window;
- decoded-color, contrast, and protected-region counts must all equal that same
  window;
- the terminal Audit-B receipt must reference the exact already-sealed
  full-decode and effect-proof artifacts.

For the canonical test fixture, the independent facts are 120 video frames at
30 fps and 192,000 samples per channel at 48 kHz. A forged one-packet receipt is
internally equal but fails the AAC coverage binding.

## General rule

For every `expected == observed` check, identify where `expected` came from. It
must be derived from immutable upstream bytes or an independent measurement,
not copied from the observation being judged.

Do not use this stricter rule when the population genuinely has no independent
definition. In that case, label the value as a diagnostic observation rather
than an approval gate.
