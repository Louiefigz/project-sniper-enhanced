# External-media decode memory must match the admitted codec class

## The incident (2026-07-30)

The supplied `IMG_7134.MOV` is 4K HEVC Main10 HLG. A bounded five-second
decode in the approved external-media image exited 137 with no stderr under
the original 512 MiB cgroup limit. Repeating the same decode with the same
image, read-only source mount, non-root user, disabled network, one CPU,
64-process limit, and dropped capabilities succeeded at 768 MiB.

A 30-second decode then completed in about 72 seconds, roughly 2.4× real
time. The old child timeout was `min(maxDecode, max(90s, mediaDuration))`, so
the 403.7-second source would have been killed after about 403.7 seconds even
though the declared admission budget was 900 seconds. Straight-line observed
runtime is about 969 seconds, already beyond that default.

That result does not mean the input is malformed and it does not justify an
unbounded decoder. It means 512 MiB was below the working set of a supported
production codec class.

## The correction

`headless/external_media_probe_policy.py` now defines one 768 MiB authority
used by both Docker launch flags and post-launch inspection:

- `--memory=768m`;
- `--memory-swap=768m`, so there is no extra swap allowance;
- the attestation rejects any resolved `Memory` or `MemorySwap` value other
  than exactly 805,306,368 bytes.

New receipts identify this changed resource/deadline contract as
`sniper-external-media-probe-v2`; a retained v1 receipt is not silently
reinterpreted under the new policy.

The other isolation controls are unchanged. Full decode still runs
networkless, read-only, non-root, capability-free, at one CPU and 64 PIDs.

The embedded decoder now reports an otherwise-silent child termination as
`DECODER_SIGNAL_<signal>` or `DECODER_EXIT_<code>`. If Docker kills the whole
probe, the host distinguishes an attested `OOMKilled` state from exit 137,
which can mean SIGKILL or a bounded-memory OOM. Neither case is mislabeled as
the old generic “decoder rejected input.”

The child timeout now uses the declared `max_decode_seconds` wall bound rather
than assuming decode is at least real time. The default is 1,200 seconds:
about 24% above the observed 969-second projection, within the existing
3,600-second hard validation ceiling, and compatible with the 25-minute
reference worker window plus bounded host cleanup slack. The canonical ingest
route now has a 30-minute process ceiling so it cannot terminate that legal
decode at its former 10-minute request limit.

## The principle

A resource cap is part of format support. Calibrate it against the highest
working-set codec class the product claims to admit, then attest that exact
cap after launch. A limit that rejects valid supported media is not safer in
practice; it is an undocumented compatibility boundary.

## When not to use this result

- Do not apply 768 MiB to the render container; admission decode and
  production composition have different working sets.
- Do not raise the 8 GiB source-byte limit or any duration, frame, dimension,
  stream, CPU, PID, network, privilege, or mount boundary based on this test.
- Do not claim that one five-second success proves every six-hour HEVC file.
  Full-source admission remains the production gate.
- Do not estimate the kill deadline from media duration. Codec, resolution,
  bit depth, hardware, and thermal state can all make decode slower than real
  time; use the explicitly bounded wall budget.
- Do not treat exit 137 alone as certain OOM. Use Docker's `OOMKilled` state
  when available; otherwise report SIGKILL-or-OOM honestly.
