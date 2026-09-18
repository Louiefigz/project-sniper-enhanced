# Performance qualification and testing

> **Status:** Targets and falsification gates, not current performance claims.
> The exact P7/P8 evidence disposition is in the
> [qualification audit](19_P7_P8_QUALIFICATION_AUDIT.md).
>
> [Previous: roadmap](07_IMPLEMENTATION_ROADMAP.md) ·
> [Back to the plan index](../COMMAND_DRIVEN_EDITING_EXECUTION_PLAN.md) ·
> [Next: implementation map and immediate work](09_IMPLEMENTATION_MAP_AND_NEXT_STEPS.md)

## `LF-14-A` workload boundary

The 90-minute number is an unproven engineering hypothesis. Its first bounded
qualification class is:

- 12–14-minute 1080p output at one frozen supported rational FPS;
- at most 30 aggregate raw minutes and two camera/screen sources;
- local SSD, frozen H.264/H.265 files up to 4K, 48 kHz audio;
- cold transcript cache with pinned provider/model/runtime;
- at most 2,500 kept words, 20 scene/render units, 20 b-roll assets, one
  destination profile, one Palmier editable build and exact master;
- exactly one `C2-A` project scene: at most two cards/eight exposed elements,
  12 seconds, 2D CSS/SVG/canvas, seeded particles, local approved assets, no
  tracking/rotoscope/3D;
- remaining scenes catalog or parametric;
- approved reference pack and approved local assets when used;
- Palmier already open on the exact expected project/timeline when selected.

New reference study, remote download, asset acquisition/approval, multiple
platform exports, advanced tracking/rotoscoping, operator wait, and later
repair rounds have separate clocks.

The initial-build clock:

- starts when the frozen request is durably accepted;
- ends only when the approved Sniper master, selected destination artifacts,
  complete QC/receipts, and selected fully-read-back Palmier editable/exact
  timelines are durable and ready for review.

A preview or pending import is not terminal.

## Baseline before optimization

Immediately after the current-system reader/writer inventory, run the shipped
full path on frozen short and `LF-14-A`-shaped long fixtures. Capture cold and
warm:

- per-stage wall/CPU time and critical path;
- memory, disk bytes/inodes, browser/ffmpeg process concurrency;
- cache keys, hits, misses, invalidations, and full-duration passes;
- model/provider calls, retries, recovery, and operator-wait state;
- decoded frame/sample counts, outputs, and complete QC result.

This baseline identifies the actual bottleneck and creates the comparator. It
does not prove the target architecture, creative completeness, or a 90-minute
SLA.

`scripts/producer/baseline_trace.py` now captures the exact two-run command,
host, wall/CPU/max-RSS observations, emitted stage/cache events, and output
hashes. The named short and LF-14 manifests under
`scripts/producer/tests/fixtures/` are deliberately classified
`synthetic-harness-validation`: they prove the harness and 20-clause
durability workload shape, not current full-path media performance. Only a
fixture explicitly classified `current-full-path-baseline`, with real stage and
cache evidence, can fill the machine inventory's baseline evidence paths.

The frozen 45-second short now has retained current-full-path evidence. Its cold
run completed in `45,407 ms`; the immediate warm run completed in `30,175 ms`,
saving `15,232 ms` (`33.545489%`). Both decoded to exactly 1,350 frames and
2,159,616 samples per channel with exact normalized PCM and complete passing
QC. The independently repeated full-frame oracle measured `0.997547469` mean
SSIM and `0.992165` minimum. Warm reuse removed `cut_speed` (`7,035 ms`),
`reframe` (`6,576 ms`), and `audio_enhance` (`1,171 ms`), but still reran
audit (`11,475 ms`), master (`10,627 ms`), and composite (`6,144 ms`).
This is a truthful current short baseline, not proof of surgical
fragment rendering or the LF-14 SLA.

The retained LF-14 current-full-path fixture is 20,139 frames at
`24000/1001`, or exactly `839.964125` seconds. Its cold run completed in
`566,941 ms`; the immediate warm run completed in `443,057 ms`, saving
`123,884 ms` (`21.851304%`). Warm reuse removed `cut_speed` (`119,722 ms`) and
`audio_enhance` (`13,587 ms`), but it still reran master (`173,612 ms`), audit
(`153,489 ms`), composite (`93,086 ms`), and proxy (`19,011 ms`).

Both runs decoded exactly 20,139 1920x1080 CFR frames and 40,318,976 stereo
48 kHz samples per channel with identical normalized PCM. QC reported 24
passes, two warnings, and zero failures; the warnings were 51 legitimate
screen/slide holds (longest 51.89 seconds) and one source flash at 167.75
seconds. A second independent full-frame run reproduced the retained oracle
receipt byte-for-byte: `0.997635465` mean SSIM, `0.986361` minimum at frame
1,578, exact decoded audio, and exact stream facts. The outputs are
codec-floor equivalent, not byte- or pixel-identical.

This closes the current short/LF-14 comparator gate and the former
25-microsecond timeline truncation (`839.964100` versus exact `839.964125`).
It does not qualify dirty-fragment equivalence, creator-footage coverage,
directional pilot, untouched confirmation, or the 90-minute SLA.

## Provisional allocation hypothesis

The table below is a top-down, falsifiable allocation fitted to the desired
90-minute endpoint. It is not a measured estimate, staffing model, or capacity
plan. Replace or rebalance it after baseline traces; only the frozen end-to-end
gate is authoritative.

| Stage | Hypothesis |
|---|---:|
| Ingest/probe/transcript | 10m |
| Cut authoring, two system reviews, selected-surface draft | 15m |
| Treatment planning, scene authoring, gates | 25m |
| Parallel scene/caption render + optional Palmier mutation | 10m |
| Complete final render/export + QC | 25m |
| Bounded recovery/retry buffer | 5m |
| **Total** | **90m** |

System retries and system-caused clarification stay on the active clock.

Cut-first reports active system time and `WAITING_FOR_OPERATOR` separately. It
does not receive an unattended wall-clock claim.

## Incremental targets

- cached scene/card repair visible in Palmier: at most 60 seconds;
- cold render of an existing scene: at most 120 seconds;
- eligible local preview: at most 2 minutes;
- eligible repair endpoint: at most 35% of forced-full control time.

Scene classes:

- `C0`: catalog configuration;
- `C1`: closed parametric grammar;
- `C2`: new project-scoped code;
- `C3`: advanced/unsupported work.

Generic C2/C3 receive no SLA. `C2-A` is the only initial bounded C2 subclass
and gets the `LF-14-A` gate only after pilot and confirmation pass.

Local targets are lane-specific. A broad optimization claim must include a
prospective organic-request census, eligibility rate, fallback jobs and
latency, portfolio latency, and operator intervention. Cases cannot be removed
after outcomes are known.

Current retained 40.4-second Palmier card replacement and fast cached
graphics/audio are mechanism evidence, not a long-form SLA.

Do not advertise:

- “fully optimized”;
- arbitrary After Effects parity;
- exact understanding/replication of any video;
- under-90-minute long-form;
- fully native Palmier editability;
- network-independent determinism;
- p95/95% reliability;

until the matching gate passes.

## Golden scenarios

1. Twenty mixed instructions with durable coverage across cut/treatment and one
   final disposition each.
2. Cut-only draft first; no treatment before approval.
3. Restore stepped-on word with no duration/unrelated drift.
4. Reject the repair when non-ripple is impossible and show ripple impact.
5. Build the two-card fire/sparkles scene offline.
6. Change right copy only; rerender one unit and optionally replace one Palmier
   clip.
7. Enable karaoke for one phrase without changing other caption groups.
8. Move one scene without rerendering its media.
9. Prove graphic-over-b-roll z-order, captions, audio continuity, and
   invalidation.
10. Apply one verified pack to short and long with independent format policy.
11. Make a manual Palmier edit and prove stale AI cannot overwrite it.
12. Run one final complete export/QC after accumulated revisions.
13. Export one short to TikTok, Reels, and Shorts with separately proved
    destination geometry.
14. Repair one word in an editable build and change only the owning
    dialogue/mix closure without doubled master audio.
15. Reject an expired/unlicensed asset while keeping the approved generation.
16. Change segment speed while preserving its stable ID and prove all affected
    content-relative/caption-placement nodes invalidate.
17. Assemble multiple AAC segments and prove container padding does not
    accumulate or change authoritative frame/sample duration.
18. Render same-aspect/different-pixel own-screen graphics and footage-exposed
    text; fail incorrect geometry or missing contrast/backing evidence.
19. At every released rational FPS, partition adjacent picture windows with
    `B(frame)`, prove zero PCM gap/overlap, and verify canonical speed retiming.

## Fault injection

Kill/fail after:

- intent persistence;
- target resolution;
- candidate plan write;
- scene render;
- scene output before proof;
- proof before cache promotion;
- dirty composite;
- Palmier import before placement;
- placement before receipt;
- Palmier activation before local `ACTIVE_HEAD` CAS;
- Palmier activation request before durable activation readback, observing
  expected parent, exact reserved candidate, and foreign/partial head;
- local `ACTIVE_HEAD` CAS before `COMMITTED`;
- paged readback;
- final render before Audit B;
- QC before promotion;
- exact-master mirror/export.

Also test:

- stale parent;
- duplicate idempotency key with same/different request;
- concurrent batches;
- cancellation and late completion;
- power loss/write reordering at each intent/receipt/rename/head boundary;
- source mutation during snapshot and decode;
- tool/runtime change;
- deliberately missing dependency edge;
- deliberately remove channel-normalization dependency from a mix node;
- retain caption word/content digest while changing its timeline-map slice;
- retain a segment ID while changing speed/version;
- stale/missing/unmeasured/error comp capability;
- AAC encoder padding and misleading container duration;
- iterative frame/sample rounding or a noncanonical speed rational;
- independently rounded adjacent 44.1→48 kHz source intervals;
- corrupt/symlinked cache;
- disk/inode exhaustion;
- browser/ffmpeg OOM/hang;
- Palmier close/crash/wrong project/manual drift;
- unreadable Palmier field/effect;
- editable stems and mastered reference both enabled;
- reference re-study interruption;
- network unavailable;
- generated comp attempting a forbidden operation.

No partial, stale, mixed-generation, or unapproved output may replace the
approved head.

Saga recovery first exercises all observed Palmier heads: expected parent
performs one re-proved CAS, exact reserved child seals activation readback
idempotently, and any foreign/partial state reconciles. Only then does it
exercise local heads: expected parent finishes the reserved CAS, exact reserved
child seals `COMMITTED` idempotently, and every other head enters
`RECONCILIATION_REQUIRED`.

## Measurement rules

Freeze:

- raw files and aggregate source duration;
- locality, codec, geometry, and timebase;
- transcription provider/model/cache state;
- output profile;
- scene counts/complexity;
- reference-pack and asset state;
- Palmier readiness;
- hardware, model/build, prompts, runtime, fonts, browser, and rate policy.

Use separate comparators:

1. capability acceptance where no old control exists;
2. identical approved plan for renderer speed;
3. identical parent/edit for incremental versus forced-full.

Report all results, median, maximum, retries, failures, active-system time, and
operator wait. Do not compare different creative outputs and call the latency
difference optimization.
