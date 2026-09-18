# Main checkpoint — September 14, 2026

This checkpoint saves the native Shorts workflow, reference studies, hook and
story strategy, supporting-media intake and website capture, pacing, bounded
rendering, shared audio finishing, and the music sourcing plan. It does not
declare the remaining music integration or full editorial review complete.

## Commit-time corrections

- Updated disposable pipeline fixtures and their golden fingerprint to include
  the newly required native Shorts route. Cross-language parity remains tested.
- Updated UI regression expectations for the supporting-media control, including
  an assertion that it stays disabled at both guided cut checkpoints.
- Registered both new routes in the executable short/long matrix and regenerated
  its documentation. Native request preparation is distinguished from execution
  and delivery.
- Excluded generated artifacts and native runtime caches from both legacy live
  code walkers, matching the newer capture path. The new parity test requires
  real code changes to continue changing the fingerprint.
- Refreshed the static source-color dependency inventory with 15 newly imported
  Shorts/Director modules. The existing graph audit verifies the complete list;
  no pin or source-identity check was weakened.
- Recorded Aaron's positive listening feedback on the cleaned offer sample.
  Added ignore rules for extracted reference JPGs and documented their local
  storage. Authored studies and manifests remain versioned.

## Verification scope

- TypeScript type-check passed; ESLint passed for all 130 changed TS/TSX files.
- All 63 native renderer/browser-policy unit tests passed.
- All 33 focused application test files passed across the focused run and
  the corrected source-color pin test rerun. The latter passed all 13 checks.
- The wider application run completed 243 test files after correcting the
  stale fixtures/UI/matrix expectations and rerunning process/socket cases
  outside the sandbox. The full 471-file suite was not completed: it stalled
  in `guided-body-controller-handoff.test.ts`. A separate rerun also exceeded
  its 45-second bound and its owned process group was stopped. Do not report a
  full-suite pass.
- Earlier real-media and Python audio qualification remains documented in
  `SHARED_AUDIO_READINESS_2026-09-14.md`; it was not rerun merely to commit.

Rendered video/audio, extracted reference frames, runtime caches, and detailed
local test logs are not included in Git. This checkpoint preserves their
authored findings and the known qualification limits.
