# Review before full rendering

Ordinary `render.py`, `assemble.py` and graph execution (including cache hits)
require `.sniper-render-ready.json` for every
scope, including trim/light and graphics-off. Studio sync changes the same canonical
plan and therefore invalidates affected evidence. `--resume`, `--skip-graphics`,
`--no-audit` and the legacy source migration flag do not waive this check.

The agent authors, critiques and revises. These commands never call a provider.
Use the existing Producer review packet and deterministic gates before critics;
readiness adds durable admission evidence to that workflow. It does not replace
source admission, template/history checks, final Audit B or final editorial review.
An isolated plan snapshot is accepted only when its bytes exactly match the reviewed
canonical plan; changing its contents requires new evidence.

## Prepare and review

1. Finish the paper edit, source/cut checks, catalog selection, layout, copy and
   timing before full rendering. Run the existing planning gates.
2. Run `./sniper node --import tsx scripts/infra/plan-readiness.ts packet <producerDir>`.
   Save its current unit IDs/hashes for the critics alongside the existing review
   packet. `plan` covers the current editorial meaning and shared dependencies; each `graphicsTrack/N`
   includes the local graphic, its neighbors and overlapping graphics.
3. Mint deterministic preparation admission with
   `./sniper node --import tsx scripts/infra/mint-delivery-approval.ts <producerDir> --draft`,
   then generate and register ordinary context clips with
   `./sniper python3 scripts/producer/ordinary_previews.py <producerDir> <manifest> <newAttemptDir>`.
   For a revision, add `--previous <previousAttemptDir>/ordinary-previews.json`.
   Inspect actual context, entrances/exits, cuts and
   audio where relevant. An isolated graphic cannot establish interaction with
   the footage. Each registered clip must be moving video of at most 30 seconds
   and 1,800 frames, within 1 GiB. Several clips may cover a long edit.
4. The automatic command writes each clip's current-unit receipt and its path in
   `ordinary-previews.json`. For a clip produced by another supported workflow,
   register it with
   `./sniper node --import tsx scripts/infra/plan-readiness.ts preview <producerDir> <clip.mp4> <unitId>...`.
   It fully decodes through the existing native media jail and writes a receipt.
   Registration binds the agent's claimed coverage to current units. It does not
   establish that a clip depicts the right candidate or that someone viewed it;
   the independent critic must check that and describe the review performed.
5. Fresh critics return the existing strict Producer review schema, eight coverage
   assessments and hashed evidence files. Write the results to
   `<producerDir>/.sniper-plan-reviews.json` using the shape below. Trim/light need
   one clean independent review per current unit; produced/full need two distinct
   clean reviewer sessions. Material findings block admission. Fix them and repeat
   affected checks before collecting clean evidence.
6. Run `./sniper node --import tsx scripts/infra/mint-delivery-approval.ts <producerDir>`.
   It verifies reviews/previews, reruns the deterministic gate bundle and refuses
   if dependencies changed during those gates. Only then can full rendering begin.

## Review bundle

```json
{
  "schemaVersion": 1,
  "reviews": [{
    "reviewer": {"identity": "critic name", "sessionId": "fresh critic session", "plannerSessionId": "author session", "independent": true},
    "coverage": {
      "briefAndRetainedMessage": "Assessment of the retained message and request",
      "assetsAndSourceEvidence": "Assessment of actual source and visual evidence",
      "cuesAndSceneCoverage": "Assessment of scene coverage",
      "layoutCropAndText": "Assessment of layout, crop and readability",
      "motionAndTransitions": "Assessment of observed motion and transitions",
      "pacingAndAudio": "Assessment of pacing and audio, or reason not applicable",
      "feasibility": "Assessment of execution feasibility",
      "visualSourceSelection": "Assessment of catalog selection or the evidenced reference/custom exception"
    },
    "evidence": [{"path": "/absolute/review-notes.json", "sha256": "ACTUAL_SHA256"}],
    "review": {"schemaVersion": 1, "stage": "plan", "verdict": "pass", "summary": "Actual reviewer conclusion", "materialIssues": [], "findings": []},
    "units": {"plan": "CURRENT_UNIT_HASH"},
    "previews": [{"unitId": "plan", "unitHash": "CURRENT_UNIT_HASH", "path": "/absolute/preview.mp4", "sha256": "ACTUAL_MEDIA_SHA256", "receipt": "/absolute/preview-receipt.json", "assessment": "Actual viewing method, context and findings"}]
  }]
}
```

Replace placeholders with real evidence; never manufacture a critic or passing
assessment. A preview can cover multiple units by listing one entry per unit.
Reviewer identities are declared, not authenticated. Receipts are local integrity
records, not signed proof of independent judgment or semantic quality.

## Revisions and drafts

Retain passing rows for unchanged units and add fresh reviews/previews for changed
units. Keep each round's referenced packet, notes and previews in immutable paths;
overwriting their bytes invalidates the retained reviews. Catalog parameter and
placement changes invalidate their own, adjacent and overlapping graphic units.
The current `plan` assessment always refreshes: a single headline can change the
promise even when distant pixels are unchanged. Track order, kinds, timing,
unknown entry fields, cuts, audio, intent, sources, fonts and shared dependencies
invalidate all units. Deterministic parameter/schema validation still applies.

For a watchable draft before critic convergence, mint with `--draft`, then run
`./sniper python3 scripts/producer/draft_render.py <plan> <manifest> <producerDir>`.
The separate `.sniper-draft-ready.json` never admits a final. Direct
`render.py --draft-only --approval-dir <producerDir>` also requires the dedicated
`<producerDir>/draft` output, forbids resume/reusable bases and burns the watermark.
The wrapper consumes only draft admission. Full drafts can still cost a full render;
use bounded previews for quick iteration rather than promising an automatic speedup.

The ordinary automatic command has separate preparation admission: it may retain a
private full graphics-free base and full audio master, then produce clips of at
most 12 seconds. It never creates the full finished composite or final readiness.
The cold base is still full-program work. Local graphic spec/placement revisions
can reuse that base/master and exact unchanged clips; other plan fields, timing,
source bytes, fonts, intent or implementation changes invalidate preparation.
Start/middle/end samples and every graphic's full duration plus two seconds of
context are covered; long graphic windows are split with overlap. Graphics retain
their original timing and captions remain above graphics. Audio comes from exact
sample ranges of the verified whole-program master, without local normalization.
Review every listed clip before recording the corresponding unit assessments.
Technical generation and decode evidence do not claim playback or listening.

The command uses the qualified ordinary `source-float-v2` preparation path. Existing
source/clock/plan restrictions still apply; unsupported input fails explicitly.
It does not fall back to lower-quality preview rendering or waive final checks.

Native Short and Long automatically check representative reference/seek states
and an encoded sample reel before full picture encoding. Source cache acquisition
uses the existing SDK, preserving its color negotiation and final render settings.
Sample checks do not constitute continuous playback/listening review. Retained
capture evidence can support final QC; the final encoded file still needs its
own full decode, picture/audio checks and editorial review. No token or elapsed-time
saving is implied by a receipt or these ordering tests.

## Native continuous preview and regional review

The supported native Short and Long exporters prepare continuous picture/audio
windows automatically. The default invocation stops at
`native-motion-previews-complete`; it does **not** authorize the full picture.
`--preview-only` explicitly requests this preparation. `--preview-reviews
/absolute/reviews.json` admits final rendering only when every current region has
passing independent review evidence. There is no new human approval prompt: the
existing agent workflow authors and obtains the critics' actual judgments.

The native previews use the full original composition, absolute frame clock,
current native capture path and final-quality encoding. Audio is a sample-exact
excerpt of the checked whole-program float master, then encoded once; it is never
normalized per excerpt. Windows include two seconds of neighboring context. Long
regions use bounded start/middle/end samples rather than claiming exhaustive
playback. Final output still receives full decode and existing encoded QC.

An optional `REVIEW-REGIONS.json` declares complete, uniquely mounted catalog
units. For Short projects author the same object as `reviewRegions` in the input;
the writer stages it and includes it in the manifest:

```json
{"schemaVersion":1,"units":[{"id":"example","file":"compositions/example.html","startFrame":1800,"endFrame":1905}]}
```

The exporter checks the files and literal mount clocks. Only literal component
copy and declared variable defaults have local preview dependencies; code, CSS,
markup, timing, source/media and unknown inputs stay global. Separate start, middle
and end context units cover global picture/audio samples. Every unit also binds
all mapped graphics visible in its preview windows, including the two-second
context. Changing an overlapping or nearby graphic invalidates those reviews too.
These declarations guide bounded review;
they do not establish semantic independence or replace the current full-plan
prebuild assessment. For components with cross-scene dependencies, omit the region
map so the project is reviewed together.

Completed previews are discovered automatically from bounded same-project export
history. `--preview-from /absolute/motion-previews.json` selects one explicitly.
Unchanged units retain their earlier media; all ancestor receipts and clips remain
required and checked. Changed units get new continuous previews. A malformed or
missing selected record is an error, never permission to claim reuse.

Store the critics' results outside the authored project to avoid a dependency
cycle. A review bundle has `schemaVersion: 1` and `reviews: [...]`. Each review uses
the same `reviewer`, eight-field `coverage`, `evidence`, and passing `review` shape
shown above, plus:

```json
{
  "units": {"example":"EXACT_CURRENT_REGION_HASH"},
  "preview": {"path":"/absolute/attempt/motion-previews.json","sha256":"ACTUAL_RECEIPT_SHA256"},
  "assessment":"Describe actual playback/listening, context, findings and limitations"
}
```

Retain earlier rows for unchanged units, add actual new judgments for changed
units, and rerun with `--preview-reviews`. The separate current prebuild assessment
still checks the complete edit's meaning and source decisions. The exporter
validates records and media; it never invents a reviewer or calls a model.
