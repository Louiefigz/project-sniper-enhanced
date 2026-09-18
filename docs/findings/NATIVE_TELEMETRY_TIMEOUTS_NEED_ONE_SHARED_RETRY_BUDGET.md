# Native telemetry timeouts need one shared retry budget

September 12, 2026. Implemented locally. The linked historical attempts remain
failed attempts; new measured evidence and its limits are recorded below.

## What the evidence establishes

The offer-story export attempts `02`, `04`, and `06` under
`artifacts/native-short-pacing-2026-09-12/exports/` failed after 7.951, 7.974,
and 7.970 seconds respectively. Each initial measurement window had the same
sequence:

1. A complete command cycle found newly started owned processes whose identities
   were not present before footprint collection. It correctly rejected that
   sample as `MissingProcessFootprint` after approximately 2.16 seconds.
2. The next `/usr/bin/top` command reached its unchanged three-second timeout.
   No complete owned-resource snapshot was written. Cleanup was verified.

The failure is therefore more specific than “cold render ran out of memory.”
The record does not establish the actual host pressure during the missing
measurement, or why `top` took too long. Extraction contention is a hypothesis;
the fact that subsequent render attempts progressed is not proof of its cause.

The resource reader previously wrapped timeout, permission, and other subprocess
failures in the same `ResourceMeasurementError`. The owner already allowed four
fresh measurement attempts within 18 seconds, but retried only missing process
footprints. The second sample's timeout escaped after roughly 5.25 seconds even
though that same bounded measurement window had unused attempts and time.

## The local change

`native_render_resources.py` now raises `ResourceCommandTimeout` specifically
for `subprocess.TimeoutExpired`. Its evidence records the exact command,
three-second timeout, partial stdout/stderr bytes as Base64, and preceding
completed command readings. A process seen in the pre-footprint identity table
remains an anchor in the next request even if it later detaches. Partial command
output is never parsed as a complete resource snapshot.

`studio/native_measurement_retry.py` handles that typed timeout in its existing
measurement loop. Missing footprints and command timeouts consume the **same**
four-attempt budget and the **same** 18-second deadline, capped by the original
run deadline. The real sampler is called again from the beginning after owner
identity refresh. There is no nested command retry, old-snapshot substitution,
timeout increase, pressure exemption, or render restart.

Every failed read remains in `measurementRetryWindows[].attempts` and
`measurementFailureEvidence`. Retry counts distinguish process turnover from
command timeouts. A complete fresh reading still goes through the inherited
host pressure, owned footprint, swap, disk, identity, and age checks. Exhaustion,
cancellation, permission errors and malformed telemetry still enter failure and
the existing owned-cleanup path.

The project `.venv` runs these tests with the standard library, since it does
not have pytest installed:

```sh
PYTHONPATH=scripts/producer:scripts/producer/tests .venv/bin/python -m unittest \
  test_native_measurement_retry test_native_measurement_reconciliation \
  test_native_render_resources
```

All 42 tests pass: 12 new timeout/retry tests and 30 existing measurement,
identity and resource-policy tests. They cover exact timeout evidence, fresh
sampling, retained child identities, mixed failure budgets, exhaustion, original
deadlines, late complete samples, cancellation, fail-fast unrelated errors and
the actual owner's pressure-stop path. These are deterministic local tests;
they do not establish a cold-start success rate or a render-time improvement.

## Separate issue: identical media still misses the extraction cache

The installed, pinned SDK's `canonicalKeyBlob` includes the resolved video path,
floored modification time in milliseconds, size, media start, duration, frame
rate, frame format and optional transform. A shared cache directory alone does
not make identical bytes reusable across new project folders.

For example, offer revisions `v3` and `v4` contain the same manifest-bound
`c99c2dc5…` source bytes (124,446,240 bytes), but different resolved project paths
and modification times, `1789246169034` and `1789246456789` milliseconds. Either
difference changes the extraction key. The pinned runtime has a separate cache
namespace, and publication uses partial directories plus a completion sentinel.

Safe next options, requiring separate implementation and qualification, are:

- Preserve and reuse an existing sealed project's matching cache for unchanged
  source/timing/format work. This behavior already exists.
- Introduce an immutable media store so equivalent projects resolve the same
  verified content path, if the portable-project and sandbox contracts can
  support it without weakening source isolation.
- Qualify a cache adapter based on source content digest plus every extraction
  dependency: time range, exact frame rate, output format, transforms and pinned
  decoder/runtime. Reuse the existing dependency guards and atomic publication;
  validate completeness and exact decoded frames before accepting migrated data.

Do not fake modification times, rename cache directories to guessed keys, or
hardlink editable source evidence merely to manufacture a cache hit. No SDK
cache code or existing cache data was changed in this work.

The next live qualification should export the sealed final offer project into a
new output directory with an explicitly empty, isolated `--cache` directory,
under `NativeRun` and the existing lease. Retain the full first measurement
window, all timeout evidence, resource samples, cleanup and output QC. A success
without a real timeout proves that one cold path completed; deterministic tests
remain the evidence for timeout recovery until a supervised run observes it.

## Follow-up: include startup in the same owner

The empty-cache offer trial subsequently passed in 86.880 seconds, including
47.646 seconds of picture rendering, with 2.711 GiB observed owned peak. It had
zero cache hits and five misses. Its turnover retries did not include a command
timeout, so this is one cold-path pass rather than live timeout-recovery proof.

The new 4K cohort then revealed a separate startup gap: the wrappers and owner
each called `read_snapshot` outside the bounded window before launching work.
A timeout there could stop without the complete owner receipt. Those duplicate
wrapper measurements have been removed. `NativeRun.prepare` now reserves its
receipt exclusively, acquires the same lease and uses `MeasurementWindow` with
an empty prelaunch process request. A missing registry accepts only that empty
request; it cannot silently discard remembered or newly observed owned identities.

The same baseline determines admission and the wrappers' existing capped
compressor allowance. Startup evidence is labeled separately from live samples.
Exhaustion records failure with no child launched, and recovered telemetry still
passes the original admission checks. A final deadline check before launch
prevents a late recovered reading or slow evidence write from starting work
after the original owner deadline. Receipt-collision, lease, cancellation,
pressure, recovery and exhaustion tests cover these lifecycle changes.

The 4K diagnostic produced its five requested native poses, but four real `top`
timeouts exhausted its live measurement budget; the run remains failed with
verified cleanup. Correct pixels do not permit reporting a failed supervised run
as successful. A different full attempt closed its Chrome target at frame 119;
that is a separate browser-lifecycle investigation, not a telemetry retry case.

## Follow-up: shorten the observation, not the evidence requirement

Two provided-source attempts subsequently exhausted four samples in 10.313 and
10.374 seconds. Each terminal window combined two 3-second command timeouts
with process identities changing during the footprint read. The saved host
tables contained about 1,200 processes while capture used about seven owned
processes. The completed readings did not establish a memory-cap breach.

Three bounded comparisons on a stable owned fixture rejected easy command-line
shortcuts. Disabling framework statistics reduced median `top` time only from
1.804 to 1.780 seconds (1.31%). Filtering to the owned PID changed the display
from more than 1,200 rows to one but took 1.810 seconds versus 1.806 seconds for
the full display. Asking for zero process rows still took about 1.82 seconds.
These switches did not fix the expensive collection or its identity-race window.

The subsequent prototype compared public `proc_pid_rusage` physical footprint
and host VM counters with the existing measurements. The separate per-process
compressed-byte field is diagnostic and is not used by a gate. An unprivileged
replacement must identify that field as uncollected/null when it cannot measure
it; zero and RSS would be incorrect substitutes. Host compressor bytes and all
owned-footprint, pressure, swap, disk, age, retry and deadline checks remain
required. A prototype comparison is not production qualification.

The owner also now pins its own supervision, retry, measurement and cleanup
implementation centrally, including callers such as website capture that omitted
those files. Existing caller hashes retain precedence, so automatic pinning
cannot refresh a stale prepared hash. Checks run before admission and before
launch, with the original final comparison after cleanup. Missing final files
retain a typed verification error and persist a failed receipt. The focused
baseline/retry/reconciliation/resource suite passes 58 tests, including four new
pinning/failure cases, and this change passed independent review.

## Qualified direct collection

The stable 64 MiB fixture recorded three paired comparisons. Median direct
helper time was 23.370 ms versus 1.789 seconds for `top`, a 76.55× difference in
collection time only. Physical footprint agreed within `top`'s display quantum.
The host compressor reading likewise agreed at its coarse displayed precision.
Only one of three unused-memory endpoint-bound comparisons passed: the other
two readings fell 8,290,304 and 2,523,136 bytes below the endpoint interval.
Host memory changes between reads, so those failures remain recorded; endpoint
bounds are not valid proof of an intermediate host measurement.

Source-backed qualification used the installed `top-144` version and verified
the public C layouts against the installed SDK. The formulas match its host
statistics: unused bytes are `free_count * vm_kernel_page_size`, and compressor
bytes are `compressor_page_count * vm_kernel_page_size`. Speculative pages are
already included in the free count. Evidence and source hashes are in
`artifacts/native-short-organic-2026-09-12/direct-macos-qualification-01/`,
including `source-backed-qualification.md` and `layout-verification.json`.

The production helper uses `proc_pid_rusage(RUSAGE_INFO_V0).ri_phys_footprint`
and `host_statistics64(HOST_VM_INFO64)`. It records paired start/exit evidence
around host collection; cross-sample ownership still uses the existing process
registry and `ps` identity checks. Per-process compressed bytes are explicitly
null with an unavailable diagnostic status. They are not RSS or zero. The
legacy parser retains historical numeric compressed readings.

The parser rejects missing APIs, invalid layouts, unknown samplers, malformed
counters and permission failures. Only validated process disappearance or actual
identity disagreement enters the existing bounded turnover retry. In particular,
flat ESRCH evidence cannot mask a nested EPERM error. No `top` fallback, new
privilege, relaxed memory cap or renewed deadline was introduced. Independent
review approved the final implementation; 107 focused sampler/runtime tests and
16 owner-baseline tests passed.

Two actual supervised workloads then passed with cleanup and implementation
pins verified:

| Workload | CLI elapsed | Owner elapsed | Result |
| --- | ---: | ---: | --- |
| `audio-regressions-02` | 12.62 s | 12.562 s | Eight codec tests, zero skips |
| `exports/official-identities-05` | 52.56 s | 48.727 s | 91 forward samples, reverse seeks, audio and full decode |

The export had nine valid live samples and a 2.963 GiB owned peak. Both workloads
observed and recovered from actual process turnover; neither encountered a
collection timeout. The final MP4 is byte-identical to the reviewed prior export,
with no additional picture or AAC encodes. These passes qualify the exercised
workloads, not every host load or cold start. The previous export encoded new AAC,
so its longer elapsed time is not a controlled sampler-only export benchmark.
