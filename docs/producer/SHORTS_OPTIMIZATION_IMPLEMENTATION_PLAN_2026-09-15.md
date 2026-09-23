# Short-form optimization implementation and verification plan

## Objective and non-negotiable output contract

Make ordinary approximately one-minute Shorts repeatable within a target of
30 minutes, including source/context decisions, real assets, karaoke and both
review surfaces. Implement the measured bottleneck fixes first, then measure
the execution path. A prepared recovery benchmark is not a complete creative
production benchmark.

Do not reduce resolution, frame rate, picture quality, source fidelity, audio
quality, caption coverage, inspection schedule or verification thresholds.
Preserve exact speech, cuts, colors, layouts, real-asset provenance and complete
viewer transformation. Keep source/context and independent visual reviews;
technical checks cannot grant listening or editorial approval.

## Implementation sequence and ownership

1. **Freeze baseline and define evidence.** Save the current dirty source state
   before changes, preserving unrelated work. Record current command settings,
   checks, timing fields and representative successful/failed receipts.
2. **Automatic compatible checkpoint recovery.** Seal every successful capture
   with the shared evidence contract. The standard exporter should select an
   admitted capture when resuming completed media and execute final QC only.
   Expose explicit attempt recovery, preserve failed directories and reject
   stale/tampered evidence. Retain the old supported recovery CLI through shared
   helpers rather than duplicate implementation. Owner: recovery agent.
3. **Bound verification storage and preflight predictable allocations.** Keep
   every frame comparison and full decode while processing selected RGB in
   bounded batches/streams. Check planned scratch plus the reserve before the
   relevant allocation, clean only owned scratch on failure and preserve
   reference evidence. Owner: storage/QC agent.
4. **Shared local and Studio preparation.** Replace dated artifact imports and
   fixed project/composition/fps assumptions with a manifest-driven adapter.
   Preserve immutable production files, editable pictures and exact final AAC
   packets. Share applicable preparation with native long form. Persist raw
   speech recognition independently from timestamp acceptance; do not turn bad
   timing into accepted karaoke alignment. Owner: review-handoff agent.
5. **Qualify audio before picture generation.** Move the existing exact audio
   finishing and technical qualification before expensive picture rendering;
   retain final encoded checks and all mastering parameters. Test that failure
   prevents picture work and success consumes the same qualified audio once.
   Owner: root.
6. **Timings and orchestration.** Reuse stage timing for early audio, render,
   capture, integrity preparation, checks and handoff. Make failed/reused stages
   visible. Provide a continuous production journal for editorial/search/review
   spans so future runs cannot hide uninstrumented time. Parallelize independent
   editorial/asset tasks, retain the shared heavy-work lane. Owner: root.
7. **Integrate, review, run representative evidence and update defaults.** Run
   focused tests, standards and independent semantic/security review of changed
   boundaries. Run bounded real-media tests through the existing supervised
   owners. Use exact equality for copied artifacts and decoded/reference
   equality for a changed execution mechanism. Document actual timings, what is
   automatic, and remaining benchmark limits. Owner: root with independent review.

The source baseline and execution evidence live under
`artifacts/shorts-optimization-2026-09-15/`. No existing delivered video is an
output target for these implementation tests.

## Reuse and invalidation rules

| Change/failure | Reusable work | Required work |
| --- | --- | --- |
| Final verification resource failure | Exact admitted media and successful capture | Final encoded checks and cleanup |
| Capture failure | Exact admitted media | Full required capture and final checks |
| Audio-only revision | Picture only if the existing picture-donor contract admits it | Qualified new audio, final mux and all affected final checks |
| Title/layout/caption revision | Valid source preparation and eligible qualified audio | New affected picture, capture and encoded verification |
| Source/cut/clock/runtime change | Only independently compatible inputs | Reject stale stage reuse; prepare/rebuild affected work |
| Reused/raw recognition with bad timing | Diagnostic recognized text | Timing remains failed/unapproved; independent alignment review required |
| Review surface failure with valid MP4 | Checked media | Repair/check the review surface, preserving the existing video |

No fallback may silently select another renderer, lower settings, skip a check,
ignore a failed integrity check or replace a missing real asset with a fabricated
claim. Unsafe or ambiguous recovery fails with the specific dependency/error.

## Target operating schedule for one approximately one-minute Short

These are planning allowances, not measured promises or permission to rush a
quality check. Start the clock with the first production work, including shared
source preparation and research; record queue and revision time too.

| Elapsed target | Work and exit requirement |
| --- | --- |
| 0–5 min | Read the source/context and instructions; select complete speech with a specific viewer takeaway. Reuse the admitted source transcript. |
| 0–8 min, parallel | An asset scout finds real proof/B-roll for the selected beats while the editor develops the cut. Reuse verified assets and check current claims when required. |
| 5–12 min | Lock cuts and karaoke timing; map scenes to existing components; prepare only selected media; inspect representative visual states and run early audio checks. A separate critic checks context, takeaway and real-asset choices. |
| 12–25 min | One owned render/capture/final-verification chain, keeping current quality settings and every required check. Independent work for another clip can continue outside the heavy-work lane. |
| 25–30 min | Check the finished Short and editable Studio playback, including audio, cuts, captions and ending/replay. Confirm the lesson and actual proof shown. |

The prior 46.28-second clean export took 9m21.7s including its automated checks;
the 13-minute media allowance is a working estimate for approximately one minute,
not a linear guarantee. Custom scenes, unavailable assets, cold caches or real
quality defects can exceed the budget. Record the cause and revised estimate;
keep the quality requirement. Never use the deadline to remove context, suppress
an audio failure or substitute invented proof.

For batches, perform source-wide review and common asset discovery once, then
freeze per-clip speech and asset decisions. Agents may scout, author independent
clips and review independently; they must not overwrite one another's packages.
Keep render, capture, audio analysis and other heavy media work under the shared
lease. More parallel encoders are not the proposed optimization. Measure both
each clip's elapsed wait and the batch's wall clock, counting overlapping work
once in the aggregate.

## Edge cases and acceptance tests

- Missing, altered, truncated or symlinked stage receipts, images or media;
  changed request/runtime/source/ordered frame schedule; wrong capture owner;
  incomplete cleanup; donor directory collisions and path traversal.
- A valid render with failed capture; valid capture with failed verification;
  render-only requests; legacy seals; repeated recovery into fresh directories;
  incompatible flags; changed dependencies after initial admission.
- Disk exactly at/above/below required scratch plus reserve; wide/portrait
  canvas; high frame rate; maximum supported duration; insufficient disk;
  failure/cancellation/truncated decode mid-chunk; source/output mutation;
  cleanup only of files owned by this attempt; no lost comparison at boundaries.
- Audio failure before picture, alternate approved mastering profile, audio
  donor, picture donor, no optional enhancement, selected sources versus legacy
  sources; unchanged picture command and final audio QC.
- Studio with multiple compositions, arbitrary names, non-25fps rational clocks,
  media wrappers and trimmed sources, missing media, unsafe paths, duplicate
  identities and output collisions; original project unchanged; copied AAC
  packets identical; both Short and compatible long-form plans.
- Recognition process failure versus timestamp-quality rejection; persist raw
  data once; no fake listening/synchronization approval; no unnecessary repeat
  recognition when valid raw text evidence already exists.
- Complete timing for success/failure/reuse without summing nested spans twice;
  nonmonotonic wall-clock inputs and missing/endless stages reported honestly.
- Cold/warm source caches and stale caches; existing cache compatibility remains
  enforced. Any broader content-addressed cache/hash optimization needs measured
  evidence and equivalent mutation detection before adoption.

## Quality and time qualification

1. Focused unit/regression tests for the changed contracts and adversarial cases.
2. Real selected-frame verification with identical comparison count/results,
   bounded scratch, complete decode and cleanup; forced final-stage recovery
   produces the identical MP4 with zero additional picture/audio encodes.
3. A supervised representative native export exercises early audio plus normal
   render/capture/check ordering; audio/picture failure fixtures prove early stop.
4. Shared review preparation exercises one Short and a supported long-form
   fixture with original-file snapshots and exact audio packet preservation.
   Live browser observations remain separate from HTTP/static success.
5. Record elapsed stage time, storage peak/estimated scratch, reuse and review
   limitations. The five-Short creative cohort from the audit is the acceptance
   benchmark for the 30-minute objective, not a reason to generate five more
   full videos solely to test a small implementation change.

## Progress

- Baseline: 186 existing files snapshotted before this turn's edits.
- Implementation: complete for the six scoped workstreams. Shared helpers are
  used where their contracts apply; no independent long-form export receipt
  adapter was invented. Existing source preparation/cache paths remain intact.
- Tests: **200 Python tests and 11 playback-controller tests pass**. Coverage
  includes stale/tampered recovery, early audio failures/donors, dimension and
  rational-clock boundaries, all 10,800 frames of a 180-second 60fps fixture,
  disk limits, partial decode/cancellation, package collisions, exact AAC copying,
  editable-state divergence, recognition reuse and overlapping/incomplete timing.
- Review: independent standards pass after fixes; independent audio/recovery
  semantic review found no actionable blockers. Root reviewed storage and review
  admission/ownership boundaries. No tests or source receipts were weakened.
- Real media: all **531 forward + 58 reverse** comparison results and the
  concatenated RGB hash match the previous 60.84-second outreach QC exactly.
  The final code's check took **12.40 seconds** and avoided **3,303,244,800 bytes**
  of RGB scratch. Only a 5,478-byte owned filter was needed and removed.
- Audio: the prepared 8.24-second float master is byte-identical to the previous
  master. A known 60.84-second hum defect fails in **12.45 seconds** before any
  picture render. Final encoded audio and AV checks remain in the normal path.
- Fresh pipeline test: an existing **8.24-second** fixture completed normal
  export/capture/all final checks in **47.34 seconds**. Automatic capture reuse
  completed a second verification in **7.65 seconds**, preserving the exact MP4
  with **zero additional encodes or captured frames**.
- Shared review: actual supervised packaging preserved exact MP4 and AAC packet
  bytes; its media owner took **2.25 seconds**. Actual managed Studio startup
  succeeded, and the user's original Studio project was restored on port 3991.
- Remaining live check: the Mac was locked, preventing interactive browser
  inspection. Browser playback, human listening and word synchronization remain
  unapproved. Server readiness and unit tests do not substitute for those checks.
- Remaining production benchmark: **30 minutes is still a target**, requiring
  a real creative cohort with source review, asset search, authoring and both
  reviews included. These prepared-fixture timings do not establish that SLA.

Machine-readable evidence: `artifacts/shorts-optimization-2026-09-15/VERIFICATION.json`.
See [the measured finding](../findings/SHORTS_OPTIMIZATION_PRESERVES_OUTPUT_AND_CHECKS.md).
Immutable owner receipts retain their tested code pins. After the real pipeline
test, one repeated dimension guard was extracted unchanged to satisfy DRY and
nesting limits; the final code then passed the 200-test suite and another real
531/58 comparison. Prior receipts were not rewritten to accept the later edit.

## Full production execution — September 16

The approved 60.84-second outreach Short completed a fresh production export in
**707.52 seconds (11m 47.52s)**, including preparation, render, reference capture
and all final checks. Its 109,933,144-byte MP4 is byte-identical to the previous
export. All 531 forward and 58 reverse comparisons and full audio/video decode
pass. The independent reviewer confirmed the file hashes and current frames.

The Mac was available for this run. Actual local and editable Studio previews
passed sampled framing, forward/backward seeking, completion and replay checks.
Studio's unmuted dialogue track played through all 60.84 seconds. Subjective
listening and exact word synchronization remain unapproved; no receipt was
rewritten to imply otherwise.

Source preparation took 13.03s without a picture encode. Review media packaging
took 12.34s without an additional encode. These owner durations exclude other
setup and operator work. The manual journal contains a wall/monotonic divergence
and the reporter correctly marks its complete window unavailable. This run
reused the approved creative work and does not establish the 30-minute creative
SLA. See the [full execution evidence](../../artifacts/shorts-optimization-execution-2026-09-16/EXECUTION-RESULT.md)
for the actual timing scope, initial stale-source admission failure and browser
observations.
