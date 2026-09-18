# Native Shorts organic-media implementation — September 12, 2026

This records implementation and measured qualification separately. See the
[remaining-work plan](SHORTS_REMAINING_WORK_PLAN_2026-09-12.md) for the complete
acceptance matrix. New private transcripts, footage and editing instructions
were kept local; there were no new Director, ASR or generated-media calls.

## Shared behavior implemented

New strategy v3 carries one speech-bound asset-use plan across logos, stills,
video and web captures. Every production asset has a frozen origin backed by
existing AssetRecordV1 source/intended-use fields. Selected uses record their
viewer purpose, exact source and output range, essential region, inspected
observations, rejected alternative and claim limit. No-insert is a first-class
choice. A style reference cannot by itself justify depicting its creator.

The same provided-only/local-only/public-web and placement policy survives
style presets, automatic selection, prepared requests, guided job authority,
assembly and cold reconstruction. Supplied media hashes remain checked even
when no insert is selected. Missing origin metadata cannot downgrade a public
capture into ordinary local media. Changed speech, assets, cuts or layout
invalidate prior decisions. The export checks admitted digests against observed
pins before launch; a changed asset cannot simply acquire a new accepted hash.

Current app intake supports raster supporting images through the project's
`broll/` folder and ingest/rescan, followed by preparing the Short brief. There
is no direct supporting-image file picker. SVG production bindings work in the
native authoring path used by these official-logo tests, but folder ingestion
now explicitly rejects SVG/SVGZ before probing. A separately admitted local
raster derivative is required for that intake path. The shared long-form format
set is preserved; a native inventory row still does not establish supported
render MIME or visual suitability. See
[supplied-media handling](SUPPLIED_MEDIA_FORMATS_2026-09-13.md).
Guided preparation is currently exposed through `prepare-guided`; the app
endpoint still prepares from the default manifest. The limited V9 scene compiler
also still rejects required external asset IDs. These native project/CLI tests
therefore do not establish automatic in-app external B-roll execution.

The supported HTML/CSS contract rejects untimed image backgrounds, CSS escapes,
entity-encoded style attributes, imported stylesheets and alternate playback
start/rate attributes. This is a structural contract, not a general JavaScript
security sandbox or an automatic semantic critic. Required audio handoffs for
external audible quotations remain unsupported and are explicitly rejected.

The public web bridge uses the same origin reader before writing its final
ASSET.json. Invalid JSON, changed capture bindings, missing/wrong origin pins
and failed shared-reader validation leave no final asset binding. Both existing
Claude and GitHub captures exercised the actual adapter and reader in
`artifacts/native-short-organic-2026-09-12/web-origin-bridge-check/result.json`.
This does not count as a new automatic browser-capture integration run.

## Real source cohort

The two new v3 projects use the same admitted C0679 source and retained transcript,
with source cuts 20.801–25.121 and 28.781–35.341. The original is 3840×2160 at
24000/1001 fps; the portrait output is 272 frames / 10.88 seconds at 25 fps.
The source probe and sampled crop inspection ran under the existing native owner.
The upper backed hook uses the canonical question template: “Are you still using
AI only for prompts?” Centered word highlighting follows the retained speech.
This is a product-identification test excerpt, not a complete instructional payoff.

- Official-identity plan: Claude and Gemini wordmarks enter at their spoken cues
  and share a readable hold through the end of the list. The official Claude
  light variant retains #141413 and its #D97757 symbol; Gemini retains its original
  gradient and black wordmark. Actual source HTML/CSS and extraction evidence
  are pinned. A tiny favicon and an older recolored cache were rejected.
- ChatGPT has an explicit no-insert gap because the attempted official acquisition
  did not supply a verified product-specific mark. No OpenAI/Codex substitution
  was made. The passage names products; it does not demonstrate a product operation.
- Restricted-source plan: the same source, cuts, hook and captions with placement
  off and provided-only sourcing. Public production assets are absent.

Both plans passed assembly and cold reading. Changing the public case to
provided-only, stripping a logo origin or changing the product speech correctly
rejects the previous plan. Exact paths, evidence and limitations are in
`artifacts/native-short-organic-2026-09-12/cohort/AUDIT.md`.

## Runtime qualification and failures retained

| Attempt | Result | Owner elapsed | Observed owned peak |
| --- | --- | ---: | ---: |
| offer-cold-01 | Full export/QC passed with explicitly empty frame cache | 86.880 s | 2.711 GiB |
| official-identities-01 | Four-sample telemetry budget exhausted; cleanup verified | 13.475 s | No complete live sample |
| official-identities-02 | Chrome target closed at captured frame 119/272; cleanup verified | 40.768 s | 3.433 GiB |
| diagnostic-capture-02 | Five native poses produced correctly; owner still failed four command timeouts; cleanup verified | 16.887 s | No complete live sample |
| official-identities-03 | All 272 batch picture frames completed; later AAC signal gate failed | 99.806 s | 2.988 GiB |
| official-identities-04 | Completed picture reused; full current audio/native/encoded QC passed | 59.717 s | 3.005 GiB |
| official-identities-05 | Direct memory sampler; picture and AAC reused; all final QC passed | 48.727 s | 2.963 GiB |
| provided-only-01 | Source extraction completed; live telemetry budget exhausted; cleanup verified | 12.670 s | No complete live sample |
| provided-only-02 | Full batch picture completed; live telemetry exhausted during audio startup | 93.937 s | 3.003 GiB |
| provided-only-03 | Completed picture and exact qualified AAC reused; all final QC passed | 57.398 s | 3.098 GiB |

The cold offer run includes 47.646 seconds of picture rendering. Its cache trace
records zero hits, five misses and 287 extracted source frames. It observed
process-turnover retries but no command timeout; it alone does not prove timeout
recovery or a cold-start success rate. The earlier failed attempts remain failed.

The 4K transport completed all 120 requests with no errors and no base64 fallback.
Its Node frame cache is bypassed by the existing URL transport, so reducing that
cache would not address the browser failure. A fresh session produced frames
119, 120, 271 and 108, then a byte-identical repeat of 119 with exact scene/source
state. The diagnostic itself remains failed because its resource sampling failed.
Browser lifetime or decode/compositing accumulation is a hypothesis; OOM was not
confirmed. The explicit 48-frame-session route completed the identity picture,
then that exact picture passed all current parent QC through verified reuse.
No source pixels, output resolution or quality thresholds were reduced.

The full official-identities-04 CLI invocation took 63.72 seconds, including
preparation. Within the worker, picture reuse took 1.606 seconds, dialogue
delivery 4.897 seconds, native capture/seek checks 35.880 seconds and encoded
comparison/full decode 4.158 seconds. It checked 91 forward picture samples,
with reverse-seek evidence, and encoded no new picture. These timings exclude
editorial planning, asset acquisition and all earlier retained attempts; they
are not raw-footage-to-finished-edit turnaround estimates.

The provided-only final CLI took 60.95 seconds. Picture reuse took 1.593 seconds,
audio reuse with current gates 1.977 seconds, native capture/seek checks 36.048
seconds and encoded/full decode 4.117 seconds. It also checked 91 forward
samples, with reverse-seek evidence. The exact previously qualified AAC and
master were reused with zero additional audio encodes. Its earlier attempts
took 15.65 and 96.75 CLI seconds and remain failed, not hidden in the final time.

Both videos are indexed by `review-manifest.json` and served locally on port 3996;
the earlier three examples remain linked on port 3995. Owned extraction produced
12 selected final frames per case in 8.373 seconds. Visual inspection covered
all 12 official-identity samples and four matching provided-only samples. The
upper title, center word highlighting, original wordmark colors/proportions,
exact entry/exit boundaries and unclipped presenter were inspected. Human
listening and complete phone-size comprehension remain open. The HTTP page,
posters and both byte-range video routes pass; unlisted files return 404.

The repeated telemetry failures led to a qualified shared sampler change.
Both provided-case terminal windows exhausted four attempts in about 10.3 seconds,
alternating new-child identity changes and two 3-second `top` timeouts. Saved
tables contain roughly 1,200 host processes versus seven owned capture processes.
No measured resource cap was breached in those terminal windows. The direct
reader now uses public macOS physical-footprint and host-statistics APIs with
verified ABI, kernel page units, before/after identity checks and explicit
sampler provenance. Per-process compressed bytes are an unavailable/null
diagnostic; host compressor and all gating fields remain measured. Permission
errors fail immediately; evidenced disappearance/identity races and command
timeouts retain the same four-attempt, 18-second and original-deadline limits.

The stable-fixture comparison measured 23.37 ms per helper command versus
1.789 seconds for `top`; this is sampler timing, not an export speed claim.
Apple's matching `top-144` source confirms the host-memory formulas. The two
failed endpoint comparisons remain recorded: nonsimultaneous host readings
cannot bound a fluctuating intermediate value merely by their endpoints.

The new actual codec run, `audio-regressions-02`, passed all eight tests with
zero skips in 11.814 unittest seconds and 12.62 CLI seconds. It retained three
complete direct snapshots, recovered one observed identity-turnover retry,
and verified cleanup and source/code pins. The interrupted `audio-regressions-01`
remains failed. The new browser acceptance, `official-identities-05`, then passed
91 forward samples, existing reverse checks and full audio/video decode in
52.56 CLI seconds. Nine complete direct samples observed 2.963 GiB maximum
owned footprint and 2.533 GiB maximum single-process footprint. One identity
retry recovered; no memory cap, deadline or comparison threshold changed.

This latest export reused both picture and AAC and produced a byte-identical
MP4 to the visually inspected `official-identities-04`. The existing review page
therefore still shows those exact final bytes. Its time is not a controlled
sampler-only comparison with attempt 04, which encoded new AAC. Two successful
workloads establish these cases, not a universal cold-start success rate.

### Native audio profile and preserved defaults

The initial 256k candidate failed one active-channel window at 19.993359 dB SNR
against a 20 dB floor. Raising bitrate alone fixed signal fidelity but exposed a
decoded peak of −1.15 dBTP, above the −1.5 ceiling. The qualified native profile
therefore reuses the same shared DSP with −2.5 dBTP internal headroom, at most
six static-gain dry runs and 320k AAC. The production export measured −14.33 LUFS
and −2.09 dBTP, with exact stereo 48 kHz / 522,240-sample presentation.

Profiles are immutable and explicit. Default long-form settings stay at −2.0
internal headroom, two dry runs and 256k; final gates are unchanged for both.
Native AAC reuse requires the exact profile, input and output evidence. A
profile-less historical policy-3 receipt requires explicit `default-v3` selection.
The subsequent native AAC-policy fix adds another independent requirement:
the donor and every candidate must record the current consumed encoding options,
including disabled perceptual noise substitution. Historical donors missing
`aacEncodingPolicy` require fresh encoding under either profile; selecting
`default-v3` cannot grandfather or backfill that missing evidence.
Completed-picture reuse likewise rechecks current dependencies, all original
frame hashes, cleanup and final audio/color/native/encoded QC. See the
[stage-reuse and audio finding](../findings/NATIVE_SHORTS_STAGE_REUSE_AND_AUDIO_HEADROOM.md).

Focused validation includes 67 TypeScript contract/request/authority tests,
11 native capture/batch tests, 18 native runtime/picture-reuse tests,
70 shared-audio/profile/compatibility unit tests and 42 ingest tests. Earlier
resource/baseline/lease suites remain recorded with the implementation. These
structural suites do not substitute for actual codecs, playback or editorial review.
The final direct-sampler suite adds 42 API/parser tests and totals 107 passing
resource/retry/runtime/origin/lease tests; all 16 separate owner-baseline tests
also pass. Shared audio now additionally has the eight passing actual-codec
cases described above. Independent source reviews approved both the sampler
and centralized supervisor-code pinning, including missing-file failure reporting.

## What remains editorial or unqualified

The next app slice is implemented: local POST preparation now derives guided
authority from the saved journal, uses its actual bootstrap manifest and intent,
and holds the existing checkpoint mutation lease across preparation. It rechecks
the complete journal and live lease before returning the brief. Malformed state
cannot fall back to ordinary preparation, and submitted packets or policy
overrides are rejected. Nine new route/service tests bring the focused app and
authority set to 58 passing tests; full TypeScript, lint and independent review
also pass. Proposal reconstruction is stubbed in the small route fixture; actual
guided external-asset execution is still a separate compiler/qualification step.

No structural report declares identity, audience comprehension, publication
permission or human listening approved. The current creator-photo/opening/quote
cohort is not complete. Tool-operation demonstrations, authenticated or nested
scrolls, broad source discovery, historical/current identity decisions and
fast/measured/changing-delivery playback need their own actual-source tests.
An illustrative clip cannot establish a transformation or measured product result.
General cross-project cache reuse and scene-level incremental encoding remain
separate work; identical source bytes do not override the SDK's path/mtime key.
