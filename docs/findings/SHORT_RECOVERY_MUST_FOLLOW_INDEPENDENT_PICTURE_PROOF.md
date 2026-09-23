# Recover picture from its proof, not one particular audio failure

The September 16 Short automatic-recovery integration exposed a narrower donor
reader than the actual pipeline. A real two-second, 50-frame SDK picture completed
and closed its browser/transport. The subsequent AAC signal comparison failed:
one first-second channel measured 15.15 dB SNR against the unchanged 20 dB minimum.
The shared audio-quality list had not run yet. That failure correctly prevented
delivery, but the old SDK picture donor reader only recognized a failed item in
that later list, unnecessarily losing valid picture recovery.

The retained attempt is
`artifacts/workflow-enforcement-2026-09-16/short-integration-03/interrupted/`.
It remains failed. No audio threshold was changed to approve it.

The picture reader now accepts a recorded local-signal failure, a recorded
audio-quality failure, or a later failure after qualified audio. All cases still
require the exact owned SDK command, complete frame/assembly/transport trace,
unchanged picture bytes, packet identity, frame/sample clocks, original pinned
dependencies, and verified child cleanup. The failure record must match the
failed audio error where audio failed. Failed audio is never an audio donor.

The automatic selector can consequently retain that picture in a new attempt
while the ordinary audio/color/native/encoded gates run again. A completed final
MP4 uses the stronger existing render-stage seal instead. Repeated recovery must
also retain the whole earlier donor dependency closure, not reconstruct only the
latest source inputs and accidentally drop old proof files.

Do not apply this to an arbitrary `picture.mp4`, an incomplete SDK log, an aborted
picture owner, changed inputs, or unexplained output. A filename and an error
message are not completion evidence. The Short SDK donor tests cover both new
failure positions and rejection when signal stability or qualification is absent.
