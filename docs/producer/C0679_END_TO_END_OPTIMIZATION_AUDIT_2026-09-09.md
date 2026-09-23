# C0679 end-to-end editing optimization audit — September 9, 2026

## Finding and scope

The current workflow has not demonstrated a complete, quality-approved edit in
120 minutes. Attempt B is substantially closer: objective file checks finished
at **1h49m07.549s**, its first complete playback at **2h00m40.653s**, and its
immutable evidence package at **2h08m57.536s**. The first playback reported four
dropped frames; a later repeat of the identical output reported zero. The repeat
does not replace the first failure or reset the clock. Actual listening, full
creative approval and a qualified editable-project handoff remain open.

The subsequent complete creative revision is now saved and visibly open in
Chrome at the beginning. Its verified request-to-ready time was
**3h08m19.598s**, including full export, QC, whole playback, corrections, archive
and visible handoff. The complete 10m57s output passed zero-drop playback, but
four uncompressed-reference sample comparisons remain failed and audible
listening/user creative approval are still unverified. This is a review-ready
delivery with explicit quality limitations, not proof of the two-hour goal.

B began at **21:26:48.341117 UTC** on September 9 from the original raw footage.
Its [sealed manifest](../../artifacts/c0679-fresh-native-b-2026-09-09/MANIFEST.json)
records 400 files, 2,469,972,749 bytes, status
`file-qc-passed-playback-failed`, and `goalComplete: false`. This is a fresh-input
trial with prior operator exposure and generic software reuse, not a blind
experiment. Source-specific A media, caches and creative artifacts were excluded
under the [fresh-trial protocol](C0679_FRESH_EDIT_TRIAL_2026-09-09.md).

The [external B audit receipt](evidence/c0679-fresh-b-2026-09-09/audit.json)
preserves six selected sealed metadata files and the two post-seal repeat
receipts. Their bytes were checked; sealed entries were compared against the
original manifest. This audit did not rehash all media or rerun playback. Both
archives remain untouched.

A subsequent [creative requirements review](C0679_B_CREATIVE_REQUIREMENTS_REVIEW_2026-09-09.md)
verified the scene sources and inspected two existing stills. It confirms padded
presenter and bubble layouts, but finds no left-presenter pose, repeated sheet
anatomy, and quantity beats presented as ordinary text. Named catalog-first
selection is not established by the archived generator. Those findings concern
the sealed B version. A subsequent working revision now has a complete 53-scene
creative allocation, catalog provenance, varied presenter/graphic layouts and
staged quantity treatments. All 37 body scenes have at least one actual native
frame manually reviewed; production separately reviewed the opening 16. The
[source handoff and review record](C0679_B_MIDDLE_TAIL_SOURCE_HANDOFF_2026-09-09.md)
preserves the source batches, cue repairs, native findings and corrections.
The revised full picture subsequently completed a higher-quality CRF 6 export,
passed full-file timing/decode/measured audio and all 23 JPEG-relative checks,
completed whole playback with zero drops, and reached the verified Chrome
handoff recorded above. Four PNG-relative comparisons remain failed. The older
wrapper and CRF 15 failures remain historical evidence; their results must not
be substituted for checks of the delivered CRF 6 bytes.

Attempt A also missed the target. Its complete 683.766417-second
HyperFrames composition and corrected MP4 are saved in an immutable package.
The final file passed whole-output objective checks, supplemental source/audio
verification and complete browser playback with zero reported dropped frames.
The native full render used a peak owned footprint of **2.214478 GiB**, with
normal observed memory pressure and no observed additional swap throughout.

Delivery still has explicit limits: the current Studio playback observation
failed with 668 real audio seek/wait pairs and a startup dependency rejection;
smooth Studio audio has not passed. A strict browser color comparison also
remains numerically failed despite controlled comparison and limited still
review finding no material visible loss. Human listening and user creative
approval are not established. The packaged re-export command was inspected but
has not been executed from the saved package. These distinctions are recorded
in the [final external handoff](evidence/c0679-optimization-2026-09-09/attempt-a-final-handoff.json).
Authored coverage is not a meaningful percentage of final delivery completion.

The largest demonstrated opportunities are preventing rejected creative work
from expanding, admitting the actual render resource requirements before work
starts, and containing aggregate browser memory. Faster encoding alone cannot
repair those problems. Attempt A's first two full failed renders consumed **1,731.349 seconds
(28m51.349s)**; this is observed failed-attempt time, not a guaranteed recoverable
saving. It includes useful source extraction subsequently reused.
The first four full attempts totaled **2,672.120 seconds (44m32.120s)**; none of
those four produced a qualified full native export. The eighth attempt later
completed the full native picture, followed by a corrected final assembly and
separate output checks. Render-attempt totals exclude authoring and intervening
debugging and must not be presented as total editing time. All failures remain
in the historical ledger and evidence collection.

This audit covers source/cuts, creative direction, catalog selection, authoring,
agent coordination, incremental preview, audio, resource admission, rendering,
review, packaging and the full-edit benchmark. It uses current C0679 receipts,
installed SDK 0.8.31 source, local orchestration code, and the independent
editorial/launcher review. The initial audit was read-only; later validation added
guarded native rendering, complete exported-video checks and separate Studio
observations. Historical
Sniper/Palmier measurements are identified as such; they do not qualify this
native route. The original request-start timestamp is not reliably established.

## Attempt B: current measured result

| Area | Established result | Remaining requirement |
|---|---|---|
| Complete exported picture | 15,761 frames at 24000/1001 fps; 657.365042 seconds, about 10m57s | Encoded coverage alone does not establish creative quality |
| Objective file checks | Whole decode and exact picture/audio clocks passed; local audio continuity passed; all three sampled native color comparisons met the unchanged 40 dB threshold | Actual listening and full creative review remain unverified |
| First playback | Reached the end at elapsed 120m40.653s; four dropped frames, zero corrupted frames | Retained as a failed zero-drop check |
| Separate repeat | Same output SHA and 75 common input pins; all 15,761 frames presented, zero drops/corruption; elapsed about 140m56.6s | Does not establish reliable playback or explain the first failure; headless muted output is not audible listening |
| Full render resources | 204 samples; peak owned footprint 2.135163 GiB, largest process 0.959961 GiB, normal kernel pressure, zero observed swap growth | 184 samples retained low-unused-RAM warnings; minimum unused RAM was 79 MiB. This is workload-specific evidence, not a host-wide guarantee |
| Delivery package | 400-file immutable archive; first failures and original timing retained | Project asset closure, portable SDK runtime and complete dependency pinning remain unverified |
| Editable Studio handoff | Production is testing a separate working copy for native edit/save/reload and export | Opening Studio or exporting a child alone does not prove complete project revision/re-export or smooth Studio audio |

The native render's guarded phase took **23m50.103s** and ended at elapsed
**104m07.727s**. The corrected delivery check took **45.748s**; its receipt
records unchanged picture slices, 30,815 AAC packets preserved from the corrected
donor, and no additional picture/audio encodes during assembly. This demonstrates
why an audio/container repair need not trigger another full picture render.

The 23 guarded phase durations total **54m24.464s**. The remaining
**74m33.072s** before the archive seal includes authoring, development, review,
tool calls and orchestration. It is not an idle-time measurement and cannot all
be claimed as recoverable savings. Failed source checks, measurement races,
input drift, output QC and playback remain in the original ledger. Later
cleanup evidence does not rewrite the earlier failed cleanup records.

For time efficiency, collect independent failures in one review pass, fix related
causes together, and rerun the affected stages before a final whole-output check.
Fix a blocking prerequisite first when it prevents useful inspection. Keep a
failure record with its first occurrence, repair, verification and elapsed time.

### Post-seal creative revision: current evidence

These phases continue B's original clock. They are not a new fresh edit or
quality-complete results within two hours.

| Phase | Measured result | Scope and retained limitation |
|---|---|---|
| Native Studio creative v1 | 206.326s; failed bridge-clock assertion before playback | Preview uses 30 fps, export uses 24000/1001. Studio also added native IDs to root HTML; first pin mismatch remains recorded. |
| Native Studio creative v2 | 289.433s; source pins and cleanup passed | 229 scene checkpoints, 188 transition states, 13 absolute points; 78s playback, 1,561 samples, zero dropped/corrupt frames, maximum A/V difference 7.243ms. Not whole-video playback or listening. |
| Final native references v2 | 11.585s; source pins passed | 23 JPEG references at 1920×1080; independent assigned checks confirmed panel 33 spacing, presenter-free panel 24, export-grid bridge and closing. Not a decoded MP4 comparison. |
| Final scoped Studio v3 | 35.312s; checks, source pins and cleanup passed | Targets final 33/52 changes, closing playback and reverse seeking; does not replace whole-video review. |
| Revised full export v1 | 14.414s; strict asset-path lint failed before encoding | Absolute presenter reference exists on disk but is rejected as a local project asset in the staged render project. Source pins and owned cleanup passed. No revised full MP4 resulted. |
| Revised full export v2 | 1,364.325s guarded wall time; all 15,761 frames assembled, native CLI exited zero | The wrapper subsequently failed because its stdout-only trace parser missed cache evidence emitted on stderr. Saved log contains the expected compile hash, cache hit, full capture and artifact validation. The failed wrapper receipt remains unchanged; independent recovery and final QC are still required. |

The failed export ended at **02:08:05.779919 UTC on September 10**, elapsed
**4h41m17.439s** from B's original start. This is an observed interim checkpoint,
not final delivery time. Its exact guard and log remain
`creative-native-export-v1.render.json` and `.render.log` in the working trial
directory. The failure was not an out-of-memory event. Production owns the
cache-preserving asset-reference repair, retry and final delivery checks.

The second attempt ended at **02:34:57.000972 UTC**, elapsed
**5h08m08.660s** from B's original start. It used one worker and the retained
source-frame cache. Across **194 resource samples**, peak owned footprint was
**2.165315 GiB**, kernel pressure stayed at level 1, and observed swap growth
was zero (7,585,797,242 bytes initially; 7,569,020,026 finally). All 194 low-unused-
RAM warnings remain recorded. Source, additional inputs, SDK and sandbox pins
were stable; tracked cleanup and lease release passed. This supports bounded
memory use for the actual full render, not a guarantee about unrelated apps.

An efficient repair here validates the completed artifact and existing trace
without re-rendering unchanged pictures. An orchestration failure does not by
itself prove a native render failure. Conversely, a successful native exit does
not replace file QC, playback or listening. Keep the original failure and bind
any recovery receipt to its exact log, guard, inputs and output.

The earliest specifically evidenced whole-program revision assignment in this
audit task was **00:42:35.395 UTC on September 10**; the enclosing task turn
started at 00:40:26, and production may have begun planning earlier. The selected
raw task records and allocation identity are retained in
`revision-work/creative-revision-start-evidence.json` under the working B root
(SHA-256 `0a803d96aa901ee570dca62817489c9b2ac437c12ca5fbc05f145e95f561e41a`).
This is a supplementary creative-phase boundary, never a reset of B's clock.
The user cancelled the proposed additional fresh trial and explicitly retained
both A and B source-frame caches. Finish and time this revision; do not launch a
replacement benchmark or delete those caches.

Production subsequently identified the earlier actual user request boundary:
**00:39:13.266 UTC** on September 10, making the creative-revision deadline
**02:39:13.266 UTC**. This reviewer independently read the exact user message
`msg_01a088c1-2072-7e33-821a-7aa8db56f0a0` at line 10994 of the coordinating
task's local session. Its timestamp and request for whole-program visual variety
match that boundary. The immutable selected record is
`revision-work/creative-user-request-start-independent-evidence.json`
(SHA-256 `032d19f3dfe542413a62250d5260835bf483b7964cd9aaf4f8f53a255aa10b38`).
The 00:42:35 audit-task assignment above is later supporting evidence, not the
start of the creative revision. A monotonic timestamp for this retrospective
user-request boundary is unavailable and must not be invented.

Native-export reconciliation v2 passed in **14.459s** and admitted the exact
762,981,039-byte native output, SHA-256
`d6a2052ec3727897987649a392befa372c2d52e733cb0e5feaa761fe313058ac`,
without another render or modification. The earlier reconciliation admission
refusal remains recorded. Delivery QC v1 then stopped in **13.979s** after four
unstable process samples involving four distinct newly observed descendants.
It had finished donor qualification, stream-preserving assembly and video timing;
its overall receipt remains incomplete. That observation does not establish an
out-of-memory event.

QC v2 consolidated stream metadata and all packets into one real `ffprobe`
invocation, partitioned by actual stream index for unchanged clock checks.
It retained only completed, byte-bound donor and assembly checks from v1; all
packet clocks, full decode, motion screening and audio measurements ran again.
No sampler rule, memory cap or retry allowance changed. In **50.976s**, these
checks passed for 15,761 frames and 31,553,522 audio samples. Audio measured
**−16.16 LUFS, −1.09 dBTP, 34.296585 dB SNR**, with zero failed local windows.

The overall QC v2 result remains failed: frame 1395's presenter bubble measured
**39.727166 dB PSNR** against the unchanged 40 dB threshold, with MAE 1.864965.
All 23 whole-frame comparisons and the other 22 sampled rows passed. Separate
inspection of that native JPEG reference and decoded PNG showed no obvious
framing, missing-content or face-detail defect; it does not override the numeric
failure. Reference compression is a candidate contributor requiring a controlled
check, not an established cause. Five additional decoded checkpoints confirmed
the presenter-free scene, repaired oval label, complete bridge graphic, fade-out
checkpoint and final end-screen layout. These selected stills do not replace
whole-program playback or listening.

The controlled lossless-reference check did not clear the failure. Native PNG
v5 captured all 23 unchanged points in **15.496s**; the prior v4 launch failed
with zero captures in **12.479s** because its phase omitted the qualified frame-
transport environment. That configuration failure is retained. Comparing the
same delivered bytes to PNG in **9.177s** yielded **14/23 passing rows** and
**19/23 passing whole frames**. At frame 1395, export-versus-PNG presenter PSNR
was **37.339105 dB**, MAE **2.323621**; JPEG-versus-PNG alone measured
**39.549236 dB**, MAE **1.739850**. JPEG reference compression contributes error,
but cannot by itself explain or dismiss the export's lossless-source failure.

The installed full-render capture block explicitly chooses JPEG95 for a high-
quality non-alpha MP4. It does not consult the generic `cfg.format/jpegQuality`
fields in that block. The next useful diagnostic separates screenshot encoding,
output chroma/color conversion and compression using small controls; this is
not justification for an arbitrary threshold change or another untested full
render. The independent PNG review and exact failed comparisons are retained in
`revision-work/creative-lossless-reference-independent-review.json`
(SHA-256 `a1e3a5b493c2fbd25c489c4d0bb5a0cb6700a5f9088d9c169c695ed66b3fd319`).

### Higher-quality export: actual result and remaining limits

One-frame encoding controls showed that the supported CRF 6 option could improve
fidelity relative to the native JPEG95 capture. They did not demonstrate a
lossless-source pass or qualify an entire long-GOP export. Production then ran
the full unchanged composition with CRF 6, one worker and the retained source
cache. The v3 guard completed successfully in **1,349.236s (22m29.236s)** at
**03:25:44.472709 UTC**. The native output contains all **15,761 frames** and is
**2,881,534,755 bytes**. Source, additional input, SDK and sandbox pins were
stable, and recorded process cleanup passed. This checkpoint was **2h46m31.207s**
after the creative request; the separate original B elapsed clock was
**5h58m59.988s**. Neither clock is a two-hour success.

High delivery QC completed in **133.523s** at **03:28:47.872938 UTC**. All
**23/23 JPEG95-relative samples** passed unchanged thresholds; the previously
failed panel-13 presenter region improved from **39.727166 to 41.713420 dB**.
Container, picture/audio clocks, complete decode, motion screening and measured
audio checks passed. Audio remains **−16.16 LUFS, −1.09 dBTP, 34.296585 dB SNR**
with zero failed local windows. Assembly preserved **30,815 AAC packets** and
added no picture or audio encodes. The finalized candidate SHA-256 is
`13af0af148295aec1299246837dbfe300fb4b5a93966f85fe44a523f4aea2bd6`.

The new uncompressed-reference diagnostic completed in **9.593s** and remains
**failed**, explicitly bound to those same candidate bytes. It improved to
**19/23 passing rows** and **22/23 passing whole frames**, but these failures
remain at the unchanged 40 dB PSNR / 2 MAE limits:

| Sample | Failing region | Actual PSNR |
|---|---|---|
| Panel 08, frame 774 | Presenter | 39.899605 dB |
| Panel 13, frame 1395 | Presenter | 37.809996 dB; MAE 2.176211 |
| Panel 16, frame 2148 | Presenter | 37.939543 dB; MAE 2.140747 |
| Closing 653, frame 15656 | Whole frame | 39.871381 dB |

No reference alignment, color fitting, source change or threshold relaxation
was used. Native JPEG95 capture is still an upstream limitation; CRF 6 does not
make that intermediate lossless. Viewing the actual decoded high-output frame
1395 alone found a readable diagram and contained presenter bubble, with no
obvious full-frame layout defect. That observation does not override these
numeric failures or establish perceptual acceptance for the complete video.

Full playback of this exact high candidate passed: all **15,761 frames** were
presented, the video reached **657.365042 seconds**, with **zero dropped or
corrupted frames**, no backward time movement and no faults after startup.
The guard ran from **03:32:05.739127 to 03:43:11.429692 UTC**, **665.673s**, with
stable input/SDK/sandbox pins and verified cleanup. The playback receipt SHA-256
is `f2f96c4926964355fb757c6664a3e4b7f6d14f927e6ad0436d4df3514de00c9d`.
This is actual new-output playback evidence, not reuse of the older output's
result. The headless browser's audio output was muted; this establishes video
decode/presentation/clock behavior, not audible listening or semantic quality.
The creative revision had reached **3h03m58.164s** at this checkpoint. Archive
verification subsequently passed as recorded below; visible Chrome handoff
remains separate.

### Pace finishing commands through the existing resource supervisor

The high-QC worker now waits for a real post-command resource sample before
launching the next command. Source review caught two preflight defects: a fresh
sample could already violate a supervisor limit before the final abort field
was persisted, and the generic recoverable exception path could allow a later
command after a failed acknowledgement. Production corrected both before the
actual high-QC run: evaluate the supervisor's identical `stop_reasons` against
the actual sample/policy/baseline, and use a latched, non-recoverable stop state
that both command and picture-hash wrappers check before doing work.

The production-reported ten regression tests passed. Actual high QC then
recorded **eight acknowledgements totaling 33.152055s of waiting**, with stable
source pins, no abort and verified cleanup. These waits are counted in the
133.523s phase, not hidden as overhead. This is a successful bounded execution
with unchanged resource limits, not evidence that all host memory problems
have been eliminated.

### Archive preparation without deleting either source cache

Read-only review found no additional concrete blocker in the final sealer,
copier or review server. The sealer binds the CRF 6 export, current high QC,
current lossless diagnostic, candidate hash and a complete zero-drop playback;
it preserves failed diagnostic history and marks the artifact as a review
candidate with a lossless-source limitation. It does not claim human listening,
creative/publication approval or goal completion.

Node's forced-clone operation returned ENOSYS, but the actual macOS `clonefile`
syscall passed a disposable font-copy isolation canary. The copier checks each
real copy's distinct inode, streamed hashes, source identity, non-symlink paths,
and disk reserve before and after copying, with no hardlink or full-copy
fallback. The canary alone is not proof that every archive copy succeeded.
Both A/B source caches stay preserved. The preview server reuses the current
working project and must verify its exact 68-file closure against the sealed
archive before launch; it creates no third project copy.

The compact independent source/runtime review is frozen at
`revision-work/creative-final-high-qc-archive-independent-review.json`, SHA-256
`1f22149f745545d2740fcf200dc97fbf7c64a7084f39668bfd6ad1d42c6ecb49`.
Further reviewer writes under the working B root stopped before archive copying.
Actual playback, archive and UI outcomes remain separate checks.

The actual [creative-revision archive](../../artifacts/c0679-creative-revision-2026-09-09/MANIFEST.json)
was sealed at **03:44:13.331752 UTC**, **3h05m00.066s** after the creative request.
The archive guard finished in **28.712s**, with stable pins and verified cleanup.
It contains **1,716 files**, **4,781,197,532 logical bytes**, including **68 editable
project files**, the finalized MP4 and retained failure evidence. The manifest
SHA-256 is `497354f15e40e222395e3302a110c02de8f9c28f0a8c598d189467b294cde517`.
Independent review checked its hash against the seal, the exact archive file
set, every file's size and distinct source/destination inode, and seven selected
small evidence hashes including the current QC, PNG failure, playback, prior
wrapper failure and final server source. All matched. Production's copier
verified every file hash; this reviewer did not repeat hashing all large media.
No source cache was deleted.

The native review server reported ready at **03:45:18.655 UTC** after verifying
the working project's 68-file hashes against this archive. It reused the same
working project and candidate hash, with no third copy. Production then observed
the actual visible Chrome DOM and screenshot: **53 child compositions plus the
root**, enabled Play, **00:00/10:57**, and the opening presenter visible. Its
post-UI verification still matched all 68 archived source hashes.

The [visible handoff receipt](../../artifacts/c0679-creative-revision-2026-09-09-handoff.json)
records **03:47:32.864410 UTC** (SHA-256
`fc3387c6901723912eed4a97b65d8bb56e97c2a4060eb473fd7c3636c9b049aa`).
The [final timing receipt](../../artifacts/c0679-creative-revision-2026-09-09-timing.json)
records **11,299.598410 seconds = 3h08m19.598s** request-to-ready (SHA-256
`c5499fb3ffdd01db4bd2e99ff3621293b0c3038419e10e680fb6558fd7a1f6fb`).
The supplements are saved outside the immutable archive. Independent review
verified their hashes, timing-to-handoff binding, candidate/manifest identity
and all 68 post-UI recorded hashes against the archive. This reviewer did not
open a competing browser session. The visible working project is ready for user
review; the bounded review server runs for up to 45 minutes, with deferred
sidebar thumbnails. No human listening or creative approval is inferred.

After that receipt, production made one defensive server-only delta, reviewed
read-only: the session receipt is first acquired with `wx`, and a failed startup
cannot overwrite an existing receipt during cleanup without owning it. Working
project verification now explicitly rejects symlinks before closure/hash checks.
The updated server SHA-256 is
`636fcaaf6abdd6db8c3aed472d06f5f30ee066ef91c02793d011eb4d4cd5e924`.
Production reported `node --check` passed; the reviewer did not rerun it or
write under B. The earlier receipt remains a correct historical source pin.

### Completion audit after the ready handoff

The 3h08m19.598s record is the first verified review-ready handoff, not a claim
that all quality work ended there. Additional diagnostics remain part of the
same current edit and must retain the original request boundary. Production's
handoff turn is terminal; there is no full render still running to wait for.

| Original requirement | Current authoritative evidence | Completion state |
|---|---|---|
| Complete approximately 10-minute edit | 53 authored scenes; 15,761 exported/presented frames; 657.365042s; source review and native checkpoints | Coverage established; stills and playback telemetry do not alone prove all creative qualities. |
| Catalog-led visual variety, presenter framing and motion | Whole-video allocation, source handoff/cue repairs, actual native scene/transition checks, opening/ending checks | Implemented and inspected at recorded checkpoints; no claim that every catalog entry was visually studied. |
| Consistent audio | Whole-file sample/packet timing, loudness/peak, global and local continuity checks pass for the final bytes | Objective checks pass; audible assessment is not established by the process-muted playback. |
| Preserve visual quality | 23/23 JPEG-relative samples pass; 19/23 PNG-relative rows pass | Four stricter comparisons still fail; investigate without changing thresholds or erasing evidence. |
| Editable HyperFrames handoff | 68 saved source files and hashes, actual Chrome inspection of 53 scenes plus root at 00:00/10:57, unchanged hashes after UI opening | Current saved project and visible opening established; complete portable/runtime or all future export workflows are not claimed. |
| Complete workflow within 120 minutes | Verified user request to ready handoff: 11,299.598410s | Contradicted for this revision. Another fresh trial was explicitly cancelled. |
| Memory discipline and preserved work | Single-worker guarded full export/QC/playback, checked cleanup, independent archive, protected A/B caches | Measured phases completed within their policy; not a guarantee about unrelated applications or all future jobs. |
| Record failures and avoid needless full rerenders | Immutable v1/v2 failures, reconciliation, batched source fixes, scoped checks, current diagnostic and timing archive | Recorded; no clock resets, discarded failures or substituted short-sample benchmark. |

Human approval is not being introduced as a mandatory stage of delegated
one-shot editing. Unobserved listening and creative acceptance must simply not
be claimed. Current engineering work can continue where a concrete quality
failure has a testable, authorized remedy.

Read-only SDK inspection identified a supported MOV/PNG/ProRes 4444 path for
the four residual image comparisons. A bounded diagnostic on the existing 23
PNG references was assigned to the existing production owner. It is not a full
render, source edit, SDK patch, fresh benchmark or alteration of the saved
candidate. MOV's encoder branch returns before the H264 color-tag arguments, so
missing color declarations must remain an actual diagnostic failure rather than
being filled with invented tags. Native transition routing and full-output
resource requirements also require their own evidence before a full MOV run.

The active preview currently occupies the exclusive media lane. Production is
preparing source/configuration and cheap argument checks, then will preserve any
unchanged-guard admission refusal. The preview is not stopped and the lane is
not bypassed. A decision to interrupt the visible review, if needed, comes only
after the concrete diagnostic is ready; a failed admission is not an excuse to
launch another full render or delete either cache.

That diagnostic is now prepared and independently source-reviewed:
`inspect_native_mov_preset.cjs`, `native_mov_reference_controls.py`,
`test_native_mov_reference_controls.py`, and the v1 phase configuration under
the retained B root. Actual execution of the pinned pure SDK builders passed
seven assertions and produced PNG-pipe / ProRes 4444 arguments with **no color
declaration arguments**. This is a source/argument result, not media fidelity.
The five pure Python fixtures cover wrong output, oversized input, missing
color-path decoding, incomplete frame count, and control-only success labeling.

At **04:03:07.458525 UTC**, the unchanged guard refused admission in **0.000504s**
with `NativeWorkBusy`. Its receipt explicitly records **child never launched**,
verified cleanup and stable source/SDK/sandbox/additional pins. No MOV was
encoded and no comparison results exist. The retained refusal is
`native-mov-reference-controls-v1.render.json`, SHA-256
`1b233277b72670a13d6c02ec0acde6d4ab2ea6eca6b660567f82cf8a6d08592f`.
The actual preset inspection SHA-256 is
`a44118d634aa406ff01d755be6eddbc9bc723f4725ad953fa9eb02c022dd0f17`.

A direct read-only `ps` observation subsequently confirmed both preview owner
processes still live: supervisor **73340**, worker **73366**. The occupied lane
is not inferred from an old lock file. The user has been asked whether to pause
the preview for the prepared check or preserve active review. Dependent media
work stays pending that decision; production was instructed not to retry,
terminate the preview, bypass admission or modify the saved candidate. This is
the first actual occupied-preview boundary encountered by this post-handoff
diagnostic, not a completed or timed-out quality experiment.

### Reserve finishing time before authoring consumes the deadline

This revision's full render started **92m59.400s** after its actual user request.
Its guarded render took **22m44.325s**, and the completed file-check attempt took
**50.976s**. One uninterrupted playback necessarily takes at least the program's
**10m57.365s**. Using those observed durations, the latest possible render start
for a 120-minute finish would be **85m27.334s**, before allocating any time to
packaging, launch overhead, diagnostics or fixes. The actual start was already
**7m32.066s later** than that boundary.

This arithmetic is an optimistic planning bound for this reused-input revision,
not a performance promise for a fresh edit. It explains why a picture export
near minute 116 cannot be called a nearly complete two-hour delivery. Plan
backward from finishing and whole-program review, and reserve additional time
for real handoff and correction work. The cancelled fresh trial stays cancelled.

Before finishing, a read-only adapter review found a real metadata schema bug:
11 bridge/closing references omit the scene/panel fields present in the other
12 rows. Production corrected normalization using explicit expected scene IDs,
retained the original receipts, and reported 11 offline tests plus the actual
23-row preflight passing. Frame selection, audio and color thresholds were not
relaxed. This is another example of finding a prerequisite failure through cheap
checks before spending a full media-review pass.

Two genuine layout findings were fixed together before full export: late
standing footage that cropped the presenter head, and a tight label inside a
hub oval. One independent reviewer initially misread the bridge image, then
withdrew the claim after reopening the identical hashed PNG alone. Preserve
the correction instead of presenting that false alarm as a renderer defect or
spending another render to repair it. The final-source review receipts and
their exact hashes are linked in the source handoff above.

The new prerequisite failure demonstrates a narrower validation requirement:
strict lint must run against the exact staged project after asset references
are transformed for rendering. Passing the editable project's lint and
source-resolved native captures does not prove that the installed render CLI
accepts the staged paths. This check belongs before a full render launch; it
does not justify bypassing strict lint or changing the SDK.

Installed HyperFrames 0.8.31 supports complete child-composition exports, but its
local render CLI has no master-interval replacement or resume option. Extracted
source-frame caching does not cache completed graphic frames. Internal
distributed chunks are not a qualified cross-edit reuse route. The
records the exact boundary; use scoped previews for fixes and batch accepted
visual changes before a required complete master export.

## Attempt A: established result and historical limits

| Area | Established result | Remaining requirement |
|---|---|---|
| Source and cuts | Source/cut provenance, full presenter media, soundtrack and governing source are saved and hash verified in A | Do not reuse these episode-specific inputs for B |
| Creative direction | Presenter-led native composition, padded rounded panels and varied treatments authored; selected encoded checkpoints reviewed | Full creative approval is not inferred from checkpoint or automated checks |
| Authored coverage | All 16,394 frames at 24000/1001 fps exported across the complete 683.766417-second composition | B must derive its own duration, cuts and frame count |
| Visual/seek checks | Full picture decode/timing and complete MP4 browser playback passed; selected framing repairs reviewed | Retain strict color-comparison failure; Studio usability is separately incomplete |
| Final audio | Corrected file passed whole-output continuity, packet/sample, loudness and true-peak checks | Actual listening remains unverified; Studio repeated audio seeks remain unresolved |
| Full export | V8 full native render completed in 25m41.357s; V10 corrected output passed objective and supplemental checks | No all-quality or user-approval claim |
| Memory protection | Complete native render: 221 samples, 2.214478 GiB peak owned footprint, normal pressure, zero observed new swap; tracked cleanup and shared lease verified | Evidence is for this workload and host; raw SDK launches bypass the manager, and other applications remain outside its control |
| Studio playback | Current 65-second observation completed and cleanup verified; timing subchecks passed | 668 audio seeks/waits and startup dependency rejection failed the observation; smooth-audio handoff remains unqualified |
| Delivery | Immutable 8,614-file package copied and hash verified; final MP4 pinned; actual package inspection passed | Saved-path re-export unexecuted; CSS-scoped wrapper is not a general fresh-edit pipeline |
| One-request edit | A's missed target is preserved; B's separate result appears above | Full editing, rendering, review, required fixes and usable Studio handoff must finish on the same clock |

## Attempt A: measured time and failure ledger

Times below are UTC on September 9. Parallel stage intervals must not be added
together as if they were sequential. No clock resets at a retry or visual pivot.

| Event | Measured evidence | Interpretation |
|---|---|---|
| Current production task turn begins | 09:05:08 | Known clock only; not a substitute for the original editing request |
| 32-second high export V1 | 135.557s | Exported fallback fonts and old panel geometry; retained revision failure |
| 32-second high export V2 | 98.082s; 72.036 capture, 23.613 encode, 0.988 assembly | Correct font/inset checkpoint and decode; overlaps other probes, so not an isolated benchmark |
| Full picture/PCM preparation | Starts 14:16:30.400; 7.172s total; picture clone 2.921s, PCM conversion 0.509s | Verified reuse avoids another picture encode or lossy audio generation; original cuts/mastering were already done |
| Incremental native coverage | 75.408667s at 14:21:29; 367.492125s at 14:29:36; full timeline at 14:41:58 | Incremental delivery is possible. These are coverage checkpoints, not full-quality completion |
| Independent 75–194s handoff | 14:25:45.793; next integration 14:29:36 | About 3m50s between handoff and integration; no evidence all of that interval was idle |
| Tail handoff | 14:39:36.082; full integration 14:41:58 | Shared helpers and separate scene files supported parallel authoring |
| Full V1: disk failure | 14:52:15.802–14:56:14.119; 238.317s, exit 1 | 16,394 source PNGs extracted in 218.171s; audio processed in 18.029s; capture then rejected for insufficient disk |
| Full V2: memory failure | 14:58:42.651–15:23:35.692; 1493.032s, exit 130 | Streaming bypassed the disk batch but memory exhaustion prevented completion |
| V2 reuse | Source extraction cache hit: 84ms; audio processing: 18.565s | Large extraction reuse worked. This does not demonstrate browser memory safety |
| Partial V2 file | 15,336 frames, 639.639s, 778,397,439 bytes, no audio | Diagnostic evidence only, not a usable delivery or successful percentage |
| Full V3: guard stop | 15:47:26.123–15:50:48.002; 201.880s | Unused-RAM threshold canceled the attempt; not a second OOM |
| Full V4: browser crash/stall | 16:03:28.879–16:15:47.747; 738.891s, exit 1 | Screenshot capture stopped at 3,949/16,394 frames; reducing browser compositor budget did not control growth |

By the V2 cancellation, the known production turn alone had lasted **6h18m28s**.
That is a lower-bound observed task interval, not the exact total project labor
or the original request's stopwatch. We have no defensible precise allocation of
hours to the rejected treatment, SDK investigation, authoring or coordination.
Future receipts must capture those intervals rather than reconstruct them.

## Third attempt: the guard worked, but its policy needs refinement

The supervised V3 trial ran 15:47:26.123–15:50:48.002 UTC, **201.880 seconds**.
It stopped after about 1,117 frames because literal unused RAM fell below the
6 GiB reserve, to 5.791 GiB. At that point the owned tree was 6.968 GiB, its
largest process 5.667 GiB, compressor about 2.231 GiB, and swap had decreased
from 16.314 to 16.193 GiB. The memory_pressure command's free percentage remained
83–84; that metric is not itself the kernel's categorical pressure state.
The owned footprint also showed a downward step during the run, so these data
do not establish a strictly monotonic browser leak.

The supervisor canceled the verified browser/native groups, handled a reparented
FFmpeg child and verified no tracked survivors. Source, SDK and sandbox hashes
remained unchanged. This establishes one real supervised stop/cleanup, not a
successful render, no-leak proof or guarantee against every detached child.
The three attempts together consumed **32m13.229s** of render-attempt wall time.
No new manual application closure was reported for this cancellation.

Do not call V3 a second memory-exhaustion incident. A minimum-unused-RAM rule can
stop normal cache use. Apple's documentation explains that memory pressure
combines free memory, swap rate, wired memory and file cache, and that cached
files occupy unused memory until reused.
[Apple Activity Monitor guidance](https://support.apple.com/guide/activity-monitor/view-memory-usage-actmntr1004/mac).

Recommended refinement: record actual kernel pressure state, retain owned-tree,
individual-process, compressor, new-swap and disk limits, and use literal unused
RAM as a launch margin/warning rather than the sole ongoing abort signal when
pressure and the other measures are healthy. Do not estimate available RAM by
adding overlapping inactive/file-backed/purgeable counters. A post-trial read
found kernel pressure state 1 and about 13.516 GiB file-backed pages, but those
later values do not establish the exact cache allocation at cancellation.
The cache-aware policy is now implemented with 20 passing regression tests.
Admission retains the 6 GiB unused floor; runtime records low unused RAM as a
warning and still stops on kernel warning/critical, unknown/unavailable pressure,
or any existing footprint/swap/compressor/disk limit. A read-only live sample
completed in 1.416s with kernel state 1, 15 GiB unused and no admission reasons.
The production owner must record warnings beside each resource sample and qualify
the complete render; this is not a new media success.

The sysctl reports userspace masks: normal=1, warning=2, critical=4. These differ
from XNU's internal pressure enum. Verified against Apple's
[conversion and sysctl handler](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_memorystatus_notify.c)
and [notification constants](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/event_private.h).
No aggregate or individual footprint limit was raised.

## Findings and changes in priority order

### P0 — Bound memory across the host and the complete owned render tree

At 15:21:39 the 64 GiB Mac reported 63 GiB used, approximately 32 GiB in its
compressor and 134 MiB unused. Four owned renderer children each showed about
14 GiB in the macOS top MEM column; the CLI showed about 3.35 GiB. Swap use was
62,539.06 MiB. Renderer RSS was only about 470–516 MiB each. Watching RSS missed
the compressed allocation burden. MEM already includes the compressed footprint;
adding CMPRS again would double-count it. These rounded samples are not a
precise process-by-process partition of physical RAM.

Installed SDK code gives each non-NVIDIA browser a GPU-memory budget of
min(total RAM / 2, 16,384 MiB). Four browsers on this host each receive that
budget. This is a concrete multiplicative-budget concern consistent with the
observed footprint, not a proven leak root cause. Frame injection also assigns
large PNG data URIs repeatedly; browser retention there is an unproven hypothesis.
The bounded Node data-URI cache does not bound every browser allocation.

Implemented sampler: [native_render_resources.py](../../scripts/producer/native_render_resources.py)
and [native_render_processes.py](../../scripts/producer/native_render_processes.py).
It measures host pressure, literal unused RAM, compressor, swap growth, disk,
owned footprint and largest process. Each OS command has a three-second deadline.
Missing/malformed measurements fail closed. Remembered PID/start-time/PGID
identities continue counting detached children after their parent exits.

The current recovery candidate explicitly uses one worker, stock low-memory and
software screenshot settings, a 32-entry/64 MiB Node frame cache, unchanged
1080p/rational fps/high preset/source PNGs and strict media readiness. Its
supervisor limits the owned tree to 16 GiB, an individual process to 15 GiB,
swap growth to 4 GiB, and reserves at least 6 GiB literal unused RAM and 10 GiB
disk. The sampler's more conservative default individual limit is 8 GiB; the
15 GiB override is explicit recovery policy. These are initial limits, not a
demonstrated optimum. Lower concurrency could make export slower.

The lifecycle owner samples at five-second intervals and discovers identities
between samples. Sampling is bounded but not instantaneous; memory can grow
between observations. Independent tests exposed and corrected four launcher/
ownership failures: missing initial descendants, skipped malformed process rows,
missing direct-child termination after registry observation fails, and receipt
collision overwrite. The sampler's malformed-row and duplicate-PID regressions
are now included in its 20 passing tests. Owner reports 11 process tests and nine
launcher tests passing; these use harmless fixtures, not a production media load.

Remaining: qualify the whole candidate render and output; enforce one shared
heavy-job lease across export, preview probes and frame-QC jobs; move the
currently fixture-specific supervisor into the supported workflow after
qualification. Cleanup cannot guarantee ownership of an unobserved detached
child or survive SIGKILL of the supervisor. An external owner/watchdog or other
supported lifecycle containment requires separate implementation and tests.
Do not claim an absolute hard OS memory cap from a polling watchdog.

Aaron closed Chrome and other applications himself. Recovery was therefore a
combined event, and the entire pressure reduction cannot be credited to our
cleanup. The guard must account for ordinary user applications being open.

### P0 — Preflight the actual render path before source extraction

The first attempt admitted roughly 70.3 GiB of available disk, then spent
218.171s extracting source PNGs before the SDK estimated 135,978.4 MB of capture
storage against about 35,031.4 MB free. The preflight had budgeted source
extraction but missed the subsequent capture-storage requirement.

Compute extraction + selected capture path + output + swap/host reserve before
starting work. Record SDK version, actual flags, rational fps, frame count,
worker count and route decision. Do not infer streaming from a single duration
flag: the four-worker route also required the stock parallel-stream opt-in.
Disk and memory are separate constraints; choosing streaming solved only one.

The recovery reuses the complete source cache and verifies frame count/completion.
Future cache admission should bind source hash, crop/cut map, fps, frame format
and SDK behavior. Keep one content-addressed cache with an explicit total disk
budget and ownership-aware eviction after work releases it. Preserve failure
receipts cheaply; retaining every failed intermediate forever is not necessary.
No user files or existing caches were deleted during this audit.

### P1 — Validate direction early; reuse motion primitives, not an old edit

The rejected 57-card treatment and accepted 32-second native presenter draft
show why creative direction must be tested before scaling. A representative
sample should include full presenter, padded side panel, live bubble, one
spoken statistic, one rehook and a transition. Inspect an encoded sample too:
Studio alone did not reveal the export-font mismatch.

For collaborative editing, publish that sample promptly. For a one-request
edit, the editor applies the same checkpoint internally using the brief and
fresh source review; do not add a routine user approval round. HyperFrames is
the default transition source and the first source for graphic mechanisms.
User-supplied Claude designs remain an allowed alternative.

Build reusable, verified primitives for presenter poses, deterministic text
changes, counts/ranges, charts, diagrams, lower thirds and reveal transitions.
Select and combine them according to the spoken meaning. Reuse palette, type,
safe areas and mechanics while varying information layout, presenter placement,
visual scale and density. Mandatory constant motion or arbitrary card quotas
can be as repetitive as the rejected treatment. Rehooks, claims and explanation
changes should drive emphasis, with clear intervals for the presenter to speak.

Font embedding and reverse-seek text state were real reusable fixes. Framing
also requires source-motion review: the 410s crop cut off hair despite correct
panel geometry, and the source stand-up spoiled the ending. The eight repaired
checkpoints resolved those static defects. A centered-frame formula alone
cannot replace watching movement in the selected source interval.

### P1 — Share source/time evidence once and integrate completed spans promptly

Prepare one versioned packet containing source and master hashes, frozen cut
map, transcript with kept words, rational frame/sample mapping, source-derived
claims, creative brief, presenter geometry and catalog provenance. The current
work reused ASR and 1,966 kept words instead of retranscribing for each agent.
Actual versus nominal cut timing differs by as much as 85.542ms at an interior
join; the 58.167ms final-duration difference is not the maximum cue error.

Use one integrator for index, media, shared motion and render lifecycle. When
parallel authoring is requested, assign disjoint spans/files with shared helper
contracts. A handoff needs cue provenance, IDs, dependencies, test results and
a small risk-window checklist. Freeze completed spans and make subsequent
changes explicit. This worked for 75–194, 194–367 and 367–end in the current edit.

Avoid repeated broad task-history/code reads and duplicate inspections without
a new question. Use compact status receipts and targeted messages. Track each
task's current assignment and whether it is authoring, reviewing, testing or
waiting. Agent count is not a progress measure. CPU/browser jobs need shared
admission even when separate agents own them.

### P1 — Make incremental progress visible and distinguish preview from export

The working Studio did grow from 75s to 367s to the full 684s composition.
Keep a stable project URL and a visible completed coverage/status record. After
each span's local checks, integrate it and identify the changed time range;
the user should not need a new whole MP4 to see a revised card. State separately
what is authored, visually checked, continuously playable and exported.

Do not repeatedly render the entire programme for an HTML/text/layout change
while the creative direction is still settling. Reuse the accepted picture and
PCM, and inspect native timeline changes plus representative encoded samples.
After source freeze, run the full export and final verification. No inspected
stock CLI range/resume/worker-recycling option establishes cheap arbitrary
segment rerenders here; do not promise chunk-resume support that this route
does not expose. Investigating supported chunking is later engineering work.

### P1 — Diagnose preview audio independently from the master

The native WAV preview logged 154 audio seeking and 154 waiting events in about
32s, averaging 208.31ms between seeks. It exceeded the 150ms drift threshold.
Sparse samples reported no active seeking and missed those short events, so
event telemetry is necessary. Other probes overlapped rendering/media work and
cannot isolate normal playback behavior.

PCM checks at 35–65s and all nine actual cut joins found no introduced mismatch
above one 24-bit LSB, equal channels and no clipping. Existing 10–40ms quiet spans
were already in the retained master. This narrows the problem; it does not
prove audible quality or identify exactly what Aaron heard.

The subsequent isolated 0–65s observation passed timing and disruption subchecks;
see the exact result and separate startup error below. Next compare full continuous
native playback with the final exported file: record wait/seek/pause events,
sampled clock and A/V drift, and perform
actual listening across the programme and joins. Keep separate source, exported
audio and preview findings. Do not alter a verified master solely to compensate
for browser playback trouble. An SDK setting or upgrade only counts as a fix
after the same test passes; release-note absence alone is not proof either way.

### P1 — Reuse relevant evidence, retain the final quality check

Cheap deterministic checks should precede expensive reviews: duration, IDs,
dependencies/fonts, forward/reverse state, source claims and cue mapping.
Fix a shared cause once rather than expanding an expensive reviewer loop over
the same known failure. Batch frame decoding/checkpoint capture when possible.

Reuse evidence only when its actual dependencies match: a card copy change need
not rerun source audio mastering; changing cut timing invalidates downstream
cues and A/V evidence. Recheck a compact global view of claims, numbers, sequence
and visual variety after local edits. Preserve the whole-video final pass.

Final checks must cover full decode, exact frame count/rational fps, expected
audio samples/end alignment, output loudness/true peak, continuous A/V and
visual inspection across all sections. Existing screenshots and decode checks
can miss frozen but valid frames. Downsampled mono correlation does not prove
full-band or perceived audio quality. Hash the actual reference/output around
measurement and label subjective listening separately from automated tests.

### P2 — Make the editable handoff reproducible

The package must contain the final reviewed MP4, native HTML/CSS/GSAP sources,
local media/icons, font evidence, source/cut provenance and outcome receipts.
Copy/clone only explicit local dependencies, verify their hashes and references,
and distinguish package integrity from quality approval. Heavy caches and
partial failed MP4s are not needed in the minimal deliverable.

The installed CLI ignores the historical hyperframes.json fps field. Without
an explicit fps flag or appropriate root metadata this source can default to
30fps; preserve the actual 24000/1001 invocation. Exact embedded Oswald and
Space Mono font bytes are already staged. The prepared README's failed four-
worker recipe was removed from recommended instructions during this audit.
The saved package now contains the bounded supervised command and passed actual
package inspection. All 8,614 copied files were hash verified. Execution from the
saved package remains untested; the proposed CSS re-export was held to preserve
disk capacity for the independent trial. Keep the archive immutable and record
later qualification externally.

## A testable 120-minute operating budget

This is a proposed acceptance budget, **not a measured ETA or a promise**. It
defines what must become fast enough, while keeping quality and required fixes.
The current recovery's 90-minute render-only abort deadline is a containment
limit; it does not fit this budget by itself and cannot establish success.

| Stage | Budget | Required result |
|---|---:|---|
| Source review, transcript/cut mapping and base preparation | 15 min | Verified source, intentional cuts, shared cue packet |
| Story/visual choices and representative native sample | 10 min | Presenter-led direction and mechanisms checked before expansion |
| Remainder of native authoring with incremental publication | 30 min | Full narration-led timeline using verified reusable mechanics |
| Integration and deterministic checks | 5 min | Frozen source with known dependencies and cues |
| Bounded full export | 25 min | Actual complete high-quality output, resource/cleanup receipt |
| Whole-video visual/audio review and automated output checks | 15 min | Full programme reviewed; measured and perceptual results separated |
| Required repairs, re-export, verification and durable handoff | 20 min | Usable final output and editable project, all necessary fixes included |
| Total | **120 min** | Both quality and time pass on this same edit |

A failure at a budget boundary remains a recorded miss; never drop review,
reduce resolution, remove necessary graphics or relabel a preview to pass.
If a single-worker full export cannot meet the render budget, profile supported
native paths under the guard before adding workers. Increase concurrency only
when aggregate memory, output quality and time all improve on representative
long-duration footage. Cache optimizations must report cold and warm results.

After current delivery, test a new full edit with its own honest start/end
record, actual raw/final durations and normal desktop applications present.
Include all work after source availability and disclose pre-existing episode
assets. One passing run establishes feasibility for that case; repeat across
different scene densities/source formats before calling it reliable one-shot
editing. Persist stage intervals, critical-path time, retries, cache hits, peak
owned footprint, host pressure/swap, final QC and publication time.

## Implementation status and evidence

The durable collection now contains 89 records, including the initial failures,
resource/cleanup regressions, complete native memory qualification, corrected
output checks, complete MP4 playback, failed Studio observation and final
external baseline handoff. All 88 preceding evidence files were verified by
size and SHA-256 before the final handoff record was added. The baseline owner
verified and saved A; production owns media execution, Studio repair and B.
Shared heavy-job exclusion and managed preview replacement are implemented.
Warm-cache and preview-record drafts remain outside the immutable package and
have not been adopted into its runtime. Complete Studio playback qualification,
saved-path re-export and the fresh full-edit benchmark remain open.

Frozen evidence: [manifest](evidence/c0679-optimization-2026-09-09/manifest.json),
[V1 receipt](evidence/c0679-optimization-2026-09-09/full-native-high-v1.render.json),
[V2 receipt](evidence/c0679-optimization-2026-09-09/full-native-high-v2-stream.render.json),
[media reuse](evidence/c0679-optimization-2026-09-09/native-full-media-preparation.json),
[PCM window](evidence/c0679-optimization-2026-09-09/audio-consistency-35-65-readonly.json),
[cut joins](evidence/c0679-optimization-2026-09-09/audio-cut-joins-readonly.json),
[framing review](evidence/c0679-optimization-2026-09-09/native-tail-independent-visual-review.json).
The [V3 receipt](evidence/c0679-optimization-2026-09-09/full-native-high-v3-bounded.render.json)
and [resource samples](evidence/c0679-optimization-2026-09-09/full-native-high-v3-bounded.resources.jsonl)
record the safe stop. The [production evidence log](evidence/C0679_NATIVE_PRESENTER_QC_2026-09-09.md)
continues as execution progresses. The following sections retain historical
decisions and intermediate failures; the opening status and final handoff above
state the current outcome.

## Guarded playback and startup-error classification

The stock Studio preview was observed continuously from 0 to 65 seconds using
the full 683.766417s presenter video and PCM. This job ran exclusively under the
shared heavy lease, with a 4 GiB tree cap, 3 GiB process cap, 1 GiB new-swap cap
and 135s deadline. Its supervisor elapsed time was **76.567s**. The recorded
owned footprint peaked at approximately **0.961 GiB**; pressure stayed normal.
All seven recorded process identities were verified absent and the lease closed.

After the 0.5s startup interval, **1,289 observations** covered 64.459 seconds.
Maximum A/V difference was **48.198ms**, maximum audio/player-clock difference
**24.000ms**, with **zero audio seeking, waiting, pause, stalled or error events**
and **zero dropped video frames**. The 35–65s subset also passed. These are
telemetry subchecks, not listening approval or proof of physical audio output.
The earlier probe used different, shorter media and different instrumentation;
the change must not be attributed solely to process cleanup.

The [original playback receipt](evidence/c0679-optimization-2026-09-09/post-cleanup-playback.json)
remains `telemetry-failed` because it also recorded one `Event: Event` page error.
A separate startup-only diagnostic took **4.847s**, required no playback or
export, and verified process cleanup and lease release. It captured the actual
error targets: Studio eagerly requested GSAP 3.12.5 `MotionPathPlugin.min.js`
from jsDelivr; that script failed under local-only networking. The CLI-injected
fallback then requested the 3.15.0 script, whose failure rejected a Promise with
the script error Event and no handler. This produced the reported page error.

Installed source confirms both paths. Studio's `ensureMotionPathPluginLoaded`
runs on iframe load even if the composition does not use motion paths. No
`motionPath` or `MotionPathPlugin` reference was found in current authored
source. No installed plugin filename was found in the repository, Codex plugin
cache or npm cache filename search; archived or unrelated copies were not ruled
out. No plugin was downloaded, error suppressed, source modified or SDK patched.
The [classification and pinned source evidence](evidence/c0679-optimization-2026-09-09/studio-startup-error-classification.json)
separate this unresolved editor dependency from audio-media health and renderer
memory growth. Full-programme playback, final encoded audio, listening and
offline motion-path editing remain unqualified.

## V4 result and durable process-management changes

V4 used one worker, the unchanged native SDK and source, high-quality 1080p PNG
frames, and a transparent launcher reducing the compositor budget from 16 GiB to
1 GiB. The owned tree nevertheless reached about **15.324 GiB**. Its renderer
disappeared before the SDK failed after 60 seconds without progress, at frame
3,949. The production task bound a macOS SIGTRAP crash report to renderer PID
69003 at 16:14:47 UTC; the report does not establish the allocation root cause.
The guard did not cancel V4: its receipt has no abort reason or cleanup signals.
All tracked processes exited. Do not credit our later stop instruction for this
termination, or claim the smaller compositor budget fixed browser memory.

The user's 11:21 screenshot showed yellow/red pressure and 65.36 GB swap while
also reporting zero installed RAM and zero app memory. A later 11:23 live sample
reported 64 GiB physical RAM, 18 GiB unused, normal kernel pressure and about
14.94 GiB swap. These are different observations, not proof of when or why the
UI readings diverged. User-reported strain remains part of the incident.

The first cleanup removed five exact obsolete preview-server identities whose
combined prior footprint was about 6 GiB. A complete foreground-preview inventory
then found nine more obsolete preview roots, with **49 recorded processes**
including their Chrome and FFmpeg descendants. Each was stopped with fresh
PID/start/group checks; all recorded identities were verified absent. Current
native preview PID 53236 and its five recorded children were preserved. No user
apps, media, extraction caches or OS caches were deleted. The subsequent live
sample showed **23 GiB unused RAM**, about **1.54 GiB compressor**, **10.58 GiB
swap** and kernel state **1 (normal)**. Changes in other apps prevent attributing
the entire host-memory delta solely to this cleanup.

Implemented safeguards:

- [native_work_lease.py](../../scripts/producer/native_work_lease.py) provides a
  nonblocking, never-unlinked kernel lock in one private per-user host namespace.
  A durable active marker survives owner failure and blocks another heavy job
  until cleanup is resolved. Every observed process identity is retained;
  completion independently checks that registered identities are absent.
- [managed_preview.py](../../scripts/producer/studio/managed_preview.py) maintains
  one current native preview across draft folders/checkouts. Reopening reuses
  it; switching drafts verifies shutdown before replacement. Startup acquires
  the same heavy-work lease and runs host resource admission. It opens no extra
  browser automatically. Existing Studio open/stop commands now use this path.
- [managed_preview_state.py](../../scripts/producer/studio/managed_preview_state.py)
  remembers detached children before stopping their parent. Permission errors
  cannot masquerade as process absence; failed cleanup retains the record.
  Re-adopting a live preview preserves earlier reparented-child identities.
- The active C0679 preview was adopted without restarting it or changing its
  composition/media. Native authored projects have a direct managed open command;
  they do not need the legacy plan-to-Studio generator.

**Validation: 101 focused tests passed in 0.450 seconds**, including real
cross-process lock contention, durable failure fencing, pressure admission,
same-draft reuse, failed shutdown, and a harmless detached child whose parent
had already exited. These verify process management, not a successful media
export. The production owner separately reports 12 supervisor integration tests.

Limits: direct raw SDK launches bypass this manager. The shared lease protects
callers that use it; it is not a machine-wide OS process limit. Snapshot-only
ownership cannot guarantee discovery of a child born and orphaned between
observations. Preview startup is budgeted; this code does not continuously sample
an idle preview. The long-render supervisor must keep sampling pressure and its
whole registered tree. The frame-allocation hypothesis still requires bounded
memory and pixel-parity evidence before another full render.

The first successful 48-frame transport attempt later exposed a shutdown race:
the process table and footprint sample straddled normal process exit, followed
by a cleanup permission error. Its failed supervisor receipt was retained even
though the native log reported a completed MP4. The shared heavy marker correctly
fenced another job. A separate explicit
[recovery helper](../../scripts/producer/native_work_recovery.py) now requires the
exact active nonce, the existing exclusive kernel mutex, an absent supervisor,
and two fresh checks of every recorded child identity. It archives the original
marker and proof before removing that marker; it sends no signals or changes to
the failed render receipt. Seven recovery regressions pass alongside the ten
lease tests. Real recovery of nonce `546ae6d001d4450292a4eff0c4c4d862` confirmed
all eight recorded children absent. Empty/unknown child registries, inspection
errors, active supervisors, a busy mutex and nonce mismatches refuse recovery.
This is an explicit diagnosed recovery path, never automatic stale-lock takeover.

A later 55-frame sparse native reference attempt stopped after **11.451s** with
48 frames captured. Two successive ps/top reads reported a missing owned
footprint during fresh-browser batch turnover. No memory threshold was reported
exceeded; the process identities behind the two failed readings were not retained
by the old exception. Browser turnover is supported by the log, but the exact
historical missing PIDs cannot be reconstructed. Cleanup and heavy-lease release
were verified, and the [failed receipt](evidence/c0679-optimization-2026-09-09/transport-baseline-reference-parent-v1.render.json)
remains failed; its partial frames are not an approved reference set.

The sampler now reads process identities both before and after `top`. It retains
owned descendants seen in the first read if they become orphans, excludes only
identities confirmed absent in the second read, and rejects new/changed live
identities whose footprint cannot be bound across those reads. A PID appearing
in `top` is insufficient when that PID now belongs to a newly created process.
Still-live missing memory raises the same retry message with structured exact
identity evidence attached. OS inspection errors continue to fail closed.
The existing supervisor's one-retry contract is unchanged; owner-side error
receipts should preserve the new evidence, and cleanup ownership should retain
the identities exposed by successful snapshots.

**31 focused tests passed** (20 existing plus 11 new turnover/identity cases).
An actual read-only sample completed in **1.352s**, verified the six current
preview identities, and reported normal pressure with a 1.5685 GiB owned
footprint. This validates the measurement path, not media execution after the
change. The [change and validation receipt](evidence/c0679-optimization-2026-09-09/native-sampler-reconciliation-validation.json)
pins the three changed files. A rerun and eventual full export remain required.

The owner's next reference attempt captured all 55 requested frames but remained
failed after **12.978s**: its new evidence recorded rapidly appearing identities
and a final missing root footprint; cleanup reported `Operation not permitted`.
Its output is not promoted to approved evidence. Explicit nonce-bound recovery
later verified the supervisor and **22 recorded child identities absent** and
archived [proof](evidence/c0679-optimization-2026-09-09/heavy.recovery-81d8e97503c64012ac619ec0594fed74.json)
before clearing only the active marker. The failed receipt stayed unchanged.
The owner added bounded pauses at the start/end of each sparse capture batch
so the host could measure a stable process tree, plus retention of sampler-observed
identities in cleanup ownership. The subsequent baseline and candidate attempts
passed in 60.363s and 59.994s with all 55 frames, eight measured batch boundaries
and verified cleanup. Prior failed receipts remain failed.

Existing useful but differently scoped work:
[latency punchlist](PRODUCER_LATENCY_OPTIMIZATION_PUNCHLIST.md),
[two-hour editor plan](TWO_HOUR_VIDEO_EDITOR_PLAN_2026-09-06.md),
[performance evidence](command-driven-editing/08_PERFORMANCE_AND_TESTING.md),
[SDK development estimate](DEVELOPMENT_ESTIMATE_AFTER_HYPERFRAMES_2026-09-08.md).
The old cold/warm LF14 baseline saved about 124s (21.85%) on its measured media
route. It did not include this complete fresh native edit and does not prove the
present goal. Legacy container memory controls also do not constrain native
Chrome processes launched directly on macOS.

## Official SDK patch inspection after V4 launch

A bounded read-only review fetched the official PR patches and tag-file metadata
through the GitHub connector. No dependency was installed or SDK file changed.

Version 0.8.32's [capture recovery change, PR 3700](https://github.com/heygen-com/hyperframes/pull/3700)
closes a failed capture session and defensively closes an orphaned probe, then
retries the complete capture once on a fresh screenshot session. It broadens
eligibility for typed sequential stalls, including screenshot/BeginFrame routes.
The bounds are 15s per drawElement frame, 60s without sequential progress and 30s
per parallel drawElement operation by default. Parent cancellation and encoder
interruption bypass retry. The implementation does not periodically recycle
browsers, preserve completed frames across the retry, or trigger on a rising
memory footprint while capture keeps advancing. See the actual
[orchestrator implementation](https://github.com/heygen-com/hyperframes/blob/v0.8.32/packages/producer/src/services/renderOrchestrator.ts#L3660).

The entire Git blob IDs of both frame-resource files are identical across the
three tags, stronger evidence than absence from release notes:

| File | v0.8.31, v0.8.32 and v0.8.33 Git blob ID |
|---|---|
| [videoFrameInjector.ts](https://github.com/heygen-com/hyperframes/blob/v0.8.33/packages/engine/src/services/videoFrameInjector.ts) | 8677ffc0d7802445c1a6df1c362df2dc4ce187ef |
| [screenshotService.ts](https://github.com/heygen-com/hyperframes/blob/v0.8.33/packages/engine/src/services/screenshotService.ts) | d67e45f3d461ec3cfa9c0a360bd26da749327f1e |

Version 0.8.33's [PR 3794](https://github.com/heygen-com/hyperframes/pull/3794)
excludes timeline onUpdate callback spans from static-frame prediction and enables
callback events during verification seeks on the disposable verification page.
It changes dedup correctness, not frame-data-URI lifecycle. No onUpdate,
onComplete or onStart callbacks were found in the current motion.js and four
extension JS files by the bounded source check.

The source review supports upgrading for genuine capture-stall resilience when
qualified. It does not establish these releases as a fix for C0679's ongoing
memory growth or as an answer to the host watchdog cancellation. This finding
must not be generalized to every possible SDK bug or later release.


## Subsequent bounded transport qualification

The isolated copy of native SDK 0.8.31 serves its registered lossless source PNGs
through short same-origin URLs rather than repeatedly assigning large base64
image URLs. It retains native extraction, frame lookup, composition, screenshot
capture and encoding. The installed SDK and authored video were not changed.
This is an explicitly qualified local transport adaptation, not an official SDK
upgrade or a return to the old graphics-only renderer.

The [paired native reference comparison](evidence/c0679-optimization-2026-09-09/native-reference-paired-v1.parity.json)
passed all **55 frames with exact JPEG bytes and exact decoded RGB**, including
matched actual lookup indices and source hashes. Four corresponding baseline and
candidate pairs at indices 92, 383, 625 and 653 were directly viewed for the
presenter bubble, padded left inset, name entrance and ten-year graphic. That
[visual review](evidence/c0679-optimization-2026-09-09/native-reference-selected-pair-visual-review.json)
is four static pairs; it does not attest whole-video motion, encoding or audio.

The [continuous canary](evidence/c0679-optimization-2026-09-09/transport-candidate-4320-v1.memory-classification.json)
captured **4,320 unique actual frames, 180.18 seconds of content, in 428.997s**.
After the predeclared 1,024-frame warm-up, the final two 1,000-frame windows had
13 observations each. Their owned-memory medians were **2,086.485 MiB and
2,084.485 MiB**: a 2 MiB decrease. The final 2,000-frame fitted slope was
**−0.015598 MiB/frame**, below the predeclared growth limit. Shutdown/inactive
samples were excluded. All 4,320 transport requests completed with zero errors,
rejections, aborted transfers or base64 fallbacks; peak open streams and source
file descriptors were one each and all were closed at completion. Source/runtime
pins, process cleanup and the shared heavy lease were verified.

These bounded results support the memory improvement without sacrificing the
tested pictures. They do not establish full-duration stability or finished
editing quality. The full 16,394-frame output and its audio/visual review remain
required. A linear extrapolation of this warm canary is not an end-to-end edit ETA.

At 18:05:13 UTC the 64 GiB host reported normal kernel pressure, 86% in the
memory-pressure command, about 1.624 GiB occupied compressor and 8.625 GiB old
swap. The one top interval showed no swap-ins or swap-outs. Literal unused RAM
was about 1.15 GiB while the file-backed category was about 17.28 GiB. This
explains why “45 GB used” in an application-facing view need not make a roughly
2 GiB render impossible. The counters use different accounting and were not
sampled simultaneously with the user's display. The pressure percentage is not
an exact available-byte measure; overlapping inactive/file-backed/purgeable
categories must not be summed. The full-render owner is reviewing an explicit
cache-aware launch policy. The default six-GiB unused admission remains distinct
from continuous six-GiB tree, five-GiB process and one-GiB new-swap limits.

The durable evidence folder now preserves **48 pinned files** including successful
bounded checks and prior failures. A prepared re-export adapter also passed
17 offline boundary tests, actual local binary discovery/version inspection,
frozen supervisor import, and native CLI help with networking restricted to
localhost. Its 5,793 runtime/dependency files total 429,732,138 bytes. It retains
one native worker, rational frame rate, high quality, PNG source frames, strict
media readiness, shared exclusion and verified cleanup. Its full-export flag is
still false; no destination package or media was copied during preparation.


## Full native render succeeded; final review remains separate

[V8's terminal receipt](evidence/c0679-optimization-2026-09-09/full-native-high-v8-url.render.json)
completed at **18:49:13.838547 UTC** with exit 0 after **1,541.357451s
(25m41.357s)**. The full MP4 is **870,320,056 bytes**. Its 16,394 source-frame
transport registrations/requests completed with zero errors/fallbacks and zero
open streams/file descriptors at completion. All source, SDK, sandbox and
additional dependency pins remained stable. Tracked process cleanup and the
shared heavy-lease release were verified with no survivors or cleanup signals.
This receipt deliberately remains `rendered-awaiting-output-qc`.

The 221 recorded host samples showed **2.214478 GiB peak owned footprint**,
normal kernel pressure in every sample, a maximum occupied compressor of
**1.5 GiB**, and **zero observed swap growth relative to admission**. Three
bounded process-turnover resamples retained complete measurement semantics.
These full-duration observations support the memory fix for this native route
and this host/workload; they are not an OS-wide guarantee against every other
application or a claim of continuous measurement between samples.

The successful attempt used the reviewed cache-aware admission: three fresh
stable observations, normal pressure, at least 50% coarse headroom, at least
8 GiB in the single file-backed category and a 10% compressor ceiling. Literal
unused RAM remained recorded as advisory. The live six-GiB tree, five-GiB
process and one-GiB new-swap limits were unchanged. No apps were closed to make
this attempt pass. The generic `NativeRun` defaults remain unchanged.

V5 (1.543474s) and V6 (1.533419s) refused before any native child launched because
a proposed one-GiB literal-unused floor was still too conservative for this
cache-heavy host. V7 (8.885877s) passed the revised admission, then failed native
strict lint because retained test HTML files appeared as extra root compositions.
V8 explicitly selected `--composition index.html` and kept strict/no-best-effort
validation. Those earlier receipts remain failures, not successful renders.

The prepared reusable command now also selects `index.html` explicitly and
preserves executable-helper modes. Its 17 offline tests pass. After complete
output QC, the specifically qualified C0679 manifest will select the frozen
cache-aware admission automatically; the simple user command can remain
`reexport.py <new-label> --execute`. Runtime/package qualification flags remain
false until the complete release evidence exists.

The eight full-export attempts total approximately **4225.440s** of attempt wall time; this excludes authoring, intervening diagnostics and final review. The durable evidence manifest now contains **56 files**. The two-hour editing target remains missed.

## First whole-output review found audio defects; release remains open

The [first whole-output measurements](evidence/c0679-optimization-2026-09-09/full-native-high-v8-url.output-qc.json)
completed in 32.237s, within a 40.873s supervised job. All **16,394 picture
frames** passed zero-based constant-frame-rate timing and complete strict decode.
Full-programme overlapping audio continuity comparisons passed with zero measured
lag; channel balance, tonal-hum and audio/video timing checks also passed.

The result remains **`objective-measurements-fail`** for two specific reasons:

- Native AAC measured **−0.24 dBTP**, exceeding the **−1.5 dBTP** ceiling by
  **1.26 dB**. Integrated loudness of −14.67 LUFS passed its separate tolerance.
- Audio presentation retained **32,820,768 samples**, compared with the expected
  **32,820,788**: a **20-sample deficit**, about 0.417 ms at 48 kHz.

These measurements do not prove the cause of the user's earlier audible report.
They identify export defects that must be repaired and rechecked. The first
failed result remains immutable. A final package must reproduce the qualified
audio assembly rather than merely ship an externally corrected video alongside
a re-export command that recreates the failed sound.

The production reviewer examined contact sheets covering 83 actual encoded
checkpoints. An [independent review](evidence/c0679-optimization-2026-09-09/full-native-high-v8-url.independent-selected-picture-review.json)
directly inspected eight extracted frames around 410, 443.6, 491.3, 668.6, 679.3,
679.7, 680.1 and 682.9 seconds. The padded rounded side insets, circular bubble,
studio overlay, repaired hair containment and ending handoff passed those static
checks. The empty end-screen slot is intentional. Neither review establishes
continuous motion quality or human listening approval. Carrying these reviews
over to an audio-only derivative requires proof that its video bitstream stayed
unchanged; a picture change requires an appropriate new review.

Color interpretation remains open. Raw RGB comparisons showed a systematic
difference, but source PNG cICP, screenshot sRGB ICC and encoded transfer/gamma
metadata differ. A raw pixel comparison that ignores those meanings is not
enough to declare displayed-color loss or justify a brightness adjustment. The
[review receipt](evidence/c0679-optimization-2026-09-09/full-native-high-v8-url.root-checkpoint-review.json)
retains this uncertainty. The owner is checking color-managed comparisons before
changing the picture. No corrected-output release is claimed here.

The durable evidence manifest now contains **63 pinned files**. Full render,
first output QC and both subsequent frame-extraction/comparison jobs verified
tracked cleanup and lease release. The editable-package copy and guarded
re-export qualification remain pending the corrected output and frozen runtime.


## Corrected output and immutable Attempt A baseline

The corrected V10 file passed complete objective QC and the independent
supplemental authority check. Its guard took **194.420299s**; stream-copy assembly
itself took **1.434203s**. The separate supplemental guard took **18.886833s**.
All **16,394 video packets/decoded YUV frames** and **32,053 donor AAC packets**
were preserved with exact clocks and observed 1,024-sample encoder priming.
Eighty-two SPS/PPS fields were checked: only transfer characteristics changed
from 1 to 13, with matching MP4 sRGB metadata. The corrected sound presents
**32,820,788 samples**, retains **460 padding samples**, and measures **−14.61
LUFS / −1.86 dBTP**. Sealed donor/float receipt bodies were recomputed and the
exact float-to-PCM24 provenance verified. No extra lossy encode was introduced.

The complete editable project, local media, corrected video and pinned runtime
were copied to `artifacts/c0679-native-hyperframes-2026-09-09`: **8,614 files,
4,123,283,470 logical bytes**, all clone hashes verified. Actual package-relative
inspection passed for **8,486 runtime files** and the recorded local binaries.
The package includes existing NumPy, SciPy and Pillow plus measurement source;
CPython 3.14 runs analysis in isolation without external site-packages. Thirty-nine
offline execution/source-boundary tests passed before this snapshot. This is a
saved baseline, not an executed saved-path re-export certificate.

The [external baseline identity](evidence/c0679-optimization-2026-09-09/attempt-a-baseline.json)
records the immutable package and output:

- Package manifest SHA-256: `1cc0c92dfc15530afb57c2f6d33caf62061a6034d648e43b69d2d64069c5f7c5`.
- Corrected output SHA-256: `eef61c5a2a410d869c79c13c6fb9ba69f52690377d0a99c3fbd53db3ffa50181`.
- Runtime manifest SHA-256: `8a668d99fbf9cc4af344022edade544728d5c873b28a629dc5ddc8ed113970f4`.

The browser's strict color comparison retained a failure at frame 653:
**39.4668 dB versus 40 dB**, while MAE was below two. Image controls were exact;
comparison to a canonical image characterized a residual video-path difference
of about one RGB level. The reviewer found no material visible issue in two
selected still pairs. This does not identify a specific Chromium implementation
bug, and the failed threshold is not relabeled as passed. No further grade or
re-encode is justified by this evidence. Complete corrected-browser playback
review remains separately recorded; the first run omitted WebIDL counters and
remains failed. The earlier 65-second Studio receipt also remains failed due to
its startup Event error, although its timing/audio-disruption subchecks passed.

The user subsequently requested an independent fresh edit from the original raw
footage, comparing quality only after it is complete. Attempt A is now immutable.
The proposed CSS full re-export is held to preserve disk capacity; its actual
execution remains pending, not passed. The same-cut wrapper must not be called a
fresh-edit pipeline. Attempt B and comparison evidence belong outside this
baseline, and B must not reuse A's edited soundtrack, cuts, source project or
frames. Only generic engineering improvements may carry over. At this historical
checkpoint, no B timer or media work had started in this audit task.

Two usability issues remain outside the archive: repeated warm exports need a
complete source-bound frame-cache attestation before lowering the cold disk
reserve; and the generated root `.studio-server.json` must be distinguished from
authored JSON. The latter has a narrow four-field, local-URL validation fix with
**42 passing offline tests** in separate preparation. Arbitrary or nested JSON
still requires soundtrack requalification; the operational record remains a
current-run input pin. The archive has not been migrated. Also, managed preview
open can replace a previously registered preview across projects: preserve the
working Studio on port 41058 instead of invoking that command blindly.

The two-hour target remains missed. The durable evidence collection now has
75 pinned files; no listening or user creative approval is inferred.


## Final MP4 playback passed; Studio observation remains failed

Corrected MP4 playback V2 completed under its guard in **694.551128s**. Playback
and coverage passed: **zero reported dropped frames**, 16,393 frame callbacks,
maximum callback gap **83.5 ms**, and no disruptive events. All tracked cleanup,
lease release and source/runtime pins passed. The combined browser review remains
failed solely for the retained strict color threshold. Headless playback was
muted at the browser output and does not establish perceptual listening approval.
V1's missing WebIDL counters remain a failed diagnostic; they are not backfilled.

A separate current Studio observation remains **failed**. Its timing subchecks
passed, but it recorded **668 audio seeking and 668 waiting events**, plus the
blocked MotionPathPlugin CDN load. The production owner is checking the event
semantics read-only. This is not equivalent to the qualified corrected MP4, and
no Studio playback pass or audio-cause conclusion is claimed. The existing
preview's PID/start identity and listener were confirmed alive; no restart or
shutdown was needed. New terminal evidence is retained outside the unchanged
Attempt A archive. At this historical checkpoint, the fresh-trial timer had not
started in this audit task.


## Attempt A external handoff finalized

The external final handoff is `evidence/c0679-optimization-2026-09-09/attempt-a-final-handoff.json` (SHA-256 `6499692cfe3418fd45434ab32ad0181381ea89a897fa04e4df627b9c2956cf1d`). All 88 preceding external evidence files were rechecked by size and SHA-256; the collection now contains 89 files. Archive and runtime manifest digests still match the saved baseline. No archive files were modified.

Independent read-only review confirms the 668 seeks/waits are real Studio player events: the observation made one initial seek and one Play click, with no media setters during playback. A transient audio readyState of 1 was captured. Stock synchronization logic is a candidate cause; no audible effect or complete cause is asserted. Smooth Studio audio remains unqualified, while corrected MP4 full playback passed. Actual saved-path re-export and human listening remain untested.

At the A handoff, production reported fresh Attempt B had started at
**21:26:48.341117 UTC on September 9, 2026**, before original-source preparation.
B was still unsealed and uninspected by this audit task at that point. Its
subsequent sealed result and selected evidence verification now appear at the
top of this document. A's failure and archive remain unchanged; generic repairs
discovered during B remain included in B's elapsed time.
