# Actual picture observations need lossless proof transport

A successfully observed or encoded picture can still fail at the receipt
boundary. Test the real returned object through the same serialization domain
used by its eventual consumer, not only through in-memory equality.

## What the tiny test found

The first two-case presenter-prefix cohort used actual 64×36 PNG/video inputs,
crossing and future layout windows, and a synthetic alpha page. It took
3.249 seconds in the suite / 6.31 seconds wall and exited 1. Its timings
overlapped another tiny owner test, so they are not isolated benchmarks.

The still case completed the actual prefix comparison and picture encode, but
`json.dumps` then failed on raw PNG chunk bytes retained in its observation.
It never reached the separate ordinary-reference comparison. The video case
passed all 24 decoded RGB frames against the ordinary identical compositor.

Retained evidence:
`/private/tmp/sniper-presenter-observer-media-dgvjyny_`.
`TEST-terminal-failure.md` records the authoritative terminal failure. The
initial TEST aggregate writer incorrectly let the later video success overwrite
its failed status; the fixture now keeps failures sticky. Do not read the old
aggregate `status: passed` as a successful cohort.

## The repair preserves the observations

The actual observer still holds immutable bytes and integer stat identities.
Only the prefix proof's JSON projection changes:

```python
{"metadataEncoding": "hex", "metadata": [[kind, payload.hex()]]}
{"statIdentityEncoding": "decimal-strings",
 "stat_identity": [str(part) for part in original_nine_part_identity]}
```

Ordered PNG chunk names, lengths, hashes and metadata bytes remain exact.
Decimal strings are necessary because inode/nanosecond values can exceed
JavaScript's exact integer range. A Python `json.dumps` success alone would not
catch that second defect. The pure regression now requires JSON roundtrip,
lossless byte/integer reconstruction, and equal cross-runtime canonical hashes.
The corrected focused cohort passed 28 tests in 0.077 seconds suite / 3.16
seconds wall before the final serial native rerun.

## What this does not prove

These are TEST-only source-admission records around genuine local observations.
Neither a type, a JSON record nor a matching hash grants source admission,
rights, framing, audio, delivery, or profile-release authority. The live owner
must retain the actual returned observation, its independently held source/tool
bytes and original deadline. The prefix layer validates that evidence without
decoding the selected presentation asset again.

Do not stringify arbitrary Python objects to silence serialization failures,
drop metadata fields, round large integers, or cold-load a record and treat it
as a newly completed execution.
