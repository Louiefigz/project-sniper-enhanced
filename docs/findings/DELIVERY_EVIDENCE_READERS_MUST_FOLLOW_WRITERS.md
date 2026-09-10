# Delivery evidence must survive readback

The September 10 regression run found a valid four-second assembly that the
guided body reader rejected after the export completed. The writer had gained
`localSignal` evidence, but the reader still required the older exact field set.
The real-media test reproduced the failure in 18.355 seconds, including setup.

Checking the writer alone missed this integration problem. The useful test
assembled actual media, read the resulting receipt through `observe_body_media`,
and compared a second independent read. It exercised the boundary where the
format had changed.

The repair reuses `verify_program_delivery_signal` to decode the final audio and
compare it with the held program master again. Source/output hashes, every local
window, thresholds, and qualification flags must match the retained evidence.
The original `elapsedSeconds` is validated and retained because a new read takes
a different amount of time; it is telemetry, not permission to select media.

Resealing a receipt after changing its audio hashes, deleting window evidence,
or changing its verdict must still fail. A receipt without the new evidence also
remains unqualified. Unknown fields are not silently discarded.

The first repaired cohort passed 48 tests in 42.222 seconds, including the real
assembly/readback test and source-origin/local-audio fault tests. These small
fixtures do not establish human listening approval, native Studio parity, or a
full-video editing-time target.

Use this pattern when new evidence becomes part of a selection requirement.
Do not add repeated decoding to simple metadata displays, or reinterpret old
receipts as newly measured evidence just to make them compatible.
