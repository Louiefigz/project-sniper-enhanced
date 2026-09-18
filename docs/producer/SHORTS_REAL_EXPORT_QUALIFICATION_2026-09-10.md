# Three real Shorts: export qualification and review handoff

All three control cuts now have actual 1080×1920, 25 fps review MP4s. Export,
source-bound picture checks, audio checks and whole-file browser playback passed.
This qualifies these technical outputs, not hook effectiveness, all library
styles, human listening or the complete application workflow.

The local [three-video review page](http://127.0.0.1:3991/) serves only the page
and three videos. Its persistent source is
[`review.html`](../../artifacts/shorts-end-to-end-2026-09-10/review.html).
The [manifest](../../artifacts/shorts-end-to-end-2026-09-10/review-manifest.json)
binds exact files, SHA-256 hashes, clocks and timings. Generated media and detailed
receipts remain in the ignored artifact directory; this is the durable checkpoint.

## Actual timings

| Cut | Treatment | Output | Prepared native export | Audio/color finishing | Peak measured owned memory |
| --- | --- | --- | --- | --- | --- |
| Follow-up | Full portrait presenter | 13.04s / 326 frames | 34.733s, warm | 4.069s | 2.174 GiB |
| Offer | Portrait → full comparison | 23.32s / 583 frames | 26.258s, cold | 3.167s | 2.310 GiB |
| Members | Portrait → arithmetic with close lower presenter | 8.24s / 206 frames | 24.220s, cold | 2.280s | 2.111 GiB |

Export plus finishing was **38.802s, 29.425s and 26.500s** respectively. These
times exclude source selection, strategy/model work, preparation, debugging, QC
and human review. They are not complete end-to-end editing times. The historical
`review-offer-warm-01` filename is misleading: its actual log records zero hits
and one miss. Copying the project changed the asset path, and the SDK's cache key
includes absolute path and mtime as well as the cut/fps.

The two revised pictures reused the original qualified AAC packets with zero
additional audio encodes. Follow-up used shared float mastering and one AAC
encode. Color correction preserved encoded picture payloads and AAC packets.

## Controlled transport comparison

The same follow-up project, cuts, warm cache and settings were exported with
the baseline private runtime and its file-backed frame transport variant:

| Runtime | Supervised elapsed | Peak measured owned memory |
| --- | --- | --- |
| Baseline | 49.961697s | 3.825425 GiB |
| File-backed transport | 34.732588s | 2.174058 GiB |

All 326 decoded frames and decoded audio were identical. This single paired
warm test observed **30.5% less time and 43.2% less measured memory**. It does not
establish cold performance, variance or a general system speedup. See the
[comparison receipt](../../artifacts/shorts-end-to-end-2026-09-10/TRANSPORT-COMPARISON-01.json).
These exports combine the tested realm fix with bounded file transport in an
isolated SDK. Installed SDK files and the application's export route are unchanged.

## Failures found and fixed

- **Scene boundaries:** offer frame 90 leaked the outgoing presenter behind its
  comparison; members frame 12 showed two presenter views and the old hook.
  Seek-safe clipping now removes outgoing views/text at the exact frame boundary.
  The shared native canvas compiler uses the same explicit exits.
- **Moving subject:** offer's fixed crop drifted off the speaker by 3.56s. Actual
  source frames drove bounded horizontal crop keyframes, preserving cuts, audio
  and caption words. The last portrait and first graphic frames were checked.
- **Audio:** raw AAC passed clocks but failed local signal checks in one, one and
  sixteen windows. Members had source true peak above zero, so some attenuation
  was intended mastering rather than proof of codec damage. The shared long-form
  float mastering path followed by one 256 kb/s AAC encode now passes loudness,
  exact clocks and fidelity against the intended master.
- **Color:** the opaque native JPEG path used sRGB transfer behavior but declared
  BT.709 transfer in H.264. Correcting only H.264/container transfer metadata to
  sRGB passed sampled picture gates while preserving encoded VCL picture payloads,
  AAC packets and clocks. This is specific to the measured renderer path.

Original controls, failures and revised outputs are retained separately. An early
PNG reference harness omitted the opaque native background and was invalid for
the comparison. Matching the real JPEG capture path repaired that harness; no
fidelity thresholds were relaxed.

## Verification on the exact review bytes

| Cut | Pixel samples | Minimum PSNR | Maximum RGB MAE | Audio windows | LUFS / dBTP | Master-to-AAC SNR |
| --- | --- | --- | --- | --- | --- | --- |
| Follow-up | 8 | 42.63 dB | 1.410 | 26 | −14.07 / −1.91 | 36.05 dB |
| Offer | 7 | 43.65 dB | 1.219 | 46 | −14.12 / −1.98 | 39.46 dB |
| Members | 8 | 43.35 dB | 1.227 | 16 | −14.08 / −1.99 | 45.37 dB |

- All 1,115 video frames and complete audio streams decode without errors.
- Twenty-three unique frames pass existing full-frame MAE ≤ 2 / PSNR ≥ 40 gates
  against source-bound native references. Comparisons honor declared output color;
  no input tag override, alignment or fitted correction is used. Pixel fidelity
  is sampled, not an all-frame comparison.
- All 88 audio windows pass both-channel local checks with zero lag and no gain
  fitting. Exact 48 kHz presented samples are 625,920 / 1,119,360 / 395,520. Every
  AAC packet is checked for priming, continuity and bounded decoder padding.
- Native reference poses reproduce after backward seeks/restart; fonts and
  actual source-frame injection load. Owned browser cleanup is verified.
- All exact review files play to the end in Chromium with zero dropped or
  corrupted frames and no waiting after playback starts. Midpoint, backward,
  near-end and zero seeks pass, followed by restart. See the
  [playback receipt](../../artifacts/shorts-end-to-end-2026-09-10/three-review-playback-01.json).
- The review page was inspected at desktop and 390 px phone widths without
  horizontal overflow. Muted browser telemetry does not establish listening.
- Forty-eight focused real-codec/audio regression tests pass, covering native
  finishing/reuse/failure retention plus existing program signal, mastering,
  packet clocks and byte budgets. Native canvas tests, TypeScript and focused
  ESLint also passed. Provider-stub tests are not real Director runs.

Media work reuses the long-form bounded owner, resource sampler, deadline and
cleanup checks, with one heavy job at a time. The user's existing unused-RAM
exception stayed local; process/swap limits and normal kernel pressure remained
required. No new ASR, generated assets or publishing was needed.

## Shared code and unresolved work

`audio/float_master.py` now owns the existing measured float mastering dispatch
for both the ordinary program bus and native finishing. The generalized
`audio/program_delivery_signal.py` shares the same bounded decoded-PCM gates.
`audio/native_dialogue_delivery.py` binds input bytes, retains failures, checks
exact clocks and output, and reuses qualified AAC after visual revisions. These
are real-media tested helpers; Studio's export button is not connected yet.

`native-short-composition.ts` supplies explicit portrait crops and exits. The
limited V9 writer still needs to execute reviewed Director typography, hooks and
views through this canvas. Default UI remains V5. The isolated runtime, color
repair and QA harness need portable application ownership instead of artifact paths.

The canonical Script Director library is connected before V9 scene planning,
but **no successful live Director/critic run has occurred**. Automatic approval
review rejected sending transcripts, instructions and template context through
the subscription CLI to an unverified external destination. Explicit permission
for that payload to OpenAI was requested and remains pending. No alternate model
route was used to bypass that rejection.

The three cuts retain provisional hooks. “Our $1K monthly goal” is a topic label,
not evidence of a strong template-selected hook. The
[six-family test plan](../../artifacts/shorts-end-to-end-2026-09-10/TEST-PLAN.md)
remains unexecuted creative coverage. Authentic evidence/capture styles also need
appropriate assets. The library is retrieved context, not a fine-tuned model.

CLI snapshot still showed stale state at the members boundary, while actual
export and renderer-bound reference passed. Studio edit/save/re-export, full
listening, new hook comparisons and complete end-to-end timing remain open.
Do not infer all-style or production-system optimization from these three passes.
