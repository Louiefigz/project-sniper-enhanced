# Graphics-only picture still needs the shared delivery path

The 8.24-second membership style test uses the original speech with a full
graphics stage. Its compiled composition correctly has zero video layers and
one dialogue layer. A real export exposed two assumptions in the source-cache
adapter: batch planning required a nonempty video inventory, and frame transport
required nonempty source roots. Synthetic capture fixtures initially concealed
the second restriction.

The shared adapter now accepts an empty video inventory only when the actual
compiled video count is zero. An actual video with missing metadata or a missing
cache still fails. The graphics case keeps the existing 48-frame session ceiling.
Its reported zero workload refers only to decoded source-video pixels; graphics,
stills and browser allocations remain under the live resource supervisor.

With zero videos, leave frame transport unconfigured. Do not add a fake cache
directory or broadly expose the project folder to satisfy setup. Accidental
frame resolution still fails and its HTTP namespace returns 404. Original audio
remains under the existing original-media guard and parent audio finishing.
Zero video plus zero audio is not admitted by this native Shorts route.

The tests now use the real local transport implementation whose hash matches
the pinned runtime. They verify graphics capture, every output frame, reverse
checks, denied accidental resolution, mandatory dialogue, populated-video
compatibility and cleanup on failure. Fourteen focused tests passed before the
real export retry; tests alone do not establish rendered quality.

This is a source-backed spoken Short with graphics. It does not broaden this
workflow into arbitrary silent motion pieces, which have their own workflow.
The failed attempts remain in `export-member-full-stage-01` and `-02` under
`artifacts/shorts-qualification-2026-09-14`.
