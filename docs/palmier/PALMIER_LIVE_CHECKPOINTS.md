# Palmier live working checkpoints

**Status: local compatibility mechanism; not connected P5 qualification.**
The workflow below describes the production-shaped checkpoint contract and its
failure policy. It does not prove a representative connected short/long build,
export, repair, disconnect recovery, or manual-edit-preservation cohort.

Palmier can remain open while Auto Edit runs. The safe implementation is a
sequence of immutable timelines in one Palmier project, not repeated mutation
of the timeline the user may be watching or editing.

## Lifecycle

1. **Create Palmier source view** creates `workspaceMode: managed-draft`, records
   a complete MCP readback, and leaves that source timeline active.
2. After plan authoring, each plan revision, and each candidate render, Auto
   Edit invokes `palmier/checkpoint_cli.py`.
3. The publisher checks the current project/timeline fingerprint against the
   saved Palmier authority. A changed project, timeline, or edit stops automatic
   publication; the manual Palmier revision is preserved as the new working
   head.
4. A checkpoint is built on a fresh timeline, structurally read back, restored
   against the unchanged parent, then compare-and-swap activated.
5. Timeline names identify their authority and approval state:
   - `Sniper · Plan authored · <hash>`
   - `Sniper · Revision N · <hash>`
   - `Sniper · Render N (unapproved) · <hash>`
   - `Sniper · QC approved · <hash>`
6. Only the final name is a verified delivery. It is still created by the
   existing QC-approved exact-master push and retains its byte/hash/readback
   proof.

If Palmier stays open, the newly created build timeline is visible as its
native cuts, motion, text, and overlay clips are applied. This is milestone
streaming, not a claim that every private critic thought is a timeline: the
visible timeline advances after an authored plan, a committed revision, a
candidate render, and final QC approval. Reopening a managed source view first
reconciles the active timeline, so it cannot switch away from a new manual
revision merely because the sidecar still names an older generated checkpoint.

Playback and scrubbing do not count as manual edits because runtime cursor
fields are excluded from the timeline authority fingerprint. Timeline content,
identity, or project changes do count.

## Working-preview fidelity

Plan/revision checkpoints use the measured native translator where Palmier has
the required primitives:

- single-source cuts, trims, speed, and linked audio;
- baseline transform and supported punch scale/position keyframes;
- rendered graphics/animation clips on separate overlay tracks;
- native title text timing.

Graphics are full-canvas normalized for source-preserving 4K projects. Their
copy, shapes, and internal animation remain baked inside each overlay clip.

The sidecar records every omitted or limited concept. Current limitations
include transitions, b-roll focus operations, captions, color grade, mastered
audio enhancement/gain, music ducking, reframe layouts, and ramp/bracket motion.
The rendered candidate checkpoint is therefore a flat, explicitly unapproved
preview with higher fidelity than the native plan checkpoint. The QC-approved
timeline remains the exact flattened visual/audio master.

## Failure behavior

Checkpoint publication is observational and best-effort; it cannot fail the
Auto Edit job. Palmier being closed, another project being active, an assemble
lock, stale plan/media bytes, incomplete readback, or manual drift produces a
`palmier_checkpoint_skipped` event. No existing timeline is overwritten.

The one-shot interface used by the GUI worker is also available for recovery:

```bash
.venv/bin/python scripts/producer/palmier/checkpoint_cli.py \
  /absolute/producer/edit_plan.json \
  /absolute/source/asset_manifest.json \
  /absolute/producer \
  --stage revision --round 2
```

Add `--media /absolute/candidate.mp4` with `--stage render`.
