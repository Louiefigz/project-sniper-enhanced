# Prepare selected footage for native long form

After selecting passages, prepare the footage before native preview/render work.
The additive `studio/long_sources.py` command creates a **separate project** with
small selected assets and translated source offsets. It leaves the original
project, graphics, captions, timeline positions and existing export code intact.
Use the new project with the existing guarded native render/review workflow.

The working C0679 long-form projects already use a cut presenter base and a
separate narration master. Keep those projects and their qualified export packages
on their existing route. The legacy `cut_speed.py` / `assemble.py` path already
cuts first. Do not insert another cut, replace its master, or rewrite an archived
export just to use this optimization.

## Commands

From the repository root, with the installed Node executable explicitly pinned:

```sh
SNIPER_NODE_PATH=/absolute/path/to/node .venv/bin/python \
  scripts/producer/studio/long_sources.py prepare \
  /absolute/original-project /absolute/new-prepared-project

.venv/bin/python scripts/producer/studio/long_sources.py check \
  /absolute/new-prepared-project

.venv/bin/python scripts/producer/studio/long_sources.py preview \
  /absolute/new-prepared-project
```

Preparation uses the same supervised source engine as Shorts: bounded handles,
original compressed picture packets, lossless working audio, exact source-clock
mapping and sealed reusable evidence. The original and prepared projects both
must pass the existing static validator. A static pass does not qualify delivery.
`preview` cold-checks the project before using the existing managed Studio owner.
Do not bypass the shared resource guard, start an unowned SDK server, or use the
test renderer below for a production master.

For another project revision with the same selections, pass
`--reuse-stage /absolute/prepared-project.preparation/media/run/selected-sources-stage.json`.
The original source identities and coverage are checked again; no new media
preparation runs. Preserve previous originals and prepared outputs as evidence.
Make revisions in a new original-project copy, then prepare a new destination;
editing either sealed project in place invalidates its cold check.

## Supported scope and failure behavior

- Landscape programs up to one hour; explicit root-timeline media at normal speed.
- Local `assets/` MP4/MOV/M4V picture sources; selected audio from those sources.
- A separate complete-program WAV at zero offset is copied byte for byte. Existing
  narration/mastering stays on the working route.
- Media in nested HTML, dynamic asset references, speed overrides and separately
  ranged audio require explicit adaptation. They fail rather than guessing clocks.
- Existing destinations, linked assets and destinations inside the original are
  rejected. Failed attempts retain diagnostic evidence in the separate preparation
  directory. Use a new destination after correcting the input.

This is an explicit native long-form preparation entry point, not an automatic
migration of old qualified packages or a change to the stored-guided controller.
Only referenced selected sources are replaced; other authored assets are preserved.

## Bounded regression test

`scripts/producer/tests/test_long_sources.py` covers preservation, reuse, stale
inputs, ambiguous offsets and failure before preparation. The opt-in
`tests/long_sources_integration.py` is restricted to a six-second 1920×1080 fixture
at 24000/1001 fps. It renders with the existing pinned native SDK under `NativeRun`,
compares all selected original-resolution frames and dialogue samples, and checks
the encoded output clock and audio alignment on both sides of the join. A second
six-second render uses the original source ranges with the same native renderer;
the decoded native pictures and program audio must match exactly before/after.

The September 15 test uses passages at 100.1 and 300.3 seconds in C0679. Its evidence
is under `artifacts/long-selected-sources-test-2026-09-15/`. Preparation reduced
working media from 10,280,473,262 to 129,749,578 bytes, without picture re-encoding.
The preparation owner took 19.90 seconds. These are sample measurements, not a
full-episode throughput or end-to-end delivery guarantee.

### Verified September 15 result

| Check | Result |
| --- | --- |
| Selected source picture | All 144 original-resolution frames identical |
| Selected source dialogue | All 288,288 stereo sample frames identical at 48 kHz |
| Before/after native render | All 144 decoded 1920×1080 frames identical |
| Before/after native program audio | All 288,288 stereo sample frames identical; maximum difference 0 |
| Cut boundary | Zero-sample audio displacement on both passages |
| Native output clock | 6.006 seconds, 24000/1001 fps |
| Prepared-package reuse | Passed without a second media-preparation run |
| Working project and pipeline | 27-file project inventory and 11 protected production-code files unchanged |
| Focused tests | 12 adapter + 10 shared-source + 15 native-pipeline tests passed |

Evidence: [native compatibility](../../artifacts/long-selected-sources-test-2026-09-15/comparison-native/compatibility.json),
[supervised comparison](../../artifacts/long-selected-sources-test-2026-09-15/comparison-native/compare.render.json),
[final preservation](../../artifacts/long-selected-sources-test-2026-09-15/PRESERVATION-FINAL.json),
[current-code reuse check](../../artifacts/long-selected-sources-test-2026-09-15/reuse-final-check.json),
[unit checks](../../artifacts/long-selected-sources-test-2026-09-15/unit-tests.log).

The prepared and original sample render owners took 56.83 and 56.68 seconds,
respectively. This sample demonstrated no final-render speed gain. The smaller
input package addresses unnecessary full-source preparation and makes the media
boundary explicit. A long edit retaining most footage will shrink much less.

Earlier development audio assertions compared lossy delivery audio with raw PCM
and initially inspected the nearly silent left channel. Those failed receipts
are retained. The final comparison uses the existing native pipeline on both
inputs and requires exact equality of both channels, plus zero displacement on
the speech-bearing channel. No production audio code or tolerance was changed
to make the test pass. Four decoded frames (opening, both sides of the join and
end) were inspected. This is a technical regression test, not a new editorial
candidate, listening approval or full-episode/Studio qualification.
