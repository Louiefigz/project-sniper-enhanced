# Short production: remove repeated work before reducing work quality

## What the timing audit showed

The original one-Short handoff covered 65m11s. The successful picture/audio render
was 6m43s; other measured media work was 16m30s. The remaining 41m58s was outside
those scopes, including preparation, reviews, troubleshooting and revisions.
It cannot all be labeled idle or blamed on encoding. Three later Shorts totaling
157.8 seconds spanned 2h19m27s; one clean 46.28-second export and its automated
checks took 9m21.7s. See the
[batch audit](../studies/SHORTS_BATCH_TIME_AUDIT_2026-09-15.md).

## Mechanisms changed

1. Check the exact float audio master before generating pictures. Pass that
   same bound file to the first AAC candidate. Continue to check the actual
   encoded audio and muxed result. A donor is checked directly rather than
   producing an unused replacement master.
2. Seal a successful native capture automatically. If later encoded QC fails,
   reuse the exact completed media and capture, then rerun final QC. Changed
   source, code, clock, runtime, image or ownership evidence still rejects reuse.
3. Stream decoded RGB frames through the same color conversion and comparisons.
   A selected-frame scratch file is an intermediate representation, not quality
   evidence that needs to occupy several gigabytes on disk.
4. Share review preparation through a manifest. Keep exact exported MP4/AAC
   bytes, editable source pictures and explicit timing/listening status. Optional
   raw recognition is reusable without pretending bad timestamps are acceptable.

The output resolution, frame rate, CRF, audio policy, comparison schedule,
thresholds and complete A/V decode have not been relaxed by these changes.

## Real-media equality evidence

The supervised test lives at
`artifacts/shorts-optimization-2026-09-15/equivalence-02/`.

| Check | Observed result |
| --- | --- |
| Original 60.84-second outreach MP4 | Same SHA-256; no new picture/audio encode |
| Selected decoded RGB | All 3,303,244,800 bytes hash identically to the retained original QC |
| Picture results | All 531 forward and 58 reverse comparison results identical; full A/V decode passed |
| Scratch storage | RGB scratch 0 bytes; owned filter script 5,478 bytes, removed after use |
| RGB buffer | Observed peak 6,285,312 bytes; this is the RGB buffer, not total process memory |
| Exact 8.24-second float master | Same SHA-256 as the previous approved technical master; 0 AAC encodes |
| Known 60.84-second hum failure | Reproduced in 12.45 seconds before any picture encode |

Selected-picture QC took 12.36 seconds. The original retained QC span was 25.28
seconds. This is a useful observation on the same media, not a controlled
cold-cache speed benchmark or a full creative production time.

The first test attempt stopped before child launch because its sandbox could
not measure host memory. The successful attempt allowed those measurements and
kept the supervisor, native sandbox, shared lease, pins, resource thresholds and
cleanup checks. The early failure was preserved, not relabeled as a pass.

## When not to use these shortcuts

- A valid MP4 without complete, compatible stage evidence is not a resumable
  capture. Never promote partial images or edit a receipt to fit current code.
- Audio preparation is not a substitute for encoded AAC/AV verification or
  listening. Codec true-peak correction still uses the existing correction path.
- Streaming does not permit fewer checked frames. Incomplete/excess output,
  wrong dimensions or changed reference bytes fail.
- Source/cut changes require rebuilding the Studio dialogue; later Studio edits
  require a fresh export and verification. Generic landscape/rational-clock
  packaging tests do not certify an unimplemented long-form receipt adapter.
- A hard kill can leave the tiny owned filter script. No successful result is
  published, and unrelated files/caches are never deleted automatically.

## Operating target

The target is roughly 30 minutes for an ordinary one-minute Short with reusable
source evidence and components. Research and independent editorial review can
overlap; heavy media work retains one shared owner lane. Quality defects or a
custom treatment may legitimately exceed the allowance. Record the cause rather
than lower quality. The prepared-fixture tests do **not** prove the full
30-minute creative target. Use the
[implementation plan](../producer/SHORTS_OPTIMIZATION_IMPLEMENTATION_PLAN_2026-09-15.md)
and continuous production clock to measure the next real cohort.
