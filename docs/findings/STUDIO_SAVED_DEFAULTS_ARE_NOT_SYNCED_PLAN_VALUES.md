# A saved Studio default is not necessarily a synced plan value

## What failed

Sniper's Codex command path already maps a review timeline's host-slot
`data-variable-values` into `graphicsTrack[*].spec`. Its composition files
also contain `data-composition-variables`: declaration metadata and defaults
that Studio can save independently.

Those are two different locations. Previously, changing a default inside a
composition could produce an `applied` response without changing the plan.
The manifest then recorded the edited file as the new clean baseline.
A subsequent render from the unchanged plan would not reproduce that edit.

Two regressions reproduced this through the actual sync command:

- Composition font default changed from 72 to 96, with no host change:
  `applied`, zero entries updated, plan version unchanged.
- Host font changed to 80 while the composition default changed to 96:
  `applied`, plan retained 80 and the conflicting 96 was rebaselined.

The two failing tests took 3.44 seconds wall time. They generated real review
files with an explicitly inert TEST base and a substituted probe; they did
not launch Studio, render graphics or inspect creator footage.

## Why this matters for the installed runtime

Static inspection of the installed HyperFrames 0.7.33 `setVariableValue`
implementation found that its save primitive changes a composition declaration
default and a root CSS custom property. That primitive does not update the
parent host's `data-variable-values`.

This is implementation evidence, not a claim that a particular visible panel
was clicked or that its full runtime behavior was qualified. Likewise, the
separate disposable 0.8.31 SDK proposal tests do not upgrade or activate 0.7.33.

## The bounded repair

The existing sync route now refuses an unmatched composition-default edit
before writing the plan, history, fingerprint or manifest. The pending Studio
file is preserved so the choice can be resolved, not discarded.

Unchanged declarations, equivalent quote/entity/number serialization, and
defaults exactly paired with the host's current values remain supported.
The comparison retains declaration order, IDs, types and other metadata.
Duplicate IDs, attributes and JSON keys are rejected; `true` is not `1`.
The reconstructed original must match its recorded manifest hash before it
can be used as the comparison baseline. Reconstruction and file reading occur
once; the operator note and declaration check use those same strings.

The implementation uses the existing host diff, contract/lint gates, history
and apply route. It does not invent a second plan writer or automatically infer
how an arbitrary DOM, CSS or scene edit should map into the plan.

## Verification and limits

The new 11-case regression file covers no-write refusal, matching-host apply,
conflicts, metadata/type changes, duplicate declarations and baseline mismatch.
Together with the existing command/copy and generated-project sync tests,
46 tests passed in 7.10 seconds wall time. The existing 17-case sync cohort
uses a temporary 12-second synthetic video; it does not exercise the live
Studio panel or prove preview/export visual parity.

Do not use this blocker as a substitute for full panel-to-host integration.
Direct native text edits, general static-element edits and SceneSpec unit
identity mapping still require their own explicit supported paths and real
preview/export qualification. Resolving a saved value into the host does not
grant creative approval or bypass normal rendering and audiovisual QC.
