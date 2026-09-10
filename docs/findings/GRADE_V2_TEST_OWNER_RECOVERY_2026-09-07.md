# TEST-only V2 grade owner: preserve cleanup authority before work

This slice changes only opt-in TEST harness files. It does not enable a production
color transform, approve a grade, or qualify creator media. The separately authorized
synthetic Phase A observation below is not production activation.
The existing V1 renderer/policy and shared `.sniper-color-resource` location are unchanged.

## Boundary implemented

1. Start a blocked, fresh POSIX supervisor session and observe its exact process identity.
2. Persist the immutable input, original clock, supervisor/owner identities, logical venv
   path, code/runtime pins, and one fresh job-derived container name before `active.json`.
3. Only an exact claim/lifecycle/input-bound pipe permit allows the fixed inner worker
   to fork in that group. EOF, parent death before permit, malformed input and timeout
   do not authorize a later fork. The normal deadline handshake only decreases work time.
4. A TEST-local policy proxy records the exact command/request/runtime launch intent
   durably before delegating the unchanged Docker launch. It replaces only that policy
   module's UUID binding, not global UUID generation, and permits one name allocation.
5. The outside Node owner alone observes whole-group absence. A normal leader return
   with an ignored-stdio descendant is rejected. Stored results remain candidate-only;
   saved records cannot replay an observation or grant approval.

Normal completion/failure retains the actual process return before publication can
throw. Final byte reads precede the last parent/lease/clock guards and exact claim
removal. Normal failed work may release proven cleanup without becoming success.

## Explicit cleanup-only recovery

The TEST owner exposes `--recover EXACT_TEST_PRODUCER EXACT_JOB_UUID`. It reacquires
the same project and global resource leases, reads the exact current claim and original
lifecycle, requires actual original-group absence, and performs no source decode or
new observation. It uses at most 90 seconds for cleanup within a 95-second command
budget; the original 120-second TEST work clock is retained, never reset or reused.

Recovery reconciles only the pre-claimed random name using the existing canonical
launch-abort/removal functions. Even a missing/deleted launch sidecar cannot assert
"not launched": the reserved name is still reconciled. An intact intent must match
the fixed source, command and runtime. Cleanup uses a new private control directory,
leaves original observation files alone, and retains its own return/failure records.

Live groups, EPERM, PID reuse, changed code/input/runtime/claim, incomplete cleanup or
late final checks preserve the active fence. Recovery does not guess PID kills,
enumerate containers, change the approved image, infer source approval or retry work.
An unresolved live descendant may therefore require waiting for actual absence;
there is no claim that a supervisor's own exit proves every descendant has stopped.

## Verification and limits

- Applied Node cohort: **34/34**, 1.55 seconds wall. It includes actual two-stage
  Node/Python pipes with explicitly fake metadata workers, real whole-group checks,
  finalization faults, original-clock checks, PID-reuse/EPERM negatives and existing
  process-monitor/harness tests. Post-venv-binding subset: **11/11**, 1.34 seconds.
- Applied Python cohort: **56/56**, 1.93 seconds wall, including **16** new tests:
  real parent death before permit/after fork, a TERM/cancel-resistant child reaped
  within a shortened TEST cleanup allowance, and mocked-daemon intent/cleanup faults.
- Scoped ESLint passed in 0.91 seconds. Whole type-check passed in 1.97 seconds after
  application; a later concurrent unrelated runtime-capsule test error is retained
  separately rather than represented as a clean current whole-tree check.
- Independent review reproduced nested `color.wall_budget` rejection in the actual
  cleanup main→helper path. One original timer now spans metadata, reconciliation
  and stdout; the new regression failed before the fix and passes afterward.
- The returned argv is copied when held: mutating the caller's list in place cannot
  alter the retained prelaunch command.

Logs: `/private/tmp/sniper-grade-v2-recovery-lKYS4A/final-{node,python,types,lint}.log`.
All tiny-process positive fixtures observed their groups absent before teardown.
At that initial implementation checkpoint, no actual Docker cleanup or V2 observation
had run. OS crash durability, large-source decode, memory qualification and
creator-quality approval remain unqualified.

## Authorized Phase A: actual synthetic UHD owner and normal cleanup

One fresh 24-frame, 3840×2160, 24000/1001 synthetic H.264 fixture completed actual
source admission and the actual V2 owner. The fixture has IEC 61966-2-4 metadata,
not demonstrated camera, gamut or transform accuracy. No existing creator source
was read or changed; no fault, retry or cleanup-only recovery was run.

Evidence root: `/private/tmp/sniper-grade-v2-live-4v4t2nmo`.
Job: `047a1de1-a75f-4ab1-947a-c151a261bef6` under
`synthetic/producer/.sniper-grade-observations/`.
Exact commands and terminal checks: `PHASE-A-EVIDENCE.md` in that evidence root.

| Measured boundary | Time |
| --- | ---: |
| Fixture including admission | 976 ms internal; 1.10 s command wall |
| Actual owner through successful final claim release | 2750.015458 ms; 3.13 s command wall |
| Python project observation | 1285 ms |
| OCI execution / actual full decoder | 905 ms / 152 ms |
| Canonical owned Docker cleanup | 119 ms |
| Existing strong readback inside project observation | 126 ms |

These are nested measurements, not additive stages. The original owner budget was
exactly 120 seconds; its actual worker request received 118 seconds. Cleanup retained
the existing 90-second ceiling. The worker reached EOF with 24 decoded frame records,
no decoder stderr, first PTS 0, step 1001 and time base 1/24000. Stream and decoded
chroma siting were both `left`, sample aspect ratio `1:1`, with no stream rotation
metadata. No unsupported inference was substituted for those observations.

The actual returned observation SHA was
`e820a9e41a726454070d1aae119a9dc605648a267e6b453e01a46a58b1fd0296`.
Independent post-return reads matched the input, all 1105 held code/tool pins,
source/original-source, project/manifest/plan, approval, execution and raw probe/frame
hashes. Actual owner PID 11678, supervisor PID 11692 and process group 11692 all
returned ESRCH. Exact Docker ID and prebound name both returned canonical
`No such container`; the real shared resource `active.json` was absent. No public
`final.mp4` or failure marker existed. Stored TEST result remains `candidate-only`
and `live-return-only`, not replay/approval authority.

Approved image: `sha256:880027231f9dab9dca988734991f25b69178929d9886c7489c6c02dfbe2c3985`.
Approval file SHA: `35ac637ac18bfe9622d52d50a4e85bca10a5e18738cab73aa35f554a97cf0e18`.
All owned resources were absent before releasing the source freeze. Both
`gradeApplicable` and `deliveryApproved` remained false. Phase B recovery with real
Docker, long/UHD resource limits, source color conversion and creative quality are
still separate unrun qualifications.
