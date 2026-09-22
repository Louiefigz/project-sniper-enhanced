# A bounded gain loop does not prove convergence

## Why this matters

The mastering filter has three branches: measured linear loudnorm, static gain
with a true-peak limiter, and dynamic loudnorm for unusable or near-silent input
statistics. The static branch uses a bounded number of full-program dry runs.
That bound keeps preparation predictable; it does not guarantee that the
selected final filter landed within the preparation tolerance.

The incremental revision plan asked for the selected branch and converged gain.
Reading the actual loop revealed a distinction a receipt must preserve.

## Concrete example

This is a synthetic callback example used by `test_mastering_decisions.py`, not
a claim about a particular person's recording:

- Measured input is -35 LUFS; the target is -14 LUFS.
- The initial selected gain is +21 dB.
- Dry run one reports -15 LUFS, so gain becomes +22 dB.
- Dry run two also reports -15 LUFS, so gain becomes +23 dB.
- The two-run budget ends. The returned filter uses +23 dB.

The +23 dB filter was never dry-run measured. Calling that value a “converged
gain” would assert evidence the loop does not have.

There is a second precision issue: a warning message formats gain to one decimal
place, while the filter applies two. A +21.23 dB filter produces a +21.2 dB
human-readable note. Parsing the note cannot recover the exact selected filter.

## Receipt contract

`audio/mastering_filter.py` now retains its choice directly while building the
same filter. A static decision includes:

```json
{
  "branch": "static",
  "gainDb": 23.0,
  "convergence": "budget-exhausted",
  "selectedFilterMeasured": false,
  "staticTrimToleranceLu": 0.1
}
```

The full record also carries each actual dry-run filter and integrated LUFS,
the selected filter, input statistics and processing profile. Possible static
outcomes are `converged`, `budget-exhausted`, and `measurement-unavailable`.
Linear and dynamic choices say `not-applicable` for static convergence.

No extra dry run is performed to populate the receipt. Existing filter strings,
rounding, iteration limits, limiter settings and delivery gates are preserved.

## Where the evidence goes

Ordinary master and music results carry `mastering_decision`. Retained program
masters use receipt schema 3 with `masteringDecision`. Native master receipts
carry the same field through preparation, candidate attempts and audio reuse.
Legacy audio-only base rebuilds retain `base_work/audio_rebuild.json`, bound to
the completed base hash. Old native donor receipts without a decision do not
gain a fabricated one.

## When not to use this as approval

A converged dry run is a processing observation. The encoded output still needs
the existing loudness, true-peak, clock, signal and review checks. In particular,
the 0.10 LU preparation tolerance and the delivery tolerance have different
purposes. Neither a selected gain nor a passing dry run replaces delivery QC.
