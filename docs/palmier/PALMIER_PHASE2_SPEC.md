# Palmier Phase 2 adversarial audit — historical decisions

> **STATUS: HISTORICAL — superseded** by [PALMIER_PARITY_CONTRACT.md](PALMIER_PARITY_CONTRACT.md) + [PALMIER_MIRROR_HANDOFF.md](PALMIER_MIRROR_HANDOFF.md). The "Open & take control / Reclaim Sniper mirror" ownership ceremony below is **not** the current model (the current UI exposes no reclaim ceremony). Only the concurrency-risk analysis remains useful.

**Status:** the concurrency findings remain active; the former all-exact sync
policy is superseded by the schema-v4 visual-master mirror. Current contracts:
`docs/palmier/PALMIER_PARITY_CONTRACT.md` and `docs/palmier/PALMIER_MIRROR_HANDOFF.md`.

This document records the useful conclusions from the original 46-agent stress
test so a future change does not reintroduce unsafe Palmier mutation patterns.

## Risks that still shape the implementation

Palmier is a global mutable singleton: one active project/timeline is shared by
the human and every MCP session. Imports and project changes can be slow, most
mutations do not carry a project id, and app-global undo can affect human work.
Timeline divergence hashes also have blind spots because readback omits some
content-affecting properties.

The durable mechanisms are therefore:

- one stable Palmier project per Producer job;
- explicit sync, never MCP mutation on every Save;
- kernel-backed per-dir lock, one-slot latest-wins queue, global Palmier
  serialization, and active-assemble deferral;
- a fresh shadow for every changed Sniper mirror;
- no app-global undo and no in-place mutation of prior/human timelines;
- project/timeline identity checks at mutation boundaries;
- failure restoration plus visible quarantine of partial shadows;
- content-addressed library reuse/adoption before import;
- canonical plan/authority staleness proof;
- explicit `sniper|palmier` ownership and no Palmier→plan merge.

## Policy superseded on 2026-07-12

The audit originally coupled visual fidelity to native editability and required
`fullyEditable == true` before sync. That was safe but wrong for the clarified
product: a produced edit could never reach Palmier because graphics, captions,
motion, audio finishing, and other concepts lacked exact native adapters.

The replacement separates two facts:

- `mirrorReady` — the plan is known/well-formed and the current schema-v2
  approved master may mirror exactly;
- `fullyEditable` — every concept has an exact native Palmier control.

Approximate, baked, and known-unsupported findings are now capability labels.
They do not block a byte-identical approved-master clip. Malformed or unknown
state still fails closed.

## Current schema-v4 transaction

1. Require the durable managed-quality marker and recompute the complete
   input/pipeline authority digest.
2. Strictly verify the schema-v2 approval, assembly proof, audit machine/report,
   sampled frames, clean plan reviews, both rendered-review lenses, and final
   bytes. Explicit legacy marker is the only legacy path.
3. Run `plan_lint` and parity mirror-safety preflight.
4. Refuse when Palmier owns the handoff.
5. Import/reuse the exact master plus best-effort non-visible component assets.
6. Create a shadow containing exactly one visible approved-master clip.
7. Read back media identity, canvas, FPS, duration, frames, and timeline range.
8. Publish `final.palmier.mp4` from byte-identical master bytes and hash it.
9. Activate the verified shadow and atomically write `palmier.sync.json`
   schema v4.

## Ownership decision

**Open & take control** marks the sidecar Palmier-owned before the user edits.
Subsequent Sniper syncs stop. **Reclaim Sniper mirror** keeps the Palmier-owned
timeline, clears old mirror proof, and forces a fresh shadow. This is safer and
more honest than trying to infer every possible manual edit from incomplete
readback.

## Risk → current mechanism

| Audited risk | Current mechanism |
|---|---|
| Focus theft / identity switch | Refuse mismatched active project; recheck target around mutations |
| Push storms / HMR lock loss | Per-dir lock, latest-wins queue, global serialization, assemble deferral |
| Human edit clobbering | Fresh shadow + explicit ownership; no in-place mutation |
| Import bloat | Content-key sidecar reuse and library adoption |
| Shared undo stack | Remove exact automation-created ids; never call undo |
| Torn/background export | Exact master publication to temp, hash verify, atomic promotion |
| False current state | Full authority digest + strict schema-v2 approval + sidecar/meta proof |
| Partial failure | Restore human timeline and quarantine `…-FAILED` shadow |
| Renderer fidelity drift | No second renderer: one visible byte-identical approved-master clip |
| Native capability gaps | Collapsed editability legend plus preserved component inventory |

## Historical implementation reconciliation

The earlier `fc1a176` in-place sync proved useful building blocks—stable
project identity, media reuse, lane fingerprints, and `up_to_date` detection.
In-place edits, divergence hashes, and `--force` rebuild were removed because
they could not protect human work. Schema v4 retains diagnostics and lineage but
uses unclobberable visual-master forks.

## Verification boundary

The current mirror and ownership changes are covered by offline Palmier unit
tests, TypeScript tests/type-check/lint/build, and pure authority tests. This
document does not claim a live MCP mutation of a user project. A live exercise
must be explicit because it opens and mutates Palmier.
