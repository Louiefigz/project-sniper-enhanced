# A render memory limit should describe capacity and actual pressure

On September 15, a title-only revision stopped at **4.112 GiB** of inclusive
owned-process footprint on a **64 GiB** Mac. Its configured job limit was 4 GiB.
Kernel pressure remained normal, the system headroom command reported 57%, and
swap did not grow. This was a software-policy abort, not evidence that the Mac
had exhausted memory. The largest child used about 1.912 GiB; parallel native
source extraction caused the combined tree to exceed the smaller job cap.

Evidence: `artifacts/img7138-editor-pov-title-2026-09-15/export-01/` retains the
failed delivery, owner receipt and resource samples. Verified cleanup left no
recorded owned survivors. Sequential SDK source preparation subsequently finished
in **66.221 seconds** under the old limits, publishing exact source frames through
the SDK. This preparation is not itself a rendered or quality-approved video.

## Separate three questions

1. **How large may this job become?** Derive a bounded allowance from measured
   physical capacity, then freeze it for the attempt. The new default uses
   `min(16 GiB, physical RAM / 4)` for the process tree and
   `min(8 GiB, tree allowance * 0.75)` for one process. A 16 GiB machine therefore
   gets a 4 GiB tree limit; this 64 GiB machine gets 16 GiB.
2. **Is the host under pressure now?** Require a healthy admission. During work,
   distinguish a moderate transient from three valid observations spanning ten
   seconds. Critical pressure and unsafe hard-limit crossings still stop at the
   next measurement. A polling supervisor cannot guarantee an OS allocation cap.
3. **Can we trust the measurement?** Keep bounded telemetry retries, start-identity
   checks, detached-child tracking and mandatory verified cleanup. Missing data
   must never become zero memory or extra grace time.

## Counters that must not be confused

The macOS system headroom percentage is a coarse system signal, not a conversion
to allocatable bytes. Literal free pages omit reclaimable cache. Physical
compressor pages measure memory occupied by compression; they do not measure the
larger logical contents. The process sampler's inclusive `ri_phys_footprint`
already accounts for compressed footprint, so adding compression again would
double count it. RSS alone is also insufficient.

Swap usage is host-wide. Growth from admission is a net cumulative change, not a
swapping rate and not proof that the owned job caused it. Stable old swap and
stable background compression should not independently kill a healthy job.
Record changes alongside pressure so a future failure can be explained.

## Where to use it

The shared current `NativeRun` policy serves Short exports and web captures.
Passing an explicit `ResourcePolicy` keeps deliberate fixed-policy semantics.
Frozen historical Long-form wrappers are evidence of their original runs and
remain unchanged; a current Long adapter can use the shared supervisor explicitly.

Do not use a larger allowance to cover lost ownership, missing telemetry, runaway
growth, critical pressure, inadequate output disk or unbounded extraction fan-out.
Capacity-aware limits and bounded work scheduling solve different problems.

## Verification

The implementation passes **218 targeted Python tests**, including 27 new policy
and owner tests. Coverage includes 8–128 GiB capacities, the observed 4.112 GiB
case on 64 GiB, explicit fixed limits, transient/sustained/alternating pressure,
recovery, irregular intervals, observation gaps, invalid counters and timestamps,
durable policy history, and independent state for each attempt. Existing sampler,
identity, retry, deadline, cancellation, cleanup, stage and recovery checks pass.
Mechanical standards review also passed.

The final combined checks passed **281 distinct tests** across two invocations:
232 resource/lifecycle/receipt/security checks and 49 additional shared-reader
metadata/security regressions. Both final mechanical and semantic reviews passed.

## Actual render and the separate capture-report defect

The revised 56.24-second Short completed its picture render in **380.914 seconds**.
The supervised media phase took **418.979 seconds** and peaked at **2.206 GiB**;
native capture took **190.688 seconds**, with a **1.314 GiB** peak. All measured
kernel pressure states were normal. Both owners verified cleanup.

The overall handoff then failed because the valid **34,382,839-byte** capture
report exceeded a generic **16 MiB** JSON input limit. This was a separate file
reader budget, not a memory-pressure abort. The completed media and capture
owners were revalidated and sealed with existing shared evidence checks. The
common encoded verifier reused their exact bytes: **537 image comparisons**, full
audio/video decode, and cleanup passed in **49.196 supervised seconds** (**86.675
seconds** including recovery admission). No second picture encode or recapture
was needed. The original failed delivery remains unchanged.

The reader repair preserves the generic 16 MiB default and uses one explicit
**256 MiB** bounded reader for native capture evidence in both consumers. It also
replaces an unbounded read in picture qualification. Exact hash, no-follow,
single-link, size-before-read and unchanged-file checks remain. The original
595-row report passes the corrected reader against its original capture-stage
hash. Very large Long-form reports may need sharded rows or deduplicated static
metadata; this budget is not a guarantee for arbitrary report sizes.

The title was independently inspected in six actual encoded frames, and the
updated local review player passed opening, advancing-picture, completion-reset
and same-file replay checks. Existing AAC packets were reused with zero new AAC
encode invocations. No subjective listening approval is claimed.

Evidence is retained under `artifacts/img7138-editor-pov-title-2026-09-15/`:
`export-02/`, `verification-03/`, `encoded-inspection-01/`,
`ENCODED-REVIEW.json`, and `PLAYBACK-VERIFICATION.json`. The exported video hash is
`d18daddc3591142da2c18044dc84b1120b9a0a7c021164aca3b2692e1e03afa0`.
These timings use prepared source caches and reused audio; they exclude
engineering/editorial time and do not establish a from-scratch production benchmark.
