# A safe output path is not enough: decode the resulting video

## What happened

The private prefix-composition adapter originally checked its output directory
before checking the approved-opening graph. A reviewer renamed that directory
and replaced it with a symlink before the encode. FFmpeg wrote into the retained
opening directory while the adapter returned success. Input hashes did not
detect this: the original inputs had not changed.

The reproduction used generated64×36 media, not creator footage. It produced
a9745-byte file in the wrong directory in471.224ms. Retained reproduction:
`/private/tmp/sniper-prefix-output-alias-repro.py`.

## Anchor the write, then check its name

The adapter now holds the original private directory descriptor throughout
the operation. After graph verification it reserves a new output with
`O_EXCL | O_NOFOLLOW`, relative to that descriptor (`dir_fd`).
The existing owned process runner passes only the explicitly held writable
regular-file descriptor to FFmpeg. The caller retains closing ownership.

FFmpeg writes through `-fd <descriptor> -f mp4 fd:`. Directory renames cannot
redirect that already-open file into another directory. Post-write observation
still rejects changed names/inodes and records the actual bounded SHA/size.
Failed partial outputs stay on their original inode; they are not selected.

The process runner's default passes no descriptors. Its opt-in accepts at most
four unique, owned, writable, single-link regular descriptors above stdio.
This is a local output capability, not source, media or approval authority.

## The first FD version still produced a bad video

On this host's FFmpeg8.0, combining the reserved `fd:` output with `+faststart`
returned exit0 and plausible MP4 metadata, but the actual composite contained
invalid H264 NAL units and failed a complete decode. A metadata-only prototype
had missed this. Retained failed output:
`/private/tmp/sniper-prefix-composition-zbwgt9pn/actual/picture.mp4`.

The likely mechanism is faststart's second-pass reopen sharing the descriptor's
file offset. This is an inference from the observed failure, not a claim that
every FFmpeg version or descriptor workflow has the same defect.

The private intermediate now uses `-movflags 0`: its moov metadata stays at the
end. The exact compositor graph, pixel format, codec and quality settings stay
unchanged. The existing final-delivery mux still owns normal faststart behavior.
There is no additional picture encode and no quality downgrade.

## Verification and limits

The independent10-test adapter cohort passed6.71s wall. It includes complete
24-frame fractional-rate decoding and equality of EVERY decoded RGB byte with
the ordinary same-graph, same-encoder faststart reference. The successful tiny
proof+encode took469.137ms before that external decode/reference test.

Three actual races are covered: parent replacement before reservation, parent
replacement at spawn, and replacement of the reserved filename with a symlink.
The original reproduction now rejects before creating output. A separate
17-test runner cohort includes real descriptor isolation and child cleanup.

This is not creator visual approval, audio comparison, encoded-output parity
between independently rendered opening/body files, or long-form throughput.
The future worker must bind this adapter in its execution closure, independently
decode/QC the whole output, reconcile owned processes and preserve approval gates.
Do not apply this private FD transport to sealed HyperFrames or normal final
delivery commands wholesale. Do not infer safety against hostile writers that
already hold the same output inode, or against arbitrary rollback of all files.
