# Studio media wrappers need active windows

## What failed

The earlier DMs Short could show a blank picture in live HyperFrames Studio
even when its video elements had the correct sources and `readyState === 4`.
The raw Skool H.264 media URL displayed correctly. Loaded media therefore did
not establish that the assembled Studio composition painted correctly.

The controlled diagnosis changed only the editable fork. Hiding inactive media
ancestors with `display:none` restored the picture. A separate
`visibility:hidden` ablation also restored it. The authored `clipPath` remained
unchanged, so removing that crop was not required for the observed recovery.

Evidence is retained in the batch's
[Studio display diagnosis](../../artifacts/img7138-remaining-shorts-2026-09-15/studio-display-diagnosis/):
[before](../../artifacts/img7138-remaining-shorts-2026-09-15/studio-display-diagnosis/dms-index-before.html),
[inactive wrappers only](../../artifacts/img7138-remaining-shorts-2026-09-15/studio-display-diagnosis/dms-index-inactive-only.html),
and [visibility only](../../artifacts/img7138-remaining-shorts-2026-09-15/studio-display-diagnosis/dms-index-visibility-only.html).
The original DMs fork was restored to SHA256
`04e846f739514b81378546af89dce35c167f0b545894d7beed26490be63df59c`.

## Why the parent matters

The framework owns the timed child `<video class="clip">`. Its crop and pose
ancestors can be ordinary, untimed `<div>` elements. A valid child source and
clock do not prove that these surrounding layers have the correct active
window in Studio. The ablations isolated inactive ancestors as the useful
control point; they did not establish a general decoder or clipping defect.

For a media-only wrapper, use the child's interval `[start, start + duration)`.
Show the wrapper during that interval and remove it from display outside it.
For example, a source crop active from 5.88s through just before 16.28s gets:

```javascript
tl.set("#source-crop-0-2", {display: "block"}, 5.88);
tl.set("#source-crop-0-2", {display: "none"}, 16.28);
```

Initial CSS must also match time zero: wrappers starting at zero use `block`;
future wrappers use `none`. This avoids depending on a first seek to establish
the opening picture. `display:none` gates descendants even if a child authors
its own visibility. The capture engine's frame-image behavior is a separate
path and was not evidence that this Studio-only fix had passed live testing.

## The bounded implementation

[native_media_visibility.py](../../scripts/producer/studio/native_media_visibility.py)
validates the native canvas, finite media clocks, unique IDs, and a crop/pose
chain containing only one video. It rejects shared/textual containers, already
timed wrappers, existing visibility/display ownership, malformed HTML, and
repeated adaptation.

It inserts initial CSS and deterministic GSAP boundary sets into the editable
Studio fork. Its receipt records both exact insertions, every wrapper window,
source/output hashes, and recovery of all unrelated original bytes. The
[batch Studio adapter](../../artifacts/img7138-remaining-shorts-2026-09-15/prepare_studio_review_contract.py)
keeps this proof separate from its assembled-audio replacement proof.

The SDK runtime and checked production HTML remain unchanged. This is a
review-surface adaptation, so rewriting a qualified runtime or a sealed
production manifest would change a wider contract without supporting evidence.
The adapter pins the helper in its supervised input closure and preserves the
original production files and individual fork provenance.

## Verification and remaining limits

- Seven pure tests passed for admission, exact windows and source preservation.
- Actual GSAP 3.14.2 executed the generated commands against plain-object
  display targets: 126 checks across 18 forward, backward and boundary seeks
  passed. These are timeline-state checks, not browser paint checks.
- The actual 1,521-frame Outreach HTML passed integrated audio/visibility
  transformation with 11 media wrappers.
- The three checked batch exports were subsequently opened in one managed
  Studio workspace. Actual browser screenshots showed their openings, real-page
  inserts, diagrams, presenter returns and endings after forward/backward seeks.
  Each main preview contained one loaded assembled AAC track; playback advanced
  without a media-element error. The old preview viewport offset initially hid
  part of a title; **Reset zoom to fit** restored the complete frame without a
  source edit. See the batch's `STUDIO-LIVE-REVIEW.json` for the sampled times.
  These observations establish sampled browser painting and playback state,
  not subjective audio approval or exact phonetic word synchronization.

Do not apply this to shared layout containers, wrappers containing labels or
multiple videos, already timed/visibility-authored ancestors, or unsupported
HTML. Do not use it to conceal missing media, wrong source selections, audio
problems, or a failed encoded render. Source/cut changes still require rebuilding
the assembled Studio dialogue and renewing the applicable checks.
