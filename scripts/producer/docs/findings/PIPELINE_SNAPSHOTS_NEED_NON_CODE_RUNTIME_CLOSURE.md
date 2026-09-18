# Pipeline Snapshots Need Non-Code Runtime Closure

## Assertion

A source-code snapshot is not an executable pipeline snapshot. If rendering
loads contracts, schemas, preloads, fonts, models, music, or SFX by path, those
bytes are part of the immutable run even when they are not `.py` or `.ts`.

## The incident

A managed saved-plan review pinned its Producer pipeline before launching the
detached worker. The snapshot walker excluded every path containing `docs`,
did not root `schemas/producer` or `assets`, and did not admit `.cjs`/`.mjs`.

The deterministic planning bundle then found:

- no
  `docs/producer/command-driven-editing/contracts/render-effect-registry-v1.json`;
- no `scripts/producer/headless/node_isolated_user.cjs`.

`plan_lint` failed because the render-effect registry could not load.
`comp_size` skipped seven comps because its Node isolation preload did not
exist. Those are pipeline-package defects, not edit-plan defects.

The old controller then labeled the result
`planning_gate_revision_required` and tried the gate-fix/full revision path.
That is especially unsafe for `reviewSavedPlan`: no writer can create a missing
runtime file, and the operator asked to preserve the complete plan.

## Evidence

After the closure fix, a real repository capture contained:

- 1,515 files;
- 14,628,535 bytes;
- all versioned Producer contracts and schemas;
- both CommonJS/ESM source extensions;
- repo-owned fonts, face model, music, and SFX;
- the Node isolation preload and render-effect registry.

The read-side capture took 224 ms on the acceptance machine. A complete
capture/write/restore smoke took about 0.4 seconds. That cost is negligible
beside comp measurement or video rendering.

Adversarial tests also remove the preload from both the lock and envelope,
recompute a self-consistent digest, and prove restore still rejects the
snapshot. Digest consistency is not enough; required closure membership is a
separate invariant.

## The principle

Define snapshot input classes explicitly:

1. executable source;
2. versioned contracts and schemas;
3. renderer templates and local preloads;
4. repo-owned deterministic media/font/model assets;
5. separately attested installed tools.

Capture and hash classes 1–4. Validate required files and non-empty asset sets
both when capturing and restoring. Keep class 5 under its existing executable
runtime identity when copying a whole dependency installation would be
incorrect or wasteful.

For immutable saved-plan review, a deterministic gate or critic finding is a
stop condition. Verify the exact file SHA-256, retain the evidence, and launch
neither the mechanical fixer nor the full revision writer.

## When not to use this approach

Do not broaden a pipeline snapshot to the repository root. In particular, do
not copy:

- `.env`, credentials, cookies, or user configuration;
- input videos, transcripts, project artifacts, or render outputs;
- caches and temporary directories;
- `node_modules`, virtual environments, browsers, FFmpeg, or model caches
  already governed by a separate runtime/tool identity.

Those inputs need their own bounded authority. Mixing them into a source
snapshot creates secret leakage, multi-gigabyte copies, and false confidence
that an installed executable closure is portable.
