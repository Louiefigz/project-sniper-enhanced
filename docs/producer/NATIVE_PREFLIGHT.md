# Native-project preflight: conservative first optimization

This is a fast **static-only check before expensive work**, using installed
HyperFrames 0.8.31's official project linter and asset-path helpers. It does not
change the renderer, authored video, fonts, cuts, quality settings or final QC.
It does not start Chrome, FFmpeg, ffprobe, API calls, downloads or rendering.

## Run on the exact staged project

From the Project Sniper repository, use the installed Node already configured
for the existing render workflow:

```bash
SNIPER_NODE_PATH=/absolute/path/to/installed/node \
  ./.venv/bin/python -B scripts/producer/studio/native_preflight.py \
  /absolute/path/to/staged-project \
  --output-dir /absolute/path/to/new-preflight-evidence
```

The project and evidence parent must be canonical existing directories. The
evidence directory must be new and outside the project. Previous results are
never overwritten. Use an isolated staged project, not an entire archive,
repository, source-frame cache or vendor catalog.

Check **after** final asset-path staging: checking only the editable project
does not establish that the renderer will accept transformed references. Run
again if its source/dependencies change. This is a callable workflow step,
not an automatic hook into every existing renderer or an approval token.

## What it checks

- Official root/project lint and its unchanged strict-error decision. All SDK
  warnings and informational findings remain visible; they are not rounded into
  errors or discarded.
- Declared local scripts, media/images, stylesheets and CSS URL/import
  dependencies, including font files, with the SDK's path-resolution semantics.
  Remote and unresolved declared dependencies are reported, never fetched.
- Nested composition mounts and SVG image/use references. Mounted compositions
  must use local `.html` files. Every inventoried HTML must appear in the SDK
  lint results; unsupported layouts/snippets are blocked explicitly, not called
  invalid HTML. `srcset` and CSS `image-set` require separate dependency review
  and are explicitly unsupported by this bounded command.
- Bounded non-symlink input inventory, exact hashes of small source/assets,
  stable media file identities and unchanged pinned SDK lint/parser bundles,
  Node, lockfile and adapter files. This is **not** an attestation of every
  installed transitive dependency such as linkedom or postcss.
- Structured result counts/content hashes, worker exit status, original
  30-second allowance and bounded output. The worker uses the existing isolated,
  credential-free process runner and no-network/no-child guard, plus a guard
  against normal filesystem write APIs inside the static SDK worker.

Source limits: 512 files, 128 directories, depth 16, 8 MiB per non-media file,
64 MiB aggregate non-media bytes. `.git`, `.hyperframes` and `node_modules`
directories are excluded; declared dependencies must still be in the snapshot.
Large media files are stat-identified, **not rehashed, decoded or qualified**.

## Read the result correctly

- Exit 0 / `static-checks-pass`: observed static checks passed for these inputs.
- Exit 1 / `blocked`: SDK errors or dependency findings need attention.
- Exit 2 / `failed`: the check could not complete reliably. Inspect retained
  diagnostics; do not treat missing observations as success.
- A `failure.json` overrides an earlier result file from the same attempt,
  including a failure during the final publication/deadline check.
- `result.json` is always marked `pending-validation`. Only a matching
  `completion.json` records the completed static status. Missing completion,
  mismatched result hash or any failure marker means incomplete/failed. Python
  consumers must use `studio.native_preflight.read_completed(output_path)`;
  do not consume `observedStatus` as completion or use this as render authority.

`inputs.json`, `request.json`, `process.json`, `result.json`, `completion.json`
and any `failure.json` retain the actual evidence. `stage_timings.jsonl` records execution;
the result's `elapsedSeconds` is explicitly before final publication. A paired
completed execution span is not an editorial/quality approval. Timing telemetry
is best effort; a missing end row is missing timing evidence, not a measured duration.

The SDK normally has an optional codec-probe branch. This static command
explicitly leaves that branch unperformed and records `codecProbePerformed:
false`; the normal native renderer and final media checks are unchanged.
Fonts may exist yet fail to load or look poor. JS imports/computed assets and
other browser-only dependency forms are not a complete runtime closure. Actual
font fallback, overflow, animation, audio continuity, color and encoded picture
quality require the following checks. Static success always carries
`renderApproved: false` and `qualityApproved: false`.

## Where this fits in the quality-first flow

For an explicitly requested reference-shot/style match, add
`--reference-map /absolute/REFERENCE-REUSE.json` using the
[shared mapping workflow](REFERENCE_SHOT_REUSE.md). The same optional check serves
native Short and Long projects, validates the project/evidence binding before the
SDK and again before completion, and records the planning report in `inputs.json`
and `result.json`. Ordinary projects need no map and do not load the catalog.

1. Reuse the accepted brief and preferences. No hard authoring deadline and no
   automatic reduction of detail, resolution, bitrate or review depth.
2. Run this static check against the staged native project.
3. Review representative **animated** native samples at intended final export
   settings, preserving root context and transitions. Include the opening,
   dense text, small presenter and difficult color/motion cases. Use existing
   guarded native tooling; this command does not render or qualify those samples.
4. Batch related repairs, rerun affected checks and render the complete master
   when visual content changes. The current local SDK does not provide a
   qualified changed-scenes-only master replacement/resume workflow.
5. Keep whole-output audio/color/layout/timing/playback QC and evidence. A
   sample pass cannot replace final checks, audible assessment or creative review.

The first target is a modest, measured improvement—roughly 10–20 minutes on a
comparable job if a preventable full rerender is avoided. This is **unproven**;
static lint alone does not establish that saving or fix the retained PNG-relative
fidelity failures. The real prior creative revision took 3h08m20s with reused
preparation. Do not reset that clock or reinterpret it as a fresh-input result.
The existing video and its archived project remain unchanged.

## Verification of this increment

The final local static run on the existing C0679 staged project checked 54 HTML
files in a complete measured stage of **0.594 seconds**, with zero SDK or
dependency findings and unchanged source state. Evidence is in
`/private/tmp/sniper-native-preflight-20260910.X9C2QM/actual-staged-v5/`;
temporary evidence may later be cleaned up. This is not a new media-quality test.

Targeted regression commands (local only; no rendering):

```bash
SNIPER_NODE_PATH=/absolute/path/to/installed/node \
  ./.venv/bin/python -B -m unittest discover -s scripts/producer/tests \
  -p 'test_native_preflight*.py' -v
PYTHONPATH=scripts/producer:scripts/producer/tests \
  SNIPER_NODE_PATH=/absolute/path/to/installed/node \
  ./.venv/bin/python -B scripts/producer/tests/test_comp_capability_lint.py
```

The adversarial cases cover missing/nonlocal fonts/assets, unlinted HTML,
unsupported mounts, nested templates/CSS, source replacement, linked inputs,
inventory/output bounds, secret isolation, denied filesystem writes, malformed
SDK results and failed/late completion. Fixtures are explicitly non-renderable;
passing them is not a claim about the existing video's quality.
