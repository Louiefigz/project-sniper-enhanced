# Open-source color grading for Project Sniper

Research date: 2026-09-15. Scope: repository inspection, upstream documentation/code/license review, and the installed FFmpeg capability inventory. No dependencies installed, footage rendered, models benchmarked, or application code changed.

## Recommendation

Build the first grading workflow on Sniper's existing FFmpeg pipeline. Add OpenColorIO when introducing explicit camera/log input transforms or a shared, more capable grading model. Use Colour Science for offline analysis and numerical QA where needed. Evaluate AI reference matching separately after preview/export agreement is proven.

The immediate product opportunity is correcting exposure and white balance, keeping cameras consistent, and applying restrained reusable looks. A LUT is a lookup table that maps input colors to output colors. It gives us a portable way to save a look, but its expected input color space must be declared.

## What Sniper already has

- A fixed warm look using `colorbalance`, `eq`, and `curves` in [baseline_look.py](../../scripts/producer/motion/baseline_look.py). This is a useful primitive, not source-aware correction.
- Source/lighting-group sampling in [sample_plan.py](../../scripts/producer/color/sample_plan.py), conservative luma suggestions in [statistics.py](../../scripts/producer/color/statistics.py), and explicitly review-only [proposals](../../scripts/producer/color/proposal.py). Existing proposals deliberately cannot write a grade. Global average chroma is not treated as evidence of incorrect white balance.
- Source-frame declarations, observation records and a private [picture-transform compiler](../../scripts/producer/color/source_picture_transform.py). Its narrowly defined xvYCC-to-BT.709 bridge does not implement exposure, white balance or LUT grading. Its [tool contract](../../scripts/producer/color/source_picture_transform_contract.py) pins FFmpeg 8.0 and zimg 3.0.6; arbitrary new transforms do not fit that contract unchanged.
- The [remaining-work checklist](../producer/REMAINING_WORK_COMPLETION_CHECKLIST.md) explicitly lists the source-aware grade application owner as missing. Observation/metadata checks should not be counted as finished grading.
- A relevant real-render issue: the [September 10 export qualification](../producer/SHORTS_REAL_EXPORT_QUALIFICATION_2026-09-10.md) found an sRGB/BT.709 transfer-tag mismatch in the native JPEG capture route. Correcting that declaration preserved picture payloads; it was not a creative grade. New grading must account for the actual native/browser output color behavior.

Local read-only verification: `ffmpeg -hide_banner -version` reported **8.0**. `ffmpeg -hide_banner -filters` confirmed `lut3d`, `zscale`, `exposure`, `colorbalance`, `colorcorrect`, `colortemperature`, `curves`, `eq`, `vibrance`, `signalstats`, `waveform`, and `vectorscope`. `libplacebo` was absent. This checks the host binary, not the independently pinned container/private runtime or a finished Sniper integration.

## Candidate comparison

Effort ratings below are engineering judgments about Sniper integration, not measured delivery estimates.

| Project | Useful capability | Fit / effort | License and caveat |
| --- | --- | --- | --- |
| [FFmpeg](https://ffmpeg.org/ffmpeg-filters.html#lut3d-1) | Apply LUTs, curves and color controls; convert color spaces; generate scopes | **Best immediate fit.** Existing subprocess/render architecture and installed filters; relatively low engine work, meaningful integration/QA work | [LGPL/GPL depends on build](https://ffmpeg.org/legal.html). This host enables GPL and version 3; do not label the shipped stack simply LGPL |
| [OpenColorIO](https://github.com/AcademySoftwareFoundation/OpenColorIO) | Explicit color management, ACES configurations, grading transforms, CPU/GPU processing | **Best foundational addition.** Especially useful for declared camera/log sources and consistent transform definitions; medium effort | BSD-3-Clause; requires a chosen configuration and known source interpretation, not automatic camera identification |
| [Colour Science](https://github.com/colour-science/colour) | Color-space math, chromatic adaptation, color correction and LUT read/write | **Good supporting library.** Use for sampled analysis, LUT tooling and QA; low-to-medium effort | BSD-3-Clause; not a complete grading UI or video renderer |
| [libplacebo](https://github.com/haasn/libplacebo) | GPU image processing, tone/gamut mapping and HDR/SDR handling | **Later, if HDR or measured throughput requires it.** Higher integration effort for this Mac/runtime setup | LGPL-2.1; its FFmpeg path uses Vulkan, including MoltenVK support in the library. Missing from the inspected host build |
| [color-matcher](https://github.com/hahnec/color-matcher) | Statistical reference-image color transfer, Python API and CLI | **Useful experiment for matching cameras/reference frames.** Needs shot-aware fitting and temporal validation; medium effort | GPL-3.0; assess distribution obligations before adopting into a packaged product |
| [VideoColorGrading](https://github.com/seunghyuns98/VideoColorGrading) | ICCV 2025 research generating a LUT from source video and a reference image | **Promising research spike, weak first dependency.** High integration effort on Apple Silicon | Repository code Apache-2.0; pretrained/base-model licenses need separate checking |
| [LUT Colorator](https://github.com/Merserk/LUT-Colorator) | Manual light/color controls, presets, preview frames and `.cube` export | **Useful UI/algorithm reference.** A standalone Windows/Gradio application requires adaptation to Sniper's Next.js UI | Apache-2.0; README describes stochastic presets and heuristic auto-adjust. The “AI-powered” label alone does not establish learned reference matching |

### Maintenance snapshot

GitHub repository API checks on the research date showed all six repositories below unarchived. `pushed_at` is a repository activity signal, not proof of a stable release or quality.

| Repository | Last push reported by API |
| --- | --- |
| [OpenColorIO](https://api.github.com/repos/AcademySoftwareFoundation/OpenColorIO) | 2026-09-14 |
| [Colour Science](https://api.github.com/repos/colour-science/colour) | 2026-09-14 |
| [libplacebo mirror](https://api.github.com/repos/haasn/libplacebo) | 2026-09-03 |
| [color-matcher](https://api.github.com/repos/hahnec/color-matcher) | 2026-02-24 |
| [VideoColorGrading](https://api.github.com/repos/seunghyuns98/VideoColorGrading) | 2025-12-29 |
| [LUT Colorator](https://api.github.com/repos/Merserk/LUT-Colorator) | 2026-05-23 |

## Why the top choices fit

### 1. FFmpeg for execution

Sniper can compile bounded, structured grade parameters into approved filters and run them at the source-picture stage. The documented `lut3d` filter accepts `.cube` files and interpolation choices. Keep the intended grade and the exact LUT bytes/version in project state; do not store arbitrary agent-authored filter strings. [Filter documentation](https://ffmpeg.org/ffmpeg-filters.html#lut3d-1).

Apply source corrections before text/graphics composition so a warmer face does not also turn white captions orange. Reuse the normal render graph where possible instead of adding a mandatory full-length encode pass. Some native/browser routes may need graded source intermediates or a qualified shader implementation; that cost is still unmeasured.

### 2. OpenColorIO for explicit transforms

OCIO provides Python/C++ integration and [primary, RGB-curve and tonal grading transforms](https://opencolorio.readthedocs.io/en/latest/api/grading_transforms.html). It also has an [ACES configuration project](https://github.com/AcademySoftwareFoundation/OpenColorIO-Config-ACES). It is a strong fit for declared source-to-working-space conversion, a saved grade and an explicit output transform.

Its [LUT baking tools](https://opencolorio.readthedocs.io/en/stable/guides/using_ocio/using_ocio.html#ociobakelut) offer an integration bridge to LUT-capable renderers. Baking is an approximation: validate the domain, shaper requirements and interpolation against the original processor. Do not flatten HDR/scene-linear values into an arbitrary 0–1 cube and assume equivalence. Use a direct processor where the required domain cannot be represented faithfully.

OCIO supplies transform machinery; Sniper still needs to choose a supported source profile, determine useful corrections and show a trustworthy preview.

### 3. Keep matching experiments behind the same saved-grade format

`color-matcher` demonstrates reference transfer through a simple Python API. For video, independently fitting each frame could change the mapping as the scene changes. Our proposed integration would fit a stable mapping per source/lighting group and test it over the entire group; temporal stability is not established by its still-image examples. [Upstream API/examples](https://github.com/hahnec/color-matcher).

VideoColorGrading is particularly interesting because it generates a LUT and then applies that consistent mapping to video. However, the [provided environment](https://github.com/seunghyuns98/VideoColorGrading/blob/main/fast_env.sh) specifies Python 3.8.18, PyTorch 1.13.1 with CUDA 11.7, xformers and Triton, plus downloaded pretrained models. This is not a ready-made Mac integration. Test it in an isolated research environment rather than merging its dependency pins into Sniper.

[LUT Colorator](https://github.com/Merserk/LUT-Colorator) offers a concrete preview/control workflow, including four video samples near 20/40/60/80% duration. Sniper already has retained-interval and lighting-group sampling, so reuse that stronger project context when borrowing interface ideas. Its Windows launchers and separate Gradio application are not drop-in components for the existing UI.

## Proposed implementation sequence

1. **One supported SDR path.** Add a saved grade for explicitly declared BT.709 SDR sources: exposure/contrast/saturation, a supported white-balance control and optional user-supplied LUT. Precisely define control units, input/output space and operation order. Reject unsupported/unknown profiles through existing source admission.
2. **Trustworthy comparison.** Show original/graded frames and short moving previews from each retained lighting group, including late footage. Generate previews through the same transform as export. Retain the existing proposal/review/acceptance workflow and undo behavior.
3. **Connect execution and cache invalidation.** Bind each grade to source identity, source-frame intervals, parameters, LUT/config hashes and implementation version. Connect the application owner to the governed picture/render paths. A grade change invalidates affected picture artifacts and downstream composites; source timing and valid independent audio work should remain reusable.
4. **Camera/log support with OCIO.** Add only declared profiles/configurations that we can test. Keep technical normalization, per-source correction and the optional creative look separately represented. Define how graphics enter the working/output space and ensure output tags describe the actual encoded pixels.
5. **Reference matching.** Compare the current conservative baseline, a statistical matcher and VideoColorGrading on the same clips. An AI method should produce a reviewable transform/LUT through the same execution path.
6. **GPU optimization if justified.** Benchmark CPU FFmpeg against an isolated libplacebo build only after a performance or HDR need is demonstrated. Revalidate the actual pinned runtime and preview/export behavior before adoption.

## Qualification needed before shipping

- Camera A/B talking heads, skin tones, mixed/colored lighting, intentional dark scenes, screen recordings, bright highlights and late lighting changes.
- Identity/bypass behavior, neutral ramps and color patches; confirm numerical agreement with the intended transform rather than expecting a graded output to equal its ungraded source.
- Source-only grading with caption/graphic colors preserved, plus comparisons between the real browser/native capture path and decoded export.
- No frame/timestamp changes, no accidental audio re-encode or source mutation, and correct invalidation when a LUT/config changes at the same filename.
- Check flicker over moving footage and cuts. One saved mapping avoids per-frame fitting drift but does not fix changing illumination automatically.
- Measure wall time and peak memory on the intended Mac and real export route. No speed or perceptual-quality benchmark was run in this research.

## Other projects considered

[Shotcut](https://shotcut.org/features/) supplies color grading, 3D LUTs, white balance and scopes, and uses [GPLv3](https://www.shotcut.org/FAQ/). It is useful for manual comparisons and interface study. Adopting its complete editor would add a second editing architecture; it is a weaker embedded fit than the libraries above.

**Decision:** proceed with FFmpeg-backed grading and explicit color-space contracts; introduce OCIO as camera/log or richer transform needs arrive. Keep automatic reference matching optional until it demonstrates better results on Sniper footage.
