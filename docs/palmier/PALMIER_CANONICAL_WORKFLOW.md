# Palmier-first canonical timeline workflow

> **STATUS: TARGET DIRECTION (aspirational).** The native-canonical candidate + compare-and-swap promotion described here is **not delivery-wired yet** — see [PALMIER_CANONICAL_IMPLEMENTATION_STATE.md](PALMIER_CANONICAL_IMPLEMENTATION_STATE.md). For what actually ships today — a flat, one-way, byte-exact visual-master mirror (one visible clip = the approved final.mp4) — read [PALMIER_MIRROR_HANDOFF.md](PALMIER_MIRROR_HANDOFF.md) + [PALMIER_PARITY_CONTRACT.md](PALMIER_PARITY_CONTRACT.md).

**Status:** product authority contract; implementation progress and remaining
native QC/promotion work are tracked in `PALMIER_CANONICAL_IMPLEMENTATION_STATE.md`.
Palmier is the primary viewer and canonical editable timeline. Sniper supplies
reviewed candidate revisions; it may not silently replace a Palmier timeline or
treat a flattened preview as editable timeline truth.

## Opening is not ownership

- **View in Palmier** opens the managed project/timeline and changes no owner,
  proof, plan, or background-job state.
- No separate ownership ceremony is required. A detected manual edit records a
  newer Palmier working head and prevents an older Sniper attempt from
  publishing over it.
- Merely opening Palmier must never pause deterministic planning, rendering, or
  QC. Editing the canonical timeline does change its readback fingerprint and
  therefore creates a rebase boundary for subsequent automation.

## Project bootstrap

After media preparation, Sniper may create a source-only **working view** in a
Palmier project. It is labeled as a working source view, not a QC-approved
video. Its source identity, project identity, timeline id, and normalized
Palmier readback fingerprint form the initial baseline. The background editor
can then run without mutating Palmier.

An approved render never overwrites that timeline in place. Palmier Pro's
`create_timeline` tool supports `{name, from: timelineId}` and must be used to
make a complete candidate fork with new ids.

## AI/review transaction

1. Read the latest canonical Palmier timeline and compute its normalized
   fingerprint.
2. Compare it with the stored baseline. A mismatch means manual edits occurred;
   stop and rebase instead of guessing or overwriting.
3. Create a full-copy candidate with `create_timeline({from: canonicalId})`.
4. Plan and apply only the requested delta to that candidate.
5. Read the candidate back, export it, and run deterministic plus visual QC.
6. Re-read the original canonical timeline before promotion. If it changed,
   leave the candidate available but do not activate it.
7. On success, activate the candidate and atomically record its id and
   fingerprint as the new canonical baseline.

This is compare-and-swap for timelines: the revision is promoted only if the
baseline it was planned against is still current.

## Fail-closed conditions

- Palmier readback cannot represent or fingerprint a lane material to the edit.
- The active project/timeline changes during a mutation batch.
- The canonical fingerprint changes after planning or during candidate QC.
- A source/component identity cannot be reconciled.
- A caller attempts an AI edit without first loading the Palmier baseline.

In every case the original canonical timeline remains untouched. There is no
`continue anyway`, lossy Palmier-to-plan overwrite, or automatic preference for
the stale Sniper preview.
