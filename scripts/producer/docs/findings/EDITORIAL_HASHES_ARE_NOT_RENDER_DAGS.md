# Editorial hashes are not renderer dependency graphs

## Finding

A single “plan hash” cannot safely answer both of these questions:

1. Did the evidence requiring editorial approval change?
2. Which renderer stages can reuse prior output?

Those are different contracts. Approval may depend on rationale, identity, intent, or provenance that does not change pixels. Rendering may depend on hidden cross-lane behavior or runtime files that a generic plan projection omits.

## The concrete Sniper failure

`scripts/producer/fingerprints.py` produced base, video, audio, graphics, and
full render-content hashes from broad plan projections. A 2026-07-18
diagnostic showed over-invalidation and exposed the need to audit cross-lane
dependencies:

```text
rationale-only punch edit:
  base fingerprint changed:        true
  render-content hash changed:     true

graphics editorial metadata edit:
  base fingerprint changed:        false
  render-content hash changed:     false

presenterFrame false -> true:
  base fingerprint changed:        false
  video fingerprint changed:       false
  graphics fingerprint changed:    true
  renderer format changed:         opaque MP4 -> alpha MOV
```

The rationale result was wasted work: `render.py` strips
`punchIns[].rationale` before the punch renderer consumes the entries, yet the
generic base projection included it.

One correction matters: the presenter-frame result was initially
overclassified as unsafe **base** reuse. `spec.presenterFrame` changes the
scene from opaque MP4 to alpha MOV, so scene/composite/final must invalidate;
the graphics-free footage base does not. Reusing that base is correct.

The actual graphics-to-base dependencies were long-form rail/recompose
geometry, which changes base footage framing, and legacy-caption suppression,
which must remove cues before captions are burned into a graphics-free base.
Treating all `graphicsTrack` changes as base inputs would be safe but would
throw away the fast path; treating none of them as base inputs was incomplete.

The same class of mistake appears outside the plan. The graphics cache hashes composition HTML, shared tokens, selected assets, spec, and duration, but a template can load other vendor or CDN runtime behavior. A valid dependency projection must include the actual loaded runtime closure, not only the most obvious source files.

## Current closure — 2026-07-30

The current compatibility renderer now implements the narrower design:

- `render-effect-registry-v1.json` has 31 closed effect rows and 42 generated
  mutations covering every released public plan/manifest root plus explicit
  nested graphics cross-lane patterns;
- `render_effect_discovery.py` scans the renderer import closure for new
  literal readers, and lint/render/assemble reject unknown or unreleased
  public roots;
- `render_stage_roots.py` compiles domain-separated timeline, base, scene,
  composite, final, and manifest roots into `RenderGraphV1`;
- `graphics_base_effects.py` adds only rail/recompose and legacy-caption
  suppression to the base projection; ordinary scene copy and
  `presenterFrame` keep the base;
- addressing/editorial row metadata no longer invalidates current render
  projections.

Fresh retained actual-media controls under
`artifacts/p0-render-effect-parity-canonical-closure-v1/{short,lf14}` prove an ordinary
graphic dirties exactly scene/composite/final, reuses source/timeline/base, and
matches an isolated forced-full output with exact final SHA-256, FrameMD5,
decoded PCM, and stream facts. LF-14 covers all 20,139 frames at
`24000/1001`; the short covers 1,394 frames. Both executions bind the current
toolchain `1c1898a4…` and registry `8f8bea83…`. Their final hashes are
`ad7592ea…` and `b7580bae…`.

This closes the current field-registry and bounded graphics/base dependency
exits. One compatibility graph is still not the final fine-grained renderer:
future fields remain rejected until registered, every renderer/dependency
change stales the retained replay, and legacy ffmpeg/browser substages still
need oracle-backed decomposition.

## Correct design

Keep three roots separate:

```text
EditorialApprovalRoot
  = normalized plan + source/intent + rationale/provenance + review policy

StageInputRoot(stage)
  = compiler-owned projection of the exact plan fields, immutable inputs,
    selected assets, implementation, and runtime consumed by that stage

StageOutputReceipt(stage)
  = StageInputRoot + exact output SHA-256 + size + decoded media facts
```

The controller—not the model—compiles `StageInputRoot(stage)` from an explicit schema. Missing inputs fail closed. A stage never discovers its dependencies by stripping fields from an all-purpose plan hash.

For a repair:

1. Normalize the before/after plans.
2. Compute a canonical JSON-pointer diff.
3. Map each changed pointer to a registered render-effect class.
4. Expand the declared dependency closure, including cross-lane effects.
5. Reuse only receipts whose exact stage input root is unchanged and whose output bytes/media facts still verify.
6. Regenerate final-derived artifacts such as the cover image from the exact candidate.
7. Fall back to the complete path for an unknown pointer or dependency.

## Start narrower than feels necessary

The first useful falsification class is intentionally tiny: one gate-approved color-token change to one existing, explicitly placed 9:16 `text-element`, with timing, text, geometry, alpha/format, runtime, source, and every other lane frozen. Compare the reused-base candidate against a forced-full candidate and run complete decode/QC. Expand only after that class proves equivalent and field feedback shows enough demand.

## When not to use this approach

- Do not build a dependency compiler for a one-shot renderer that never reuses intermediates; the receipt machinery may cost more than it saves.
- Do not reinterpret legacy fingerprints as new authority. Preserve their existing behavior for compatibility and introduce versioned stage roots beside them.
- Do not use renderer-stage equality to skip editorial review. An addressing, rationale, intent, or provenance change can require approval even when delivered pixels are identical.
- Do not use editorial-root inequality to force every render stage. It guarantees correctness by discarding legitimate reuse and can hide the actual latency bottleneck.
- Do not widen an allowlist from model instructions such as “make the smallest change.” Locality must be verified by controller-owned diffs and effect schemas.

## General lesson

Hash the contract you are proving. Editorial sameness, stage-input sameness, output-byte integrity, and final approval are four different claims; one digest cannot safely stand in for all of them.
