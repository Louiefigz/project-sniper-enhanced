# C0679 native presenter edit — September 9, ongoing

## 21:25 UTC — corrected MP4 playback passes; current Studio fails

`corrected-browser-whole-v2` completed694.551128s guarded. Initial/final explicit
quality counters were248/16639 total and0/0 dropped (delta16391, not a claim of
16394 observed counter frames).16393 rVFC callbacks,83.5ms maximum callback gap,
1370 samples and zero disruptive events passed coverage/playback checks. Actual
ended event683.8465s, final media683.766417s, final-frame time683.724708s. Polling
added1.4337s; it is not playback slowdown. All source/runtime/cleanup/lease checks
passed. Combined browser-review-fail remains ONLY the original strict numerical
color miss. The browser was headless/muted; no listening or user approval implied.

`current-studio-full-source-v1` completed74.327707s guarded/66.492s browser with
FAILED status.1285 opening samples cover64.4454s, maximum A/V43.629ms and
audio/clock70.960ms. The35–65s timing also passes. However active narration has
668 seeking and668 waiting events, no pause/stalled/error events, and two dropped
picture frames. Event buffer did not overflow. Startup diagnostics identify blocked
MotionPathPlugin CDN3.12.5 and3.15.0 loads followed by unhandled rejection. Stable
sample clocks do not excuse repeated seeks or prove audible continuity. Cleanup
verified; the current user Studio server was not restarted or closed.

Terminal receipts are under `/private/tmp/sniper-native-frame-transport-20260909.wsUupP/`.
The durable Attempt A archive stays byte-identical; handoff limitations and later
evidence belong outside it. Saved-path re-export and human listening are untested.

## 21:01 UTC — browser color discrepancy characterized; playback measurement retry

Three exact corrected-MP4 frames in the same pinned Chrome completed10.075383s
guarded/1.878s browser. Color comparison retained a strict failure at653:
MAE1.879724/PSNR39.466828dB versus required MAE≤2/PSNR≥40. Frames312/383 passed
at40.565834/41.443199dB. This failure is not silently reclassified as a pass.

Same-Chrome image controls then completed11.130239s guarded/2.760081s worker.
Native JPEG→Chrome and canonical FFmpeg PNG→Chrome were EXACT RGB at312/383/653.
Canonical image→Chrome video measured MAE0.920406/1.302479/1.036080 and
PSNR44.271296/42.267408/42.252427dB. Thus the remaining difference is in the video
decode/conversion path, not image color management; no particular rounding/chroma
implementation defect is proven. Independent agent still review of383/653 found
consistent presenter/skin/blue graphics/background/lower-third and no material
legibility loss. Keep the corrected V10 bytes unchanged. This supports presenting
the candidate for review with the numeric limitation disclosed, not a claim that
all browser color checks passed. No calibrated display/human approval is implied.

Uninterrupted playback V1 reached683.766417seconds. It observed16393 rVFC callbacks,
83.8ms maximum callback gap and no disruptive events. Guard695.017459s, browser
687.319s; all cleanup/lease/source/runtime pins passed. However initial/final
VideoPlaybackQuality objects serialized as empty objects, leaving total/dropped
frame counters null. The run remains FAILED/INCOMPLETE; callbacks are not used to
invent the missing counter observations. V2 uses a separate recorder differing
only in two explicit scalar snapshots and is running under the same790s guard.
The WebIDL prototype-getter regression reproduces the old failure and passes the
fix. Eighty focused Python tests,10 JS classifier cases and that regression pass.

User was asked asynchronously to listen around35–65seconds, especially47.7;
no answer or human listening claim exists yet. Source/Studio user processes remain
untouched. Full output candidate was queued in Codex's file panel for review.

## 20:31 UTC — corrected full output passes objective QC; browser review remains

Candidate `native-presenter-v1/renders/full-native-high-v10-lossless-av-color.mp4`
SHA256 `eef61c5a2a410d869c79c13c6fb9ba69f52690377d0a99c3fbd53db3ffa50181`
passed all complete objective phases. Guard194.420299s; worker187.183792s;
stream-copy assembly1.434203s; preservation143.829307s; whole-output36.454335s.
All16394 native YUV frames identical (frame-receipt SHA256
`4f83e64da11cd618e0e33096d3cee583709a7a603d4f36a44de88fd4714f211e`).
All16394 coded video and32053 AAC packet payloads, rational PTS/DTS/durations,
side data and audio decoder configuration match selected source streams.
82 traced SPS/PPS fields differ only in transfer_characteristics1→13; MP4 nclx
independently reads primaries1/transfer13/matrix1/limited. No lossy generation.

Final AAC presentation is32820788samples, decoded32821248 with460padding;
−14.61LUFS/−1.86dBTP. Complete picture decode, exact CFR clock, channel/hum/AV,
waveform continuity and actual-declared three-frame color gates all passed.
Canonical sRGB PSNR at312/383/653 is42.751343/44.287096/42.107898dB. Root viewed
all three corrected images: natural presenter, readable text/graphics and intact
inset crop; this is not a continuous-motion or listening claim.

An independent review caught two proof weaknesses: missing observed hashes or
priming could compare equal, and receiptHash strings were not recomputed. New
separate code and16 passing offline tests close those gaps. Guarded supplement
`full-native-high-v10-authority-v1` passed18.886833s (worker11.910189s): every
packet hash actually observed, explicit1024AAC skip-sample priming, sealed float
and AAC receipt bodies recomputed, same-soundtrack PCM24 conversion chain pinned.
Candidate unchanged. Both guards verified owned cleanup/lease release and every
source/SDK/sandbox/dependency pin. Original V10 code/proof and failed V8 evidence
were not overwritten. Independent supplemental code/evidence review reports no
further concrete blocker. Perceptual/browser/revision and full-goal work remains.

## 20:21 UTC — transfer-only repair isolated; guarded assembly not yet launched

Canonical sourcePNG(cICP1/11/0/1) to nativeJPEG(sRGBICC) has MAE1.029807 and
near-zero channel shifts. The apparent raw darkening is not an exposure error.
Actual MP4 decoding at indices312/383/653 favors sRGB transfer with BT709 matrix:
MAE1.3932/0.7684/1.4267 and PSNR42.751/44.287/42.108dB versus native JPEGs.
BT709 declared transfer gives MAE8.7568/3.0716/8.2612; changing matrix to601 is
worse than retaining709. The proposed repair changes only H264 VUI transfer13
and matching MP4 nclx transfer, retaining primaries709/matrix709/TV range.

The original full MP4 and failed QC remain untouched. The new assembly copies
its coded picture plus the already-qualified same-soundtrack AAC, with explicit
mapping, movie_timescale48000 and video_track_timescale24000. No picture or audio
re-encoding, duration truncation, filters or timestamp resetting. All packet
payloads/rational PTS/DTS/durations/side data, decoded YUV, AAC configuration,
SPS-only transfer delta, MP4 nclx and complete output QC must pass. The three
new final color checkpoints must use ACTUAL declared metadata, not an override.

First attempt `full-native-high-v9-lossless-av-color` failed prelaunch admission
in6.752882s because compressor growth exceeded16MiB consecutive/whole-window.
No child launched; cleanup verified. Eight offline repair contract tests passed.
No final correction, human listening, continuous-review or delivery approval yet.

## 18:59 UTC — actual output QC catches audio failures; color interpretation open

Whole-output QC ran40.872623s guarded/32.236796s measurement. Exact16394zero-origin
CFR packets, complete strict video decode, channel balance/hum/AV timing, and
overlapping8kHz waveform continuity all passed. Native AAC failed two delivery
requirements:32820768presented samples versus32820788required (20short), and
−0.24dBTP versus the−1.5dBTPceiling, despite−14.67LUFS passing loudness. Cleanup,
lease and input pins passed. This original failed measurement is retained, not
relabelled a successful final export. Output SHA256 is
`73f883d2b03aa2129b605fe298147bf834e9e3b5d0de485f9dfc2b6e98d43a8c`.

The existing base's already-qualified AAC is a viable no-reencoding candidate:
it comes from the same headroom float soundtrack as native narration PCM, has
32820788presented samples and−14.61LUFS/−1.86dBTP. Any audio-only stream-copy
derivative must retain exact rational packet clocks/codec data and repeat whole
QC; no repair has yet executed. The native mixer uses192kAAC and its final mux
does not set movie_timescale; these are investigated causes, not proven complete
explanations. The proposed reusable path must not repeat the failing raw AAC.

Guarded83checkpoint extraction passed19.959151s (12.647896s extraction), then
four exact-source comparisons ran8.939981s. Root viewed all11contact sheets and
the first exact source pair; independent review passed the eight targeted layout/
ending frames. These are static layout checks only. Raw RGB differences at13,
300,495,650seconds showabout12levels darker output, PSNRabout26dB. However the
source PNG includes cICP010b0001 not exposed in PIL.info, the pre-encode JPEG has
an sRGB ICC profile, and final PNG has a different gamma tag. A color-managed
comparison is now required before identifying real displayed-color loss or
making any correction. Transport baseline/candidate equality cannot alone prove
source-to-final color fidelity. No final audio/color/continuous-review approval.

## 18:49 UTC — complete native render and owned cleanup pass; output QC running

`full-native-high-v8-url` finished at18:49:13.838547UTC with status
`rendered-awaiting-output-qc`. Guarded elapsed time1541.35745075s (25m41s), native
CLI pipeline1533.333s, full output870320056bytes. Native capture completed all
16394frames; URL transport registered/requested/completed all16394sources,
streamed40340940370original PNG bytes, reported zero errors/rejections/aborts/
base64 fallbacks, and closed with zero active streams/descriptors/map entries.

The221actual host samples peaked at2.21447849GiB owned footprint. Kernel pressure
was1(normal) throughout, maximum compressor1.5GiB, maximum observed swap equal
to first observed swap8.60974609GiB. Three bounded process-turnover resamples
were recorded; no missing live telemetry was replaced by zero. Native exit was
successful, no resource abort occurred, recorded process cleanup/no survivors,
independent heavy-lease release, source/SDK/sandbox/additional pins all passed.
This is full-duration resource/transport/render evidence, not final creative or
audio approval and not a claim that the whole editing request took25minutes.

The sole next media operation is the guarded whole-output audiovisual qualifier.
Actual frame-clock/decode, AAC presentation, loudness/channel/hum and overlapping
waveform continuity results are pending. Actual83checkpoint extraction and
source-frame comparison follow sequentially under the same resource policy.
The new wrapper's13gate tests plus existing focused admission/parity/memory/
progress/barrier tests passed together:60tests in0.032s. No human listening or
delivery approval is inferred from any of these tests.

## 18:39 UTC — full native render running under reviewed cache-aware admission

`full-native-high-v8-url` launched at18:23:39.131UTC and has passed9795/16394
frames. Recent measured owned process footprint remains about2.1GiB with normal
kernel pressure and no resource abort. This is running evidence, not a completed
render or delivery. All16394 retained source PNGs were reused in58ms. Native
high/JPEG95 capture, full1920×1080 canvas,24000/1001fps and one software worker
remain unchanged. The isolated URL transport is still not a general SDK release.

After review of the user's low-pressure observation, an explicit full-only
cache-aware admission was added. Literal unused RAM is advisory for this named
policy; three fresh readings must each show normal kernel pressure, at least50%
coarse headroom, at least8GiB file-backed pages, compressor at most10% of physical
RAM, stable swap/compressor and at least10GiB free disk. File-backed pages are not
added to overlapping memory categories or claimed guaranteed reclaimable. The
six-GiB owned-tree/five-GiB individual-process/one-GiB new-swap runtime limits and
independent deadline/cleanup remain enforced. Other launches retain their default
conservative admission. No user applications were closed or global cache purged.

V5 andV6 never launched a child because the original unused-RAM floor rejected
admission; V7 passed the new admission but failed strict native lint because
retained test-only HTML roots coexisted with the full root. V8 explicitly selects
`--composition index.html` while preserving strict mode and those prior artifacts.
All original failed receipts remain failed. No clock has been reset: the original
two-hour end-to-end target is already missed.

The next sequential operations are guarded complete-picture/audio measurements,
actual encoded checkpoint extraction, exact source-frame comparisons, then agent
visual review and separate perceptual/listening assessment. Their new entry gate
rechecks render source/dependency hashes and output size, carries expected hashes,
pins the existing local measurement import closure and verifies exact FFmpeg/
FFprobe resolution. Twelve pure gate tests passed; those are not media QC passes.

## 17:57 UTC — exact dense-opening parity and continuous memory canary pass

All55 selected baseline/candidate native JPEG95 files and their decoded RGB
pixels are exactly identical. The stock sparse reference took60.362954s,
candidate59.994337s and supervised comparison3.653518s. Each reference completed
four batches and eight bounded stable-measurement barriers. All receipts have
verified process/lease cleanup and stable source/dependency pins. Four exact
pairs were independently viewed (92,383,625,653), with five additional root
frame views (baseline200/501,candidate598/629/639). The visual evidence clearly
distinguishes this selection from55numeric matches and from human approval.

The uninterrupted `transport-candidate-4320-v1` completed4320frames/180.18s in
428.996674s including fresh source preparation. It kept the same full-resolution
source PNG, native high/JPEG95 screenshot capture and24000/1001fps, one software
worker, six-GiB tree/five-GiB process/one-GiB new-swap limits. No sparse batch
barriers or browser recycling were used in this run.

The fixed final windows[2321,3320] and[3321,4320] each contained13aligned active
capture observations, spanning919.0 and915.5frames (largest gap80). Medians were
2086.4853515625 and2084.4853515625MiB; increase−2.0MiB; fitted slope
−0.015597733747MiB/frame. The last active midpoint was4255, within the128frame
coverage requirement. Extraction and final browser-memory release were excluded.
Transport registered4320unique canonical sources and completed4320requests with
zero errors/aborts/fallbacks; source-stream/descriptor peaks1 and terminal0.
Native exit, owned process cleanup, independent lease release and pins passed.

The full export is NOT yet produced. The reviewed recovery command requires
these evidence hashes plus the explicit selected agent visual record before it
can launch. A fresh post-canary check measured2586836992unused bytes (~2.4GiB),
normal kernel pressure, low compressor and87% coarse memory-pressure headroom,
but the unchanged launch reserve requires6GiBunused. Full launch is therefore
deferred; no global purge, user-app closure or admission relaxation was performed.
Durable guarded re-export packaging continues separately. This successful
experiment does not reset the already-missed two-hour end-to-end clock.

Evidence under `/private/tmp/sniper-native-frame-transport-20260909.wsUupP/`:
`native-reference-paired-v1.parity.json` + supervisor receipt,
`native-reference-visual-review-v1.json`,
`transport-candidate-4320-v1.memory-classification.json` + original render/log/
resources. The unchanged installed SDK remains0.8.31; only the pinned isolated
candidate adds native frame URL transport and strict decode-failure propagation.

### Failed sparse reference attempts retained

`transport-baseline-reference-parent-v1` failed after11.451283s in fast browser
turnover; its monitor correctly refused missing memory telemetry. After a
ps/top/ps reconciliation correction, `native-reference-baseline-v2` failed after
12.977903s on newly appearing identities and a terminal measurement race; cleanup
was initially unproved because of EPERM. Nonce-bound recovery independently
verified its supervisor and22recorded child identities absent and archived proof
at `heavy.recovery-81d8e97503c64012ac619ec0594fed74.json`. Original failure status
was never changed. The reference-only stable-phase handshake, exact sampler
identity retention, second-read exit handling and atomic handshake publication
now have focused regression coverage. Successful references are separate new
attempts, not relabelled partial outputs.

## Historical 17:09 UTC — stock opening baseline hit guard; tiny transport parity proven

The stock data-URI 800-frame baseline safely aborted at648/800 after109.900918s,
on the unchanged experimental6GiB owned cap (observed6.157GiB). Kernel pressure
stayed normal; recorded cleanup and heavy-lease release were verified. This is
not a candidate-transport failure and not dense-output qualification. No cap is
being relaxed and no identical stock retry is planned. An existing-native-API
snapshot baseline in small fresh batches is being investigated for the fixed55
indices, preserving actual rendering functions and high capture quality. The
parallel audio task has been granted the sole bounded0–65s playback slot while
that read-only API investigation proceeds; no render will overlap it.

### Historical 17:07 UTC — tiny tests complete, opening baseline started

The isolated copy in `/private/tmp/sniper-native-frame-transport-20260909.wsUupP`
wires the SDK's existing frameSrcResolver to its existing localhost server.
Installed SDK/full native index, timeline and media are unchanged. Source PNGs
are streamed byte-for-byte under capability URLs with no-store; the copied SDK
additionally propagates image decode failure instead of accepting a missing frame.
The module admits only native materialization-directory aliases and pinned
canonical extraction roots. This is an immutable-cache experiment, not a claim
of general atomic adversarial-filesystem protection.

Three actual native 48-frame fault canaries passed: missing image 4.910289s,
corrupt image 4.929232s, interrupted response 4.940906s. Each reached the intended
HTTP fault and produced EncodingError in capture_streaming at zero completed
frames, without publishing output. Process and heavy-lease cleanup were verified.
Two earlier compatibility attempts (5.537920s, 4.930723s) safely rejected the
native compiled-directory link before fault injection; those are not fault-test
passes. A bounded root also bounds native extraction, so these trials created
then reused a 48-frame cache; do not call them full-cache hits. Its first source
PNG is byte-identical to the corresponding retained full-cache PNG.

The unchanged 48-frame baseline completed in 12.696049s; the accepted candidate
retry completed in 10.649262s (native pipeline 7.455s). Guarded FFmpeg QC took
3.636626s and 3.550965s and proved exact decoded RGB equality for every index0–47.
No perceptual tolerance was needed. URL telemetry:48 distinct source-frame
registrations,48 HTTP completions,0errors,peak1stream/1source descriptor, both
zero after close. This covers only two seconds, not the dense opening/full video
or a memory plateau. It does not establish an overall speedup.

The first candidate native export finished, but its supervisor withheld approval
after a ps/top exit race and cleanup EPERM. That original receipt remains failed
(9.690642s). All8 recorded identities and supervisor were subsequently verified
absent; explicit nonce-bound recovery under the existing mutex archived proof
before clearing the heavy fence. Reviewed fixes narrowly resample the exact
missing-footprint race once, retain newly discovered identities, and never ignore
unrelated live/terminal telemetry errors or denied control over a live owned group.
Seven exit-race regressions,12 launcher cases,4 wiring cases,22 transport/injector
fixtures,1 actual native-Hono route test and3 progress-parser cases have passed.
These overlapping focused suites are not a new full-system qualification claim.

The 800-frame unchanged opening baseline has started. The protocol fixes55 exact
comparison indices and later requires4,320 distinct source frames, beyond the
prior ~3,500-frame problem region. Resource samples are bracketed by observed
native frame progress, not inferred fps. Experimental stops are stricter:
6GiB total owned,5GiB individual,1GiB new swap,normal kernel pressure,10GiB disk.
No full retry until reviewed dense-frame parity and bounded memory criteria pass.
The shared lease/preview-lifecycle task separately cleaned14 obsolete preview
servers and verified their recorded descendants absent while preserving the
current preview. Audio/continuous playback, full export/QC and end-to-end timing
remain open; the original two-hour target is still missed.

## Historical 16:25 UTC — V4 failed; no full render running or qualified

V4 ended at 16:15:47.770 UTC after 738.891335s, exit 1, at roughly
3,949 of 16,394 frames. The native renderer reported a 60s no-progress stall.
Its message names drawElement, but the recorded capture mode is screenshot.
Owned footprint peaked at 15.324 GiB (largest renderer ~14 GiB); reducing the
compositor allowance did not prevent growth. Kernel pressure remained normal,
and the resource supervisor did not trigger (`abortReason: null`). This does
not invalidate Aaron's report that the Mac felt strained. Cleanup verified all
recorded identities absent; no final output exists.

The matching macOS crash report identifies renderer PID 69003, parent 68995,
launch 11:03:47.5118 -0500 and crash 11:14:47.0964 -0500 (16:14:47 UTC),
EXC_BREAKPOINT / SIGTRAP on CrRendererMain, before the native stall timeout.
Stripped symbols do not establish the underlying allocation/decoder cause.
Both proposed read-only heap-counter attempts obtained zero samples: the first
failed process verification inside the sandbox, and the second found the browser
already exited. No heap diagnosis can be inferred from either attempt.

Do not start another full retry. An isolated opt-in candidate is under review to
wire the SDK's existing frameSrcResolver to its existing localhost file server,
avoiding multi-megabyte data-URI transport without changing source PNG bytes.
The stock image injection path swallows decode errors; a candidate must propagate
HTTP/decode failures and prove that behavior with failure injection. Approval
requires bounded actual-pixel parity and footprint testing, plus the shared
heavy-work lease being implemented separately. Neither candidate performance nor
memory boundedness has been established. Installed SDK and native edit remain
unchanged. V1–V4 render attempts total 2672.120s (44m32.120s), not total edit time;
the original two-hour end-to-end target remains missed and is not reset.

## Historical 16:05 UTC — V4 browser-budget trial running; V3 safe stop retained

V3 stopped automatically after 201.879638s at 15:50:48 UTC, around 1,117 frames.
Only the literal-unused RAM floor tripped: 5.791 GiB unused, 6.968 GiB owned,
~2.23 GiB compressor, 83–84% `memory_pressure` free and slightly declining swap.
This was not a second out-of-memory incident or proof of a monotonic leak.
Tracked Chrome/native groups and a reparented FFmpeg process were signalled and
verified absent. Source/SDK/sandbox hashes stayed unchanged. The retained partial
MP4 lacks its moov atom, so no V3 encoded-pixel quality claim is possible.

`full-native-high-v4-browser-budget` started at 16:03:28.879 UTC. The cache-aware
guard now also reads the kernel's actual pressure mask (1 normal, 2 warning,
4 critical, independently verified against Apple XNU). Launch still requires
6 GiB unused RAM. Runtime low-unused RAM alone is recorded as a warning when
pressure and the other limits remain healthy. Kernel warning/critical/unknown,
measurement failure and unchanged owned/swap/compressor/disk limits still abort.
Do not estimate available RAM by adding overlapping cache counters.

The same stock renderer and cached Chrome are used through the explicit SDK
browser-path setting. An exec-only adapter replaces exactly the SDK's single
16384 MiB compositor-resource argument with 1024 MiB. All other browser arguments,
PID/PGID, cwd, environment, stdio and inherited debugging descriptors are retained.
No V8 heap cap was added. This is a cache allowance, not a total-browser RAM cap.
Actual launch evidence records exactly `--force-gpu-mem-available-mb=1024`, Chrome
SHA256 `3985a87c5905cf9ecd25d49638822cf071a517f5d976ef8c5e8fe2c6d5496cae` and
adapter SHA256 `6705cbc3d9580245b72c3830c8e3e47fd7195d04df993f3867544461a90b6447`.
The SDK's pre-adapter log can still show 16384; the separate effective-argv record
is authoritative for the actual browser launch. Native source hashes match V3.

Root's final adapter/launcher/resource-wiring union passed 28 tests in 0.080s;
20 cache-aware sampler cases passed in 0.003s. Together with the unchanged
11 real/mock ownership cases, 59 distinct focused safety cases have passed.
The adapter review found and fixed FIFO-log blocking before fstat (O_NONBLOCK).
No actual full output, quality parity, speedup or bounded full-run memory has yet
been established. The original two-hour end-to-end target remains missed.

## Historical 15:48 UTC — tested supervisor; single-worker trial started

`full-native-high-v3-bounded` began at 15:47:26.123 UTC. It reuses all 16,394
PNG source frames and the exact same native composition hashes as failed V2.
Stock SDK 0.8.31 remains SHA256
`95be44729e244283cb685833a20b94e00c96aaafba7848b9182db01771477c78`.
Native flags preserve high quality, 1920×1080, 24000/1001fps, PNG source and
strict/no-best-effort readiness. The candidate uses one worker, native low-memory
mode and software screenshot capture; Node data-URI cache limits are 32 entries
and 64 MiB. This does not prove bounded browser memory or visual equivalence.

The new host-side supervisor leaves the native child inside the same
localhost-only sandbox with no inherited billing credentials. It records actual
macOS footprint including compressed memory, host unused RAM, swap growth and
disk headroom. Run policy: 16 GiB total owned footprint, 15 GiB individual,
at least 6 GiB unused physical RAM, no more than 4 GiB swap growth, 10 GiB disk
headroom and a 5400s render-only deadline. Identity discovery runs between
resource samples; remembered detached browser groups remain owned after their
parent exits. Telemetry failure aborts. Cleanup is checked on success and failure.
Polling cannot prove an unobserved detached child absent; supervisor SIGKILL
protection is explicitly not claimed. No other applications are automatically
closed. Aaron's earlier manual application closure remains part of the incident.

Independent adversarial review found and fixed four exercised lifecycle defects:
constructor discovery omitted existing descendants, malformed process rows were
silently skipped, failed cleanup observation did not stop the direct child, and
an exclusive receipt-creation race could overwrite another receipt. Root's final
union passed 20 process/launcher cases in 10.842s, including real macOS idle
detached children requiring SIGKILL and survival of an unrelated process. Fifteen
read-only sampler/policy regressions passed in 0.002s. These harmless fixtures
qualify exercised safety paths, not the video, SDK memory behavior or timing.

The failed V2 partial picture is 15,336 frames / 639.639s / 778,397,439 bytes,
without final programme audio. A decoded 410s PNG confirms the localized crop
repair in encoded pixels; the partial file is not a complete delivery.

## 15:30 UTC — full streaming render stopped after host memory exhaustion

`full-native-high-v2-stream` failed with exit 130 at 15:23:35.692 UTC after
1493.032 seconds, following the user's macOS out-of-application-memory report.
Last progress was approximately 15,330 of 16,394 frames. Root interrupted only
the verified owned render tree, then verified that its CLI, FFmpeg, four browser
roots and four heavy renderer children had exited. The partial working MP4,
all source PNGs, failed logs and original media remain; none is a final delivery.
The receipt confirms that all tracked native composition source hashes remained
unchanged. This is an execution/resource failure, not a timing success.

At 15:22 UTC `top` reported roughly 14 GiB physical footprint and compressed
memory for EACH of the four renderers (~56 GiB total). The host had 63 GiB used,
31 GiB in its compressor, 132 MiB unused, and ~65,004 MiB used swap. Small RSS
values had concealed the compressed footprint. At 15:29, after cancellation,
the host measured 40 GiB used, 23 GiB unused and ~2.6 GiB compressor; swap
usage had fallen to ~17,385 MiB. Aaron subsequently clarified that he manually
closed Chrome and other applications too. The recovery is confounded: do not
attribute that entire host-memory reduction to automatic render cleanup alone.
Future monitoring must not use RSS as a proxy
for true process footprint. The failure is attributable to the owned workers,
not dismissed as other applications or normal output-file storage.

The stock streaming path avoided the raw-RGBA disk batch but did not bound
browser memory. A single-worker native low-memory candidate and fail-closed
host-side footprint/swap watchdog are under investigation; no retry has started
at this checkpoint. Resolution, rational frame rate, high output quality, exact
audio and strict media readiness remain required. Final output QC and continuous
preview/audio qualification are still open. The two-hour end-to-end target is
still missed and is not reset at any retry.

## Historical 15:00 UTC — full timeline integrated; streaming export started

The complete 683.7664166666667s native timeline was integrated at 14:41:58 UTC.
All 21 tail snapshot checkpoints were independently reviewed at full resolution.
Two findings were repaired: a 100-source-pixel leftward crop shift only for the
404.4482–418.65 diagnosis scene, and a 679.5–679.9 presenter fade before the source
stand-up. The existing end-screen region centers by 680.0; all goodbye speech is
retained. Both reviewers inspected the eight repaired PNGs and found those static
issues resolved. `native-presenter-qc-xAJBhw` passed all 24 native tail forward,
reverse, numeric, visibility and ending checks in 24.020s. Native lint: zero
errors/warnings. This does not qualify continuous playback or human listening.

Full high-quality V1 render began 14:52:15.802 UTC and failed after 238.317s at
the stock disk-capture admission. Source preparation completed all 16,394 PNGs in
218.171s; audio processing took 18.029s. The SDK conservatively budgets full RGBA
capture storage (~136GB), exceeding the remaining ~35GB. Root's earlier 55GiB
preflight covered source extraction but missed this second SDK storage gate.
No output was promoted and no user files were deleted. Failed receipt and cache
are retained. Raising only the streaming duration would not enable four-worker
streaming: the actual stock router also requires its parallel-stream opt-in.

`full-native-high-v2-stream` is running with the same source PNGs, 1920×1080,
24000/1001fps, high quality and four workers. Installed SDK bytes are unchanged.
Inspected supported settings: streaming duration ceiling 900s,
`HF_CAPTURE_PARALLEL_STREAM=true`, experimental fast capture disabled, streaming
timeout 3600000ms, retained extraction cache budget 65536MiB. `--no-best-effort`
rejects missing/unready media. The renderer reports four-worker streamed frames;
no completed export or timing success is claimed yet.

The user's audio-consistency report remains open. PCM35–65s and all nine cut
joins match the retained float master within one 24-bit LSB, with identical
channels and no clipping. An earlier native-WAV Studio test logged 154 seeking
and 154 waiting events over ~32s (mean seek interval 208.31ms); sparse samples
missed the brief seeking states. This is concrete preview continuity evidence,
not proof of the user's exact perceived cause. Full exported audio will be
checked separately, including overlapping waveform comparison to retained PCM.

The two-hour end-to-end target remains missed, including failed attempts and
creative rework; the native pivot and streaming retry do not restart that clock.

##14:40UTC progress — same whole-video deliverable

At14:29:36UTC the existing native project was extended to367.492125seconds.
Twenty-five actual native snapshots across78.5–362.8s passed root contact-sheet
review; root additionally inspected full244.8/267.6/316.7/362.8frames. Independent
review inspected all25 full PNGs and found no blocking static geometry/content
issue. This is not human listening or continuous playback approval.

`native-presenter-qc-r1k71L/result.json`: thirteen32–75s forward/reverse/repeat
checks PASS10.492s. Earlier2.443s attempt failed its seek-clock assertion and
remains retained in `native-presenter-qc-aUaoNZ`; the rerun explicitly records
initial native/root/timeline duration and decoded media readiness.
`native-presenter-qc-7aBIxo/result.json`:24body checkpoints PASS20.599s through
367.45, including future sentence slots, quote lines, hub nodes, cost rows,
X/Y fold and repeated resource reveal. No skipped media/visibility assertion.

Source-word QA then corrected the opening limitation/better emphasis. Original
BETTER started22.12 and retired23.65; the actual word is24.9183–25.6883. It now
lands24.9183 after a24.70entrance, with camera/name transition after25.57. ONLY
now begins20.8583. The same accepted visual design, exact narration and frozen
cuts remain. Six actual native repair frames are in `native-opening-cue-repair-v3`;
root inspected their contact sheet. The receipt's unnecessary internal caveat
was removed; no prices were added. The condensed pain example remains a summary,
not a verbatim transcript. Original source SHA is06c50ce8c2e9da0a954f9301b1cba0dbfeb62ecebcdd956a034eb1597a301e14,
confirmed against the existing admitted asset_manifest.json; do not confuse a
summary's other digest with this source hash.

Final367.4882–683.766417s is independently being authored. Root owns integration,
native full render and output QC. Native continuous playback is still unresolved.
Full-render wrapper records timestamps, trace, output and before/after source
hashes, requires the full duration/final section and55GiB free disk. Measured
769-source-frame PNG cache averages2.318MiB/frame, projecting37.10GiB for the
whole16394-frame source. The installed high-quality MP4 path captures JPEG95;
do not claim lossless final capture just because source extraction is PNG.
Drive free space measured~71GiB. Planned output keeps high quality, rational
24000/1001fps and4native workers; no render has started at this checkpoint.

Not a completed video, delivery approval, listening attestation or timing success.
Workspace: `/private/tmp/sniper-c0679-produced-review-20260909.FCYcRv` (FCY below).
Project: `native-presenter-v1`; existing native Studio is on port41058.
Installed stock SDK/CLI0.8.31 is unchanged. No paid API calls, model generation,
downloads, billing fallback, source recut or original-footage mutation was used.

## Direction and actual edits

Aaron accepted the new native presenter-first visual direction. His scoped
revision asks for inset, rounded rectangular video with space on all four sides;
circle, copy and timing remain preserved. Shared rectangle poses scale the
original720×1080 source crop uniformly to633.6×950.4, leaving43.2px horizontal
and64.8px vertical padding in each720px side region. Radius is26.4px in output.
The same live presenter moves between full view, rounded side panels and circle.
Catalog camera, lower-third and count-up mechanisms are actually source-inspected
and adapted; provenance is in the project BRIEF.md and extension notes.

Native32–75s authored content includes video-first-brands annotation, Drop-in
descriptor panel, workbook-to-brand/client diagram, prompting rehook, spoken
prompt construction and the first narrated example. Timeline now75.408667s;
its pictures/seek behavior still require QC. Independent75–194s authoring is
underway. The remaining body is not silently represented as a completed edit.

## Actual exports and detected regressions

|Artifact|Length|Pipeline time|Result|
|---|---:|---:|---|
|`renders/native-opening-high-v1.mp4`|32.041667s|135.557s|Decode passes; wrong fallback fonts in actual output, old edge-to-edge geometry. Retained.|
|`renders/native-opening-high-v2.mp4`|32.041667s|98.082s|Correct embedded Oswald/Space Mono and rounded insets in inspected10s output frame. Full decode passes.|

V2 is44,929,480bytes,1920×1080H.26424fps,48kHz stereo AAC. Audio and video start0;
end-duration difference0.667ms. Encoded audio measures−14.46LUFS,−2.02dBTP,LRA2.90;
strict target−14±1LUFS/peak≤−1.5dBTP passes. This is measurement, not listening.
V2 capture72.036s, encode23.613s, assembly.988s. Source PNG cache hit took.005s
versus V1 miss12.584s. V1 playback probe and V2 inspect overlapped their renders;
these are observed pipeline times, not isolated whole-workflow benchmarks.

The compiler did not consistently discover fonts declared only in external CSS.
Explicit small font declarations in the document head caused actual deterministic
two-family embedding in V2. Installed renderer/runtime was not patched.
Future-child opacity was also corrected after native18s paint showed words too
early. Static lint/inspect alone had not detected these visual problems.

The32–75s extension's original tl.set text rows failed actual-GSAP reverse seeks:
75→59 retained future words. Adding a blank baseline did not fix it. Each row now
records previous/next text in zero-duration fromTo with immediateRender:false.
Agent's nine text-state checks pass; native paint/seek test remains required.

## Preview failures retained

All thresholds remain150ms; no custom patched SDK was promoted into this project.

|Probe directory in FCY|Surface/input|max A/V drift|max audio/clock|Status|
|---|---|---:|---:|---|
|`native-presenter-qc-CRFlxk`|Studio, MP4 audio element|2.782537s|2.304s|Fail; overlaps V1 render.|
|`native-presenter-qc-0MwR7h`|Studio, separate PCM WAV|.236184s|.278101s|Fail.|
|`native-presenter-qc-oJWsZX`|Stock lightweight player, separate WAV|.994527s|.018664s|Fail; full-media preparation overlaps startup.|

Lightweight49.395s probe has130 active samples;10 dropped frames reported after
many seeks, with cumulative counters (not a clean playback-only denominator).
The earlier old V5 full-program probe in `native-full-program-v5-mastered` also
failed:187.022s wall, default180s Puppeteer protocol timeout. Its120s sample
already has~1.522s video/audio drift. It is not a successful full-length run.
Generic MotionPathPlugin network errors reflect blocked remote requests in the
localhost-only sandbox; no missing plugin was downloaded to hide those errors.

## Reuse, quality and timing

Full media preparation began2026-09-09T14:16:30.400Z and took7.172s including
streaming source/output hashes. `native-full-media-preparation.json` records all
commands, paths and hashes. Picture clone is byte-identical to the qualified
headroom base (SHA374fcd0e…72ebe2), with no picture reencode. Browser24-bit PCM
comes directly from retained headroom float PCM (SHA790f38dd…0a606), not from
decoding an AAC generation. No new lossy audio generation is added at this stage.
Final native AAC still needs fresh output measurement. Old32s media is retained.

The full two-hour delivery target has already been missed. Keep original failed,
rejected and rework time; do not restart the clock at the native visual pivot.
Current production-turn09:05:08UTC is a separate known clock, not proof of the
original request/admission start. Short render timings do not prove whole-video
quality, a two-hour end-to-end result, or general autonomous completion.
