# Exact-frame rendering must not reload original media

A short timeline can still make a browser load a large recording several times.
The September 13 integration used a 38.64-second timeline, four camera views of
one 10,280,473,262-byte 4K recording, one website recording, and three dialogue
elements. Its exact source PNGs were already available. Nevertheless, the SDK
initialized the original video and audio elements with `preload='auto'` and
`load()`. Hiding those elements did not prevent their original media requests.

The distinction matters: the native screenshot injector supplies the actual
source pixels, and the parent FFmpeg path supplies the final dialogue. Browser
decoding of the original recording serves neither output in this route.

## What the failed runs established

The default concurrent SDK extraction stopped at 29.574 seconds when compressor
occupancy crossed the existing limit. Sequential SDK extraction subsequently
published all 643 exact source frames in 13.397 seconds of extraction work,
without changing source resolution or frame identities.

Browser capture remained a separate problem. A 48-frame session stopped after
19 screenshots with a sampled process footprint of 3.457 GiB. An eight-frame
session plan still stopped during its second browser, after 15 screenshots,
at 3.001 GiB. That second run had only one populated 4K frame image. Counting all
declared video elements as simultaneously active PNGs did not explain the
observed memory. All failed attempts retained their receipts and verified
cleanup. The 4 GiB owned-tree and 3 GiB process limits were not raised.

## Remove the redundant input path

`native_original_media.mjs` builds an exact URL contract from the compiled local
video/audio sources. Before navigation, cached picture and QC sessions suppress
only those original URLs. PNG transport, fonts, scripts, source geometry and
the frame clock remain unchanged. Unexpected browser media requests fail closed.
CDP records any received bytes for the original URLs, and nonzero observations
fail the session. The normal preview and parent dialogue renderer keep access to
the original recording. The helper is included in export and picture-reuse pins.

Use the shared `withNativeCaptureSession` lifecycle; do not add a separate
unowned browser or a second loading policy at individual call sites.

Source hashing also needed a lifecycle fix. Four views synchronously rehashed
the same 10GB file four times while SDK background probes were exiting. A failed
receipt observed the same already-exited child over four spaced samples.
Streaming SHA-256 in 1 MiB chunks yields to child-exit callbacks; per-preparation
metadata/hash reuse avoids repeated reads. Canonical device/inode/size and
nanosecond modification/change timestamps guard reuse, with checks after reads.
The resource monitor and source pins remain authoritative.

## Qualification boundary

The owned `media-equivalence-02` experiment passed in 50.495 seconds. All 15 JPEGs
were byte-identical to the retained original-path screenshots across two fresh
sessions. Typography and source-frame checks passed. The two browsers suppressed
32 original-media requests and observed zero original payload bytes. Sampled
owned-tree/process peaks were 0.527/0.247 GiB, versus 3.352/3.001 GiB in the failed
eight-frame attempt. These are sampled peaks in those runs, not continuous peak
guarantees or a general speed benchmark. Source/tool pins and cleanup passed.

An earlier diagnostic also matched all frames, but its launcher paired a Node
executable path with the SDK CLI hash. The owner correctly rejected that identity
mismatch. The failed receipt remains; the corrected launcher was rerun, without
changing production code or relaxing any check.

Later website scenes, graphics, reverse seeks and final audio require the
complete export checks. A first-15-frame experiment does not qualify the whole
Short or other media combinations.
Live results are recorded in `SHORTS_VISUAL_STORY_INTEGRATION_2026-09-13.md` and
`artifacts/native-short-storytelling-2026-09-13/`.

Do not apply this suppression to browser-native video playback, interactive
product recordings, an incomplete frame cache, or a composition relying on
browser audio. Do not blanket-block file extensions or claim a browser-load
optimization changes the underlying recording or its publication rights.

## Use actual render observations as the forward baseline

The complete revision-6 picture captured all 966 frames. Its 121 disposable
sessions took 217.739 seconds in total; picture rendering including preparation
and encoding took 266.740 seconds. The next revision's QC schedule contained
526 forward points and 280 reverse occurrences. Repeating all 806 screenshots
in 101 fresh sessions projected about 182 seconds of capture alone, before
preparation or assertions, against the unchanged 180-second QC stage deadline.
That projection was a planning estimate, not a measured failed QC attempt.

The shared renderer now runs the existing typography and visual-state checks
on the required forward points while it captures the actual full picture.
Those observations, source payloads and JPEG hashes become the forward baseline
for encoded comparison. QC verifies the exact current plan, checking code,
compiled output, runtime, encoder, session disposal, original-media guard,
picture bytes, retained JPEGs and active source PNG payloads before reusing them.

Every required reverse occurrence remains independently captured. Each fresh
reverse session is seeded at the last valid frame before descending, with one
slot reserved for that seed. Thus the eight-frame bound permits at most seven
checked reverse frames plus one seed. A one-frame bound uses the historical
full-replay path. Seed images have unique retained paths. The logical forward
and reverse inventory and final encoded pixel/decode checks remain complete.

This removes a second independent forward replay; it does not provide identical
replay independence. Receipts distinguish render-observed baselines from fresh
reverse captures. Historical absence of new evidence permits full replay;
malformed or incomplete new evidence fails. Picture donors must carry the exact
pinned receipt and source-image locations, with the new helper in their code pins.

The cold receipt reader admits only regular files of at most 32 MiB before
opening, uses nonblocking/no-follow descriptor reads bounded by admitted size,
and checks descriptor and path identity around the read. It hashes the validated
bytes. Generation observes the same size limit. Typography assertions retain a
compact passing observation hash alongside full visible state rather than
duplicating all off-screen word rows hundreds of times.

Nineteen focused synthetic forward-QC tests and thirteen existing capture tests
passed, as did twelve Python donor tests and targeted ESLint. These tests launch
no media processes. Independent review caught and corrected the extra seed slot
and premature unbounded receipt hash before real qualification. The complete
real-run result is recorded separately in the integration report.


## Complete integrated result

The corrected revision-8 full run passed in 470.098 seconds for 966 frames
(38.64 seconds at 25 fps), using the source-frame cache prepared by preflight.
Fresh picture preparation/capture/encoding took 254.377 seconds. Forward
baseline validation and 280 independent reverse occurrences took 111.891
seconds within the unchanged 180-second stage deadline. All 526 final encoded
comparisons and full audio/video decoding passed. Sampled owned/process peaks
were 1.082/0.908 GiB, and source/tool pins plus owned cleanup were verified.

This run qualifies the complete tested combination of presenter, actual page
recording, diagram, captions and dialogue. It does not establish every other
media combination or a cold transcription-to-export speed benchmark. The
preceding revision's same optimized checks caught a real reverse-only page
visibility defect; the failure was fixed in the composition instead of weakening
QC. See the [integration report](../producer/SHORTS_VISUAL_STORY_INTEGRATION_2026-09-13.md)
for final MP4 identity, individual timings and review limits.
