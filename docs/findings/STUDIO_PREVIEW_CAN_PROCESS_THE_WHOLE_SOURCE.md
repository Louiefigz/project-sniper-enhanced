# A Short preview can unexpectedly process the whole recording

Observed September 15, 2026 in the native pricing Short system test. The composition is 55.32 seconds; its source is a 31 minute 44 second iPhone recording. The prepared source preserves the original picture packets and uses lossless ALAC audio.

## What happened

The managed Studio startup passed resource admission and released its heavy-work lease once the server was ready. Opening Studio then caused stock HyperFrames 0.8.31 to launch a background H.264/AAC proxy of the **entire source**, rather than the five selected spans. Its partial file reached about 1.28 GB before the managed owner was stopped. Startup admission did not bound this later work. A persistent preview server is lightweight only while it remains idle.

The same source produced an unsupported-ALAC warning. That warning alone does not establish a playback failure: Studio has separate metadata, thumbnail, waveform and audio playback paths. The video proxy code handles video elements; it does not automatically replace the native project's separate dialogue audio elements.

The first export attempt was subsequently refused before child launch when kernel memory pressure was warning. After closing this task's Studio tab and stopping its server, a fresh sample reported normal pressure and 53% headroom. This is a measured sequence, not proof that Studio was the only contributor to system pressure.

## Keep preview preparation separate from rendering

The installed SDK supports this project setting:

```json
{"media":{"autoProxy":false}}
```

Set it on an **editable review copy**, before loading that copy. Preserve the checked production project and its receipts. This disables automatic conversion; it does not add codec support to a browser. Verify actual picture playback and seeking. When a browser needs another video codec, prepare only the required media through a supervised job instead of silently encoding the entire recording in the background.

For this native Short, the completed review adaptation uses the framework's existing program-length audio-track contract and the checked delivery's AAC soundtrack. Source video elements stay muted and retain their original cuts, and graphic layers remain editable. Audio should be stream-copied from the checked delivery, its 48 kHz sample clock verified, and its origin recorded. The intended 55.32 second clock is 2,655,360 samples. Moving source cuts after this adaptation requires rebuilding the soundtrack; graphic and title adjustments do not.

The adapter is a review artifact, not a new production renderer or automatic approval of modified HTML. Its live-browser checks and final result belong in the pricing artifact's review records. Automatic proxy suppression has been set on that review copy; it is not yet a universal shared-preview policy.

## A second source of time and disk cost

The native writer already requests `COPYFILE_FICLONE`, but that request permits silent byte-copy fallback. This machine's Node 23.10.0/libuv 1.50.0 combination therefore cannot use the flag as proof of physical cloning. Replacing the two new inactive source copies with verified `/bin/cp -c` APFS clones recovered 5.51 GB while preserving SHA-256 and independent inodes. This proves excess allocation existed across those copies; it does not identify which earlier copy operation created it.

The build also reads the 5.50 GB source at least four times for before/after source and staged-file checks, about 22 GB of hash input. Cloning alone cannot eliminate that I/O. Do not remove integrity checks to improve a benchmark. A future shared copy helper should report the actual copy method, keep exclusive destination creation and verification, and distinguish unsupported/cross-device clone fallback from permission, disk-space and identity errors.

## When not to apply this approach

- Do not disable automatic proxies and claim success when the browser cannot decode the actual picture.
- Do not point a browser audio track at an entire multi-gigabyte source merely because its final cut is short.
- Do not replace lossless production audio with a review codec inside a sealed project.
- Do not treat a low literal-unused-RAM value, historical swap or cache occupancy as current memory pressure. Use the shared capacity/pressure policy.
- Do not claim one successful native export qualifies automated editorial selection, subjective listening or every browser/codec combination.

Evidence: `artifacts/img7138-pricing-system-test-2026-09-15/` contains source diagnostics, storage consolidation, Studio preparation and preserved export attempts. The managed preview admission change separately passed 58 focused tests and independent semantic review.


## Cache space is a separate admission concern

The next supervised export started six source-frame extractions and correctly stopped when free disk fell below the 10 GiB reserve. The native work cache contained many older completed entries plus 4.30 GB of new incomplete frames. With all owners stopped, 20 regenerable cache entries were evicted under the shared heavy-work lock, reclaiming 22.63 GB of payload and leaving 30.44 GiB free. Originals, project files, finished outputs and failed-attempt audit records were retained. See `FRAME-CACHE-EVICTION.json` for the exact entries.

A startup disk minimum alone does not reserve enough space for future decoded frames. Admission planning should account for selected source resolution, frame count and expected cache size, with bounded eviction of inactive reproducible entries. Repeatedly retrying without reclaiming space would reproduce the same failure.

## Final result of this test

The third export passed in 12 minutes 48 seconds, including preparation,
604 native capture states and 542 encoded-frame comparisons. The SDK picture
render alone took 6 minutes 48 seconds. All three successful owners verified
cleanup; peak sampled owned memory was 7.45 GiB, with normal kernel pressure.
These times exclude editorial work and the debugging described above.

The audio-only Studio adapter completed in 4.32 seconds without another encode.
Live Studio showed original footage and editable graphics while playing and
seeking, with automatic proxying disabled. The local MP4 review passed play,
pause, seek, resume, natural completion and replay. Live testing also caught a
metadata event arriving before the page's module initialized; registering one
handler and invoking it when metadata is already ready fixed that race. Four
page smoke tests cover immediate and delayed metadata, invalid-duration recovery
and preserving active playback state on repeated metadata events.

See the pricing artifact's `LIVE-REVIEW.json` for browser observations and limits,
including remaining SDK warnings and the Studio display clock. No subjective
listening or universal browser/codec approval is claimed.
