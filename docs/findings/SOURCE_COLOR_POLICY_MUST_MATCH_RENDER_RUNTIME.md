# A color transform must match the actual rendering toolchain

## The mismatch found on September8

`scripts/producer/color/source_picture_transform_contract.py` accepts a specific
FFmpeg8.0/libzimg3.0.6 transform class with separately bound executable/library
hashes. The actually approved rendering image instead records FFmpeg
4.4.2-0ubuntu0.22.04.1. Copying the filter string into that image would not
qualify the specified transform.

The approval is `scripts/producer/headless/render_image_approval.json`, raw SHA
`0f4e356571d3cd03914ce3f6e875763e18cab3fea96b274e4cfdf65035c1e369`.
It binds image
`sha256:b96bfe4a5b828eb99bebc26209cd005d1ab1a658a13f14d70cf596f3e27ca686`
and `/usr/bin/ffmpeg` SHA
`5b53d938b60170b22003b05d5aa8cbbc73d98c06ff2e2b73e4e0a0cf4448c569`.
The inherited Dockerfile does not establish actual zscale availability or its
libzimg closure. This finding came from read-only code/retained approvals, not
a newly executed container capability probe.

This mismatch applies specifically to putting the transform inside that image.
The compiler does **not** mandate Docker, and the ordinary cut stage uses host
FFmpeg. A real host8.0/zimg3.0.6 tiny-math closure already exists; do not mistake
the image mismatch for proof that a host transform is impossible or replace
tools unnecessarily. `/private/tmp/sniper-picture-transform-0my1m7j7/TEST-ramp-calls.json`
records host FFmpeg SHA
`d94d8e7af675f813e0a0faf036ff936d334ceb18daaec3a10a355679994e0311`,
libavfilter SHA
`8b9fc1afe025358a31c50047b92ec28a611e1af94449289e53b2fbc1b7b0fe15`,
and libzimg SHA
`819b778478990bc932fbd276ca574d29d9bc2fc7cf7a892f41357f58ac496951`.
Tiny uniform-patch residual1.19e-7 and zero output-code error at three rates
are limited math evidence, not full-source gamut, live tool freshness, owned
transform execution, creator history or whole-video qualification.

## Smallest useful path

Known BT.709 footage with explicit known history and no requested new look can
use a distinct identity/no-conversion class. Its genuine completed observation
must include already-held probe/frame evidence for square pixels, no rotation
and supported consistent signaling. Missing facts must not default to identity.
Do not delete a requested look to squeeze footage into this class.

Identity preserves declared source interpretation; it is not a measured RGB
gamut guarantee or creative approval. It need not wait for an xvYCC converter.
Keep original audio source paths and the existing float master unchanged.
Validate before the first lossy picture encode and before output publication.

A separate FFmpeg4.4 conversion policy might be feasible with the installed
image, but needs a separately authorized capability/closure check and actual
reference qualification. It must not silently relax the existing8.0 contract.
No download or image replacement is assumed necessary or authorized.

## Why streaming alone does not establish the time target

The present xvYCC contract requires every channel of every native pixel to be
finite and within[0,1] after its specified chroma reconstruction/linearization,
before destination conversion. Existing V2 ffprobe observations collect frame
metadata, not those RGB measurements.

C0679 has20,004 UHD frames:165,921,177,600 pixels. Float RGB would traverse
1,991,054,131,200 bytes even if nothing is stored. Passing that stream in the
1,200-second observation phase alone requires about1.66GB/s, excluding decode
and arithmetic. Tiny uniform-patch references establish neither spatial chroma
behavior nor UHD throughput.

Reduce inside the existing isolated worker and retain small source/tool-bound
extrema, nonfinite/out-of-range counts, exact sample/frame counts and actual
EOF/frame-clock evidence. A Node reducer uses installed tooling but still needs
measurement; an AVFrame-native reducer adds a separately qualified compiled
dependency. Raw byte count alone loses PTS/duration evidence. Combining proof
and conversion into one pass would change the current pre-conversion contract.

Do not promise two-hour output or bypass source history, gamut or runtime gates
from these arithmetic estimates. Known BT.709 and xvYCC are separate supported
classes until actual qualifying evidence connects them to the renderer.
