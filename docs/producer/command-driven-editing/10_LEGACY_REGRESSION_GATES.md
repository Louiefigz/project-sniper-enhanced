# Legacy regression gates and traceability

> **Status:** Mandatory preservation gates for the proposed architecture.
>
> [Previous: implementation map and immediate work](09_IMPLEMENTATION_MAP_AND_NEXT_STEPS.md) ·
> [Back to the plan index](../COMMAND_DRIVEN_EDITING_EXECUTION_PLAN.md) ·
> [Next: P0 exit audit](11_P0_EXIT_AUDIT.md)

The new command, caption, scene, and render-node layers do not waive lessons
already encoded in the failure ledger and producer edge-case contract. Each
item below must have a named fixture, executable gate, and owning phase before
its affected lane can ship.

The closed machine-readable traceability record is
[`contracts/legacy-regression-gates-v1.json`](contracts/legacy-regression-gates-v1.json).
Its 13 rows name every owner, source lesson, enforcing code or known gap,
fixture, evidence artifact, receipt binding, and blocking/diagnostic status.
`p0-legacy-regression-gates.test.ts` parses the registry, verifies every
repository path, and rejects missing owners, false enforcement, or a hidden
gap. All 13 underlying gates are now enforced. The final
`graphics-over-broll-layering` gap was closed during P5 by a decoded
real-media fixture; this traceability completion does not release the broader
P5 render graph or Palmier claims.

Source authorities are
`scripts/producer/docs/findings/FAILURE_LEDGER.md` and
`docs/producer/PRODUCER_EDGE_CASES.md`; the tables below trace their relevant
IDs into this plan.

## Graphics geometry and visibility

| Existing lesson | Preserved target gate | Phase |
|---|---|---|
| `LL-019`: “full screen” means exact delivery pixels, not merely the same aspect ratio | Render a 1920×1080 source comp on a 3840×2160 delivery; require exact delivery-canvas coverage and proved bounding box through `graphics/delivery_geometry.py` and `audit/audit_placements.py` | P0/P4 |
| `LL-033`: text exposed over footage can pass generic critics while lacking usable backing/contrast | Sample the actual underlying footage through the visible interval; require measured contrast or a proved backing treatment. Missing/no-verdict evidence fails | P0/P4 |
| `LL-036`/`LL-037`: declared metadata cannot override measured comp capability | Released comps require fresh, complete measured entries. Missing, stale, unmeasured, or `renderError` capability blocks use; measured canvas/aspect/fade class/bounding box wins | P0/P4 |

`DeclaredSceneVariablesV1` and the scene manifest are interface contracts only.
Physical canvas, aspect, opacity/fade behavior, pixel occupancy, and
renderability come from the measured/proved capability matrix.

## Audio and duration authority

| Existing lesson | Preserved target gate | Phase |
|---|---|---|
| `X21`: mono/dead-channel repair must precede mixing | Every program-mixing node that consumes source dialogue/audio must depend on the normalized dialogue/program stem; independent music/SFX asset work may remain parallel. A mutation test removing that dependency must fail | P0/P5 |
| `X8`/`X19`: container duration and AAC padding are not editorial authority | Use compiled delivery-frame count at exact rational FPS and compiled/pre-AAC PCM sample range at project sample rate. Decoded AAC/container durations are QC observations only. Run a multi-segment AAC fixture, prevent padding accumulation, and clamp the final master to those compiled clocks | P0/P5 |
| `X20`: fractional rates must remain exact rational values | Carry numerator/denominator verbatim through compiler, fingerprints, manifests, ffmpeg invocation, receipts, and QC; reject float-rate drift | P0/P2/P5 |

The final mux may reconcile authoritative video and audio clocks only through a
declared, receipt-bound policy. It may not stretch, drop, or add content based
on container-reported duration.

## Current contract defects that become regression gates

| Defect | Required gate | Phase |
|---|---|---|
| Resolved: `captionsTrack` formerly satisfied plan coverage while the renderer consumed only global `captions` | Keep the released end-to-end gate: one compiler feeds SRT, bounded burned-alpha media, Palmier, authority, and Audit B; retained short/long dirty-versus-full traces must stay green | P0/P3 |
| Cut-authoring prompt advertises `longform|shortform` and `clean|produced`, while canonical vocabulary is `short|longform` and `trim|light|produced|full` | Generate the prompt shape from the canonical schema and contract-test it. A self-contained prompt may forbid source inspection, but its embedded schema must be canonical | P0 |
| Resolved: graphics-over-b-roll layering was formerly inferred from stage order only | Keep `test_graphics_broll_layering.py` green: real b-roll → alpha graphic → caption burn must prove z-order, alpha, caption policy, stream-identical audio, and b-roll reuse across a graphic-only edit; the same oracle must reject missing-graphic and reversed-order controls | P4/P5 |

## Authority and recovery preservation

| Existing behavior | Preserved target gate |
|---|---|
| Downstream authoring requires both deterministic cut approval and two-clean-review authority | The P1 compatibility picture-lock hash binds both validated receipts; deleting or changing either invalidates it |
| Plan refit maps old output → source → new output and searches removed spans in old-output order | Freeze early/middle/late removal, reordered source, and repeated-source fixtures; any source-order search is a regression |
| Pending refit/audio receipts recover from exact durable bytes | New commit-saga recovery follows the same observed-state principle; it never blindly repeats an uncertain external mutation |
| Headless primitives are non-authorizing until their own gates pass | Adapters may reuse mechanisms, but no experimental `CURRENT`, worker, or publisher silently becomes project authority |

## Required traceability record

The executable record is
[`contracts/legacy-regression-gates-v1.json`](contracts/legacy-regression-gates-v1.json).
Its closed TypeScript parser, JSON Schema, and path-existence test require every
listed gate to retain an owner, current enforcement or exact known gap, named
fixtures, evidence artifacts, and receipt bindings where enforcement is
claimed. `completeness:"complete"` describes the traceability record; it does
not convert a gate's passing mechanism into its owning phase's release.

Each release gate records:

- legacy lesson/edge-case ID and source document;
- current enforcing code or known gap;
- target schema/node/phase owner;
- fixture inputs and expected failure/pass;
- evidence artifact and receipt binding;
- whether the gate is blocking, diagnostic, or an explicitly approved
  approximation.

The phase exit checklist must link this record. A rewrite of the enforcing code
cannot delete the behavior without an explicit replacement gate and migration
evidence.
