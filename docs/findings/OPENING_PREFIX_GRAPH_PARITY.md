# Opening/body parity: compare the graph before lossy encoding

The reusable primitive is `scripts/producer/opening_prefix_oracle.py`:

```python
verify_compositor_prefix(request: CompositorPrefixRequest,
                         runtime: PrefixOracleRuntime) -> dict
```

It proves exact pixels of the supplied full-body composition's core/review
intervals against the supplied opening composition. It does **not** compare
an encoded full output with an approved MP4, authenticate operator approval,
or authorize body generation/delivery.

## Why not compare decoded MP4 bytes?

The existing `test_opening_compositor_oracle.py` demonstrates the correct
boundary: independent full/prefix H264 encodes can choose different
quantization despite identical incoming pixels. Opening core/review AAC is
also independently encoded from the same float master. Packet identity or
exact decoded PCM equality across those AAC encodes is not an appropriate
content identity gate.

The new primitive captures the command produced by the **existing shared
compositor**, retaining its inputs, ordering, filter graph, exact frame gates
and absolute animation origin. Only the encoder/output suffix is replaced by
rawvideo SHA-256 frame hashes. It executes the full graph through the end of
review, then the core/review range graphs, comparing exact frame hashes and
integer PTS/durations. It does not shorten graphic assets or restart animation.
Identical core/review ranges reuse the same observation within this call.

The prior test remains an independent regression. The old P2 outside-dirty
oracle is a lossless H264/PCM repair proof, not a lossy delivery comparison;
its historical policy is unchanged. No SSIM or audio tolerance was invented.

## Caller contract and remaining integration

`opening_prefix_contract.py` defines held regular-file identities, exact clock,
core/review ranges, actual resolved full/opening clip dictionaries, and held
FFmpeg/FFprobe plus remaining timeout. Every supplied media/tool byte identity
is checked before and after execution; same-byte rewrites also fail inode/time
identity checks. Current local implementation hashes are observed separately.

The caller must bind these dictionaries to its **actual owned render
invocations**, not reconstruct a convenient graph after the fact. It retains
the authenticated source, cut, opening approval, lease, current code and
original generation deadline authority. A self-created request/returned hash
does not establish those facts. The function does not persist or promote a
receipt and has no final/body/approval side effects.

For audio, retain the existing separately held actual
`audio.program_master_selection.read_master_selection` and
`audio.program_master_excerpt.read_master_audio` evidence. Exact whole-master
float sample ranges are the content authority; there is no second master or
excerpt normalization here. Connecting both proofs to the actual body output
is still required before claiming opening/body audiovisual preservation.

## Bounds and lifecycle

- Review must contain core and end within 120 seconds and 7,200 frames.
- Rational frame rate is positive and at most 60; expected canvas is even and
  at most 4,096 pixels per side / 4,096 × 2,160 pixels total.
- At most 512 clip rows per graph and 512 held graphic files; graph JSON is
  preflighted for depth/node/string bounds and capped at 512 KiB.
- Every actual graphic is probed (metadata only, not a full decode): one
  zero-origin picture stream, matching rational rate/aspect, native surface
  at most 4,096 per side / 4,096 × 2,160 pixels. The larger graph's sum of
  input surface pixels, including base and repeated decoder occurrences,
  must not exceed 64 × 1,024 × 1,024. This conservative verifier admission
  accommodates 30 full-HD occurrences; it is not a 512-graphic render
  qualification. Oversized work is rejected, never downscaled or dropped.
- Held files are at most 8 GiB each and 32 GiB in aggregate. Hashes use 1 MiB
  chunks with a deadline check per chunk and no-follow single-link reads.
- One caller-supplied remaining allowance, at most 900 seconds, covers input
  checks, base probe, all graph executions and final checks. It never resets
  the original job's budget. Base probing counts all base video frames; graph
  pixel verification covers only the declared prefix, not the whole body.
- The existing owned-process runner has an optional empty-stdin byte-capped
  mode. Aggregate stdout/stderr is bounded before append; UTF-8 is decoded
  after complete capture. The old default remains unchanged. Timeout/overflow
  closes capture pipes before existing group termination/reaping, avoiding an
  unbounded cleanup capture. A declared external process ledger is preserved.
- Python output capture is bounded (maximum framehash output about 1.9 MiB,
  plus one 64 KiB read chunk). Native FFmpeg RSS is **not a measured fixed
  memory ceiling** or OS-contained. The input surface ceiling is workload
  admission, not a promise of total native decoder/filter memory usage.
- No Docker, provider, network or encode/delivery subprocess is invoked.
  Escaped process sessions/host-crash recovery still require the caller's
  existing durable resource ownership mechanisms.

These are mechanical verifier workload limits, not a product policy limiting
creative video length, graphic count, or quality.

## Local synthetic evidence — 2026-09-07

First actual cohort: six tests passed in **6.11 seconds wall / 3.200 seconds
suite**, retained at `/private/tmp/sniper-prefix-oracle-4rg0ane5` with log
`/private/tmp/sniper-prefix-oracle-first-20260907.log`.

The 64 × 36 moving-texture/translucent-overlay cases passed at 24,
30000/1001 and 24000/1001 FPS. Actual full/core/review comparisons took
266.5 / 271.8 / 269.8 ms respectively: first hash/implementation work
45–48 ms, complete tiny-base probe 48–49 ms, graph executions 169–173 ms,
final rehash 1.6–1.8 ms. These are **not** long-form or 4K forecasts.

Missing graphics, shifted half-open endpoints, changed same-start collision
order, actual timestamp offsets/multiple video streams, wrong full count or
canvas, and same-byte file rewrites all rejected. The actual no-graphics
shared-base range also passed. No failure was repaired or relabeled as a pass.

Initial old/new process cohort: 11 tests passed in 4.26 seconds wall, including
actual TERM-resistant descendants after overflow/timeout and group absence;
three pure held-input/clock tests passed separately in 2.73 seconds wall.
The successful graph observations explicitly report `encodedOutputObserved`,
`audioCompared`, and `approvalObserved` as false.

After graphic metadata admission was added, the combined final cohort passed
**26/26 in 11.45 seconds wall / 8.580 seconds suite**. Log:
`/private/tmp/sniper-prefix-oracle-final-20260907.log`; current proof fixture:
`/private/tmp/sniper-prefix-oracle-zhbnw8bg`. It includes the original independent
pre-encode and visible-marker tests as well as the new primitive. Actual
4098 × 2 and mismatched-rate graphic metadata rejected before graph execution.
The aggregate decoder-occurrence limit has a separate pure negative test.

The three positive current calls took 412.2 / 411.5 / 407.3 ms: first
hash/implementation 48–52 ms, base probe 48–49 ms, three graphic metadata
probes 140–144 ms, graph observation 166–168 ms, final recheck 1.8 ms.
The extra metadata cost is explicit; earlier 266–272 ms measurements do not
include that later admission step. All generated media and logs are retained;
no provider, Docker, creator footage or delivery action was used.

Reproduce from `PROJECT_SNIPER` with the existing local environment:

```bash
PYTHONPATH=scripts/producer:scripts/producer/tests PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m unittest \
  test_process_runner test_process_runner_bounded test_opening_prefix_contract \
  test_opening_prefix_oracle test_opening_compositor_oracle \
  test_opening_compositor_media -v
```

## Native-size overhead observation

A separate TEST-only benchmark reused a retained311.742-second,9346-frame
1920×1080/30000/1001 test base and one retained full-canvas catalog asset repeated
seven times. The new synthetic graph used1853core/2013review frames. It neither
requalified the historical run nor rendered new assets or creator media.

The oracle succeeded in82.0035s: input/implementation hashes0.2765s, complete
base decode/count39.8461s, graphic metadata0.0591s, graph observation41.6055s,
final recheck0.2136s. Proof and scope are retained at
`/private/tmp/sniper-native-prefix-cost-p8ficdrx`.

This shows a material full-base decode cost that tiny tests conceal. No quality
check was removed to improve the number. A future optimization may reuse a
separately authenticated, unchanged decoded-base observation; a filename/stat
cache or unbound caller-supplied frame count is not that proof. Thirty graphics,
ten-minute output, memory ceiling, asset-generation time and end-to-end SLA are
not qualified by this single loaded-host observation.

The benchmark script succeeded and retained both JSON records. The surrounding
`/usr/bin/time -l` command then exited1 because the sandbox denied its
`sysctl kern.clockrate` query; RSS statistics were unavailable, not zero. Its
reported82.12s wrapper wall time is secondary to the monotonic proof timings.
