# A faster sampler can spend every retry inside one process burst

The MP4/MOV/JPEG/WebP HTTP acceptance attempt exposed a scheduling issue in the
native resource monitor. Its faster direct macOS sampler correctly rejected
newly born processes that lacked a complete before/after identity bracket.
But four immediate retries encountered four different new children at 0.111,
0.258, 0.403 and 0.545 seconds. The monitor exhausted its four-sample limit
inside one short burst and stopped the job, although the measurement window
allowed up to 18 seconds. This was not a memory-cap violation.

The shared `MeasurementWindow` now spaces retryable failures by 0.1, 0.2 and
0.4 seconds after refreshing process ownership and its durable lease. Each wait
stays inside the original alarm and original run deadline. The monitor retains
the same four attempts, all identity evidence and the same complete-snapshot
requirement. It records requested and actual wait durations. It never waits
after the fourth failure, treats missing memory as zero, or retries permission
and malformed-measurement errors.

The 87 focused monitoring tests pass. A simulated 250 ms child-birth burst
recovers on a complete third sample after 100 ms and 200 ms waits; immediate
retries would exhaust their count inside that burst. Tests also cover a deadline
or cancellation during a wait, four exhausted attempts, and permanent errors.

The failed real attempt remains recorded with verified owned cleanup. The
controlled rerun passed the actual four-format HTTP case in 4.946 seconds
(28.404s complete owner and exact cleanup). It recovered from an observed
turnover sample after a 0.110-second wait. One successful workload does not
establish reliability under every process pattern or prove that retry spacing
alone caused the different outcome.
See [the integration receipt](../producer/SUPPORTING_MEDIA_AND_GUIDED_BUILD_2026-09-13.md).

This approach is useful for short, observed process-turnover races. It does not
repair permanent access failures, stale process identity, malformed counters or
actual memory pressure. Those still stop the owner. There is no Shorts-only
sampler or relaxed limit: the adjustment lives in the existing shared owner.
