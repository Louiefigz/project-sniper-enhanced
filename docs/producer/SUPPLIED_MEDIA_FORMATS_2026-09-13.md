# Supplied media format admission

Folder discovery and native Short selection have different responsibilities. Shared
Producer ingest still recognizes the raster, video and audio formats used by the
long-form route. It keeps each admitted snapshot, original path, SHA256, byte size
and sandbox admission receipt in the supplied inventory. An inventory entry is
available source material; it is not permission to select an unsupported native
format or a claim that the image has been visually reviewed.

SVG and SVGZ now receive an explicit error when supplied as a direct input, a
top-level folder input or a nested B-roll file. Previously, the extension filter
could silently omit these files. Candidate collection rejects them before the
sandbox runner or host ffprobe executes. A bounded rejection check also blocks
XML/gzip document headers masquerading as raster files and opaque `.media`
snapshots. Cataloging rejects a retained `svg` media kind and direct extra B-roll
rows; it cannot reinterpret that admission label as an ordinary still image.

A UTF-16/UTF-32 BOM alone is not a document signature: `FF FE` also begins a valid
MPEG-1 Layer I audio frame. The bounded check decodes the prefix after that marker
and rejects document-shaped text beginning with `<` after whitespace. A prefix
containing only whitespace is rejected rather than skipping beyond the bound. Binary
headers continue to the existing sandbox admission and media probe. Tests include
this exact signature collision as well as UTF-16 SVG in both byte orders.

This does not add an SVG sanitizer or expand native SVG support. The existing
sandbox SVG probe is a bounded document check, not a general resource-closure
validator. In particular, its acceptance is not proof that every relative URL,
event attribute or embedded resource is safe for native browser rendering. This
ingest route therefore rejects the document instead of attempting to rewrite it.

For a supplied SVG logo, provide a local PNG, JPEG or WebP derivative and admit
that derivative independently. Preserve the original source/provenance when
authoring its origin record. No automatic conversion, invented approval or
reclassification as public-web media occurs here.

Formats such as GIF, BMP, TIFF, WebM, MKV and AVI remain available to shared ingest.
The native `AssetRecordV1` MIME contract remains the selection gate. An unsupported
native format needs a separately admitted local derivative before selection;
being included in `availableSupportingAssets` does not change that requirement.
No second native MIME table is maintained in Python.

Validation uses tiny fixture bytes and mocked admission/probe callbacks. It checks
explicit direct/folder rejection before runner invocation, renamed active or
resource-bearing documents, opaque snapshots, retained SVG kinds, extra B-roll
rows, and continued snapshot/provenance handling for all 16 existing shared
image/video extensions. These are ingress tests, not media render tests.

## Supporting-media control and additive rescan

The project card now offers **Add supporting image or video** before guided cut
acceptance. Its dedicated native picker accepts PNG, JPEG, WebP, MP4 and MOV,
up to 1 GiB per file. The ordinary source picker keeps its movie/audio behavior.
The selected file is copied through the existing stable stream-copy path into
an exclusive hidden staging directory; only a completed copy and SHA256 receipt
are renamed into the scanned B-roll folder. This is staging, not decode admission.

The control and existing **Rescan after adding** action call ordinary ingest
with `reuseTranscripts: true`. CLI callers
can use `--reuse-transcripts`; it is mutually exclusive with `--no-transcribe`.
This mode requires a prior admitted manifest and verified transcripts. It retains
the complete verified old ingress set, including externally referenced recordings,
reclassified source-folder images, external B-roll and music. Existing asset IDs
remain stable; new IDs avoid collisions. Every retained supplied file is admitted
again and must keep its bytes. The source-bound transcript files must remain
byte-identical. No ASR/provider fallback is permitted.

Only after all checks does the caller atomically publish the new manifest. A bad
new file, changed/missing original or changed transcript leaves the previous
manifest in place. The staged file remains available when admission fails, with
an explicit incomplete-preparation message. Prepare a new Short brief after a
successful rescan; an old frozen request cannot silently incorporate new media.

Eleven focused intake tests exercise real stream copying, cancellation, callback errors,
FIFO replacement, source restrictions, request validation and client SSE failure handling. Format acceptance
and actual media admission have separate tests; neither the picker nor a passed
extension check establishes visual suitability or native rendering support.

Three actual sandbox-admission/rescan cases now pass: copied recording + PNG,
referenced recording + retained old supporting images + PNG, and bad image or
changed recording rejection. They ran in 11.137s; complete supervised execution
and exact cleanup took 58.967s. All 14 requested containers were proved absent.
These are one-second synthetic media fixtures with test-only words over a tone,
not speech-quality or native rendering qualification. See the
[integration receipt](SUPPORTING_MEDIA_AND_GUIDED_BUILD_2026-09-13.md).

Two additional tests passed through the actual `ingest.main()` entry, including
real argument parsing and atomic manifest publication. A successful rescan
replaces the manifest inode while preserving old bytes through an already open
file descriptor. An invalid PNG exits nonzero and preserves the old inode,
manifest bytes and transcript bytes. These took 5.608s worker time and 24.908s
including the owner and exact cleanup of six containers. This is in-process
main-entry coverage, not a separate CLI process or complete HTTP request run.

Four subsequent **real Next HTTP/SSE tests pass**, including seven separately
spawned Python CLI processes. The app stages a supplied PNG, admits it through
the actual rescan, preserves copied or externally referenced source identity and
exact transcript bytes, and publishes the new manifest. Invalid media preserves
the prior files; active writers and guided checkpoints reject mutation before
Python starts. The tests took 11.120s, with verified server/process cleanup and
all ten containers absent in a 49.854s complete owner run. This closes HTTP and
separate-process coverage for those cases; the native picker dialog and visual
suitability remain separate from format acceptance.

The other supported intake formats now also pass one actual HTTP test: H.264/AAC
MP4 and MOV, JPEG and WebP were generated as real formats, staged together,
then admitted into one manifest with distinct IDs and verified snapshot hashes.
Source/transcript bytes stayed unchanged. The test took 4.946s; complete ownership
and six-container cleanup took 28.404s. This qualifies those concrete codec
fixtures, not every codec carried in MP4/MOV. A previous monitor-interrupted
attempt is retained as failed in the integration receipt.
