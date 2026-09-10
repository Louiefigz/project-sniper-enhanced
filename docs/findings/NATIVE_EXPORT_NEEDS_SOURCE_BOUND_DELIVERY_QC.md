# Native render success is not delivery-quality success

Observed on2026-09-09 in the fresh-input C0679 B trial, using installed
HyperFrames0.8.31 with the private native PNG URL transport. This is measured
local evidence, not a claim about every SDK version or every source format.

## What happened

The native renderer successfully produced15,761 frames at24000/1001fps,
1920×1080, with complete source-frame coverage. Its process guard passed.
Yet independent delivery checks found three defects:

| Check | Native output | Corrected copy |
| --- | --- | --- |
| Presented audio samples |31,553,520 |31,553,522, matching the frame-derived plan |
| Source-aligned audio SNR |24.823dB |34.297dB |
| Audio true peak |−0.78dBTP |−1.09dBTP |
| Failed local audio windows |79 |0 |
| Full-pose color PSNR against native reference |29.885dB |43.063dB |

The corrected output was **not** another picture encode. H264 picture-slice
SHA-256 remained identical after a metadata-only transfer-tag correction.
All30,815 encoded AAC packets matched a fresh single-generation256kbps donor
made from the same float narration master. No additional AAC encode was used.

## Why the checks matter

1. **A duration label can hide clock errors.** Count every video packet's exact
   rational PTS and duration. Check AAC packet continuity, priming/skip metadata,
   and the presented end against an integer sample count. Here the error was
   only two48kHz samples—inaudible by itself, but evidence that container-level
   rounding was not preserving the exact contract.
2. **A whole-program audio average can hide a local failure.** The new PCM helper
   evaluates each channel in one-second windows with half-second hops and full
   tail coverage. It does not normalize, shift, resample or gain-fit the result.
   An offline test exposes a one-second dropout in600seconds despite an otherwise
   passing27.78dB global SNR. Its reference-RMS activity threshold is not semantic
   voice detection, and its pass is not human listening approval.
3. **Color metadata changes how unchanged samples are displayed.** The native
   output declared BT.709 transfer. Separately captured native JPEG95 references
   and declared-color-to-sRGB export decoding exposed the mismatch. Retagging the
   output transfer as sRGB, including H264 metadata, restored fidelity without
   changing picture slices. Never apply this automatically to HDR/log/other
   pipelines; derive the expected transfer from that render path and verify it.

## Reproducible quality contract

References used the exact retained compiled master HTML, the fresh extracted PNG
cache, identical native lookup/injector, virtual-time shim, Chrome version,
software screenshot backend,1920×1080/DPR1 and JPEG95 capture. They did not read
the encoded export to generate their reference pixels. All three selected native
images were proved loaded and visibly decoded; an empty/missing injection cannot
pass just because the server reports zero errors.

Both whole-image and presenter-region MAE had to be≤2 and PSNR≥40dB. The corrected
three whole-image results were43.063,45.531 and43.930dB; presenter regions were
42.580,40.062 and41.682dB. Thresholds were declared before comparison and unchanged
after failures. The small presenter region has little margin; do not generalize
three passing poses to every frame or every source.

Audio gates were−16LUFS±0.5, true peak≤−1dBTP, global aligned SNR≥25dB,
finite stereo PCM and all local windows passing. AAC decoder tail padding was
explicitly bounded separately from the exact presented container length.

## Also avoid two authoring/testing traps

The SDK relocated an external root animation script into the HTML head. Its
selectors ran before the presenter existed. Registering the root GSAP timeline
inline **after** its elements repaired actual presenter movement. Passing lint,
timeline duration and child text visibility did not catch this: assert real
presenter geometry for full, split and bubble layouts, including reverse seeks.

A new resource-measurement retry mixin also omitted the original terminal-child
exit branch. It incorrectly tried to obtain a live footprint for an exited
worker. Restore terminal handling only after actual `child.poll()` proves exit;
never invent a zero-memory live sample. Nonzero worker exits and unrelated
measurement failures must remain failures. Preserve old failed receipts and use
exact-identity cleanup recovery instead of rewriting history.

## Scope and next integration work

The pure local audio comparator and stricter AAC packet clock have now been
integrated into ordinary program-master delivery, including candidate-hash
binding before promotion.56 focused regressions pass; nine real-codec short
fixture tests passed before a subsequent metadata-only receipt clarification.
This is not a fresh real-B invocation of the ordinary program-master pipeline.

The native audio/color repairs qualify a measured B delivery candidate. They are not proof
that unmodified Studio's Export button performs the same audio/metadata finishing.
The native project remains editable, but a new export must run the same finishing
and quality checks. Whole-output playback subsequently reached the end but failed
the unchanged zero-drop gate with four browser presentation drops (two near79.21s,
two near115.31s). It had no stalls or corrupt frames; the cause is not established.
The first full check ended at120m40.653s, missing the two-hour target even before
archiving. A later retry cannot erase this result. Human listening and creative acceptance
remain explicitly unclaimed. Full Studio tests deferred sidebar thumbnails and
used a separate realm-corrected preview staging; do not call that stock Studio
qualification or a measured thumbnail-enabled workflow.

The same delivery and playback harness later passed a complete repeat with
15,761 presented frames and0 drops. Keep that result separate: it does not
identify the first failure's cause or retroactively change its timing/result.

One more native authoring trap emerged during scoped revision. Studio accepts
`<!DOCTYPE html>...<body><template>...`, but0.8.31's standalone render entry
dispatch explicitly tests `rawEntry.trimStart().startsWith("<template")`
before extracting the parent shell. A full-document-wrapped template can
therefore preview yet fail independent export with no live duration/timeline.
Do not “fix” this by weakening strict lint or adding a CDN dependency. Qualify
the intended child format through both save/reopen and actual child export;
that export still does not include the parent's presenter/audio context.

Trial evidence root:
`/private/tmp/sniper-c0679-fresh-b-20260909.0Ydfxp`.
Key receipts: `native-export-v1.render.json`, `final-qc/native-qc.json`,
`native-reference-qc.json`, `delivery-qc-v2/native-qc.json`.
