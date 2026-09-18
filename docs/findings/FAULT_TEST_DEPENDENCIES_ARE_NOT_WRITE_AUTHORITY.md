# Fault-test dependencies are not permission to modify them

## What happened

On September8, a new presenter-caption fault test selected `held.external[0]`
and wrote TEST bytes to it. The list included real production dependencies,
not only fixture files. Its first entry was the untracked production file
`scripts/producer/audit/audit_glitch_scan.py`. The test therefore damaged a
shared input instead of simulating a corrupted caption in its temporary root.

The intended assertion was sound: original held caption bytes changed after
the first encode must stop a second encode. The mutation target was not sound.
Membership in a dependency inventory establishes what must stay unchanged;
it does not grant write ownership. A name such as `external` is an additional
reason not to assume fixture ownership from position in a tuple.

## Containment and exact recovery

All parallel source writes and tests were paused. Recovery did not use HEAD:
the source file was untracked, so the checkout could not establish its original
contents. A retained capsule supplied bytes that matched two independently
captured preincident inventories, at03:54:16.935Z and03:54:59.297Z:

- Size:13013bytes.
- SHA256:`04a66fa1a1d492a24bd6e0cbd48d24e1c3c9cf98c9603514e3e5956d35e812f0`.
- Capsule:`/private/tmp/sniper-capsule-actual-20260907.rEbRi7/owner/capsule/repo/scripts/producer/audit/audit_glitch_scan.py`.
- Inventories:`/private/tmp/sniper-v8-presenter-durable-input-20260907-second-before.json`
  and the corresponding `second-after.json`.

The exact bytes were restored with apply_patch. A separate agent verified both
inventory rows, current size/SHA and byte-for-byte `cmp` against the capsule.
No other bytes were inferred from memory or reconstructed as an approximation.
The13-case hot-import test process was discarded as final qualification; fresh
processes are required after restoration. Modification/change times necessarily
changed. An original still-live stat hold must reject that change rather than
silently adopting new timestamps because the content hash is familiar.

## Required TEST mutation boundary

Choose a named, fixture-created target rather than an arbitrary dependency.
Before any append, replace, rename, unlink or link operation:

1. Retain the exact fixture root created by this test.
2. Require an absolute canonical path strictly below that root, without parent
   aliases. Verify the exact target also belongs to the intended fixture group.
3. Require a regular file with a single link; a path below a temporary root can
   still be a symlink or hard link to shared production bytes.
4. Where a descriptor is used, open without following links and compare the
   descriptor identity with the validated file before writing.
5. Reject before mutation if any check fails. Never reinterpret an external
   dependency as owned because the test needs something to corrupt.

The repaired live test chooses its actual `caption_pages.json`. Negative
no-write tests exercise a shared dependency, a lexical parent alias and
nonregular/multiple-link metadata. Those three guards passed in a fresh process.
The cold-reader TEST helper applies the same rule to its explicitly named plan,
page, shard and fixture probe, never to the whole external dependency list.

## When not to use this

Do not use mutation tests on a user's media, a real project workspace, shared
installed tools, or a retained production capsule. Read-only tests may inspect
those inputs, but faults should occur only in newly created exact TEST fixtures.
If an exact backup does not match independently captured prior identity, stop
and report recovery uncertainty rather than overwriting with an approximate
version and treating passing tests as evidence of restoration.
