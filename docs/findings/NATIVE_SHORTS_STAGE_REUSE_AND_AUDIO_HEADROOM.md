# Finish the failed stage without discarding a completed picture

Measured locally September 12–13, 2026. These are specific qualification cases,
not a claim that every source, style or machine has the same behavior.

## What the real Short exposed

A 10.88-second portrait Short used a 3840×2160 source, retained its original
decoded pixels and produced 272 output frames at 25 fps. A long-lived native
browser session closed at frame 119. Transport evidence showed 120 completed
requests, zero transport errors and no base64 fallback; an OOM cause was not
established. The observed owned-process peak was 3.433 GiB.

An explicit route that disposes the native browser after at most 48 frames
captured all 272 frames and encoded them once, using the same native screenshot
quality, absolute timeline and SDK software encoder settings. Its observed
owned peak was 2.988 GiB. Source resolution and final comparison thresholds
stayed unchanged. The overall attempt still failed at the later audio gate.

Duration alone does not describe native render memory. Original frame size,
concurrent decoders and browser lifetime matter. This test supports bounded
session lifetime as a useful execution option; it does not establish the cause
of the earlier browser crash or a universal optimal batch size.

## Why the audio failure needed two checks

The 256k AAC encoded from the qualified stereo float master failed one active
channel's 0.5–1.5 second window: SNR 19.993359 dB against the unchanged 20 dB
floor. Quiet-channel windows passed their separate activity-aware rule.

A controlled 320k encode of that exact master raised the lowest active-window
SNR to 25.660761 dB. It nevertheless failed decoded true peak: −1.15 dBTP
against the −1.5 dBTP ceiling. The source channels did not need remapping to
repair this signal-comparison failure.

A second owned experiment reused the shared float-master algorithm with an
internal limiter target of −2.5 dBTP, a bounded six dry-run measurements and
320k AAC. It measured:

| Measurement | Float master | Decoded AAC |
| --- | ---: | ---: |
| Integrated loudness | −14.31 LUFS | −14.33 LUFS |
| True peak | −2.48 dBTP | −2.09 dBTP |
| Minimum active-window signal SNR | Reference | 25.467199 dB |

Every original delivery/signal gate passed. The exact 522,240 sample clock and
272 picture packets were retained. The trial took 4.740 seconds, with zero
picture encodes and one AAC encode. The second proposed target was not attempted
because the first qualified. This experiment alone is not a finished export.

The implementation now passes the immutable `native-short-v1` profile into the
shared mastering algorithm: a −2.5 dBTP internal target, at most six static
dry-run measurements and 320k AAC. Long-form callers retain `default-v3` with
their existing −2 dBTP target, two dry runs and 256k AAC. Donor reuse requires
the selected profile; historical receipts without profile metadata are accepted
only when the caller explicitly selects the legacy profile. Shared AUDIO/ENCODE
dictionaries and final tolerances remain unchanged.

Two subsequent exports completed every current gate. The official-brand case
took 63.72 seconds from CLI launch through return and reused its completed
picture. The provided-only case took 60.95 seconds and reused both its picture
and the exact qualified AAC packets. Each checked 91 forward native/encoded
samples plus reverse seeks and full audio/video decode. Both delivered
−14.33 LUFS and −2.09 dBTP. These times exclude the original picture-render
cost; human listening and complete phone-size editorial review remain separate.

The final shared-sampler acceptance reran the official case with both qualified
stages reused. It passed all checks in 52.56 CLI seconds and produced the exact
same MP4 bytes as the reviewed official export, with zero additional picture
or AAC encodes. Eight actual codec regressions also passed with no skips in
`audio-regressions-02`. Since the prior official export encoded new AAC, this
elapsed-time difference cannot isolate the sampler's contribution.

## Reusing the completed stage

`native_short_picture_reuse.py` requires the completed batch receipt, all frame
hashes, disposed sessions, current project/assets/runtime/tools, original
supervisor before/after pins and verified cleanup. A later audio failure does
not invalidate the already completed picture when those dependencies match.
Copying is exclusive and rehashes source and destination. Current audio, color,
native/reverse-seek, encoded-picture and full-stream checks still run.

```bash
.venv/bin/python scripts/producer/studio/native_short_export.py \
  <same-project> <new-export-directory> --cached-native-batches \
  --picture-donor <completed-picture-attempt>
```

Do not use this route when source, layout, runtime, picture implementation,
clock, inventory or cleanup evidence differs. It is not a general cache-key
migration, a substitute for final QC or permission to label a failed output
approved. Retain the failed attempt unchanged and record the new attempt's
actual end-to-end time separately from the original picture-render cost.

Evidence: `artifacts/native-short-organic-2026-09-12/exports/official-identities-02`,
`official-identities-03`, `audio-fidelity-01/diagnostic-summary.json`, and
`audio-fidelity-02/comparison.json`, `exports/official-identities-04`, and
`exports/provided-only-03` in that same artifact group.
