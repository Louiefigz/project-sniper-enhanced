# Validate current results before projecting historical receipts

The September9 C0679 editing trial exposed a contract mismatch after the worker
upgrade. The current admitted render lane returns seven result fields:
`cached`, `fmt`, `fps`, `key`, `kind`, `path`, and `proof`. The frozen V1 receipt
writer accepts six fields; it already records the measured FPS inside the media
proof and predates the redundant worker-level `fps` declaration.

A valid current render therefore reached the historical writer and failed its
exact-key check. Seven controller tests initially failed during setup because
their fixture still used an old build manifest. Updating that fixture exposed
the actual production projection mismatch; fixing the fixture alone was not a
complete repair.

## Preserve the historical contract

The adapter in `scripts/producer/headless/admitted_graphic_receipt_projection.py`
now checks the exact current shape and verifies both clocks before building a
new dictionary for the V1 writer:

```python
result["fps"] == "30"               # exact string in the current worker schema
asset["fps"] == 30                  # exact int/float; no bool or coercion
projected_result = {k: v for k, v in result.items() if k != "fps"}
```

This is a projection of an already verified duplicate fact. The measured asset
FPS stays in the receipt, the original lane dictionary remains unchanged, and
unknown or missing fields are rejected. The frozen writer and historical V1
receipt validation were not broadened.

The current controller fixture now uses the current build manifest, SDK version
label and output quota. Shared historical fixtures remain unchanged. A focused
cohort covering historical receipt semantics, current controller persistence and
replay, positive/negative projection cases, and assembly stage order passed
25tests in1.103seconds. This was a synthetic control-path test, not a new native
render or a pass of the aggregate producer suite.

## When this approach does not apply

Do not drop an unfamiliar field merely to satisfy an older consumer. If it adds
new meaning, authorization, policy or media facts that the older format cannot
represent, define an appropriate versioned contract instead. Do not normalize
`"30.0"`, `"30000/1001"`, numeric30, or booleans into the current worker's exact
`"30"` declaration. A mismatch should remain visible rather than being hidden
by a permissive compatibility conversion.
