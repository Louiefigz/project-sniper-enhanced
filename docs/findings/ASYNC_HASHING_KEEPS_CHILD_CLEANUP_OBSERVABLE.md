# Asynchronous hashing keeps child cleanup observable

## The failure

The standalone source-cache alias recovery performed SDK compilation, then
hashed several gigabytes of source files and retained PNG frames synchronously.
Two supervised attempts stopped after approximately 15.7 seconds with
`MissingProcessFootprint`. Node itself remained alive at roughly 226–233 MB.
The missing child PIDs, 91872 and 92171, had nonzero exit times and zero measured
footprints across all four resource-sampling retries.

This evidence was consistent with exited SDK children waiting to be reaped
while synchronous hashing blocked Node's event loop. Repeating the attempt did
not resolve the condition.

## The bounded fix

The standalone helper now uses the existing asynchronous streaming hasher:

```javascript
const sha256 = await nativeCaptureSourceHash({}, file);
```

The fresh context matters: each verification must read the current bytes,
including repeated checks of the same path. Sharing a memoized context across
checks would undermine mutation detection. Reads remain sequential and bounded;
file canonicality, device/inode, size and nanosecond timestamps are checked
around them. There is no new concurrency or change to resource thresholds.

Twenty-four focused tests passed independently, including event-loop yielding,
fresh repeated reads and mutation during a read. The next live attempt was held
before launch by kernel memory pressure. After pressure returned to normal,
attempt 04 prepared 11 exact cache-directory aliases in 35.4 seconds with
verified cleanup, zero source extractions and zero picture encodes.

Evidence: `artifacts/img7138-remaining-shorts-2026-09-15/outreach/`
contains the four `source-cache-alias-*` attempt directories. The implementation
is `scripts/producer/studio/source_cache_alias.mjs`. All 140 recorded Producer
script pins from the existing render remained unchanged during this repair.

## When this does not apply

Do not treat every missing process footprint as an exited-child race. Confirm
the recorded process identities and exit evidence. Do not waive measurements,
invent a footprint, skip fresh hashes or reuse a cached hash after mutation.
Successful cache recovery also does not certify the final encoded video; its
normal final checks still have to run.
