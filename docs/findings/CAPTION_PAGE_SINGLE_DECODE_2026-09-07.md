# Caption page proof: one decode, unchanged evidence

Implemented 2026-09-07. This is a PAGE-proof optimization, not a new renderer,
caption quality approval, source qualification, or shard optimization.

## Result on identical retained bytes

An actual ~30-second PNG/RGBA alpha page from the completed captioned TEST run
contains899frames at30000/1001,1920x1080,41,203,062bytes. The old and new
algorithms produced byte-identical ENTIRE framemd5 output (72,142bytes,
including all headers), byte-identical every-frame alpha metadata (61,079bytes),
and equal public proof dictionaries with Python float alphaMax255.0. The decoded
hash also equals the immutable old receipt:
fd95405f5733391690a5d300e554ef0e53418903a6ed7a2aee4eeb5699df3ee9.

| Same page, test order | Old proof | New proof | Reduction |
|---|---:|---:|---:|
| Old first |25.733s|10.459s|59.4%|
| New first |25.968s|11.404s|56.1%|

First old leg: frame-count probe9.114s +RGBA framemd510.193s +alpha6.425s.
First new leg: metadata-only probe0.061s +single split decode10.394s.
Second new-first leg: metadata0.114s +decode11.285s. The test ordering exposes
cache/order bias; it is not a statistical performance distribution.

A/B total times36.237s and37.416s include shared exact file/tool/code observations.
Initial/final hashing cost23.091/21.114ms and23.076/20.849ms respectively.
There is no extrapolated whole-program speedup: the observed471.613s caption
stage also included81shards,11pages, compilation and rendering.

## How it works

Previously the page proof decoded all frames3times: ffprobe -count_frames,
framemd5, then alphaextract/signalstats. The metadata probe now does no counting.
One strict-EOF owned FFmpeg process splits the same decoded frames into:

- untouched whole-RGBA framemd5 stdout;
- all-frame alpha metadata stderr;
- terminal progress on one new held regular descriptor.

The parser requires the exact frame count, zero dup/drop, one final end record,
exact rawvideo payload size/rational clock, complete alpha pairing and finite
bounded alpha occupancy. No seeking, frame cap, resize, skipped gap, or sampling
can turn an incomplete decode into proof. The public result schema is unchanged.

Implementation:
scripts/producer/captions/caption_page_decode.py and caption_page_proof.py;
surgical caption_page_media.py delegation; shared explicit identity map in
caption_pages.py mirrored by guided_caption_identity.py.

The caller still owns source/hash/font/plan/timeline/currentness. Existing
whole-page byte checks and stronger independent readbacks remain in place.
Both ordinary compositor identity and held projection dependency identity bind
the new helpers plus reused progress/runner/deadline code. Old compositor
receipts become stale normally; none were resealed or re-admitted.

## Regression and process evidence

Final combined53tests PASS3.759s suite/3.88s wall:
test_caption_page_proof, test_caption_page_decode,
test_caption_page_draft_integration, test_caption_pages,
test_caption_page_native_proof, test_guided_caption_projection,
test_guided_caption_records.

Actual tiny regressions cover integer/NTSC one-frame and transparent-gap pages.
Six actual defect controls reject: wrong canvas/rate, valid clip missing its last
frame, empty alpha, truncated container, and corruption in the final PNG packet.
No timeout/setup error is counted as defect-recall success. New native tests
retain each old/new channel and failure under a private TEST root.

A real probe started under the original1ms deadline throws ProcessDeadlineError
and returns no proof. Matching spawned/reaped rows plus actual group absence
are checked by the native regression. Across the retained qualification cohorts,
147recorded spawned groups match147reaps; every group was independently absent
at final observation. This is not external-crash recovery or native RSS proof.

Actual tiny ordinary source-float render →returned caption projection→capture→
strong read→new-only AuditB dependency staging also passes2/2:
11.651s suite/12.31s wall. Capture60ms, read32ms, staging67ms. A second read traps
materialization/cache/recompilation and verifies unchanged original inventory.
This separate test is mechanical integration, not a guided job or approval.

## Exact retained evidence

- Initial native fixtures/defects/ledgers:
  /private/tmp/sniper-caption-page-native-ZQFU5R
- Same page old-first:
  /private/tmp/sniper-page-ab-retained-30s-20260907-first/result.json
- Same page new-first:
  /private/tmp/sniper-page-ab-retained-30s-20260907-reverse/result.json
- Final native regressions:
  /private/tmp/sniper-page-proof-regression-ioj7wm6l
- Actual returned projection:
  /private/tmp/sniper-held-caption-media-lp368366/helper-evidence.json
- Initial draft, pure history and TEST old comparator rationale:
  /private/tmp/sniper-caption-page-proof-draft-mTJMrn/README.md

Input page is the unchanged full-program-base caption-page-70900b0778f2578f0e373af531ccfd81210b655ae983ee01814446690bc64026.mov
in the completed lyq4t3 TEST producer's opening execution b135538b-bca7-4098-8714-798ab935b766.
Whole page SHA256cb1f441baf6ce29b1b80da575f256a648687cbdbd6aad362ebada07c1d905ed1.
Every A/B records its exact absolute path, bytes, tools, argv and implementation.

## Limits and when not to generalize

Only pages are consolidated; shard edge/bbox proof is unchanged. Do not replace
independent source, presentation, packet/audio, font or QC authority with this
decoded proof. Do not remove terminal progress just because framemd5 has some rows.

Captured stdout+stderr is capped16MiB; held progress64KiB is checked after return.
The existing original process deadline/group cleanup is reused. This is not an
OS memory quota or disk-write quota for native FFmpeg. No provider/download,
C0679 decode, old receipt rewrite, full workflow rerun, or creative approval was
performed. The old full-run pipeline/agenda text-occlusion finding remains a
separate visual-quality failure; page equality does not fix that composition.
