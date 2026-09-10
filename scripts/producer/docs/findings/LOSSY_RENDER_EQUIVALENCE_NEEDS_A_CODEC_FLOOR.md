# Lossy render equivalence needs a measured codec floor

## The assertion

Two independently encoded H.264 masters can be the same approved program
without having identical decoded pixels. An incremental-versus-forced-full
oracle must require exact clocks and normalized PCM, then distinguish exact
picture identity from picture equivalence above a pinned, independently
measured codec floor.

## The incident

The first current-render oracle required equal full-stream `framemd5` output.
That passed a stream-copy harness, but failed two canonical `libx264` masters
made from the same byte-identical pre-master file.

The source and all pre-master intermediates were byte-identical. The two
delivery files had different sizes and decoded picture hashes. Their normalized
48 kHz stereo `s32le` PCM was exact, their geometry and `30/1` rate were exact,
and both decoded to 1,350 frames. Full-frame SSIM showed a mean of
`0.997570375` and a worst frame of `0.991984`. The difference came from the
final lossy ABR encode, not an editorial change.

The first retained cohort still had a durability flaw: its `source.path`
pointed at `short-clean-source/work/enhanced.mp4`. A later real baseline trace
correctly rewrote that runnable work file, so source revalidation rejected the
cohort as stale after all six calibration renders had passed. The measurements
were real, but the authority was not durable. The calibrator now copies the
input before encoding into a dedicated SHA-256-addressed retained-source store,
encodes every pair from that retained object, and rehashes it at closure.

## Evidence with real numbers

`current-render-codec-floor-calibration-v1.json` retains three independent
control pairs—six canonical masters—of the same 45-second source:

- source SHA-256:
  `cbd60508ceed6af23291ac4dadf5127207142c2d4df7a4e5cdb857032d5a8cc8`;
- retained source size: `54,640,334` bytes, stored read-only at
  `artifacts/current-render-codec-floor-calibration-v1/sources/sha256/cb/`
  under its full digest;
- exact source geometry/rate: 1,350 frames at `30/1`;
- exact normalized PCM in all three pairs;
- lowest pair mean SSIM: `0.997517339`;
- lowest individual-frame SSIM: `0.992094`;
- all six output byte hashes and sizes are distinct retained observations;
- exact FFmpeg, FFprobe, Python, oracle, master, and configuration hashes are
  bound into calibration receipt
  `6aaf2c09760ebd3d44c808635dd32fc96ef009bbefd415659306e27b3584f366`.

The production comparison policy is fixed independently of the candidates:

| Check | Requirement |
|---|---:|
| Decoded frame count | Exact |
| Rational frame rate | Exact |
| Width, height, pixel format | Exact |
| Stream structure | Exact |
| Normalized 48 kHz stereo `s32le` PCM | Exact |
| Picture fast path | Exact complete `framemd5` |
| Lossy picture fallback, mean SSIM | `>= 0.995` |
| Lossy picture fallback, every-frame minimum | `>= 0.985` |

The retained control floor leaves margins of about `0.00252` on the mean and
`0.00709` on the worst frame. The receipt reports
`codec-floor-equivalent-not-pixel-identical`; it never relabels SSIM acceptance
as exact decoded-picture identity.

## The principle

Separate three claims:

1. **Same intent:** the render graph binds the same plan, source set, exact
   toolchain, dependency edges, and actual artifact hashes.
2. **Same clock and sound:** complete decode proves exact frames, rational rate,
   geometry, stream structure, and normalized PCM.
3. **Picture equivalence:** exact `framemd5` wins immediately; otherwise compare
   every frame against a policy calibrated only from independent controls.

Never derive the threshold from the incremental and forced-full candidates
being judged. That would let the disputed output define its own passing gate.
Recalibrate on a toolchain or encode-policy change, retain every control result,
retain and rehash the exact source object outside runnable fixture work/render
trees, and keep the policy version in the oracle receipt. A source digest beside
a mutable pathname is an integrity alarm, not retained authority.

SSIM is a bounded divergence guard, not proof that no tiny localized pixel
change exists. The graph's identical-intent and dependency closure is therefore
not optional.

## When not to use this approach

- For stream-copy, lossless, raw-frame, or deterministic encodes, require exact
  decoded hashes; a codec-floor fallback only weakens those proofs.
- Do not compare different approved plans, frame rates, geometries, color
  formats, or audio programs with this oracle.
- Do not carry this calibration to a different FFmpeg/libx264 build, encoder
  policy, hardware path, source class, or destination codec without a new
  control cohort.
- Do not use SSIM to approve copy, pacing, layout, legibility, safe zones,
  glitches, or style replication. Those remain semantic and visual QC gates.
- Do not infer a long-form speed or reliability claim from this 45-second
  calibration. It qualifies the comparison method, not pipeline performance.
