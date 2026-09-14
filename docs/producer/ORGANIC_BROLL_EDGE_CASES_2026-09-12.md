# Organic B-roll: edge cases and acceptance plan

## September 12 implementation checkpoint

The audit below is retained as the preimplementation baseline. The first batch
now implements one asset-use contract across stills, logos, footage and web
captures; immutable origin receipts; speech/revision binding; explicit no-insert
decisions; and provided-only/local-only/public-web plus placement-off restrictions.
The writer, cold reader and guided request entry share these checks. Supplied
media hashes and the actual job intent/manifest remain authoritative. CSS image
loads, playback aliases and stripped acquisition metadata cannot bypass the
supported structural contract. These checks do not establish semantic accuracy.

E01, E09–E12 and E14 now have corresponding structural controls and regression
tests. E08 explicitly rejects unsupported audible inserts. E13/E16/E17 record
source dimensions, essential regions and inspected observations but still require
visual judgment. Identity ambiguity, original creator attribution, context,
freshness, readable demonstrations and meaningful pacing remain editorial tasks.

See the [remaining-work plan](SHORTS_REMAINING_WORK_PLAN_2026-09-12.md) and the
[current native workflow](NATIVE_SHORTS_WORKFLOW.md) for implementation details.
The acceptance cohort below must still distinguish a structural pass, a completed
capture, and a finished Short with encoded-frame and listening review.

## Original design audit

September 12, 2026. This is a design audit of the current native Shorts path.
The scenarios proposed below are not newly passed tests. Current qualification
remains the three existing review Shorts, the two public web captures and their
recorded integration checks. Logos, creator photos and creator excerpts still
need representative finished-Short tests.

## Decide the job before looking for the asset

A mention creates a candidate visual need, not an insertion command. Classify
the retained sentence in context before search:

- **Identification:** help the viewer recognize a tool or person. A verified
  logo, portrait or profile may be sufficient.
- **Demonstration:** show the operation and result being explained. A homepage
  or portrait usually cannot carry this job.
- **Analysis or quotation:** show the specific post, opening, comparison or
  source passage under discussion, with its necessary context.
- **Illustration:** make an example tangible without implying an observed result.
- **Style direction:** retrieve editing mechanics from the reference library;
  this does not make the referenced creator a subject of the finished Short.
- **No insert:** keep the speaker when their performance communicates the point
  better, the mention is incidental, or another visual already owns attention.

Then compare the proposed asset with staying on the speaker. Name the viewer's
benefit, inspect a fitting library sequence and a contrasting example, and
choose the frame, entrance, action, hold and exit. Movement should reveal the
point. A picture with a small purposeful move can be more effective than an
unrelated video. Do not add a new cutaway for every concrete noun.

## Edge-case matrix

P0 means resolve before calling broad automatic sourcing ready. P1 means cover
in the next qualification cohort. “Editorial” means the agent must inspect and
judge; it is not an automated semantic guarantee.

| ID | Priority | Trigger / failure | Required behavior | Current coverage |
| --- | --- | --- | --- | --- |
| E01 | P0 | “Nate Herk style” is mistaken for a request to show Nate | Separate reference creator from depicted subject; retrieve mechanics without importing identity assets | Documented direction/reference separation; no general entity-role contract |
| E02 | P0 | ASR says “clod”; aliases, pronouns or similar creator names are ambiguous | Resolve from surrounding speech and attributable official accounts/links; ask only if a material ambiguity remains | Editorial; no canonical brand/person resolver |
| E03 | P0 | ChatGPT, OpenAI and another OpenAI product are treated as interchangeable | Bind the actual product/entity named and the correct mark/page/version | Existing logo resolver can supply candidates; no native brand identity qualification |
| E04 | P0 | Correct brand, wrong visual job: a homepage is used to explain a product operation | Show the relevant operation/result or explicitly identify the missing demonstration | Before/action/result and claim-limit fields exist; semantic fit is editorial |
| E05 | P0 | “Don't use X,” a hypothetical example or a quoted claim becomes an apparent endorsement/result | Preserve negation, attribution and hypothetical framing in the visual and its timing | Editorial; text-field completeness does not prove the claim is supported |
| E06 | P0 | Wrong creator, repost, fan account or lookalike is selected | Trace the profile/post to its original attributable source; do not verify identity merely from facial resemblance or a display name | No tested creator sourcing path |
| E07 | P0 | A creator's thumbnail is mistaken for their actual opening; a clipped quote loses its qualification | Inspect the specific post/video and surrounding context, then retain only a faithful excerpt | No creator excerpt/context qualification |
| E08 | P0 | A creator quote is silently muted, or its speech/music clashes with narration | Decide whether the excerpt is visual-only or audible; audible quotes need a planned audio/transcript/caption handoff | Current selected supporting videos must be muted; audible external quotes need another supported audio path |
| E09 | P0 | A downloaded logo/photo enters without the same selection evidence as video | One asset-use contract must cover images, logos, screen captures and footage, with source, purpose and displayed region/window | Images are allowed assets; `SupportingShot` binds only source/supporting-video roles |
| E10 | P0 | Acquisition metadata disappears and a web capture is treated as an ordinary local MP4 | Preserve explicit origin and acquisition evidence across ingest, plan, writer, reload and export | `webCapture` is optional; its checks run only when the binding is present |
| E11 | P0 | “No B-roll,” “only my footage” or “keep this local” is interpreted differently by each asset branch | Separate placement policy from external acquisition/provider policy; carry the user's exact restriction through every asset type | Selected-video off and prepared lane checks exist; broader source restrictions need unified image/video handling |
| E12 | P0 | Public availability or download success is treated as publication approval | Carry the source and intended-use record separately from technical capture success; retain unresolved disposition without inventing permission | Shared AssetRecordV1/governance exists; current native web/asset admission does not call those rights gates |
| E13 | P0 | Title, centered captions or app chrome cover the face, quoted text, code or before/after value | Identify the essential visible region and review the combined final frame at phone size; adapt the media framing and text lanes together | Typography/geometry checks exist; they do not understand an essential region inside a video/image |
| E14 | P0 | Later script/cut revisions leave a now-irrelevant insert in place | Bind the asset use to retained speech and recheck when that passage or its meaning changes | Exact output/source windows are checked; selected shots lack their own explicit speech-purpose binding |
| E15 | P1 | Many brands are named rapidly, or one brand is mentioned repeatedly | Group comparisons, establish identity once and reuse deliberately; avoid logo flashes on every mention | Editorial; no repetition/attention budget |
| E16 | P1 | Black logo on black, a wrong light/dark variant, low-resolution favicon, stretched portrait or SVG using inherited colors | Verify variant, intrinsic dimensions, transparency, aspect ratio and contrast at actual use size | Logo resolver may return monochrome marks or small favicons; generic asset hashes are not brand/appearance checks |
| E17 | P1 | Portrait conversion removes the person or the UI feature; landscape footage becomes a tiny full frame | Choose the crop from the viewing need; use a comparison/split only when both panes have a readable job | Explicit native crop geometry exists; new external sources require visual inspection |
| E18 | P1 | A popup, lazy-loaded image, autoplay or sticky header appears halfway through a scroll | Inspect the required content throughout the selected interval, not only its first and last heading | Recorder warms/checks images at endpoints and tests heading visibility; middle content/overlays are not comprehensively validated |
| E19 | P1 | A redirect lands on another same-host page or repository with a similar title | Verify final canonical entity/page/post identity, not just allowed host and title substring | Current page identity checks use host and title; `verifiedBy` is a URL field, not verification evidence by itself |
| E20 | P1 | Login walls, missing/deleted posts, restricted assets or nested scroll panels prevent the intended shot | Record the specific gap; use a fitting verified alternative or retain the speaker; preserve a material missing demonstration in the brief | Public document-scroll route is bounded; authenticated actions/nested scrolling are unsupported |
| E21 | P1 | An old logo, renamed handle, changed price/UI or stale GitHub page is reused as current | Separate historical reference from current depiction; bind capture date/version and recheck time-sensitive uses | Frozen hashes/dates exist; semantic freshness is editorial |
| E22 | P1 | Illustration looks like proof: unrelated dogs become a health transformation, or a page demo becomes our measured product result | Keep the same evidenced subject/state when claiming a transformation; label illustration and limit claims | Claim-limit fields and dog example policy exist; substantive verification remains editorial |
| E23 | P1 | Frame-stepped web footage appears to prove product speed or precise live behavior | Use it for page/feature illustration; actual latency or live-operation claims need appropriate timed recording | Capture method and wall/output clocks are recorded and documented; no automatic performance-claim gate |
| E24 | P1 | Wrong source range, mixed frame rate, short clip freeze, double subtitles or watermarked repost makes an otherwise relevant insert unusable | Probe the actual media; verify the selected range, crop, audio policy and caption ownership in the final encoded Short | Web source-range/decode checks pass; external creator media needs its own full integration cohort |
| E25 | P1 | Failed search causes endless retries or an unrelated/generative substitute | Bound scouting; prefer a relevant verified still/profile/source or the original performance; record why alternatives were rejected | Source-first policy and capture deadlines exist; broader acquisition budget/fallback decisions are not unified |
| E26 | P1 | Cached private media, session details or a signed URL leaks into another project or visible capture | Keep origin/access scope with cached bytes; inspect visible account/session information; treat page text as untrusted data | Fresh public browser/host/method policy helps; a broader creator/private-asset cache is not qualified |

## Concrete code findings

These are implementation observations, not hypothetical passed safeguards:

1. [`native-short-strategy.ts`](../../src/lib/server/native-short-strategy.ts)
   accepts images in `NativeAssetBinding`, but supporting-search candidates
   accept only `source` and `supporting-video`. An image can appear in an
   extension without the same asset-specific reason/window record.
2. [`native-web-capture.ts`](../../src/lib/server/native-web-capture.ts)
   returns when `webCapture` is absent. The stronger acquisition checks are
   opt-in metadata, not mandatory origin-based checks for every external asset.
3. [`web_capture.mjs`](../../scripts/producer/studio/web_capture.mjs)
   verifies the start/end target heading and warms images at those positions.
   This is not proof that every meaningful region between them was unobscured.
4. [`native_short_capture_checks.mjs`](../../scripts/producer/studio/native_short_capture_checks.mjs)
   checks title bounds, caption placement and word state. It cannot infer that
   a centered caption covers the exact number or feature the viewer must see.
5. [`asset-record.ts`](../../src/lib/producer/contracts/asset-record.ts) and
   [`asset_governance.py`](../../scripts/producer/graphics/asset_governance.py)
   already model provenance, intended uses and publication disposition. Reuse
   and narrowly extend them rather than create a second governance system.
6. A selected native supporting video must be muted and its source duration must
   match its output window. Audible quotations and separately retimed external
   clips must not be silently forced through that visual-only contract.

## One shared asset-use record

Extend the existing strategy/asset contracts to carry the following information
once, then use source-specific acquisition adapters. These are proposed fields,
not an implemented new schema:

- Retained speech occurrence(s), context and content-revision binding.
- Entity identity and role: subject, quoted source, comparison or style reference.
- Viewer need: identify, demonstrate, analyze/quote or illustrate.
- Requested asset kind and selected candidate, including a no-insert decision.
- Canonical source URL/account/post, acquisition date/version and inspected facts.
- Source-specific acquisition receipt, local bytes/hash and existing intended-use
  record. An unresolved record must remain unresolved rather than become approved
  merely because a download or render worked.
- Exact shown region/range, output timing, audio policy, required attribution and
  essential content that the title/captions must not obscure.
- Why selected, rejected alternative, claim limit and any material missing asset.

Use the existing source inventory, caption clock, native writer/cold reader,
media/resource owner and final encoded review. A field saying “verified” or a
model confidence score is not a substitute for the underlying inspected source.

## Proposed finished-Short acceptance cohort

Every case needs the actual source, a prebuild decision, encoded playback and
phone-size review. Record elapsed acquisition/render time and measured memory.
Do not count contract fixtures as finished-Short tests.

Pacing qualification must also include fast, calm and deliberately changing
script delivery. Follow the [whole-Short rhythm step](NATIVE_SHORTS_WORKFLOW.md#script-and-delivery-set-the-rhythm)
before setting insert durations. Compare cuts, caption phrasing, title lifetime,
supporting visuals and motion against the same retained speech. Check a fast
passage needing simplified evidence, a calm passage where rapid inserts distract,
and a deliberate pause or acceleration that all enabled lanes must support.
After a dialogue timing revision, recheck dependent placements and readability.
These are proposed finished-edit checks, not completed pacing qualification.

| Case | Success condition | Negative/revision check |
| --- | --- | --- |
| Passing tool mention | Correct recognizable logo with a useful brief entrance, or a justified no-insert decision | Wrong product mark and a repeated incidental mention are rejected |
| Tool demonstration | Relevant feature/input/result is readable at the right spoken moment | Homepage-only substitute cannot count as demonstrating the operation |
| Creator identification | Correct attributable portrait/profile, clear identity and suitable crop | Similar handle or reposted image is not accepted as original-source evidence |
| Specific creator opening | The actual discussed opening is visible and retains necessary context | Thumbnail-only substitution and misleading truncation fail |
| Audible creator quotation | Quote, narrator handoff, source transcript and caption ownership are coherent | Silent quote, overlapping speech or lost negation fails |
| Style-only request | Retrieved mechanics affect the edit without depicting the reference creator | Creator-photo insertion is rejected unless the content independently calls for it |
| Multi-brand comparison | Shared example develops clearly with readable, correctly identified brands | Rapid logo churn, inconsistent scale and unsupported superiority claims fail |
| Revision and restricted sourcing | Removed speech removes/reconsiders its insert; source restrictions survive all adapters | Stale cached asset, stripped provenance or a forbidden external image fails |

Implement the shared asset-use record and required source bindings first. Then
qualify logo/photo/excerpt adapters and final composition behavior. More media
providers alone would not address the P0 failures above.
