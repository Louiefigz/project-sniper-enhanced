# A matching hash does not prove that the right work happened

2026-09-06. These are Project Sniper engineering findings from synthetic media
and the pinned HyperFrames runtime, not creator-quality or throughput claims.

## The tempting cache check

A cached artifact and its receipt can agree perfectly while both describe the
wrong computation. SHA-256 proves byte identity against a held expectation;
it does not establish where that expectation came from.

Two independent regressions reproduced this distinction in the new opt-in
source-float audio integration:

1. Scale every retained dialogue PCM part by0.5, encode a matching float WAV,
   and recompute the receipt and public pointer. The admitted original sources
   and picture base remain unchanged. The former loader accepted the mutually
   consistent replacement even though it was not the captured source bus.
2. Substitute a valid picture, then recompute the final sidecar and audio
   pointer while leaving the visual plan unchanged. A recomputable visual-input
   key alone was not proof that this picture came from those inputs.

The corrected reusable read paths require an expected identity obtained from
the actual render completion, its verified pending handoff, or the prior graph
held by the controller. An ungraphed direct v2 call does not manufacture that
identity from the same mutable cache file it is trying to validate.

## The useful pattern

Conceptual code, not a Sniper API:

```python
# Captured separately from the output being reopened.
expected = controller.held_execution.source_bus_receipt_hash
receipt = read_regular_bounded_file(selected_receipt_path)
assert sha256(receipt) == expected
assert receipt.source_inputs == current_admitted_source_inputs
assert receipt.runtime == current_qualified_runtime
assert sha256(retained_pcm) == receipt.pcm_sha256
```

Every comparison has a different responsibility. Do not remove current-source
checks because a receipt is content-addressed. Do not obtain `expected` from
an editable pointer and describe it as independent execution evidence.

The source-bus substitution first failed the new negative regression in5.84s.
After the held-selection correction, the25-case source/cache/actual
graph/assembly/publication cohort passed in89.89s wall. That cohort is useful
evidence for these mechanisms, not proof of perceptual sound or picture quality.

## Successful encoding is another insufficient substitute

Four-frame stroke-badge probes produced decodable movies after a required icon
failed, a page error prevented timeline registration, and the renderer waited
45seconds. The48-second output was not a valid animation merely because its
codec and duration passed. Correcting the declared diagnostic asset and adding
runtime health checks reduced representative probes to about5.2seconds.

Similarly, a full-program loudness result did not reveal a music stem that had
lost its tail. A3.003-second legacy ducking fixture lost421.67milliseconds.
Whole dialogue kept the program duration plausible. Exact per-stem sample and
content checks were needed in addition to final loudness and decode checks.

## When this is not enough

Held receipt identity is not a signature against a fully compromised host.
It also does not prove editorial meaning, readable graphics, comfortable audio,
or correct color. Those still need their own full-output technical checks and
actual audiovisual review. A local edit may reuse byte-intrinsic evidence while
requiring fresh contextual checks over its new footage, timing and neighbors.

Keep the missing proof explicit. A cache miss can safely trigger recomputation;
a missing required quality review cannot safely become approval.
