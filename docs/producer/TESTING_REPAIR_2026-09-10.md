# Regression repair follow-up — September 10, 2026

Status: software repairs, focused reruns, the aggregate JavaScript inventory,
and the production build are complete. Eight retained measurement/freshness
checks still fail. This is not a fully green release or native-video approval.
The starting development checkpoint is `565a4ed01a20854ec0e6fdfe35539eb4e8a4e173`
on `headless-architecture-checkpoint`.

## Baseline and repairs

The complete initial Python discovery run executed **6,978 tests in 1,976.794
seconds**, reporting **27 failures, 20 errors and 5 skips**. There are 42
distinct failing identities because some failures are subtests. This run
preceded the final repairs below; it is retained as a failed baseline.

- The body-delivery reader now replays the writer's actual local audio-signal
  evidence against the held master and final AAC. Only the validated original
  measurement time is retained. Resealed tampering still fails.
- Mandatory grade cleanup defers owner cancellation across background threads,
  preserves the original signal state, and keeps the independent wall deadline.
- Shared subprocess deadlines now live in the headless process runner. The
  Palmier adapter delegates to the same nested clock; headless code no longer
  imports its connected-client dependency.
- Current compositor V2 and render V3 build receipts cover the current source
  dependencies, while historical contracts and fixtures remain byte-identical.
  See [the build release record](BUILD_CLOSURE_RELEASE_2026-09-10.md).
- Frontend opening/body preflight now recognizes existing shared-master voice
  cleanup and valid gain windows. Direct Python gain parsing also rejects
  booleans, numeric strings, null, nonfinite values and overflow.
- The final JavaScript inventory caught a missing current source pin for the
  new finishing helper. Current V2 snapshots now require that file explicitly;
  legacy V1 still selects its original five controller files. A snapshot missing
  the helper is rejected, never repaired by borrowing current host code.
- The staging fault fixture now checks the canonical OS temporary directory
  used by its creator, plus its fixed filename prefix and exact file identity.
  Its old `/private/tmp` assumption prevented 15 macOS fault cases from reaching
  the intended mutations. All 36 cases now exercise their actual checks.
- Updated stale test seams for graphics jobs, b-roll dispatch, prompt extraction,
  current renderer image labels/quota/rate, timing arguments and imports. The
  GUI dependency check now matches a module or its dotted descendants; it no
  longer mistakes `guided_…` modules for `gui`.
- The ingress registry follows the existing assembly-argument extraction and
  render-layout archive-verification owner. No new physical ingress was inferred
  from the new pure build parsers.

## Verification

Counts below overlap; do not sum them into a unique full-suite pass.
Python timings are unittest-reported; final JavaScript repair/build timings
measure command wall time. None measures an editing workflow.

| Check | Result |
| --- | --- |
| Delivery reader and audio evidence regressions | 48 passed / 42.222 s |
| Cleanup, deadline, import, timing and static lint regressions | 96 passed / 7.421 s |
| Final cleanup/process rerun after nesting cleanup | 50 passed / 3.399 s |
| Caption/audio/dependency cohort | 187 ran / 166.367 s; one stale helper-path fixture failed |
| Corrected caption/helper-path/import cohort | 14 passed / 0.686 s |
| Current/historical build, admission, binding and compositor cohorts | 146 passed; see build release record |
| Previously failing renderer protocol/cache group | 24 passed / 1.986 s |
| Direct gain parser, finishing, motion, lint and audio-path regressions | 129 passed / 3.577 s |
| Caption/manual/opening TypeScript metadata files | 6 + 4 + 10 passed; includes 140 actual-Python finishing cases |
| Current source-dependency inventory and missing-pin refusal | 13 passed / 11.676 s |
| Complete staging batch fault group after fixture repair | 36 passed / 120.302 s |
| Official JavaScript test-file inventory | All 447 have passing results across retained runs and final repairs; no unaccounted-for file |
| Current supervisor, skill surface and SDK prefix | Passed; SDK 14 tests |
| TypeScript type check | Passed |
| Isolated production build, including TypeScript and 24 static pages | Passed / 31.685 s; 50 broad-file-pattern warnings in 25 unchanged files |
| Full ESLint | Zero errors; 41 existing warnings |
| Changed TypeScript source/tests ESLint | Passed without warnings |
| Whitespace and bounded semantic/security review | Passed; no outstanding actionable review finding |
| Current retained qualification records | 8 ran / 1.881 s; 7 failures and 1 error |

Logs are retained in [the follow-up evidence directory](evidence/testing-repair-2026-09-10/retained-logs.json).
The [Python resolution index](evidence/testing-repair-2026-09-10/python-baseline-resolution-index.json)
maps the 42 distinct baseline failures: 34 addressed by focused repairs and
eight requiring new measured evidence. No new full Python discovery pass is
claimed after the focused repairs.

The [JavaScript coverage index](evidence/testing-repair-2026-09-10/javascript-coverage.json)
joins the original fail-fast prefix logs, explicit continuation exits and final
targeted reruns by file. Earlier prefix evidence predates these final source
repairs. This is **aggregate coverage, not one fresh full `npm test` pass**.
The initial caption-profile failure and the two later dependency/fixture failures
remain in the logs alongside their successful final reruns.

The server tail was repartitioned into disjoint groups. The first serial tail
recorded 83 passing files; A/B each completed their required 12-file prefix,
and C/D each completed their remaining 41 files. Each retired coordinator was
stopped from launching more files, allowed its current child to finish, then
terminated. Duplicate final child reports do not add unique coverage. The
partition manifests and retirement observations are retained. No owned test
coordinator remains paused or running.

The build used `.next-testing-repair-20260910`, leaving the open editor's cache
alone. Its original `tsconfig.json` and generated `next-env.d.ts` were restored
byte-for-byte after Next added temporary build-type paths. The isolated build
cache is about 164 MiB. The build warnings concern broad filesystem patterns in
unchanged code; they are separate from the 41 existing ESLint warnings.

## Remaining measured evidence

These failures require actual new evidence under the current source/toolchain,
not new hashes attached to old measurements:

| Retained check | Current failure |
| --- | --- |
| Composition/frame-rate matrix | Old 46 × 8 source matrix is stale; current catalog has 53 kinds |
| Current-system short and LF14 baselines | Retained baseline is not one current closed trace |
| P0 adversarial media ingress | Source dependency hashes changed |
| P0 incremental/forced render parity | Retained toolchain is stale |
| P2 row-one editing cohort | Source dependency hashes changed |
| P4 live exit/geometry/treatment cohort | Source dependency set and hashes changed |
| P5 24-overlay compositor | Source dependency set and hashes changed |
| P5 LF14 review/repair | Browser/toolchain changed |

No qualification thresholds, resource allowances or historical measurements
were relaxed. The separate native 67-second real-footage check still has no
new render. The closing read-only observation at UTC epoch 1789058870.780805
reported compressed memory of 10,043,260,928 bytes, above the unchanged
6.4 GiB ceiling. Unused physical memory was 6,957,301,760 bytes, above the
six-GiB reserve, and kernel pressure was normal. This is a conservative policy
refusal, not evidence that the SDK would necessarily crash. It requires fresh
successful admission before native work can begin; the observation is retained
as `native-readiness-close.json` in the evidence directory. The earlier
read-only observation is also preserved.

The five baseline skips are also preserved: three admitted hostile/complete
grade-decoder tests, one native punch-endpoint test, and one metadata-only
check of a specifically retained failed placement report. The last fixture's
documented `sniper-body-live-Pc8XlW` directory no longer contains the required
plan/placement/report files; no replacement evidence was fabricated. The four
native tests need their explicit execution prerequisites. None counts as a
passing test in this report.

The saved C0679 revision and its **3 h 8 m 19.598 s** review-ready timing remain
unchanged. Neither these unit tests nor the held native short test establish a
fresh full-video edit within two hours. The canceled fresh full-video trial was
not restarted.

## Existing local artifact

`templates/motion/comp_capabilities.json` was already dirty before this repair
pass. Its provenance is not established by these tests and it is excluded from
this repair's commit scope. The repair does not delete footage, caches or
existing final videos.

The subsequent operator-requested commit checkpoints that existing catalog
separately from repair commit `394029f`. Its exact SHA-256 is
`3f25ab0810cd0dd47c074ce9eede3a79c2bcc215331cfe0117c175f68f57ac7f`.
The semantic changes are a one-pixel reduction of the `punch-shout-lockup`
bounding box and dimensions, plus the capability and source digests; the rest
of the textual change is JSON formatting. The bytes were preserved without
regenerating or relabeling their measurements.

All 53 rows pass the existing integrity, source-freshness, inventory and row
shape readers. The artifact, source-dependency and plan-lint regression group
passed 27 tests in 3.004 seconds. These checks do not establish the artifact's
measurement provenance or constitute new rendered evidence. The eight
qualification failures above remain open; this is a development checkpoint,
not a release qualification.
