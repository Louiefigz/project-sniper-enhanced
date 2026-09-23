# Process churn is not proof of memory exhaustion

The five-minute native fixture requested 2,670 preview frames. One attempt stopped
on sustained host memory pressure; a subsequent attempt finished capturing those
frames but stopped during audio packaging because short FFmpeg processes changed
between identity and footprint measurements. These require different remedies.

## Measure within one already-started helper

Starting Python between two `ps` snapshots lengthened the interval in which an
FFmpeg child could start or exit. Increasing retries alone still failed one of
eight live churn probes. The replacement reads the owned process tree through
SDK-declared libproc calls immediately before and after collecting footprints,
inside one helper. Eight live churn measurements then passed on their first
attempt. The original four-attempt, 18-second retry ceiling is retained.

`proc_listchildpids` returns a PID count, not a byte count. Its buffer argument is
still in bytes. See [Apple's implementation](https://github.com/apple-oss-distributions/xnu/blob/main/libsyscall/wrappers/libproc/libproc.c).
The local SDK layout was checked against compiled C: `proc_bsdinfo` is 136 bytes,
with process group at offset 100 and start seconds at offset 120. Unsupported ABI,
permission errors, oversized trees and unavailable live measurements fail closed.

An exited or zombie child is not a missing live measurement. A newly observed live
child requires a fresh sample; it is never assigned zero bytes. PID identity and
ownership checks remain required. Sampling does not establish the lifetime peak
of an arbitrarily short process and is not an operating-system memory quota.

## Preserve work at cleanup boundaries

Each preview window now has separate picture and audio-packaging owners:

```text
picture -> verified cleanup -> sealed picture
        -> capacity admission -> package -> verified cleanup -> sealed package
```

The existing heavy-work lease and host pressure policy apply to each owner. This
releases browser/encoder processes between windows and gives the host a bounded
capacity wait before the next owner. It does not purge other applications or
promise that unrelated host pressure disappears.

New attempts may copy completed sections only after validating the original
owner, cleanup, source/tool/runtime pins and media hashes. Packaging failure can
reuse its sealed picture. Unsealed output from older monolithic failed attempts
cannot be retroactively certified. Edited inputs invalidate incompatible seals;
final media QC and human editorial review still apply.

Do not use checkpoint reuse to bypass changed-source checks or a failed cleanup,
and do not treat telemetry failure as evidence that more RAM is needed.
