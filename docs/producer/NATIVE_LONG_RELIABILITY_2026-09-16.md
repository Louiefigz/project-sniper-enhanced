# Native long export reliability — September 16, 2026

Status: implemented and qualified for the supported explicit native long route.
Repository-wide checks still have failures described below. This document records
measured evidence, not a promise that an arbitrary 15-minute edit meets an ETA.

Follow-up: [mandatory workflow enforcement audit](WORKFLOW_ENFORCEMENT_AUDIT_2026-09-16.md)
records the later public-entry guards, automatic recovery, current review
admission, reference binding and native Long review-bundle integration.

## Scope and acceptance

Aaron authorized fixes to the avoidable delays in Trevor / World Pet Health's
145.9-second production, with particular concern for 10–15-minute edits. The
scope is reusable native landscape export and its edge cases. The active Trevor
project and its creative revision remain separate.

Sources: [the production audit](../../../youtube-automation/docs/findings/TREVOR_LONG_FORM_PRODUCTION_AUDIT_2026-09-16.md),
the workspace working agreement, Project Sniper AGENTS/CLAUDE, pipeline direction,
the existing native owner/audio/stage contracts, and HyperFrames entry/CLI/core.

| Requirement | Implementation | Evidence / status |
|---|---|---|
| Stop repeating audio work after picture failure | Early exact float mastering, checked master/AAC reuse, independent program audio clock | Real float-master and AAC-donor picture/final-QC recovery passed with zero additional picture encodes |
| Admit future disk use before source extraction | PNG probes across distinct used ranges, conservative mixed-HDR cache accounting, cache/scratch/output allowance and 10 GiB reserve | Allocation/probe regressions and real storage-plan receipts |
| Catch source endings and exact-cut glitches early | Full-context cut ±2, first/last, two-second interiors, reverse visits and encoded sample reel | Real unpatched fixture rejected stale outgoing video at frame 60 before picture rendering |
| Correct the actual cut boundary defect | Content-addressed SDK patch uses half-open video windows in all four lookup paths | Actual patched-class integer/fractional clock and forward/reverse regression checks |
| Admit longer work without infinite hangs | Frame-derived outer and inner SDK source-process limits, advancing-work watchdog, ten-minute queue allowance separate from work time | Fifteen-minute clock, duplicate-log, cancellation and admission tests; real waiting/late recovery |
| Bound source decoder fan-out | Sequential metadata/direct/superset work inside the pinned SDK, retaining full HDR negotiation | Patched-helper test with 256 tasks (maximum one active); real final-runtime export |
| Keep expensive completed picture after later failure | Separate immutable picture seal, exact project/source/runtime binding, picture-only and final-QC resume | Both real audio routes and final-QC reuse passed |
| Preserve quality and lifecycle controls | PNG sources, original source geometry, same CRF 15/quality high, shared audio/pixel/full-decode gates and owned cleanup | Full short export, 15-minute stress qualification and final-runtime recovery tests passed |
| Make the workflow reusable | `native_long_export.py`, `LONG-PROJECT.json`, pipeline/module-map routing, public recovery command | [Runbook](NATIVE_LONG_EXPORT.md) |

## Real observations

All paths below are relative to the Project Sniper root.

- `artifacts/native-long-reliability-2026-09-16/export-01` and `export-02`:
  the new pre-master seam check rejected the stock lookup's stale outgoing video
  at exact frame 60. Full picture rendering never launched.
- `export-03`: exposed a strict geometry reader rejecting FFprobe's harmless
  `side_data_list` alongside width/height. The reader now validates the one video
  stream and required dimensions without equating unrelated metadata to geometry.
- `export-04`: all technical gates passed in 19.867 seconds for 120 frames and
  192,000 samples. Capture 4.413 s, picture/audio 10.013 s, final QC 2.254 s.
- `export-05`: the separate picture-owner/seal design passed in 23.276 seconds.
  Its incoming cut-frame image was visually inspected: the expected empty left
  quarter and incoming picture are present, without the outgoing full-frame layer.
- `artifacts/native-long-stress-2026-09-16`: the first looping test-audio generator
  accidentally produced 948 seconds. The exact sample gate rejected it before
  picture work. Test generation was corrected with explicit sample trimming.
- `artifacts/native-long-stress-v3-2026-09-16`: repeated speech triggered the
  existing steady-frequency gate at 87 Hz. No audio threshold was weakened to
  accept a synthetic loop. Preparation also demonstrated real capacity waiting
  behind Trevor's active proof, without launching a second renderer.
- `artifacts/native-long-stress-v4-2026-09-16`: 900-second, 1920×1080, 30 fps,
  27,000-frame technical fixture with exact 43,200,000-sample stereo audio.
  It uses a small solid-color source and deterministic broadband test audio.
  Early audio, source, sample-encoding and reverse-seek gates passed in 162.231 s;
  picture ownership/render/cleanup took 1,213.295 s, audio/color assembly 52.801 s.
  The first verification owner waited 121.191 s and refused admission because
  Trevor's revision owned the heavy lane. It launched no child and preserved the
  completed master and capture seals. This demonstrated that the initial
  two-minute queue allowance was insufficient; the final adapter reserves ten
  minutes for waiting in addition to its work allowance.
- `artifacts/native-long-stress-v4-2026-09-16/verify-02`: public `--resume-from`
  passed final qualification in 136.013 s including preparation, capacity waiting
  and verification. It captured zero new reference frames and performed zero
  picture encodes. Final verification checked 458 encoded reference frames,
  exact 27,000-frame / 43,200,000-presented-sample clocks and a complete A/V decode.
  Every executed owner recorded verified cleanup. Master SHA-256:
  `224a27687902644d20eec795cfa7876de87a697141e942e5c793e39220a27983`.
- `artifacts/native-long-reliability-2026-09-16/recovery-final-01`: actual
  preparation/capture/picture stopped at its valid picture seal, then completed
  picture-only recovery with zero new picture encodes and zero mastering passes.
  A further final-QC-only recovery reused both media and capture.
- `recovery-aac-final-01`: repeated that lifecycle starting with qualified AAC.
  The recovered audio receipt reports zero AAC encodes; completed picture and
  capture were retained. Both recovery harnesses have `integration-result.json`.
- `export-final-06`: the final code, including the SDK inner-process timeout
  propagation, passed a fresh 120-frame / 192,000-sample export in 23.955 s.
  Its full decode and native/encoded picture checks passed. Its review hash
  matches both recovery outputs byte for byte:
  `c4124b107cc78862c73556c8294967fd8ddbb90e329613df342f55eeb78e9a93`.
- `export-final-07`: after consolidating two small helpers into their owning
  worker/source modules, the same full export passed in 23.406 s with the same
  review bytes. A subsequent NumPy parameter annotation is type-only; the long
  unit tests were rerun, without claiming another full-duration qualification.

The long-duration stress run used CLI hash `fa2a210d…c04`. Subsequent hardening
added bounded SDK source work (final CLI `e565a664…fb9`), complete internal-window
checks, conservative HDR allocation, donor recovery and larger queue/inner
timeout budgets. Those changes were verified with targeted regressions and
real short exports/recovery; the complete 15-minute render was not repeated
after them. The unmodified stock SDK and earlier installed runtimes remain intact.

Earlier exports remain evidence for their recorded implementation hashes.
Changes to pinned implementation intentionally make those attempts unsuitable
as resume donors for newer code. No old receipt has been rewritten to grant
new authority.

## Regression evidence

- 130 native Node assertions passed with an after-test active-handle diagnostic.
  The stock Node 23 test runner intermittently stayed open after all cache
  assertions passed; the diagnostic run exited normally. No renderer cleanup
  gate or assertion was removed to obtain the pass.
- The complete native Python subset passed: 451 tests in 25.707 s. After the
  inner-timeout change, all 14 long-export tests passed, including the new
  five-minute-default regression; the source/probe Node tests also passed.
- The full Producer sweep ran 7,533 tests in 2,076.787 s: 10 failures, 8 errors,
  15 skips. Its native picture mocks had not yet been updated for the timeout
  argument, and an audio test expected the old malformed-receipt exception.
  Those five reported native failure/error entries were corrected and are
  covered by the passing native subset. The wider sweep was not repeated.
- Other full-sweep findings include stale retained P0/P2/P4/P5 evidence/toolchains,
  a lesson-order assertion, an observation-timer test, a separate private-graphics
  assembly audit, and existing mix/effect registry gaps (Short dialogue concat
  and `audioReviewSections`). Those files/authorities were not rewritten to grant
  a pass as part of this long-export change.
- `npm test` completed the earlier core suites and stopped at two separate
  `guided-native-binding.test.ts` diagnostic-message expectation failures.
  The cases still rejected the invalid input. These TS files were not changed.
- Production build passed using isolated `.next-long-reliability-20260916` output.
  Next's generated additions to `tsconfig.json` were removed. Final ESLint:
  zero errors, 41 warnings in the existing repository source/vendor set.
- The changed Python logic passes the 300-line file / 50-line function checks;
  `git diff --check` passes for the touched implementation scope.

[Retained test/build logs](../../artifacts/native-long-reliability-2026-09-16/verification-logs/)
contain the exact results. No UI code changed; real owned CLI exports and recovery
were the applicable walkthrough, rather than a claim of a GUI editing exercise.

## Limits

The adapter currently admits explicit root-timeline landscape projects through
15 minutes, 1–60 fps and 3840×2160. Its WAV is the full premixed program authority.
Nested/dynamic media and HTML audio effects require an explicit adapter rather
than silently changing the mix. Disk sampling remains a projection with headroom;
continuous disk and memory guards are still authoritative.

The stress fixture qualifies frame/sample clocks, long deadlines, stage behavior,
native/encoded checks and lifecycle cleanup. It does not qualify complex 4K-source
throughput, editorial turnaround, listening approval, full creative playback or
a 120-minute full-edit target. Production handoff still requires the matching
MP4 and live Studio project under the existing review rules.
