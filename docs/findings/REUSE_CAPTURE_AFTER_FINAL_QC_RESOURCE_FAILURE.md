# Reuse completed capture when only final QC fails

## Observed waste

Two Shorts completed picture/audio production and native forward/reverse capture,
then stopped at final encoded verification. Messaging was held at admission by
kernel memory pressure. Outreach stopped when a derived `selected.rgb` file
crossed the 10 GiB disk reserve. Neither failure established a defective video.

Repeating `--verify-from` preserved the video but repeated native capture. The
successful captures took 169.8 seconds for messaging and160.1 seconds for
outreach. Their original owners, JSON receipts and JPEG references already
existed and had verified cleanup.

## Recovery contract

`scripts/producer/studio/resume_final_qc.py` uses the existing `StageEvidence`
contract to seal the successful capture owner, original request, native JSON and
every forward/reverse JPEG. It binds that capture to the original render seal,
current project, runtime, tools, ordered frame schedule and exact final video.
Its pipeline subclass changes only capture acquisition. Media reuse and the
final encoded/audio checker remain the original shared implementations.

Use `--seal-only` before pruning derived source PNG caches. Then pass the same
render seal and capture root plus a fresh output directory to resume. Preserve
failed directories and original JPEGs. A changed video, missing/changed JPEG,
altered capture, wrong worker, incomplete cleanup or failed final owner rejects
the result. The recovery does not fabricate a third newly executed owner.

The final checker reads the final MP4 and retained JPEGs. Source PNG paths remain
recorded inside the unchanged capture JSON but are not reopened by this checker.
After sealing, this batch reclaimed18.48GiB of PNG caches and11 exact cache
aliases. Original footage, MP4s, JPEGs, capture JSON and failure evidence stayed.

## Result and limits

- Outreach passed531 encoded comparisons and full audio/video decoding. Its
  final owner took38.88seconds; the complete recovery invocation took115.94s,
  including source/proof revalidation. Zero new picture encodes or captures.
- Messaging passed576 comparisons and full decoding. Its final owner took
  33.46seconds; the full invocation took48.43s. Zero new encodes or captures.
- Forty-two focused/shared tests passed. Independent review validated the
  actual589 outreach and637 messaging JPEG bindings before reuse.

Do not use this when capture itself failed, source/timing/visual inputs changed,
original ownership is incomplete or a JPEG is missing. This explicit CLI recovery
does not imply that the default exporter automatically selects it. Technical QC
also does not replace editorial review, listening or user approval.

Evidence lives in `artifacts/img7138-remaining-shorts-2026-09-15/`: outreach
`export-04/capture-stage.json` and `export-05/delivery.json`, messaging
`export-01/capture-stage.json` and `export-02/delivery.json`, and
`SEALED-CAPTURE-CACHE-CLEANUP.json`.
