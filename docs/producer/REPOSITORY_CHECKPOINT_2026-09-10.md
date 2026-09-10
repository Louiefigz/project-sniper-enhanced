# Project Sniper development checkpoint — September 10, 2026

This checkpoint preserves the accumulated local editing-system development on
`headless-architecture-checkpoint`. Its parent is
`cbcb264` (mandatory operator style/graphics/captions questions).
It is a development checkpoint, not a claim that native delivery or the
two-hour raw-footage workflow is fully qualified.

## Work preserved

- Guided short/long editing, cut and revision authority, source admission,
  resumable execution, bounded process ownership and recovery paths.
- Caption controls, timing, media integration, graphics and catalog contracts,
  frame/asset checks, audio mastering and incremental rendering work.
- HyperFrames 0.8.31 dependency pins, Studio integration, managed native
  resource controls and the conservative static native preflight.
- Producer prompts and Codex/Claude routing, visual storytelling guidance,
  presenter framing, composition variety and explicit native-route boundaries.
- Regression tests, workflow documentation, measured trial records and the
  read-only upstream catalog reference with its provenance metadata.
- Private native-work helper sources and reconstruction evidence, documented
  separately in the native private runtime checkpoint note. Those sources are
  retained as experimental evidence, not silently installed into the app.

## Validation for this checkpoint

Validation is performed against the working source while the production task
holds repository source/doc changes. Its separate temporary media work does
not modify the checkpoint inputs.

- `npm run type-check`: passed.
- `npm run lint`: passed with 41 warnings and zero errors. Eight warnings are
  unused variables in application/tests; 33 are in a read-only upstream
  `liquid-glass.iife.js` catalog reference.
- Staged authored-source/document whitespace check: passed. Five authored files
  received trailing-whitespace-only cleanup. Captured evidence and upstream
  catalog bytes are preserved exactly; their CRLF/blank-line/whitespace findings
  remain in the full diff-check log rather than altering provenance.
- Credential-signature scan: no private-key or service-token signatures in
  the checkpoint candidates or the 16 unpublished ancestor commits. Two
  credential-shaped URLs are intentional rejection fixtures in tests.
- JavaScript/TypeScript regression suite: partial, not a full-suite pass. The first
  run reached the color diagnostic API suite and hit the sandbox's process-table
  restriction. All six tests in that file passed with normal process-table
  access. The continuation passed further server suites before being stopped
  when the Python run had already established a non-green checkpoint.
- Producer Python `selftest.py`: partial with observed failures/errors, using
  the project virtual environment and documented `PYTHONPATH=.:tests`. Both
  broad test commands were deliberately interrupted (exit 130); neither is
  represented as an aggregate passing run.
- An isolated diagnostic rerun of 21 Python tests reproduced **3 failures and
  3 errors** (15 passed). See the concrete findings below and the retained log.
- Latest native-preflight and capability-lint checks: **43 tests passed in
  11.400 seconds** using the project virtual environment.
- All 21 archived private helper/recipe files matched their recorded sizes and
  SHA-256 hashes. Credential-signature checks also passed for those sources.

Exact logs and a machine-readable validation summary are retained in
`evidence/repository-checkpoint-2026-09-10/`. The focused native checks and their
scope are documented in [NATIVE_PREFLIGHT.md](NATIVE_PREFLIGHT.md); the private
sources have a separate [preservation note](NATIVE_PRIVATE_RUNTIME_CHECKPOINT_2026-09-10.md).

## Confirmed regression findings

The isolated diagnostic run reproduced these findings; this checkpoint does
not modify expectations or weaken gates to make them green:

- The color diagnostic policy command requests 4 CPUs while its test expects 1.
- The retained composition/rate matrix cannot verify the current motion-source
  closure.
- The frozen compositor catalog omits 14 transitive source imports.
- The current-system baseline evidence is not one closed trace.
- The external-ingress registry has stale file/token ownership after extraction
  of assembly arguments and addition of a render-layout archive verification.
- The b-roll layering test searches for a function call no longer present in
  the inspected function body; the source-inspection assertion raises.

Additional failures encountered by the interrupted media-heavy Python run are
retained in its log and summary; they were not all independently diagnosed.
These need a separate repair/qualification pass before a fully green release.

## Video and timing boundaries

The C0679 creative revision reached its ready-review handoff in **3 hours,
8 minutes, 19.598 seconds** from the recorded whole-video revision request.
This reused the existing cut decisions and prepared media. It does not prove
a fresh raw-footage edit within two hours. Subsequent troubleshooting is
additional work beyond that review-ready milestone.

The saved review export passed its delivery checks against the native JPEG
references and completed uninterrupted playback with no reported drops/stalls.
Four of 23 comparisons against stricter lossless PNG references remained below
their thresholds. Preserve that limitation and the failed attempts; human
creative/listening approval has not been inferred from automated checks.

The earlier separate fresh full-video trial was canceled. A later, separately
authorized short revision test is independent of this repository checkpoint.
See the current native direction and production progress records for its scope.

## Files that remain local

Original footage, rendered delivery videos, caches and generated run trees
remain on disk. Both `/artifacts/` and `/scripts/producer/artifacts/` are ignored.
The latter rule prevents nested test renders, mutable locks and scene caches
from entering Git. This change does not delete any footage or evidence.

Authored findings and selected diagnostic evidence under `docs/producer/`
remain versioned. Upstream catalog sample assets are reference inputs with
provenance, not generated C0679 outputs.

The sibling `youtube-automation/docs/findings/` directory is outside this Git
repository. Its native-preflight finding remains there; the substantive
instruction, measured result and limitations are already in `NATIVE_PREFLIGHT.md`.
