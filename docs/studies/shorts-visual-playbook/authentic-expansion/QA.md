# Research coverage and evidence checks

Version `2026-09-10.3`. Eight additional public Instagram reels, 271.249 seconds
in the saved review containers. They were selected to broaden format decisions,
not ranked by views or retention. All source files, fingerprints, chronological
sheets, accepted transcripts and acquisition receipts are under
`artifacts/shorts-authentic-expansion-2026-09-10/`.

## What was actually inspected

| Case | Duration (s) | Chronological samples / sheets | Directing beats | Unique selected native frames | Motion bursts inspected | Individual original-resolution checks | Machine transcript |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| CR04 | 37.746 | 75 / 7 | 4 | 19 | 1 | 1 | Accepted local Whisper |
| CR05 | 15.022 | 30 / 3 | 1 | 3 | 0 | 2 | Text-led; not submitted |
| CR06 | 54.208 | 108 / 9 | 5 | 23 | 1 | 1 | Accepted local Whisper |
| CR07 | 39.509 | 79 / 7 | 7 | 50 | 4 | 2 | Failed timing gate; visible captions used |
| LM04 | 43.367 | 87 / 8 | 7 | 36 | 2 | 2 | Accepted local Whisper |
| LM05 | 14.070 | 28 / 3 | 3 | 17 | 1 | 1 | Text-led; not submitted |
| LM06 | 29.744 | 59 / 5 | 8 | 46 | 3 | 2 | Accepted local Whisper |
| LM07 | 37.583 | 75 / 7 | 4 | 19 | 1 | 1 | Accepted local Whisper |
| **Total** | **271.249** | **541 / 49** | **39** | **213** | **13** | **12** | **5 accepted** |

Every chronological 2 fps sheet was visually inspected across every source's
duration. All 13 native-frame bursts were also opened and inspected. This is
complete chronological sampled coverage, not every decoded frame or uninterrupted
real-time playback. Burst samples are approximately 80 ms apart; the files carry
actual decoded frame indices and PTS. They bound specific visible changes and
do not establish arbitrary sub-frame timing or easing.

Twelve representative images were additionally opened individually at original
resolution. The exact file paths and hashes are listed in each case's
`review.individual_original_resolution_frames_reviewed` field. This supplements
the complete sheets rather than claiming every one of the 213 saved native
frames received an individual full-resolution review. It corrected CR05's small
sheet interpretation: the seated person is using a laptop, not a phone.

For cross-case comparison, the existing Nate frames `N03/f000450.jpg` and
`N10/f003297.jpg` were also individually opened at original resolution. Their
earlier case coverage remains governed by the Nate study's separate receipts.

## Provenance and timing

The original reel URLs were observed on the public creator profiles. CR07 is
a collaborative podcast post appearing on Caleb's profile. Its profile placement
does not establish that Caleb personally performed the edit.

Public browser-visible video/audio resources were acquired without cookies and
combined by codec copy into review MP4s. Each `acquisition.json` retains the
observed media URLs, asset IDs, probe information and content hashes. Selected
library frames were extracted by decoded frame index; their JSON receipts retain
the exact source PTS and original image dimensions. Contact-sheet time labels
are resampling estimates. Editorial beat boundaries are approximate and do not
replace the exact frame receipts. Container duration may include a short audio
tail beyond the final video frame.

One downloaded resource was found to belong to a prefetched, unrelated reel and
was excluded from the source set. It is quarantined under
`artifacts/shorts-authentic-expansion-2026-09-10/excluded-unbound-media/` and is not
counted, linked as a case or used as evidence. Browser resource inventories may
contain neighboring media; binding to the current reel requires visual checking.

Local machine transcription reused the existing Whisper workflow. Five outputs
passed its timing gate and were read alongside visible captions. CR07 failed the
tiny-word-rate timing gate after a CPU retry and has no accepted transcript.
CR05 and LM05 were treated as text-led cases and were not submitted. An accepted
machine transcript is not phonetic alignment verification or an audio audition.

## Artifact integrity

The saved [integrity receipt](integrity.json) records file/hash, dimensions,
decoded index/PTS, beat coverage, source uniqueness, counts and local-link checks.
These mechanical checks are separate from the visual inspections above.

<!-- integrity-status -->
**PASS** — 342 hash-bound files; 213 unique decoded index/PTS checks; 264 local links; 0 errors.
<!-- /integrity-status -->

## Limits and application

Source audio was acquired but not auditioned. No uninterrupted real-time source
playback, exact font identification, independently verified business results,
retention causality or rendered adaptation is claimed. Purposes attributed to
visual choices are editorial interpretations; they are not known editor intent.
The study preserves counterexamples: competing text in LM04, reading density in
CR05, the deferred answer in LM05, and ambiguous result lineage/fast report
scrolling in LM06.

The catalog mapping records inspected implementations and specific gaps. It does
not qualify a new portrait scene or implement automatic selection, asset
retrieval or general catalog binding. Use the cases during prebuild direction,
then check the new Short's actual assets, font loading, crop, reading holds,
speech alignment and delivered answer in native Studio with audio.
