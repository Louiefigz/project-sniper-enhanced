# Serialize media duration from the intended final frame

## Observed failure

The fifth IMG_7138 journey Short has 828 frames at 25 fps: 33.12 seconds.
Its final source passage begins at frame 661 and lasts 167 frames.
The authored HTML originally declared a start of 26.44 seconds and a duration
of 6.68 seconds. In JavaScript, adding those decimal values produces
33.120000000000005, just beyond the composition's 33.12-second endpoint.

The native source-cache admission correctly requires every source view to end
inside the composition. It rejected this mathematically intended final frame
before any picture frames were rendered. This was a serialization error, not
a missing source, insufficient RAM or an editorial problem.

## Correction

The shared native composition author now detects a terminal media element
whose serialized start plus duration exceeds its intended frame endpoint.
For that case alone, it writes duration as endpoint minus start:

```js
const start = 661 / 25;                 // 26.44
const end = 828 / 25;                   // 33.12
const duration = end - start;           // 6.679999999999996
console.assert(start + duration === end);
console.assert(Math.round(duration * 25) === 167);
```

The frame-based source cuts, word occurrences and visual exit times remain
unchanged. The SDK receives a source window that agrees with its composition
endpoint, and its cache identity uses that same duration.

The implementation is in `src/lib/server/native-short-composition.ts`.
It preserves prior serialization outside the terminal-media overrun case.
The source-cache guard, SDK, native runtime, resource limits and strict
source-window checks are unchanged.

## Why the check must stay strict

Simply permitting an epsilon overrun at admission is insufficient here.
The SDK also limits extraction to the composition endpoint. Accepting the
original larger endpoint while retaining its cache key could produce a
different extraction duration and invalidate the exact source-cache identity.
Correct the authored representation before those two paths diverge.

Do not use this technique to hide a real out-of-bounds source range, trim a
word, add a frame or change speed. Genuine frame-clock errors still require
correcting the plan. Do not round every timestamp to a few decimal places:
fractional frame rates and fine source offsets need their own precision.

## Evidence

- A regression test reconstructs the failing 661-to-828 frame interval and
  verifies both audio and video endpoints, 167 retained frames, exact visual
  exit and unchanged source/word evidence.
- All 57 related composition, project, pacing, story and asset-use tests pass;
  ESLint passes for the changed code and test.
- The four already completed production projects still reconstruct their
  saved HTML byte for byte. The corrected fifth project also matches its
  newly saved HTML. See the batch's `timing-serialization-compatibility.json`.
- The initial failed export is retained as `export-education-to-experiment-v1`
  under `artifacts/img7138-journey-shorts-2026-09-15/`. Subsequent export
  qualification is recorded separately in the batch's timing and QA reports.

The corrected project's final export v4 subsequently passed the full native,
encoded-picture, audio, full-decode and owned-cleanup checks. The first four
completed exports were retained without rebuilding or re-encoding them.
