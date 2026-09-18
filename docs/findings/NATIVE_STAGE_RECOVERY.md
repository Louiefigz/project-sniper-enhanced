# Preserve completed media when verification needs another attempt

Date: 2026-09-15

## Problem and measured cause

The 56.24-second IMG_7138 Short took **65m11s** from production start to review
handoff. That total is not the renderer's duration. Successful picture rendering,
dialogue finishing and color metadata took **403.020 seconds (6m43s)**. Other
measured media attempts and checks took about 16m30s. The remaining 41m58s covered
preparation, authoring, review, orchestration and gaps without individual timers.

The first export began 30m54s after the production clock started. Four project
builds were authored; these were not four successful video renders. The available
records do not justify attributing this interval to lengthy web research.

The failed batch picture route started 173 browser sessions and timed out after
1,376 of 1,406 frames. The successful streaming route used one render browser.
Its final verification then hit a generic 180-second subprocess timeout after
562 of 595 native capture occurrences. A separate supervised capture completed
in 186.436 seconds. Recovery also encountered missing SDK/sandbox admission
metadata, which was discovered after expensive work had finished.

Evidence: [original handoff](../producer/HANDOFF_ONE_SHORT_PLAYBACK_2026-09-15.md)
and `artifacts/img7138-editor-visual-short-2026-09-15/TIMING-ANALYSIS.json`.
The original failure records remain unchanged.

## Implemented behavior

`studio/native_short_export.py` now coordinates three **sequential** owners:

1. Render picture, finish dialogue and attach color metadata. After successful
   cleanup, seal the exact completed media in `render-stage.json`.
2. Capture the existing native references and forward/reverse seek states.
3. Run the existing encoded-frame comparisons and full audio/video decode.

Each stage keeps the existing 600-second `NativeRun` limit, shared heavy-work
lease, live resource measurements and descendant cleanup. The streaming capture
launches its existing Node worker directly under that owner, avoiding the generic
180-second Python wrapper. Batch capture keeps its existing phased checks.

The default is still full-quality streaming. No lower-quality export, skipped
reference checks, concurrent render trees or memory-policy relaxation was added.

`delivery.json` records the final status and export elapsed time, including
preparation and all owners. `pipeline.render.json` describes only the media
owner. Neither a completed picture nor `--render-only` qualifies final delivery.

## Recover without another encode

```bash
.venv/bin/python scripts/producer/studio/native_short_export.py \
  /absolute/project /absolute/new-verification \
  --verify-from /absolute/original-export/render-stage.json
```

The new attempt copies the exact completed MP4 and runs capture/decode checks.
It preserves the original route, cache and audio policy. It does not render
picture or re-encode audio. Old output and failed receipts remain immutable.
There is no automatic fallback to rendering when recovery admission fails.

`--render-only` deliberately stops after sealing media for later verification.
Conflicting render flags are rejected when `--verify-from` is supplied.

## Edge cases and shared code

`native_stage_evidence.py` owns generic stage, dependency, supervision and cleanup
proofs. Existing picture reuse calls the same guards. `native_run_lifecycle.py`
restores the caller's signal handlers between owners, including failed setup,
cancellation and finalization errors. Admission metadata is checked before any
heavy process can launch, avoiding late missing-key failures.

Recovery rejects changed source, project, tools, runtime, media, audio receipts or
supervision records; missing proof fields; unsafe aliases and overlapping output
directories; incomplete cleanup; failed owners; and conflicting options. Audio
review flags must be booleans and encode counts must be integers, because Python
otherwise treats `False` as equal to zero.

Shared audio mastering, exact timing, AAC packet handling, resource ownership and
picture/decode functions are reused. Short-specific native picture contracts stay
in their adapter. The generic evidence/lifecycle helpers can serve long-form
native adapters, but this change does not migrate the long-form render graph or
claim a measured long-form speedup.

## Validation and limits

- **183 tests pass**, covering stage orchestration/recovery, changed or incomplete
  evidence, cancellation, admission, leases, shared audio and exact timing.
- Independent standards and semantic reviews found no remaining blocking issues.
- `npm run build` and `npm run lint` exit successfully. They report existing
  broad-file-pattern build warnings and 41 lint warnings in unrelated files.
- Lint now excludes generated `.sniper-native-runtime` SDK copies after the live
  lint run was observed parsing multiple huge generated bundles.
- Live technical sample: existing `member-math-v3`, 8.24 seconds / 206 frames.
  `artifacts/native-stage-recovery-2026-09-15/render-01` stopped before launch when
  the tool sandbox prevented host telemetry. `render-02` obtained host telemetry
  but refused admission because macOS reported kernel memory pressure level 2
  (warning). Both retained truthful failures and verified no-child cleanup.
- After host pressure returned to normal, `render-03` sealed the completed media
  in **35.239 seconds**, including preparation and owned cleanup. `verify-01`
  resumed from that seal in **16.524 seconds**, checked 64 encoded frames, passed
  full audio/video decode and completed both owners' cleanup. The media SHA-256
  remained `eaccc509ed081a2f06f82a7cbb6842eb1e6b27b258f603f48fb1392e80081b0d`.
  There were **zero additional picture or audio encodes** during verification.
  The sample's existing audio-review warning remained visible; human approval
  remains false. Machine-readable evidence is
  `artifacts/native-stage-recovery-2026-09-15/VALIDATION.json`.
- These are successful invocation times for a small prepared sample, excluding
  prior admission failures and gaps. No new full-production time or achieved
  percentage speedup is claimed. The delivered 56.24-second Short's hash was
  independently checked unchanged; it was not rendered again.

## When this helps, and when it does not

Use this boundary when picture/audio completed but verification timed out or was
cancelled. It removes the need to repeat completed media work and eliminates the
specific streaming capture wrapper timeout seen in this incident.

Do not reuse a render after changing the story, source, captions, visuals, audio,
runtime or verification implementation. Historical exports without a valid new
stage seal cannot be backfilled into this recovery path.

A checkpoint does not shorten unmeasured editorial work. The production playbook
now calls for independent audio/caption and visual/reference owners after the lead
fixes the story and source clock, with a separate critic and one heavy render lane.
Measure actual wall time for those overlapping tasks; do not add their durations
and present that sum as elapsed time. A future full production run is required to
measure the combined benefit.
