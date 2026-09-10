# Toolchain hashes need the executable closure

## Finding

A render-toolchain hash should cover every source and runtime file that can
change the rendered result, but it should not cover unrelated application code.
Hashing too little permits stale reuse. Hashing the whole repository makes safe
local reuse disappear whenever unrelated code changes.

## The incident

The current-render graph originally hashed every non-test Python file below
`scripts/producer`. On 2026-07-30 that meant **744 Python files**. A change to
an ingress checker or cut-repair QC adapter therefore changed the render
toolchain digest even though neither file could execute during a normal render.
Every retained render generation became stale.

The render-effect audit tried to describe a narrower boundary by walking Python
imports from four entrypoints. That closure contained **174 files**, but it
missed path-invoked renderer programs. `render.py` launches
`motion/reframe_split.py` and `audit/audit_render.py` as subprocesses without
importing them. It also missed a relative import from
`headless/sealed_archive.py`.

This was both sides of the same bug:

- the cache invalidator was broader than execution;
- the dependency audit was narrower than execution.

## The correction

`render-effect-registry-v1.json` now declares every current top-level renderer
and path-invoked stage. `render_effect_discovery.py` follows absolute and
relative imports, and it rejects a Python path referenced through the current
stage-launch conventions when that file is outside the closure.

`current_render_toolchain.py` now hashes that same closure instead of all
Producer Python. The corrected closure currently contains **201 files** and
the reader audit observes **260 literal plan/manifest reads across 61 files**.
The same hash still includes all composition HTML, shared motion runtime,
vendored GSAP, HyperFrames, the isolated Node launcher, and the exact
Python/Node/browser/ffmpeg/ffprobe binaries.

Executable tests prove that subprocess stages and the relative-imported sealed
archive format join the closure, while unrelated
`edit/cut_repair_candidate_qc_waveform.py` and
`external_ingress_registry.py` do not.

## The principle

Define one versioned executable closure and reuse it for both:

```text
render dependency audit
  = import closure + declared/path-invoked programs

render toolchain digest
  = that source closure + templates + loaded runtimes + exact binaries
```

Adding a new dynamic loader, subprocess convention, plugin directory, or
runtime requires extending closure discovery before release. A source file
should not enter the digest merely because it shares a parent directory with
the renderer.

## When not to use this approach

- Do not use static import discovery for arbitrary user plugins or runtime
  module names. Those need a sealed manifest or a deliberately broader root.
- Do not remove templates, fonts, assets, vendor scripts, environment policy,
  or executable binaries from the digest just because they are not Python.
- Do not claim that fewer invalidations make rendering correct. Reused outputs
  still need exact stage-input receipts, retained-byte verification, and a
  forced-full oracle for each released repair class.
- For a tiny one-shot renderer with no reuse, a coarse whole-package digest can
  be simpler. The narrower boundary matters when retained work is expected to
  survive unrelated development.
