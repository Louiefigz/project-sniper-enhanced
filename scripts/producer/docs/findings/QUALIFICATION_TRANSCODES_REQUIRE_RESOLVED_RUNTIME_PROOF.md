# Qualification Transcodes Require Resolved Runtime Proof

## Assertion

A correct-looking ffmpeg command and mocked Docker inspect are not enough to
authorize a large qualification transcode. The exact pinned image must execute
a bounded synthetic cohort, and Docker's resolved launch must be attested.

## The incident

The first over-cap mezzanine worker passed all seven original unit tests but
was not safe to run on the 9.57 GiB long-form source.

Independent review found four gaps before the source was touched:

1. the container proved only source size, not the bytes it decoded;
2. cancellation between two hard links could leave a partial publication;
3. output audio duration and decoded sample coverage were unproved; and
4. pathname-based chmod, cleanup, and rollback had race windows.

After those were fixed, a synthetic approved-image run found two more defects
that mocks could not reveal:

- the pinned image contains FFmpeg 4.4.2, which rejects the newer
  `-fps_mode` option;
- Docker reports the 256 MiB tmpfs as `size=256m`, while the mock reported
  the equivalent `size=268435456`.

## Evidence

The corrected networkless synthetic cohort used a 48-frame
`24000/1001` source and produced:

- 48 frames at exact `24/1`;
- H.264 High, level 4.2, 1920x1080, 1:1 SAR, limited-range BT.709;
- an exact 96,000-sample, 2.0-second stereo timeline;
- 96,256 decoded AAC samples, with the 256 codec-padding samples explicitly
  recorded rather than mistaken for program duration; and
- identical in-container source SHA-256 values before and after transcode.

The exact production launch/inspect/removal path was then exercised with an
intentionally undersized fixture. It passed isolation attestation, returned
only the expected source-bound rejection, and proved canonical container
removal.

Fourteen focused tests now include cancellation between publication links,
post-publication verification and cleanup faults, source-hash disagreement,
short audio, symlinked stage media, and failure-path container removal.

## The principle

Qualification evidence must bind all four authorities:

1. **input bytes** — host pre/post hashes equal container pre/post hashes;
2. **resolved execution** — pinned image, command, mounts, limits, and network;
3. **program clocks** — exact video frames and audio timeline samples; and
4. **publication ownership** — no-follow descriptors and exact created inodes.

Publish evidence before media. Cooperative cancellation rolls back both names,
and abrupt process death between the two link calls leaves evidence without
media. This is deliberately an evidence-first transaction, not a claim that
two POSIX names form one power-loss-atomic commit.

## When not to use this approach

Do not use this conversion for a source already within the immutable 8 GiB
admission cap; normal external-media admission is the authority. Do not use it
to normalize VFR, missing/ambiguous color tags, multiple video or audio
streams, or media that cannot retain at least the minimum video bitrate under
the cap. Those inputs require a separately approved policy, not a relaxed
qualification receipt.
