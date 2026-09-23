# Shorts production time: measured audit and a 30-minute target

Date: September 15, 2026, America/Chicago. This is an audit of existing records;
no new media job or production-code change was needed.

## Conclusion

The 65-minute single Short was not an efficient production baseline. The latest
three-Short batch also spent far too long on platform repair and manual assembly
of pipeline steps. A normal export and automated checks can finish in roughly
10 minutes on this machine. End-to-end production within 30 minutes per Short
is a reasonable engineering target for an existing source/transcript and known
style, but has not been demonstrated by these runs.

The primary improvement is to make the existing workflow repeatable. Faster
encoding alone would not recover the large amount of time outside media jobs.

## Scope and clock definitions

The detailed audit covers all three latest approved cuts: outreach, education
and common message. It also compares the original 65-minute editor Short and
the intervening title, pricing and DMs export records. Revisions are not counted
as additional unique finished videos. Earlier rejected candidate experiments
are outside this audit's aggregate; their history must not be added to a new
Short's normal production estimate.

- **Output duration:** finished video length, not production time.
- **Owner time:** recorded supervised media work, including admission, cleanup
  and failed attempts. It is not pure encoder time.
- **Export invocation:** preparation plus its nested render/capture/check jobs
  and command overhead. Never add this to its nested owners.
- **Observed delivery window:** earliest recorded batch source-review job to
  final live Studio evidence. It excludes any earlier planning/request time;
  it is a lower bound on total delivery time, not a complete request clock.
- **Outside recorded work:** the remainder after interval union, including
  editorial work, authoring, independent review, debugging, browser checks,
  coordination and unmeasured gaps. It is not all proven idle or removable.

The machine-readable [batch audit](../../artifacts/img7138-remaining-shorts-2026-09-15/TIME-AUDIT.json)
retains individual source records and interval-union calculations.

## Original 65-minute Short

Its explicit continuous clock ran from 11:06:53.992 to 12:12:04.745 UTC:

| Work | Measured time |
| --- | ---: |
| Successful picture, audio finishing and metadata | 6m43s |
| Other supervised media attempts and checks | 16m30s |
| Outside those media spans | 41m58s |
| Complete recorded delivery clock | **65m11s** |

The other media work mixes necessary checks and retries. The failed picture
attempt reached 1,376 of 1,406 frames before its timeout. Another attempt finished
picture/audio but timed out during reference capture. Those are pipeline failures,
not evidence that a 56-second Short requires an hour to render.

Sources: [continuous clock](../../artifacts/img7138-editor-visual-short-2026-09-15/EDIT-TIMING.json),
[timing analysis](../../artifacts/img7138-editor-visual-short-2026-09-15/TIMING-ANALYSIS.json),
and [original handoff](../producer/HANDOFF_ONE_SHORT_PLAYBACK_2026-09-15.md).

## Latest batch: three finished Shorts

| Short | Finished length | Successful picture encode | All export invocations | Export evidence |
| --- | ---: | ---: | ---: | --- |
| Outreach | 60.84s | 7m05.7s | 17m03.3s | Five invocations; separate audio/cache recovery adds time |
| Education | 46.28s | 5m22.6s | **9m21.7s** | First export and automated checks passed |
| Common message | 50.68s | 5m55.9s | 10m06.7s | Initial export plus final-check-only recovery |
| Total | **2m37.80s** | **18m24.2s** | **36m31.7s** | Three distinct finished videos; picture time is nested in export time |

The batch's first source-review owner began September 15 at22:57:26.613 UTC.
Final live Studio evidence is dated September16 at01:16:53.675 UTC. The observed
window is **2h19m27s** (17:57–20:16 Central on September15).

| Clock | Duration | Interpretation |
| --- | ---: | --- |
| All 34 supervised owners | 37m52s | No overlapping owner intervals; includes failures |
| Union of export invocations and all owners | 42m31s | Includes recorded preparation/command overhead without double counting |
| Outside that union, through Studio evidence | 1h36m56s | Editorial, authoring, repairs, review, browser work and uninstrumented gaps |
| Observed batch window | **2h19m27s** | A lower bound; earlier planning is not timed |

Nine owners ended unsuccessfully, totaling9m51s. That is not a wasted-time total:
outreach's failed audio attempt produced the successful picture reused later.
Likewise, later failures preserved valid capture work. Necessary recovery and
the engineering needed to build it occupy both job time and uninstrumented time.

Education is the strongest clean technical baseline: its9m22s export included
5m23s picture encoding, audio/media processing,2m13s native reference capture,
37s encoded verification, and preparation/overhead. It excludes script selection,
asset work, independent editorial review, Studio preparation and browser checks.

The outputs passed technical audio/decode checks and independent sampled visual
review. These records explicitly do not certify subjective listening or exact
phonetic karaoke synchronization. A production-time benchmark must include those
reviews rather than treating an automated technical pass as complete quality.

## Earlier related pieces: export commands only

These rows provide coverage beyond the latest batch. Their records do not expose
a comparable complete request-to-delivery clock, so no total production duration
is inferred from them.

| Piece/revision | Sum of recorded export/recovery commands | Clean final invocation | Reason for extra work |
| --- | ---: | ---: | --- |
| Editor POV title revision | 13m42.8s | Separate final verification86.7s | Resource interruption and verification integration |
| Original pricing system test | 14m32.2s | 12m47.7s | Memory admission and disk reserve failures |
| Pricing with real assets | 17m42.3s | 9m56.7s | Disk failure and source-frame clock repair |
| DMs/community,21.40s | 8m10.0s | 4m04.8s | First technically valid render failed visual review; opaque wrapper fixed |

Sources: respective `delivery.json` records under
`artifacts/img7138-editor-pov-title-2026-09-15`,
`artifacts/img7138-pricing-system-test-2026-09-15`,
`artifacts/img7138-pricing-real-first-2026-09-15`, and
`artifacts/img7138-dms-community-short-2026-09-15`.
The [DMs handoff](../../artifacts/img7138-dms-community-short-2026-09-15/HANDOFF.md)
and [pricing handoff](../../artifacts/img7138-pricing-real-first-2026-09-15/HANDOFF.md)
explain their exact revisions and review limits. New research, manual editing,
runtime repair and browser work are additional to the command sums above.

## Where time was avoidably spent

### 1. Product work became platform engineering

We repaired cache identity, process-exit observation, late-stage recovery and
Studio adapters while producing the requested videos. Fixing real defects was
useful, but this must be accounted for as engineering/rework, not described as
the unavoidable cost of high-quality short-form video.

The latest batch directory alone contains13 top-level Python/TypeScript helper
files totaling1,816 lines. This inventory is not a measure of writing time or a
claim that every line was newly written. It demonstrates how much routine timing,
audio, publishing and Studio behavior still depends on project-local wrappers.

### 2. Predictable problems were discovered late

Outreach's hum check failed after its successful7-minute picture render. Source
audio qualification belongs before expensive picture work when independent of
visuals. Final encoded audio still needs its own check.

The verifier's selected RGB scratch was predictable:531 frames required3.076GiB
for outreach;576 required3.337GiB for common message. Admission only tested a
10GiB reserve, so outreach crossed it during verification. More physical RAM
does not solve this disk allocation problem.

### 3. Successful work needed manual rescue

The normal `--verify-from` route reuses finished media but captures again.
Both successful captures already existed before final-check failures:
outreach160.1s and common169.8s. The new explicit recovery avoided repeating them,
but required manual sealing, dependency handling and handoff integration.

An audio-only revision also changed the absolute project path, invalidating
source-frame cache lookup despite identical pictures. The alias helper recovered
11 cache directories without re-extraction. A shared content-based cache identity
should include source bytes, extraction clock/ranges and runtime recipe.

### 4. Routine verification was repeated or requested in the wrong form

Studio requested timestamped recognition when its immediate purpose was spoken
text comparison. Invalid word timestamps rejected otherwise useful raw text,
leading to another recognition pass. Preserve raw output once; grade text and
timing separately, keeping invalid timing rejected.

Outreach's render seal binds357 input paths totaling6.094GiB, including a5.126GiB
source. Multiple preparation/seal boundaries reread this dependency set.
Its final recovery spent46.4s in preparation alone, although that figure is not
isolated hashing time. Profile bytes/time before changing evidence boundaries;
do not replace mutation detection with an unchecked cached-hash flag.

## Ranked changes and current implementation status

| Priority | Change | Already available | Remaining work |
| --- | --- | --- | --- |
| 1 | Preflight audio, expected disk allocation and Studio compatibility before encoding | Selected-source preparation and resource guards | Stage-specific allocation estimate, early audio routing/quality check, eligible cache retirement |
| 2 | Automatically resume the latest compatible completed stage | Media reuse, SDK picture reuse, explicit capture/final-only recovery | Integrate checkpoint selection/sealing into default exporter; bounded resource retry without bypassing guards |
| 3 | One shared local+Studio handoff driven by the project manifest | Working packet-copy audio, cloning and wrapper handling | Remove dated artifact imports, fixed directory names, fixed composition lists and assumed stage counts |
| 4 | Reuse approved transcript, assets, captions and native components | Direct CLI automatically prepares selected clips; real captures and templates were reused | Shared batch preparation; preserve source provenance and invalidate only affected dependencies |
| 5 | Persist recognition once and profile redundant integrity reads | Local text-only diagnostic and asynchronous hashing helpers | Shared text/timing results; immutable verified snapshots with required mutation checks |
| 6 | Measure complete production, not just rendering | Per-owner and export clocks | Request-to-handoff clock including selection, search, authoring, review, queue time and engineering/rework |

Read-only independent code audit identified the relevant paths:

- `scripts/producer/studio/native_short_pipeline.py:69` and`:129` — normal stage flow.
- `scripts/producer/studio/resume_final_qc.py:86` — explicit recovery.
- `scripts/producer/studio/native_short_worker.py:131` — picture precedes audio finishing.
- `scripts/producer/studio/native_short_delivery.py:185` — selected RGB decode.
- `scripts/producer/native_render_resources.py:230` — fixed free-disk reserve.
- Batch `prepare-studio-review.py:10` and`:93` — old artifact adapter and recognition.
- `scripts/producer/studio/native_short_export.py:47` — dependency pins.
- `scripts/producer/studio/native_stage_evidence.py:201` — stage revalidation.

Existing findings preserve qualifications and edge cases:
[selected media](../findings/CUT_SELECTED_MEDIA_BEFORE_NATIVE_AUTHORING.md),
[asynchronous hashing](../findings/ASYNC_HASHING_KEEPS_CHILD_CLEANUP_OBSERVABLE.md),
[final-only recovery](../findings/REUSE_CAPTURE_AFTER_FINAL_QC_RESOURCE_FAILURE.md).
These helpers working in recovery does not mean all remaining integration is done.

## Proposed 30-minute budget per approximately one-minute Short

Assumptions: local source and usable transcript already exist, style is selected,
and ordinary footage/real-asset research plus existing components suffice. The
clock includes selecting a source-backed argument; approval of a candidate alone
does not replace reviewing its actual speech. These are budgets, not measured SLAs.

| Elapsed window | Work |
| --- | --- |
| 0–2min | Resource, source, microphone and output-route preflight |
| 2–7min | Select complete context→development→payoff and viewer change; independently source/reuse real assets in parallel |
| 7–14min | Assemble proven layouts, proof inserts and karaoke; check cuts/audio early; independent prebuild review before export |
| 14–22min | Picture render, qualified audio and final assembly |
| 22–26min | Native/encoded correspondence, full decode and final technical audio checks |
| 26–30min | Full playback/listening/caption review, sampled independent visual review, local and editable Studio handoff |

Agents should have separate responsibilities: source/context review and real-asset
research can run alongside root assembly; final criticism can overlap compatible
handoff preparation. They should not duplicate research or create unnecessary
dependency chains. Keep heavy jobs under the measured resource scheduler; do not
assume simultaneous encodes are safe or faster because the machine has64GB.

The current three-clip batch's successful picture renders alone totaled18m24s.
Its successful capture and final-check owners add about9m32s. Thus30minutes for
all three, including selection and review, is a materially harder target than
30minutes per Short with the current serialized workflow.

Fresh source transcription, a detailed new style-reference analysis, difficult
asset discovery, custom animation or a real source defect may exceed this budget.
Record the concrete exception and time; reuse the simplest treatment that serves
the story. Do not remove source context, real proof, meaningful visual storytelling,
karaoke checks, or required review just to satisfy the clock.

## Acceptance test for calling the optimization done

Measure five representative Shorts through both live review surfaces: simple
presenter edit, real-proof inserts, reused explanatory graphics, cold assets and
a revision. Record total and stage time, fresh asset work, failures and rework,
whether code had to be repaired, and completed listening/caption review. Exercise
post-render failure recovery and near-capacity disk admission in focused tests.
Report median, slowest run and quality findings; five clips are not enough to
claim a reliable95th-percentile service level.

The target is repeatable delivery within30minutes for the defined ordinary
case, with truthful exceptions. No new end-to-end benchmark is claimed here.

## Requirement/source/evidence record

| Requirement | Source | Evidence/status |
| --- | --- | --- |
| Check actual time and waste | Current user request | Existing clocks,34 owners, interval union and related export records |
| Assess roughly30-minute readiness | Current user request | Explicit per-Short budget and unmeasured benchmark limits |
| Preserve quality, real assets, karaoke and viewer transformation | User's standing requirements | Included in preparation/review budget; no gate removal proposed |
| Use independent agents to verify | User's standing request | Separate timing aggregation and read-only code-path audit |
| Avoid further waste while auditing | Current user request | Existing records only; no render, repeated media QA or production-code change |
