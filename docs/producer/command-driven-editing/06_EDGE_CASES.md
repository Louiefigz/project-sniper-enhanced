# Edge-case and recovery matrix

> **Status:** Proposed release requirements. These are fail-closed unless a row
> explicitly defines a safe fallback.
>
> [Previous: render, Palmier, and QC](05_RENDER_PALMIER_AND_QC.md) ·
> [Back to the plan index](../COMMAND_DRIVEN_EDITING_EXECUTION_PLAN.md) ·
> [Next: implementation roadmap](07_IMPLEMENTATION_ROADMAP.md)

## Commands and authority

| Case | Required behavior |
|---|---|
| Phrase appears multiple times | Use occurrence, speaker, approximate time, and context; otherwise ambiguous |
| “Here” has no marker/selection | Ask for a marker; never guess |
| Note came from an old proxy | Resolve against its parent or reject and show remapped point |
| One brief mixes cuts and treatment | Persist one request; commit cut first, then resolve deferred treatment against the child |
| P1 compatibility lock enters P2 | Require selected-policy approval of the exact cut, mint `PictureLockV1`, and migrate/revalidate clauses; never reinterpret compatibility as approval |
| Non-ripple repair creates child lock | Emit old→child supersession receipt; supersede and recompile/revalidate treatment bound to old lock |
| Crash during repair review/promotion | Resume the exact content-addressed package and independent phase idempotency key; block every unrelated writer while an intent is unfinished or `CUT_REVIEW` is selected |
| Another repair package owns pending phase state | Reject before materializing or advancing anything; recovery keys must match every unfinished review/promotion intent |
| Completed repair package is replayed after a newer revision | Reject as stale before compatibility-plan publication; historical transition receipts remain readable but cannot overwrite the selected plan |
| Repair action reaches `CUT_REVIEW` | Keep its parent lock/timeline hashes bound to the original `PICTURE_LOCKED` parent; the separate promotion action and child lock bind the review revision |
| Execute request lacks full QC/operator package | Reject before review CAS; never infer audition approval from the original damage report |
| Two operations change one property | Normalize or reject before mutation |
| Delete then update same element | Reject or require explicit dependency/order |
| Batch targets a newly created element | Controller resolves a temporary in-batch alias |
| Supported and unsupported clauses mix | Atomic stage blocks; receipt identifies every blocker |
| Unknown action/field/target | Closed schema rejects it; no broad writer fallback |
| Concurrent UI/agent/Palmier edit | Expected-parent/version/hash CAS fails |
| Retry after timeout | Idempotency returns original attempt; no duplicate |
| Cancellation/restart | Generation fence prevents late promotion |
| Ask Editor request names another workspace or nonlocal origin | Reject before reading authority, invoking a model, acquiring Palmier state, or mutating |
| Palmier writer starts during Ask Editor finalization | Shared mutation lease serializes it; Ask Editor rechecks Palmier authority before promotion and around sidecars |
| Local candidate succeeds, Palmier fails | Keep old head; quarantine/reconcile candidate |
| Crash after durable proved Palmier activation readback | Finish reserved local CAS or block in `RECONCILIATION_REQUIRED` |
| Recovery sees Palmier expected parent | Re-prove candidate/intent, CAS once to reserved candidate, and persist full readback before local advance |
| Recovery sees exact reserved Palmier candidate | Verify hash/readback and persist `PALMIER_ACTIVE` idempotently |
| Recovery sees another/unreadable/partial Palmier head | Persist `RECONCILIATION_REQUIRED`; local head cannot advance |
| Crash after local head CAS, before `COMMITTED` | If head equals exact reserved child, verify it and mark committed idempotently; any other head reconciles |
| Sidecar writer publishes bytes and then throws | Restore exact prior cut/template/refit bytes, or remove the newly created file, while continuing every other recovery action |
| One rollback action fails | Continue all independent rollback/release actions, persist reconciliation evidence, and report the aggregate failure |
| Palmier not selected | Zero Palmier discovery/read/import/mutation/export |

## Cut, timing, and speech repair

| Case | Required behavior |
|---|---|
| Word-safe boundary clips a plosive | Waveform/VAD/alignment plus audition; operator report is ground truth |
| Word straddles segments | Repair both only when exact ownership/dependencies are proved |
| No adjacent source handle | `NON_RIPPLE_IMPOSSIBLE` or exact ripple proposal |
| First/last source edge | No fabricated handle; block or use authorized take |
| No removable silence | Do not steal speech |
| Multiple/interleaved sources | Require owning source/segment and explicit anchor |
| Speed-adjusted segment | Solve in source samples/delivery frames; verify stretch/sync |
| Stable segment ID but speed changed | Increment version/hash and re-resolve every affected content-relative dependent |
| Overlapping speakers | Do not extend crosstalk blindly |
| Multi-camera seam | Preserve camera/sync; audio-only repair may be safer |
| VFR/fractional FPS | Normalize once; rational FPS and half-open frame/sample ranges |
| Frame/sample conversion is fractional | Use exact integer rational math and declared floor/ceil policy; never accumulate rounded deltas |
| ASR absorbs dead air | Inspect waveform/VAD, not nominal word span only |
| Repair duplicates neighbor | Alignment/re-transcription rejects zero/multiple occurrences; audition uncertainty |
| L/J cut breaks lip sync | Bound to covered picture or use picture repair |
| Quantized picture repair clips a word | Use bounded audio-only overlap/room tone or return `NON_RIPPLE_IMPOSSIBLE`; never steal speech/onset |
| Authorized ripple | Show every moved/dropped dependent first |
| Semantic beat removed | Explicitly remove/rehome dependents |
| Output-locked element after ripple | Keep frame unless operator changes it |
| Word/segment/beat split/merge/remove | Apply unique supersession map or tombstone/stop |
| Equal-duration semantic change | Recompute claim/chapter/beat/scene/b-roll/reference closure |
| Alternate take | Same meaning/source provenance plus explicit selection; no voice clone |

## Captions

| Case | Required behavior |
|---|---|
| Tiny scene overlap hits long cue | Split/suppress overlapping words only |
| One-to-many display correction | Bind source IDs to display tokens with deterministic timing |
| Repeated homophone/name | Stable IDs/context; no global replacement |
| Punctuation-only correction | Preserve timing/audio identity |
| Word crosses cut/speed change | Recompile affected group |
| Same caption words, changed timing map | Rebuild cue/placement fingerprint; content texture may be reused only if its own digest matches |
| Very fast speech | Enforce readability or disclose/group |
| Multiple speakers | Speaker-aware groups/styles and collision handling |
| RTL/CJK/emoji/URL | Local glyph closure, shaping-aware measurement, safe wrapping |
| Profanity | Separate display and audio policies |
| Fractional FPS | Test first/last visible frames on project clock |
| Palmier native timing is lossy | Use regenerable alpha clips |
| SRT and burned output diverge | Fail shared cue compiler |

## Motion and reframe

| Case | Required behavior |
|---|---|
| Equal-time layers | Explicit z-order |
| Zero/subframe duration | Reject after frame quantization |
| Scene/comp duration mismatch | Root duration and proof match exact frames |
| Declared and measured comp capability disagree | Measured/proved canvas/aspect/fade/bbox/render result wins |
| Capability missing/stale/unmeasured/renderError | Block the comp; do not trust manifest declaration |
| Same aspect, different delivery pixels | Scale to exact delivery canvas and prove bounding box |
| Mixed FPS | Render at target supported rational FPS |
| Text/font/unicode overflow | Real-copy shaping/layout proof with local fonts |
| Wrong alpha/premultiplication | RGBA and opacity-class proof |
| Exit extends past clip | Finish inside duration and prove terminal state |
| Fire/particles | Seeded PRNG and complete decoded-frame determinism |
| Async race/infinite loop | Static lint, randomized seek test, hard resource/time limits |
| Remote URL/import/eval | Deny unless reviewed local capability permits it |
| Traversal/symlink | Canonical allowlisted no-follow paths |
| Secret/UI-origin access | No secrets/env, isolated origin/CSP, networkless sandbox |
| Browser abuse | Admission budget, PID/process cap, timeout, kill/reap |
| Subject/caption/b-roll collision | Occupancy gate over sampled subject positions |
| Presenter-hole geometry changes | Invalidate scene and presenter/recompose closure |
| HDR/color mismatch | Declared pipeline and seam comparison |
| Static checks pass but blank | Pixel/alpha occupancy fails |
| Text readable on synthetic background only | Test actual footage interval; require contrast/backing evidence |
| Shared mask/interaction | Rerender disclosed group/scene |
| Unit differs from full-scene oracle | Disable unit granularity |
| One-frame nondeterminism | Fail; sampled hashes cannot waive |
| No/multiple/occluded face | Continuous tracking remains unsupported or uses explicit manual override |
| Unsupported AE/3D/rotoscope | Prepared asset, approved approximation, or `unsupported` |

## Reference study

| Case | Required behavior |
|---|---|
| Private/deleted/login/geo/rate-limited | Acquisition failure; allow operator local file |
| Corrupt/truncated/missing-audio | Fail completeness or visible noncritical waiver |
| Same filename, changed bytes | New source hash/generation |
| Aspect/language/content mismatch | Show transfer limits; do not silently change target |
| Burned captions/watermarks | Classify mechanics without copying identity |
| Construction cannot be inferred | Mark mechanism unobservable; reproduce supported outcome |
| References conflict | Require priority/merge policy and provenance |
| Re-study interrupted | Approved pack remains; candidate unpromoted |
| V1 during V2 rollout | Use V1 reader or separate V2 candidate |
| Reviewer disagreement | Block verified mimic |
| Critical mechanic unsupported | Downgrade to inspired/partial; no critical waiver |
| Prompt injection in media | Treat pixels/text as untrusted evidence |
| Rights unclear/expired | Block asset use |

## Audio

| Case | Required behavior |
|---|---|
| No/corrupt audio | Visual-only classification or block speech edits |
| Mono/multichannel/dead channel | Normalize declared channel policy |
| Program mix reads raw dialogue before channel repair | DAG validation fails; every program-mixing node that consumes source dialogue/audio depends on its normalized stem |
| Sample-rate mismatch/drift | Convert to project sample clock and prove sync |
| Adjacent 44.1→48 kHz source ranges | Use one absolute `P(sourceSample)` boundary; no independent interval rounding |
| Loop seam | Crossfade/alternate asset |
| Fade too long | Reject by default; clamp only with typed policy and receipt |
| Quiet/clipped/high-crest dialogue | Eligible mastering path; preserve declared LRA |
| Duck pumping/unmeasurable gap | Revise/fail rather than claim measurement |
| License/attribution expired | Block publication |
| Room tone changes in repair | Patch/crossfade or block |
| Final mastering changes global PCM | Compare exact pre-master stems and final tolerance separately |
| Editable stems + master both audible | Export gate fails |
| Container/AAC decoder reports longer duration | Ignore it as authority; use compiled delivery frames and pre-AAC PCM samples, then prove padding does not accumulate |

## Render, cache, durability, and crash recovery

| Case | Required behavior |
|---|---|
| Disk/inode preflight fails | Do not start expensive work |
| Browser/ffmpeg hangs/OOM | Kill process group; bounded transient retry |
| Corrupt/symlinked cache | Re-prove or quarantine |
| Crash after output, before proof | Output stays private/untrusted |
| Crash after receipt, before promotion | Resume exact attempt only |
| Power loss/write reordering | Recover from fsynced intent; head pointer written/fsynced last |
| Source changes mid-run | Snapshot/hash mismatch invalidates |
| Source changes between hash/decode | Render only immutable snapshot |
| Two workers build same node | Single-flight or verified CAS winner |
| Stale PID/PID reuse | Kernel-held locks/process identity |
| New-format shared mutation lease has a dead durable process identity and its lock/recovery/nonce owner are the same inode | Reap that exact hard-linked owner automatically, fsync the directory, and retry acquisition |
| Shared mutation lease is legacy/malformed, lacks a supported OS start identity, does not bind the expected owner inode, or already has an interrupted recovery claim | Fail closed with recovery-required; an operator verifies no writer/recoverer remains and quarantines only the named lock/claim |
| Canceled worker finishes late | Fence prevents publication |
| Remote dependency unavailable | Production closure is local; no network retry |
| Cache hides cold cost | Benchmark isolated cold/warm roots |
| Dirty preview misses global issue | Full final decode/QC remains mandatory |
| Temp/final on different filesystems | Same-filesystem staging for atomic rename |
| GC sees referenced generation | Reachability pins prevent deletion |
| Dependency edge missing | Required-invalidation proof fails |
| Saga observes expected parent | Re-prove reserved child/external state, CAS once, verify, then commit |
| Saga observes exact reserved child | Verify receipt/hash and mark committed idempotently |
| Saga observes any other head | Persist `RECONCILIATION_REQUIRED`; never blindly retry |

## Palmier

| Case | Required behavior |
|---|---|
| App closed/crashes | Pause safely; no mutation on another surface |
| Wrong project/timeline | Exact identity preflight fails |
| Operator edits during batch | CAS fails; preserve manual state |
| Offline media/locked track | Stop with exact binding |
| IDs changed | Resolve by stable media/clip identity immediately before mutation |
| Readback paged/truncated | Read every page before approval |
| Mutation applied before timeout | Reconcile exact state; never replay blindly |
| Replacement leaves duplicate | Remove only ledger-known old clip and re-verify |
| Manual edit changes baked scene | Branch authority; no reverse import |
| Adapter loses fidelity | Baked-regenerable/approximation label |
| Affected property unreadable | Keep mutation class disabled |
| Export wrong timeline | Bind exact project/timeline/candidate and decode result |
| Exact master visible with editable stack | Visibility/layout/audio gate fails |

## Assets and destinations

| Case | Required behavior |
|---|---|
| License expired/excludes platform | Block that destination |
| Required attribution missing | Block until verified |
| Generated face/logo lacks consent | Reject publication |
| MIME disagrees with bytes | Quarantine |
| Archive bomb/escaping symlink | Sandbox rejects |
| Malformed codec/huge dimensions/frame count/truncated stream/hang | Bounded sandbox rejects/kills |
| OCR/transcript/metadata contains instructions | Treat as untrusted data |
| TikTok/Reels/Shorts fan-out | Compile/prove each profile; hash-compatible reuse only |
| UI covers caption/card | Destination occupancy gate fails |
| Duration/codec/file limit exceeded | Explicit alternate deliverable or block |
| 16:9 short/vertical long | Honor independent axes where supported or reject clearly |

## Legacy traceability

The named regression fixtures for graphics geometry/contrast, measured comp
capability, audio ordering, authoritative duration, exact rational FPS, refit
order, ghost captions, prompt enums, and headless authority are in
[Legacy regression gates](10_LEGACY_REGRESSION_GATES.md). Phase exits must link
their evidence; this matrix alone is not proof that the behavior is wired.
