# Shorts: shared optimization map

## September 11 local integration

The [native request/execution workflow](NATIVE_SHORTS_WORKFLOW.md) now connects
requested/automatic treatment, source-first supporting shots, canonical backed
titles, shared canvas assembly and supervised export. It uses the existing
frame/sample clock, caption grouping, float mastering, AAC reuse, work lease,
resource sampler and verified owned-process cleanup. The pinned runtime and
file-backed frame transport are installed locally from verified patches.

All three request-bound exports pass. Additional AAC encodes are zero when
reusing their qualified audio. Measured owned-tree peaks are 2.23 GiB (presenter),
2.71 GiB (offer story) and 2.12 GiB (math). The same 149-frame picture QC dropped
from 62.099 to 5.989 seconds with identical MP4 and metric results after replacing
temporary PNG compression with one raw RGB batch decode. See the
[measurement and limitations](../findings/NATIVE_SHORT_QC_CAN_BE_FAST_WITHOUT_CHANGING_PIXELS.md).

This supersedes older “pending connection” notes below for the shared local
native route. General scene-level incremental encoding, automatic external media
acquisition and qualification across every library style remain unestablished.

Aaron explicitly requested on September 10 that Shorts inherit the useful
long-form optimizations and reuse code where possible. This is an implementation
constraint, not a claim that the native Shorts path is already qualified.
The [implementation checkpoint](NATIVE_SHORTS_DEVELOPMENT_2026-09-10.md) records
the current executable path, tests, real-source sample and remaining QA blocker.

The latest [real export qualification](SHORTS_REAL_EXPORT_QUALIFICATION_2026-09-10.md)
records three completed MP4s, measured transport improvements, actual failures
and shared fixes. It supersedes preview-only statements below for those exact
cuts. Complete editing time and the live strategy/style matrix remain unqualified.

The primary creative catalog is the **HyperFrames registry**. Its inspected
blocks/components, variables, assets and native composition model govern reuse.
Sniper's local graphics-kind catalog is neither the Shorts catalog nor a native
eligibility gate. Reuse the long-form catalog-first native workflow, qualify the
specific portrait adaptation needed, and keep the current two-mechanism V9
development exercise separate from that broader implementation.

## Existing evidence and decisions

The [Nate storytelling test](NATE_STORYTELLING_TEST_2026-09-10.md) extends actual
exports with a 24.52-second evolving offer example (48.34s render, 2.61 GiB measured
peak). It reuses the same file transport, source clock, caption grouper, resource
owner and audio delivery gates. The shared canvas now clips successive phrase
lifetimes at the next phrase start while retaining original word bounds. The
follow-up revision reuses a byte-identical verified export; members reuses proved
AAC after its title/caption picture change. These are measured local applications
of long-form reuse, not proof of general UI integration or a complete editing-time
target. The new gallery retains all three revisions for operator review.

The [native Director integration](NATIVE_DIRECTOR_INTEGRATION_2026-09-10.md) now
reuses the Script Director's canonical format/hook/formula/training sources and
the existing subscription worker, deadline and journal. It freezes one library
snapshot per attempt, stores author and independent-critic decisions, and gives
the critic only the relevant examples/category context. This is connected to
native V9 preparation before scene planning; the limited renderer and default
UI route are unchanged. No hook effectiveness or editing-speed claim follows.

The primary references are
[the C0679 end-to-end audit](C0679_END_TO_END_OPTIMIZATION_AUDIT_2026-09-09.md),
[the applied GUI punch list](PRODUCER_LATENCY_OPTIMIZATION_PUNCHLIST.md),
[audio revision dependencies](../findings/AUDIO_REVISIONS_NEED_STAGE_SPECIFIC_DEPENDENCIES.md),
[single-decode caption proof](../findings/CAPTION_PAGE_SINGLE_DECODE_2026-09-07.md),
and [cheap metadata guards](../findings/PRIVATE_METADATA_GUARDS_ARE_NOT_RECEIPT_SERIALIZERS.md).
Also read the [private runtime checkpoint](NATIVE_PRIVATE_RUNTIME_CHECKPOINT_2026-09-10.md)
and [catalog-first native direction](C0679_NATIVE_HYPERFRAMES_DIRECTION_2026-09-09.md).
Read their result limits along with their numbers. The C0679 revision took
3h08m19.598s to its verified review-ready handoff; a quality-approved two-hour
workflow was not established. No fresh benchmark or canceled repair is resumed.

| Optimization | Existing implementation to reuse | Native Shorts disposition |
| --- | --- | --- |
| Direct and critique before assembly | Native BRIEF/scene plan; existing author/critic runners, review contract, planning loop and immutable authority | The native Director freezes the canonical library and requires source-bound author/critic decisions before V9 scene planning. Aaron declined external transcript/reference transfer and requested local work. Local template filling and manual review candidates do not count as a live Director/critic qualification. The limited writer does not yet execute general reviewed typography/crops. |
| One retained source/transcript and exact output clock | `guided-proposal-inputs.ts`, `guided-proposal-speech.ts`, `edit/exact_timing.py` | V9 uses the existing transcript staging and occurrence mapping. Never rerun ASR for each scene or remap nominal seconds independently. |
| Shared complete-program and frame-range validation | `guided-proposal-frame-ranges.ts` | Extracted from the existing candidate compiler; both routes call the same implementation. |
| One caption grouping policy | `captions/captions_whisper.py` `_whisper_cues`, `studio/native_caption_groups.py` | V9 calls the existing gap/word/sentence grouper once and retains exact occurrence IDs. Portrait DOM placement remains a native adapter; no ASS raster proof is inferred. |
| Source/cut verification and immutable proposal reconstruction | `guided-proposal.ts`, `guided-proposal-store.ts`, pipeline snapshots | V9 uses the same leases, before/after verification, immutable records, prompt binding and cold reconstruction. |
| One original work clock and attributable stage times | `generation-deadline.ts`, `generation-clock-watermark.ts`, `stage-timing.ts`, Python `stage_timing.py` | V9 compilation inherits these. Native project writing and later encoding/QC must use the same journal, with separate measured stages. Failed attempts remain counted. |
| Invalidate only dependencies that changed | `fingerprints.py`, `current_render_graph_inputs.py`, `audio/program_master_cache.py`, `graphics/render_cache.py` | Preserve stable cuts/captions/scene IDs. Connect a native adapter to the existing graph before claiming incremental export. Text changes must not remaster dialogue; cut changes invalidate downstream timing. |
| Audio repair without a new picture encode | `audio/float_master.py`, `audio/program_delivery_signal.py`, `audio/native_dialogue_delivery.py`, existing render/master caches | Shared float mastering and decoded delivery gates now serve both routes. All three actual Shorts pass; offer/member revisions reuse proved AAC with zero additional audio encodes. Application export integration remains pending. |
| Decode and inspect a batch once | `captions/caption_page_decode.py`, caption page proof, current native QC packet batching | Reuse existing proof helpers when those artifacts exist. Native DOM captions do not have raster page proofs; do not fabricate equivalence. Batch native checkpoints rather than launch a browser per word. |
| Cheap repeated guards | `guided_presenter_read_fingerprint.py`, immutable input holds | Keep byte/currentness checks, but do not recanonicalize complete receipts on every callback. Do not replace strong authority reads with an unrelated stat-only cache. |
| One bounded media owner | `native_work_lease.py`, `native_render_resources.py`, `native_render_processes.py`, `studio/managed_preview.py` | Mandatory for native Shorts previews and heavy work. Keep RAM/disk reserves, original deadlines, process identity, cleanup and failed-admission evidence. No ad-hoc preview bypass. |
| Preflight the actual route before extraction | `studio/native_preflight.py`, native resource supervisor | Check pinned runtime, fonts, dependencies, target/fps and full storage needs before heavy media work. Structural lint is not audio/visual QA. |
| Retain source-frame cache and bounded transport | SDK native frame cache and guarded single-worker export | Preserve existing caches. Reuse only matching source/cut/fps/frame-format/runtime entries. Do not recreate long-form extraction for each Short or promise unsupported range/resume export. |
| Validate representative direction before scaling | Native scene snapshots, forward/reverse seek and encoded samples | Prove one whole Short before all three. Holds and visual changes follow meaning; long-form card-density rules are not shared creative requirements. |
| Reduce orchestration and failed work | Planning-loop no-progress/gate-fix bounds, checkpoint mutation barrier | Keep existing routes intact. Native adds no retry loop or model downgrade. Share source/reference evidence once, fix common causes together, rerun affected checks, then retain the whole-output pass. |
| Portable editable handoff | Existing dependency closure, hash verification and archive workflow | Reuse explicit local dependencies and source provenance. Avoid unnecessary media copies; no hardlinks that let an edit mutate source evidence. |

## Long-form trial improvements that still need application integration

Several important optimizations exist as frozen trial/runtime sources rather
than installed production modules. Reusing them means resolving configuration
and dependency ownership, relocating their tests, and qualifying the native
Shorts use. Copying historical absolute paths or combining SDK patches does not
establish that work.

| Preserved improvement | Evidence and transfer rule |
| --- | --- |
| File-backed frame transport instead of repeated large base64 URLs | The isolated long-form adaptation passed 55 exact comparisons and a full 16,394-frame render. The new paired warm Short test observed 49.962 → 34.733s and 3.825 → 2.174 GiB with all 326 decoded frames and audio identical. All three exports used the isolated transport variant; installed/application integration remains pending. |
| Cache-aware admission for the qualified workload | Three fresh stable samples, normal pressure, coarse headroom, one file-backed category and compressor bounds admitted that trial; live tree/process/swap limits remained. The trial alone does not authorize changing generic preview admission. Aaron subsequently explicitly authorized bounded short previews despite low unused RAM; the three-case test keeps that exception local and retains the measured limits/failures. |
| Realm-safe Studio preview variant | Earlier previews qualified this separately. The new isolated exports combine it with file-backed transport and pass recorded output checks. Outgoing-element clipping was also needed at boundaries. Installed SDK is unchanged; CLI snapshot still disagrees at one members boundary, so full Studio qualification is not inferred. |
| Process-turnover reconciliation | Shared sampler reads identities before and after footprint collection, preserves detached ownership and rejects unbound live processes. Trial capture workers also used bounded batch pauses for stable sampling. Reuse ownership semantics rather than suppress measurement failures. |
| Trace reconciliation without re-encoding | A completed native export was recovered from exact stdout/stderr logs, input pins and output bytes after the wrapper missed stderr cache evidence. Preserve the failed wrapper result; validate the existing output before scheduling another full render. |
| Audio/container correction with unchanged pictures | Three Shorts reuse shared mastering and output QC. Measured sRGB-transfer correction preserves H.264 picture payloads/AAC packets and passes all 23 native pixel samples. Color repair remains a local harness, not a generic installed retag policy. |
| Batch packet/decode/visual checks | One ffprobe packet inventory replaced repeated process launches. Collect independent failures together; retain completed byte-bound checks and rerun affected checks plus final whole-output review. |
| Copy-on-write packaging | The frozen clone helper reduces unnecessary copying while retaining independent files and hash checks. The current development writer uses the existing verified byte-copy helper; native archive integration is still pending. |
| Cache identity and operational metadata | Same-project warm frames were reused. Copied revision projects missed because identity includes absolute path and mtime; actual hits/misses are recorded regardless of labels. Portable source identity and cache admission need application integration. |

Keep Studio preview and final encoded playback evidence separate. The long-form
archive had a successful complete MP4 playback while Studio still recorded 668
audio seek/wait pairs and a dependency-load failure. Neither static lint nor
muted browser telemetry establishes listening approval. The two-hour target
also remained unmet after later creative revisions.

## Boundaries

The [three-case strategy/preview report](../../artifacts/shorts-strategy-validation-2026-09-10/QA.md)
now supplies contrasting native Short evidence: full presenter, full teaching
graphic, and diagram with a close presenter. They share one experiment assembler,
the existing source clock/caption grouper, source verification and managed
preview ownership. A review bound to the plan, executable direction and source
evidence blocks missing/stale/unreviewed assembly in that experiment. The native
application planning adapter remains pending. Source/audio/caption evidence was
preserved during the visual revisions; one Studio text edit was saved/restored
exactly. No new ASR, full encode or paid asset generation was needed for these
checks. These are reuse observations, not a measured editing-speed improvement.

Share transport, timing, validation, storage, resources and applicable media
execution. Keep Short-specific direction, portrait geometry, caption layout and
hook selection in narrow adapters. Do not make long-form execution accept a new
scene type it cannot render. V9 is deliberately refused by legacy readiness,
opening and body paths until its native review/execution has an explicit owner.

The first development executor is deliberately small: presenter holds and a
source-timed original message illustration. Required outside assets stay explicit
blockers. Native asset acquisition, production hook assembly, render graph
integration and general incremental encoding remain subsequent connections.
Shared audio finishing is now tested on real outputs; its application connection
is pending.

## Verification required before a speed claim

Compare the same source and output quality at native portrait resolution. Record
input preparation, creative compilation, project writing, static checks, preview,
encoding, output QA and complete elapsed time separately. Include cold and warm
behavior, memory/disk pressure and failed attempts. A shorter clip or a warm cache
alone is not evidence of a better implementation.

A scoped scene revision must preserve unaffected footage ranges, caption IDs,
source/audio bytes and other scene definitions. A changed source cut must reject
old scene timing. The final audiovisual check remains necessary after local reuse.

## September 12 pacing integration

The native pacing layer reuses the retained occurrence clock, caption membership
and the same next-phrase end clamp as rendering. It adds measured observations
and editor-authored budgets, not another ASR or caption renderer. New strategy
and visual hashes reject stale timing; the writer/cold reader share one report.
The changed follow-up and offer revisions reuse the existing qualified AAC donor.
The member-math project emits byte-identical HTML and reuses its prior MP4.

Explicit native checkpoints now run in both forward and reverse seek order.
The dog insert exposed why an exit belongs on the untimed wrapper containing
both the video and injected frame; reuse `nativeVisualExit` there and remove a
redundant video-only mask. Do not weaken reverse-state comparisons.

The current source-frame cache includes the staged file path and modification
time. A new isolated project does not automatically reuse every source-frame
entry merely because source bytes match. A capture-only attempt against a new
project correctly stopped before capturing because its exact cache key was not
present. Render-to-QC reuse within one staged project remains available. Several
cold-start attempts also stopped on the host's three-second `top` query timeout;
their cleanup passed. Keep these failed attempts in timing totals and investigate
extraction concurrency separately before claiming fully optimized cold starts.

## September 12 organic-media and runtime integration

The new v3 asset-use plan reuses AssetRecordV1, source inventory, exact retained
occurrences, canonical hashing and writer/cold-reader checks. Images, logos,
footage and web captures share one source-policy and speech-purpose contract.
Guided preparation reconstructs the actual stored job intent and source manifest;
it does not create a second source inventory or trust a submitted replacement.
The source origin adapter preserves technical acquisition and unresolved intended
use separately, and the web wrapper calls the same reader before emitting its
final binding. Two actual prior web captures passed that adapter/reader bridge.

Prelaunch and live telemetry now use one bounded measurement implementation.
Typed command timeouts and process-turnover failures share four attempts,
18 seconds and the original run deadline. The owner reserves its receipt before
the first sample; wrapper-specific duplicate reads were removed. The existing
Short compressor allowance is computed once from that same verified baseline.
All other admission and owned-process caps remain unchanged. See the
[retry finding](../findings/NATIVE_TELEMETRY_TIMEOUTS_NEED_ONE_SHARED_RETRY_BUDGET.md).

An explicitly empty-cache offer export passed complete native/encoded checks in
86.880 seconds with 2.711 GiB observed peak. This is one successful cold run,
not a measured success rate. Actual new 4K identity tests also exposed a Chrome
closure during a longer capture session; no OOM diagnosis was confirmed.
Direct fresh-session poses rendered correctly, but that diagnostic still failed
its supervision gate. The opt-in bounded-session path completed both new 4K
pictures; strict reuse then carried those exact pictures through all final
audio/native/encoded checks and owned cleanup. Each final export checked 91
forward picture samples with reverse-seek evidence. Final CLI attempts took
63.72 and 60.95 seconds; earlier failed attempts and original picture-render
costs remain reported separately. SDK/source cache keys and source pixels stay
intact. This does not qualify general cold-cache session rotation or a speed
improvement across arbitrary sources.

The new native audio profile uses the shared immutable DSP settings adapter:
−2.5 dBTP internal headroom, six bounded dry runs and 320k AAC. Default long-form
settings remain −2.0/two/256k. The actual native delivery measured −14.33 LUFS
and −2.09 dBTP without changing signal or delivery gates. Its matching restricted
version reuses the exact mastered WAV and AAC with zero additional audio encodes.
Picture reuse similarly skips only completed work and reruns current final QC.

The live sampler now reads public macOS physical-footprint and host VM counters
directly, retaining the shared process-identity reconciliation, retry budget,
resource limits and owner cleanup. The separate per-process compressed-byte
diagnostic is explicitly uncollected/null; historical `top` receipts remain
readable with their measured numeric values. Host compressor bytes remain
required. Permission errors and malformed evidence stop immediately.

On a stable owned fixture, median helper collection took 23.37 ms versus
1.789 seconds for `top`. This is a sampler-only comparison. Matching installed
Apple source and ABI checks establish the counter formulas; failed comparisons
that tried to bound a fluctuating host reading between two endpoint samples
remain in the evidence. They are not relabeled as passes.

The subsequent `audio-regressions-02` workload passed all eight actual codec
tests in 12.62 CLI seconds. `official-identities-05` passed native, encoded,
audio and cleanup checks in 52.56 CLI seconds with 2.963 GiB observed owned
peak. A real identity turnover recovered within the original budget. Its output
is byte-identical to the reviewed official-brand export and reused both picture
and AAC with zero additional encodes. The earlier interrupted regression remains
failed. Different stage reuse prevents attributing the export-time difference
solely to the sampler; these workloads do not establish general reliability.

The [implementation receipt](SHORTS_ORGANIC_IMPLEMENTATION_2026-09-12.md)
retains actual failures and the remaining finished-case matrix. Long-form timing,
mastering, source pinning and process ownership remain shared; Short-specific
identity selection, portrait framing and readability remain editorial work.

## September 13 supporting-media and guided reuse

Adding supporting media now reuses stable streaming copies, the same sandbox
admission/snapshot implementation and existing transcript source-authority checks.
The additive mode preserves exact verified speech bytes instead of retranscribing
an unchanged recording. It also retains original external paths and all previous
admitted supporting assets, so changing the scan folder does not change the cut.
The 31 focused Python regressions and intake/stream checks establish those local
contracts. Three actual admission/rescan cases also pass in 11.137s worker time
(58.967s complete supervised owner including exact cleanup), recorded in the
[integration receipt](SUPPORTING_MEDIA_AND_GUIDED_BUILD_2026-09-13.md).
No measured end-to-end speed improvement is claimed from avoided ASR alone.

V10 reuses strategy v3 asset-use/source policy, canonical proposal reconstruction,
caption grouping, the shared native project writer and cold reader. It adds a
supplied-raster scene-to-decision mapping and persistent guided binding rather
than another media executor. V9 semantics and long-form admission remain intact.
A finished service-backed guided example is still needed for route qualification.

Five subsequent real HTTP tests exercise the same stable-copy, decoder admission,
transcript reuse and publication path through Next and standalone Python children.
The four-case PNG/control suite passed in 11.120s (49.854s complete owner); the
MP4/MOV/JPEG/WebP case passed in 4.946s (28.404s complete owner). Both retained
local-only provider policy and verified exact process/container cleanup. These
are tiny fixture timings, not whole-Short production timing or a measured ASR
speedup. The harness reuses the existing NativeRun owner and reviewed server
connection checks; it does not add a second production media executor.

The format run also exposed a consequence of the faster memory sampler: four
immediate retries could be spent within a 0.545s process-start burst. Shared
monitor retries now wait 0.1/0.2/0.4 seconds within the existing four-sample,
18-second/original-run budget. All 87 monitoring checks pass; the format rerun
recovered a real turnover sample after a measured 0.110s wait. Resource caps,
complete readings and identity checks remain unchanged. The earlier failed
attempt remains in the receipt; one rerun is not a universal reliability claim.
