# macOS CPU counters need their timebase and a host reader that is not cached

Adding CPU evidence to the native resource sampler turned up three traps in public
macOS APIs. Each produces believable numbers that are wrong.

## 1. rusage CPU times are Mach ticks, not nanoseconds

`proc_pid_rusage(RUSAGE_INFO_V0)` fills `ri_user_time` and `ri_system_time`. The
header calls them times; on Apple Silicon they are `mach_absolute_time` ticks.
Measured on the M3 Max (timebase `125/3`) with a one-second busy loop in one process:

| Reading | Value |
|---|---:|
| `time.process_time()` delta | 0.9949 s |
| raw `ri_user_time + ri_system_time` delta | 23,877,360 |
| raw × 125 / 3 | 0.99489 s |
| raw read as nanoseconds | 0.0239 s (41.67× too low) |

On Intel the timebase is `1/1`, so code that ignores it looks correct there and is
wrong on every current Mac. The helper now reads `mach_timebase_info` in the same
call and the parser converts with that value (`native_render_measurements.cpu_nanoseconds`).
`ri_proc_start_abstime` is in the same unit, so it can be compared directly with a
`mach_absolute_time()` read without conversion.

## 2. Under Rosetta the timebase and the rusage counters disagree

A helper Python running as x86_64 under Rosetta (`arch -x86_64`) sees
`mach_timebase_info` = `1/1` and nanosecond `mach_absolute_time()`, while the kernel
still fills rusage CPU and `ri_proc_start_abstime` in native `125/3` ticks. Converting
with the translated timebase makes every owned CPU figure 41.67× too low, and it still
looks measured. Checked on this host: `sysctl.proc_translated` is 1 under
`arch -x86_64` and 0 natively. The helper asks that sysctl first (Apple's documented
probe; ENOENT means a host without translation) and reports CPU unavailable when
translated. Memory readings are unaffected.

## 3. `host_statistics` is rate limited across processes and returns cached values

`host_statistics(HOST_CPU_LOAD_INFO)` is the usual host CPU reader. For unprivileged
processes the kernel rate limits it and returns the previous answer. The limit is
not per process: among fifteen fresh one-shot processes started 0.13 s apart, four
consecutive intervals advanced zero ticks, then one interval advanced 4.93× the ticks
it could hold. Inside one process, 19 reads 50 ms apart (about 0.9 s) were identical.
`host_statistics64(HOST_VM_INFO64)`, which the existing memory sampler uses, behaves
the same way: 3 of 19 consecutive fresh-process reads 0.1 s apart returned identical
free-page and fault counts.

`host_processor_info(PROCESSOR_CPU_LOAD_INFO)` is not cached: 40 reads 20 ms apart
were all distinct and advanced by about 16 processors × 100 Hz × the interval. The
sampler uses it for host CPU. It returns kernel-allocated memory, so the helper copies
the array and calls `vm_deallocate`.

## What the tracker does with this

- A reading whose ticks do not advance means "no answer", never 0% busy.
- Every processor must advance 0.8–1.2× its tick rate over the elapsed Mach interval
  (live readings on this host: 0.965–1.015). An aggregate band is not enough: with a
  frozen idle counter, a 0.5–1.5 band accepted 0.55 coverage and reported the host
  1.8× busier than it was. Below the bound is `host-counters-stale`, above it
  `host-counters-reset`.
- Counters are cumulative, so an interval longer than 15 seconds is still exact when
  every owned process continued across it; only an identity break (an exit, a counter
  that fell, a process first seen after it started) over such an interval is refused.
- A process is identified by PID and kernel start time. The `lstart` text depends on
  the time zone and a process may change its group; neither may split one process
  into two.
- The counters are 32-bit `natural_t`. `HOST_CPU_LOAD_INFO` sums all processors into
  one counter; this host's idle counter was already 3,626,203,972 of 4,294,967,296,
  about five days from wrapping. Per-processor counters wrap about sixteen times more
  slowly. A modular delta is accepted only while it fits the interval, so a true wrap
  is exact and a reset far from the wrap point is rejected.
- `RUSAGE_INFO_V0` has no child totals, so summing each owned process's own counter
  counts a browser descendant once. Never add `ri_child_*` fields from later versions
  to an owned-tree sum.

## When not to use this

These are 5-second samples. CPU used after a process's last sample, and processes
that start and exit between samples, are not observed: totals are lower bounds.
CPU evidence does not justify stopping or deferring work. A launch deferral needs a
measured profile that shows a throughput or deadline benefit on the qualified host
(`native_render_deferral.py`); none exists yet.

The helper validates every CPU value it emits with the parser's own rule
(`native_render_macos.cpu_problem`) and reports anything else as unavailable, so a
CPU-only defect (for example a negative `SC_CLK_TCK`) never turns into the terminal
measurement failure that would stop a healthy render. Only a forged or
version-skewed payload fails closed. Resource journal lines carry the interval
deltas, not the raw processor counters; the owner receipt keeps raw counters for its
baseline and latest snapshot.

The VM statistics used for memory admission can also be up to about a second old
when many samplers run together. That was observed, not changed, here.
