# C0679 A/B comparison after fresh B was sealed

Comparison began only after B's first benchmark was sealed at
2026-09-09T23:35:45.889907+00:00. Its manifest SHA256 is
`d83b8ff08a1175679a6fdfa60b64203643f54c0e32771f9fc152ce9b667357db`.
A remains unchanged. B used fresh source/transcript/cuts/assets; prior operator
exposure and generic software reuse mean this was not a blind experiment.

## Measured outcome, not an overall quality winner

| Observation | A | B first benchmark |
| --- | --- | --- |
| Duration | 11m23.766s | 10m57.365s |
| Picture | 1920×1080, 16394 frames | 1920×1080, 15761 frames |
| Rate | 24000/1001 | 24000/1001 |
| Guarded full native render | 25m41.357s | 23m50.103s |
| Peak owned native render memory | 2.214GiB | 2.135GiB |
| Observed new swap during render | 0 | 0 |
| Corrected output integrated loudness | −14.61LUFS | −16.16LUFS |
| Corrected output true peak | −1.86dBTP | −1.09dBTP |
| Exact presented audio | 32820788 samples | 31553522 samples |
| Corrected file objective gates | Passed | Passed at109m7.549s |
| First full corrected playback | Reported0 drops | 4 drops; zero-drop gate FAILED |
| Complete two-hour workflow | Not met | Not met: playback ended120m40.653s; seal128m57.536s |
| Human listening/creative approval | Not claimed | Not claimed |

The render timings are not controlled speed comparisons: B has633 fewer frames
and different graphics. Loudness targets also differ; louder is not necessarily
better. Both corrected deliveries preserve already encoded picture during the
metadata/audio assembly correction, rather than adding another picture encode.

## Differences in the edit

B moves the existing three-stage compass (source195.56–205.45s) into the first
minute. It removes the repeated future-release invitation/recap at792.62–818.20s,
while retaining the preceding statement that full script/post writing comes later.
That preserves the distinction between today's angle inputs and future automation.
The final watch-next resource is still unverified in both publishing packages.

A's reviewed credibility frame uses a full presenter, blue/white credential card
and lower third. B's nearby credibility scene uses a warm-paper notebook layout,
large explanatory type and padded/rounded presenter crop. Both reviewed stills
keep the face unobstructed and text legible. This is a limited agent visual review
of different frames, not a matched color experiment, retention test, whole-video
visual certification or a user preference decision.

## The QC methods are not interchangeable

A's browser color review failed the40dB whole-frame threshold at frame653
(39.4668dB); that failure remains even though its FFmpeg color checks passed.
B's three independently captured native reference comparisons passed whole-frame
and presenter-ROI gates, but they used declared-color FFmpeg output decoding,
not the identical browser color method. B's minimum ROI40.0616dB is close to the
threshold. Do not claim B fixed every browser color discrepancy from this evidence.

A's full playback check reported0 drops with a1% configured drop allowance,
500ms frame-gap bound and500ms sampling. B requires0 drops, checks100ms samples
and tighter presented-frame coverage. B's4 actual drops remain a failure under
its own declared contract. A's looser configured allowance was not needed for
its reported0 count, but identical pass labels do not imply identical methods.

A's retained continuity check compares8kHz audio over10s/5s-hop windows plus
20ms dropout checks. B adds a48kHz per-channel comparison over1s/.5s-hop windows,
with no gain/lag fitting. These are useful complementary evidence, not a basis
to invent a numeric A/B listening-quality score.

B's65s native Studio opening had no observed audio seek/wait disruption and
maximum A/V difference4.631ms. A's later recorded Studio test had668 audio
seek/wait events. However, B used a realm-corrected preview staging, deferred
sidebar thumbnails and retained an outer guard failure in that specific Studio
phase. Neither result proves a fully qualified stock Studio workflow.

## What actually saves time next

B's400-file archive is2,469,972,749bytes. The sum of its23 guarded phases is
3264.464s (54m24.464s); the other4473.072s (74m33.072s) includes authoring,
development, review, orchestration, hashing and packaging. It is not a measured
human-wait bucket. There was only one full B native picture render; the audio/color
repair and repeat file QC took45.748s, preserving the expensive picture result.

Batch independent file/visual checks before real-time playback, fix related issues
together, and rebuild only invalidated stages. Promote the proved audio/clock checks
into ordinary pre-publication delivery, qualify one saved-project text revision,
and verify that the native export path applies required finishing automatically.
Do not shorten verification by lowering thresholds or omitting requested outputs.

Evidence: A's `docs/producer/evidence/c0679-optimization-2026-09-09/attempt-a-final-handoff.json`
and `corrected-browser-whole-v2.browser-review.json`; A archive
`evidence/full-native-high-v10-lossless-av-color.assembly-qc.json`; B archive
`HANDOFF.md`, `MANIFEST.json`, `delivery-v1-playback.json`, `delivery-qc-v2/native-qc.json`,
`cut-plan.json` and `transcript.json`. Any later playback repeat is separate evidence.

## Separate repeat and implementation follow-up

B's identical-file playback repeat completed in666.151788s with0 drops,
15,761 presented frames and0.041709s maximum media-frame gap. Its unchanged
strict gates passed. This does not replace B's first result in the table,
establish the original four-drop cause, or count as human listening.

The local-window comparison and exact AAC packet checks have since entered
ordinary pre-publication program delivery, with56 focused regressions passing.
Native edit/save/reload passed on a separate working copy. Direct child export
then exposed a wrapper/lint contradiction. A normal native root mounting the
saved child exported successfully; its separately corrected silent MP4 passed
exact picture-clock, full-decode and three source-snapshot pixel checks. Full
revised-master and child-playback acceptance remain separate. The existing
`--composition` command is not a proved strict template-child route here and
is not incremental replacement in a completed master. No supported local
changed-interval/patch-export command was found in this installed0.8.31 CLI.

The independent creative review found that B lacks a left-presenter variant
and overuses one sheet/line-reveal treatment. Three source-timed catalog
adaptations are proposed separately; shorter duration and technical file
passes do not establish that B is creatively finished or universally better.
