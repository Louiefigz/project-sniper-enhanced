# QC cost follows the number of sessions as well as duration

The 43-second audience-to-business Short from IMG_7138 uses six retained 4K
passages and one real-page insert. Its admitted source-pixel budget selects
four captures per native session. This is the existing conservative memory
plan, not a reason to enlarge a browser session.

The exact point planner requests 1,278 QC occurrences: 721 render-observed
forward checks and 557 reverse/terminal checks. Every reverse session also
captures the final frame as a seed, leaving three checked points per session.
That requires 186 fresh sessions. The old single QC child exceeded its 180-second
limit even when its completed picture and qualified audio were reused.

## Partition work without reducing evidence

The new phase coordinator groups at most 48 whole existing sessions into one
child invocation. It imports the existing point planner, native capture
context, retained-forward verifier, typography and visual-state primitives.
The Python worker invokes these children sequentially under the same outer
NativeRun. Child 180-second and outer 600-second deadlines remain unchanged,
as do the 4 GiB owned-tree, 3 GiB process and single-worker bounds.

The first phase freezes the complete schedule and source/runtime/checker
identity. Each capture phase independently revalidates the forward baseline,
then records its exact reverse occurrences and successful disposals. The parent
keeps the digest returned by each live child; a later edited receipt cannot
replace that digest. Final aggregation rejects missing, duplicated, reordered,
changed or incomplete evidence before exposing the standard native-frames
receipt. The existing reverse-pixel, encoded-picture and full A/V checks then
run unchanged.

Partial output from the failed single-child attempt is retained for diagnosis
only. A collection of JPEGs cannot prove that the subsequent state, typography
and cleanup checks completed.

## When this is not enough

Phases do not extend the overall deadline or support parallel browsers. A
render plus all checks can still exceed the existing 600-second owner budget.
The existing verified picture/audio reuse paths may finish a later verification
attempt without re-encoding. They still require unchanged inputs and completed
supervised cleanup. Changing a pinned picture implementation or authored
project is not grounds to relabel an old donor as current.

The streaming path is unchanged. Valid batch projects without retained forward
evidence, or with capacity for only one capture per session, retain the original
full replay. Present but malformed forward evidence still fails. Repeated source
cache admission binds stable source and cache identities, while preserving its
changing observation timestamps and SDK timings outside that identity.

## Verification

The final phase and compiler-cache changes pass 92 related JavaScript tests
and 20 Python runtime/phase tests. These cover the exact capture/seed sequence, sequential
ordering, bounded counts, schedule and receipt tampering, changed source/image
bytes, interrupted children, legacy full replay, and repeated cache admission.
ESLint reports zero warnings. Final run results are recorded separately from
unit tests.

The real six-cut v7 attempt completed its first 48-session phase in 107.60 seconds
before host compressor growth stopped the second phase. Owned memory at the stop
was 0.644 GiB, below the unchanged 4 GiB cap. A second attempt stopped on the same
host guard during preparation. Both verified owned cleanup; neither is a passing
whole-export receipt. Final completion remains pending available host capacity.

## Compile once inside the same verified run

Measured v7 preparation took 36.85 seconds and its actual fresh-session captures
took 70.66 seconds. Forward-image copies took less than half a second. A locally
supervised child-process trace then identified the remaining delay: the SDK
launches advisory keyframe scans for local video elements during compilation.
Repeated cuts of the same 32-minute 4K source queued two scans that each timed
out after 30 seconds. The plan returned at 36.920 seconds, but Node naturally
exited at 60.537 seconds. The 66.500-second diagnostic completed cleanup and
peaked at 0.324 GiB of owned memory. It was not a whole-export qualification.

The eligible phase route now preserves one actual compiler result, its mutated
render configuration and its complete output file tree in the current run.
Node's V8 serialization preserves Maps, shared references and undefined values;
a checked round trip precedes publication. The parent holds hashes of the JSON
receipt, binary payload and every compiled file. Every later phase verifies the
source and project dependencies, compiler configuration, and exact compiled
inventory before and after capture. Missing, changed or extra dependencies fail;
they do not trigger unchecked fallback or a replacement compiler result.

This removes repeated compilation, not source-frame admission or visual checks.
It does not patch the SDK, simulate probe output, force Node to exit, enlarge a
session, or change any resource or deadline policy. Valid legacy and one-frame
cases still use their existing full replay. No listening approval follows from
these technical checks.


After the compiler optimization and independent review, the v9 export attempt
was stopped by host compressor growth after 23.246 seconds, before the compiler
phase began. The export owned 0.138 GiB at the stop and cleanup was verified.
This does not establish the real export runtime of the new compiler cache.
That performance validation remains pending available host capacity.


## Production follow-up: a shorter edit can cost more to verify

The separate IMG_7138 journey batch on 2026-09-15 produced these completed,
supervised review exports using the existing phase coordinator:

| Edit | Duration | Compiled 4K views | Frames per capture session | QC phases | Final verification attempt |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pricing | 39.24s | 6 | 8 | 1 | 304.58s |
| Editor download | 24.28s | 7 | 4 | 3 | 396.02s |

Both rows reused a completed picture/audio stage after an earlier combined run
hit the unchanged 600-second owner deadline. The final-attempt column therefore
measures the reuse-and-verification attempt, not the entire edit or the initial
picture render. All earlier attempts remain in the batch's EDIT-TIMING.json.
Both completed runs passed native state/seek checks, encoded-picture comparisons,
full audio/video decoding and owned cleanup. Subjective listening remains separate.

The planning threshold explains part of the difference. Each 3840×2160 RGBA
view contributes 33,177,600 bytes. Under the 1,536 MiB planning budget, six views
fit eight frames; seven views select the next supported preset, four frames.
This estimate counts admitted video elements across the composition. It is not
an observation that seven full frames are simultaneously live in memory.

Use this when estimating production cost: retained duration, number of source
cuts/visual views and the resulting QC schedule all matter. Do not remove a
useful trim to game the count, or enlarge browser sessions based only on this
comparison. Further performance work needs to preserve source admission and the
complete existing forward, reverse, terminal and encoded evidence.

Evidence: `artifacts/img7138-journey-shorts-2026-09-15/`, pricing exports v4/v5
and editor-download exports v1/v2; their `batched-picture.json`, QC schedules,
`checks.json`, and `pipeline.render.json` records.

### Audio corrections can also repeat picture work

The 32.04-second Outreach edit completed its first picture stage in 382.52
seconds, then failed encoded audio quality after 11.89 seconds of dialogue
finishing. The failed check identified a stable 181 Hz tone: 17.2 dB prominence
at -40.6 dBFS. Timing, loudness, peaks, channel balance and section consistency
all passed. This was an audio-quality failure, not an exhausted-RAM failure.

Changing that project's cleanup from `voice` to the installed `voice-rnn`
separator produced passing encoded audio checks on the next attempt. The
strongest remaining tone measured 11.9 dB prominence at -42.5 dBFS. These
measurements establish the technical check result, not listening approval.
The picture HTML digest stayed identical, but the existing donor contract
binds the whole authored manifest, including audio settings. Consequently the
new authored project required another picture pass.

For future performance work, qualifying the assembled audio before expensive
picture capture is a concrete candidate for avoiding this waste. A separate
picture-only dependency contract would require its own design and validation.
Do not edit old manifests or receipts to make an incompatible donor appear
eligible, and do not weaken the hum check merely to preserve a completed render.
An audio-first check would also not replace final encoded audio/video checks.

Evidence: Outreach exports v1/v2 in the same batch, `stage_timings.jsonl`,
`audio/receipt.json`, and the v2/v3 authored project manifests. Subsequent full
export qualification is recorded independently in the batch timing report.
