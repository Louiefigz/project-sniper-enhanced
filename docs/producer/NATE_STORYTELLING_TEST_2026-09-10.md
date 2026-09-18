# WildFireVlog3: Nate-style story and three revised Shorts

## Latest operator feedback: benefit-led hooks

Aaron liked example 2's story and real footage, and requested a stronger viewer
benefit in its hook. Current example 2: **“Use this offer formula to get more
buyers.”** Current example 3: **“Who else wants $1K/mo in their first 30 days?”**
The [hook finding](../findings/TEMPLATE_COMPLIANCE_IS_NOT_A_STRONG_HOOK.md) records
the reason and shared Director guidance/validation changes. The earlier hook
wording in the initial-test sections below is historical.

New projects are `nate-offer-v2` and `revised-members-v2`; exact deliverables are
in [benefit-review-manifest.json](../../artifacts/shorts-end-to-end-2026-09-10/benefit-review-manifest.json).
Example 3 starts its existing close lower presenter at frame 0 to give the two-line
hook room. Source cuts, speech, durations, arithmetic and the offer story remain.
All 33 compared post-title Nate poses and five post-title members poses match
their earlier native captures byte-for-byte (`benefit-body-continuity.json`).

Both revised deliveries pass source-aligned audio, exact AAC clocks, whole decode
and native/encoded frame comparison: 36 offer samples and 11 members samples.
Their qualified AAC packets were reused with zero additional AAC encodes.
The offer render took 47.83s with 2.64 GiB measured peak; members took 24.79s with
2.08 GiB. Finishing took 3.58s and 2.26s respectively. These are stage timings,
not complete editing-time measurements. The first offer attempt's 5.67s process
measurement timeout and verified cleanup remain in its failed receipt.

Actual title previews were inspected. Native forward/reverse capture and title
lifetimes passed; CLI checks reported zero errors and 24/24 and 38/38 sampled
contrast checks. `benefit-playback-01.json` passes all three full playthroughs,
seeks and restarts with zero dropped/corrupted frames or wait events. Its 61.28s
supervisor verified cleanup and stable inputs. The same local URL at port 3993
now serves this revision; earlier project/output/manifest bytes remain retained.
The five Director regression tests, lint and TypeScript checks pass locally.

## Initial complete Nate test

The offer example is now a complete 24.52-second Nate-style storytelling test,
using the raw WildFireVlog3 recording supplied by Aaron. It joins the revised
13.04-second follow-up and 8.24-second members clips in the
[local review page](http://127.0.0.1:3993/). These are manual local review candidates;
no live Director, independent model critic or external media service was called.
Aaron explicitly requested local-only work. The earlier three control exports
remain available at port 3991; the title palette comparison remains at port 3992.

## Source, references and planning

The source is `/Users/aaronfigueroa/Downloads/WildFireVlog3.mp4`:
1920×1080, 25 fps, 825.84 seconds, SHA-256
`1fc683881182c422303a2d191965ee39cfcd7ca22ea001691af12e1a69cac7a5`.
The existing excerpt and word transcript were reused after source derivation
verification. No new transcription was required. The excerpt's original video
offset is 76.715 seconds; the retained audio offset is 76.714667 seconds.

Actual library images were reopened: Nate N27 overview parts 1/2, N26 part 1,
N27-B16 and N26-B06 sequences, and N27 f001013/f001103/f001154. The primary
transfer is N27-B09–18: keep one recognizable offer object, change its value/time
variables, and connect those changes to the explanation. N26-B04–09 supplies the
alternative stable-world/changed-variable pattern. The test does not establish
coverage of every Nate reference or audience effectiveness.

The source-bound [BRIEF](../../artifacts/shorts-end-to-end-2026-09-10/projects/nate-offer-v1/BRIEF.md)
and [STORYBOARD](../../artifacts/shorts-end-to-end-2026-09-10/projects/nate-offer-v1/STORYBOARD.md)
preceded composition assembly. They include hook alternatives, reference choices,
shot crops, caption/title lanes, exact source cuts and a manual editorial review.
There is no fabricated independent-critic approval. The canonical Script Director
catalog is loaded locally and frozen with its hash in the project.

## What the Nate test does

| Output time | Story job | Visible treatment |
| --- | --- | --- |
| 0–3.24s | Establish the real situation | Close portrait presenter; upper white-on-black template hook |
| 3.24–4.96s | Make the problem concrete | 294 visitors → 0 conversions, labeled as the reported last 30 days |
| 4.96–6.60s | Bridge into the plan | Return to the actual presenter/board action |
| 6.60–11.56s | Establish the current promise | One persistent offer object with “Make your dog's health better” |
| 11.56–15.36s | Explain why it needs revision | Presenter says it seems too vague; centered karaoke remains separate |
| 15.36–18.52s | Teach the formula | Specific outcome + timeframe, with source-cued entrances |
| 18.52–20.52s | Apply it to the same object | Current wording transforms into distinct outcome/timeframe slots |
| 20.52–24.52s | Complete the worked example | “Get your dog to eat raw food” + “in 21 days”; owned dog footage and a short ending hold |

The hook uses canonical `value-formula`: **Use this [X] formula to [Y]**, filled
with X=`offer`, Y=`get specific`. Its two backed lines are at the top, end at
frame 81, and never determine the caption position. The 70-pixel captions remain
centered around torso height with dark outline and yellow source-timed words.

The offer is explicitly proposed wording, not an achieved conversion or health
result. Dog footage comes from the same recording, excerpt 81.00–83.80 seconds;
it illustrates feeding. There was no verified matched health before/after pair
in the selected evidence. No Higgsfield or generated asset was necessary here.

Ten retained source ranges create 583 speech frames plus a 30-frame ending hold:
8.56–11.80, 14.80–16.52, 36.88–38.52, 51.92–54.24, 54.96–56.80,
57.60–58.40, 61.92–63.32, 64.40–66.80, 67.92–73.08 and 90.16–92.96 seconds
on the verified excerpt clock. The last range supplies a fluent complete example.
The existing caption grouper creates 27 groups from 65 retained word occurrences.

## Other two revisions

**Follow-up:** canonical `value-how-to` produces “How to earn trust with a
follow-up.” White-on-red upper backing, centered outlined karaoke and full portrait
framing replace the earlier middle heading/displaced captions. The final HTML,
font, GSAP, source and MP4 match the already qualified title component exactly.
The final delivery is reused, with no new picture/audio encode.

**Members:** canonical `value-how-to` produces “How to plan a $1K month.” A single
red-on-white upper line clears the opening hairline. The accepted 26 × $39 =
$1,014 arithmetic and close lower presenter remain. Captions move to a black-backed
center strip just above the divider, clearing both the diagram and the speaker.
The goal stays a goal. Source cuts, 19 word occurrences and proved AAC are retained.

## Measured results

All outputs are 1080×1920, 25 fps, with exact frame and presented audio sample
counts. Timing is for prepared renders/finishing, not full end-to-end editing.
Planning, source selection, earlier development, retries and human review are
excluded from these individual stage values.

| Revision | Duration / frames | Prepared render | Peak measured owned memory | Audio finish | Color metadata finish |
| --- | --- | --- | --- | --- | --- |
| Follow-up | 13.04s / 326 | 36.45s, earlier verified export reused | 2.22 GiB | 1.91s, earlier finish reused | 1.09s, earlier finish reused |
| Nate offer | 24.52s / 613 | 48.34s | 2.61 GiB | 5.38s | 1.01s |
| Members | 8.24s / 206 | 24.52s | 2.12 GiB | 1.43s | 0.84s |

Nate has 36 successful unique native-to-encoded frame comparisons; members has 11;
the exact reused follow-up has 10. Minimum PSNR is respectively 42.23, 42.76 and
42.20 dB. Each file passes whole decode, frame count, exact AAC packet-clock,
decoded loudness/peak and local dialogue-signal checks. The two new CLI checks have
zero errors; sampled contrast passes 30/30 for Nate and 37/37 for members.

Native capture checks include forward/reverse seeks, title exits, caption seams,
active words, source crop transitions and final frames. Repeated native poses
produce identical hashes. All three exact deliveries completed browser playback,
backward/mid/end seeks and restart with zero dropped/corrupted frames or playback
wait events. Desktop and 390-pixel phone gallery screenshots were inspected; the
phone page has no horizontal overflow. `revised-playback-01.json` records that
pass; its 60.96-second supervisor also verified cleanup and stable inputs. Muted
telemetry is not listening approval.
See the exact paths and hashes in
[revised-review-manifest.json](../../artifacts/shorts-end-to-end-2026-09-10/revised-review-manifest.json).

## Failures retained and fixes made

- The first offer swap had both CSS translation and GSAP `yPercent`, leaving its
  replacement outside the mask. The corrected motion uses one transform owner;
  inspected native and encoded frames prove the replacement is in its slot.
- Rounded source word bounds caused two successive caption phrases to share one
  frame. Shared canvas code now ends each visible phrase at the next phrase start,
  without mutating word evidence. Eight focused canvas/title tests, TypeScript and
  ESLint passed. See the [finding](../findings/CAPTION_PHRASE_WINDOWS_MUST_NOT_OVERLAP.md).
- Native AAC initially failed the shared signal gates. Nate rebuilt its exact
  changed speech program from source PCM and encoded AAC once; members reused its
  previously qualified AAC. Neither finishing path re-encoded pictures.
- The first Nate render attempt stopped after 5.82s when process measurement
  timed out. The retained second attempt completed and cleaned up its owned tree.
- The native reference capture itself passed, but its supervisor failed during a
  measurement/cleanup race. All six recorded child identities were independently
  verified absent. The existing nonce-bound recovery proved the supervisor and
  children absent, released the stale fence and preserved the failed receipt.
  `nate-native-01-cleanup-follow-up.json` records the follow-up evidence. This is
  not mislabeled as an originally successful supervisor run.
- CLI crop overflow reports describe deliberate source cropping. The remaining
  Nate duplicate-audio warning is decimal-to-frame rounding in the linter:
  12.96 + 2.40 ends at 15.36s, exactly where the next segment begins. The final
  source-bound sample program and every AAC packet are separately checked.
  Members also retains an advisory for eight arithmetic elements on one track.

## Reuse and remaining integration

This work reuses long-form file-backed frame transport, retained source frames,
the bounded process owner, source-word mapping, caption grouping, float mastering,
AAC reuse and batch output checks. Shared title/caption primitives serve all three
styles; the evolving offer object is a narrow project-owned visual extension.
Its source reconstructs the qualified HTML byte-for-byte after refactoring.

These tests qualify the delivered cuts and specific mechanisms. General native
planning/UI integration, live Director/critic evaluation, installed runtime
integration, every library style, fresh transcription timing and complete automated
editing time are still separate work. Retention and the strength of the hook
require audience/editorial judgment; successful rendering alone cannot prove them.
