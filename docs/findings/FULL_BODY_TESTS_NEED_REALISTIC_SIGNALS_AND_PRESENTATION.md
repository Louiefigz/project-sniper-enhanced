# Full-body tests must exercise real signal and presentation rules

## What the actual run found

On2026-09-07 a fresh local five-minute1080p TEST workflow reached actual
eight-graphic rendering, full picture composition, source-master audio reuse
and Audit B. It failed after17m32.708s with33 passing checks,3 warnings and
2 failures. This was useful negative evidence, not a finished video.

The first failure was legitimate: the synthetic source used a continuous
140Hz harmonic bed. After encoding the hum detector measured a stable141Hz
line,50.9dB prominence and100% stability over230.5s. Loudness at−14.0LUFS and
true peak at−5.0dBTP were both acceptable, but neither makes a persistent tone
acceptable dialogue. A short transport fixture can be unsuitable for a
complete quality test.

The second failure was an applicability bug. `module-bullet-bars` normally
uses a720px side rail, but this candidate explicitly requested `own-screen`.
The compositor honored that request with a1920x1080 frame. The auditor looked
up rail geometry by template kind before checking the explicit presentation,
then rejected the correct full-screen bounding box as an escaped rail.

## Corrections without weaker gates

- Keep the original tonal fixtures and hum thresholds. Use a separately named
 TEST-only non-speech calibration signal for the complete positive workflow;
 test its full-duration encoded audio through actual mastering and analysis
 before spending another full video-render cycle. This does not test speech
 intelligibility, ASR accuracy, dialogue timing or subjective sound quality.
- Apply rail containment only when the effective presentation is a rail.
 Explicit own-screen still needs exact full-canvas coverage. Missing,
 malformed, partial and wrong-canvas placement evidence must still fail.
 Default and free-band rails must still stay inside their registered band.
- Re-run the actual retained plan/placement check read-only to reproduce the
 bug. Do not rewrite the historical report or promote the failed candidate.
 The next execution needs a fresh admission and original-clock lineage.

## Why unit pass counts were insufficient

The same run extracted272/272 required frames and24/24 graphic references,
and detected all eight graphics. Isolated metadata/template tests had passed.
Only the full path connected the long test signal and explicit presentation
override to the actual auditor. Test data must match the contracts consumed
downstream, not merely satisfy the first compiler.

The failed attempt's cleanup was independently verified:20 process
intent/spawn/reap records, normal worker return, and exact removal/absence
evidence for eight registered containers. Cleanup did not authorize retry,
selection or delivery. The in-memory prefix check logged completion, but no
durable whole-body proof receipt was written after QC failed.

## When not to use this approach

Do not replace problematic creator audio with synthetic noise, weaken hum
detection for a desired pass, or mark a full-screen layout good merely because
its geometry is legal. Do not use synthetic fixture timing as a ten-minute
creator-video SLA. Mechanical qualification, human creative review and actual
source-specific audio/color checks remain separate obligations.
