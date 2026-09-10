# Current C0679 quality gap: native MOV diagnostic preflight

The first review-ready candidate remains unchanged at
`artifacts/c0679-creative-revision-2026-09-09/`. Its exact first-ready time was
2026-09-10T03:47:32.864410Z, **3h08m19.598s** from the actual current creative
request. The following work is additional quality investigation on that same
revision; it does not reset its clock or start a fresh-input benchmark.

## What is actually known

The pinned SDK selects PNG capture for MOV and ProRes 4444 with
`yuva444p10le`. The single-worker low-memory streaming path permits MOV.
The exact native `buildStreamingArgs` ProRes branch returns before the
H264/H265 color-tag code. Its generated argument list contains no explicit
primaries, transfer or matrix options. What FFmpeg actually reports or whether
canonical RGB decode succeeds is **not measured yet**.

Read-only extraction of the pinned SDK's pure functions passed seven argument
checks. The SDK and current project were not modified. Five cheap Python tests
passed in0.006 runner seconds, including unsafe output, payload cap, incomplete
frame count, and failed canonical decode without invented color tags or metrics.
Independent source review found no concrete blocker in the prepared helpers.

## Actual refusal — no media was launched

One unchanged-guard admission attempt failed with
`NativeWorkBusy: Native heavy work is already active`.
Its receipt says `childNeverLaunched: true`, `cleanup.verified: true`, and
unchanged source/additional-file pins. No MOV output directory exists.

The current human-review server owns that exclusive slot (supervisor73340,
worker73366, active lease nonce `4a6a8e520ccd46a3b7c5c9340e0316bf`). It was
preserved, not stopped or bypassed. Its latest inspected disk reading was about
13.37GiB; that is not a fresh diagnostic admission or permission to share the
exclusive slot. The ten-GiB reserve and all other resource limits stay unchanged.

## Prepared files and exact next step

All are under `/private/tmp/sniper-c0679-fresh-b-20260909.0Ydfxp/`:

- `inspect_native_mov_preset.cjs` and `native-mov-preset-inspection-v1.json`:
  exact source-function hashes and actual generated MOV arguments.
- `native_mov_reference_controls.py`: only the23 retained exact native PNG
  references, bounded PNG payload, native streaming preset, ffprobe metadata,
  existing canonical RGB conversion and unchanged whole/presenter metrics.
- `test_native_mov_reference_controls.py`: no-media failure-path regressions.
- `native-mov-reference-controls-phase-v1.json` and
  `native-mov-reference-controls-v1.render.json`: the retained refused attempt.
- `native-mov-reference-controls-phase-v2.json`: a prepared **unrun** attempt
  with the acknowledgement gate bound to its own new guard receipt.

Do not repeatedly retry, steal the lease, move encoding into the preview-control
lane, restart scheduling, or shut down the review without user direction.
After the user authorizes pausing the preview, or it has cleanly ended, verify
its exact owned cleanup and lease release. Then the prepared single attempt is:

```bash
/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/.venv/bin/python /private/tmp/sniper-c0679-fresh-b-20260909.0Ydfxp/run_native_phase_v5.py native-mov-reference-controls-v2 /private/tmp/sniper-c0679-fresh-b-20260909.0Ydfxp/native-mov-reference-controls-phase-v2.json
```

Use the existing outer host-measurement permission and inner localhost-only
sandbox. Preserve missing-metadata/decode failures instead of adding guessed
input-color tags. Record bytes, all23 frame/ROI outcomes, actual resource/timing
and cleanup. A passed frame control only supports considering further native
MOV qualification; it is not a full MOV render, browser delivery, audio,
lossless-source, human or overall-goal approval. No full MOV render is authorized
by this diagnostic, and no new full render or fresh benchmark has started.
