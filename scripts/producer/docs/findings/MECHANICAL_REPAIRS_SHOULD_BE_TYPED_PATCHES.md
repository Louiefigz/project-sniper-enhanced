# Mechanical repairs should be typed patches, not full-plan writer calls

## Finding

When the requested change is already expressible as one exact operation on one stable plan element, an LLM should propose the operation at most—it should not rewrite the entire plan.

A typed compare-and-swap patch is faster, easier to prove, naturally idempotent, and has a much smaller failure surface. LLM plan writing remains appropriate for semantic editorial work; it is unnecessary authority for mechanical changes such as replacing one known token value.

## The concrete Sniper path

The current Ask-AI request passes natural language plus a controller-inferred top-level lane. It does not carry a target element ID, expected plan hash, expected old value, or exact nested pointer. For a graphics request, the writer may change any part of `graphicsTrack`; the final guard verifies only that no other top-level field changed.

This creates four avoidable costs:

1. The surgical writer can run for up to 10 minutes even when the desired mutation is one JSON scalar.
2. “Make it lemon” does not match the current lane router, while wording that does match grants access to the entire graphics array.
3. Candidate normalization can mint/remint IDs and widen an intended one-field edit.
4. Preview authority is invalidated before candidate staging. A no-op, timeout, invalid response, critic rejection, or ENOSPC can clear a good prior approval even when the canonical plan never changed.

The existing incremental renderer makes the mismatch more obvious. A retained graphics-only assemble completed in 19.9 seconds on a 108-second specimen, while the no-GUI request can still pay a model writer, governance, critics, and repeated full review. Optimizing a tens-of-seconds renderer without removing an unnecessary writer call attacks the smaller term.

## Correct contract

Represent the operation as data:

```json
{
  "schemaVersion": 1,
  "effectClass": "R0_TEXT_COLOR",
  "realizationKind": "deterministic-mp4",
  "expectedPlanHash": "sha256:...",
  "target": { "lane": "graphicsTrack", "id": "g-abc" },
  "op": "replace",
  "relativePointer": "/spec/color",
  "expectedOld": "#FFFFFF",
  "value": "#054BC9",
  "requestId": "operator-request-..."
}
```

Then let the controller:

1. Resolve the stable ID and require exactly one match.
2. Verify the current normalized plan hash and expected old value.
3. Validate the effect class, new value, and request-specific policy.
4. Apply the patch to a private copy without ID reconciliation or unrelated normalization.
5. Compute the canonical before/after diff and require exactly the registered pointer/value change.
6. Run every deterministic/global gate that can still be affected.
7. Render and review under the effect class's proved dependency/evidence policy.
8. Atomically publish the accepted generation; until then, leave the previous approved generation intact.

If the operator supplied a precise ID and token, no additional model is needed. If the request is vague, a model can act as a read-only intent compiler and return this schema. The controller still chooses the scope and applies the operation.

## Important edge cases

- **Already satisfied:** normalize values first. `#FFFFFF` to `#ffffff` is a no-op, not a cache miss or rerender.
- **Retry:** the same `requestId` and operation returns the existing intent/generation state; it does not replay.
- **Stale parent:** a plan-hash or expected-old mismatch fails. Never silently rebase onto a newly authored plan.
- **Bad identity:** missing, duplicate, nonconforming, minted, or reminted IDs make the fast path ineligible. Do not fall back to array index.
- **Normalization widening:** if applying/serializing changes any other pointer, reject the fast path.
- **Syntactically valid but illegal value:** `#123456` is valid template input but is not a Sniper brand token. Effect policy must validate semantics, not only JSON shape.
- **Rendered request not fulfilled:** plan equality does not prove pixels. For color, prove the exact token/raster before encode, then use a control-calibrated decoded color-distance check—H.264/YUV need not preserve byte-exact RGB—and verify legibility over actual footage.
- **Candidate failure:** staging, model compilation, gate, critic, render, decode, or disk failure discards only the private candidate. It does not revoke the prior committed generation.
- **Remote ambiguity:** if a later Palmier delivery was actually touched, quarantine that delivery. Local generation rollback cannot prove a remote effect did not land.

## When not to use this approach

Do not use a typed mechanical patch when:

- the request changes narrative, copy meaning, cut selection, pacing, timing, placement, or visual anatomy;
- the target cannot be named uniquely;
- the effect crosses captions, reframe, presenter composition, audio, transitions, or another unproved dependency;
- the new value requires editorial choice rather than validation against a finite controller-owned catalog;
- the controller has no rendered request-fulfillment oracle;
- an unknown pointer, schema version, runtime, or normalization behavior appears.

Those cases fall back to the semantic writer and the full current review path.

## General lesson

Use models for judgment, not for avoidable mutation authority. A semantic repair may need an editor; a one-field compare-and-swap needs a schema, a stable identity, and proofs.
