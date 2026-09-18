# Cut receipts must use the producer’s precision contract

An eleven-minute C0679 draft exposed a mismatch between receipt production and
verification. The timeline duration was `683.70825` seconds. The existing cut
producer writes `round(expected_s, 4)`, yielding `683.7083`. The retained receipt
was correctly hashed and its 16,394 picture frames were unchanged, yet the reader
required a difference no greater than `0.000001` seconds and refused it. This
stopped an audio-only mastering attempt before any media work, after 1.1359 s.

The repair preserves the original receipt and accepts either the existing exact
comparison or precisely the producer’s four-decimal rounded value:

```python
abs(proof_expected - expected) <= 1e-6 or proof_expected == round(expected, 4)
```

This is not a general increase in allowed drift. For that same timeline,
`683.7082` remains invalid even though it is equally close numerically. The
reader still verifies timeline bytes, cut rows, receipt hash, exact frame sum,
ordered elementary-stream identity, and drift against the rational frame clock.
Nonfinite timeline durations are rejected explicitly.

The regression uses the actual `24000/1001` frame rate and fractional duration,
checks both exact and correctly rounded representations, and rejects the wrong
rounding and an altered frame count. Whole-second synthetic fixtures had hidden
the mismatch. Use representative fractional frame clocks for producer/reader
contract tests.

Do not apply this compatibility rule to source positions, word timings, packet
PTS, or samples: those fields have their own precision and identity contracts.
Do not re-seal an old receipt merely to make a reader accept it. A changed cut,
source, or picture stream requires new observations.
