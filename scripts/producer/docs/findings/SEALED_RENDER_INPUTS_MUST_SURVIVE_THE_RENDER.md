# Sealed Render Inputs Must Survive the Render

## Finding

A manifest and a tar digest are not independently reviewable evidence if the tar is
deleted when the render function returns. Retain the exact archive that crossed the
isolation boundary, bind it to the media proof, and revalidate both its outer digest
and every member on cold and warm paths.

## What exposed it

The G2 HyperFrames preflight initially retained `snapshotSha256` and seven manifest
rows, but `render_entry()` created `render-input.tar` inside a temporary directory.
The directory disappeared on return. A later reviewer could see what the controller
*said* it sealed but could not enumerate the bytes the container actually received.

The corrected preflight retained a 1,269,760-byte USTAR archive with SHA-256
`2d6e7ea6bfaa531ff0b798cc9356e586245e382bea87bd3984d4561f73a12459`.
Its exact eight-member closure was:

- the rewritten `section-marker` composition;
- `hyperframes.json`, root `index.html`, and `package.json`;
- `tokens.css` and vendored GSAP;
- canonical variables JSON; and
- the canonical input manifest itself.

The archive verifier rejects a digest mismatch, duplicate or extra member, link or
non-regular member, wrong member size, and wrong member hash. The cache promotes the
archive beside the MOV and copies/revalidates it on every warm hit. In the local
preflight, the cold path took 11.755 seconds and the fully re-proved warm path took
0.665 seconds with the same media hash.

## General rule

The render cache key should be a function of the exact sealed archive digest plus the
approved execution/proof closure. The proof should retain enough bytes to reproduce
that key and inspect the boundary later. Hashing mutable source paths separately is
weaker because the renderer may have observed a mixed or later version.

## When not to use this approach

Do not duplicate a multi-gigabyte source corpus beside every derivative. Put large
inputs in an immutable content-addressed store and retain the verified object ID plus
a durable availability receipt. A 1.3 MB composition capsule is small enough that
keeping the exact tar is simpler and safer.
