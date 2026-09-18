# Versioned build-closure repair — 2026-09-10

Status: the bounded implementation and its 146 directly related tests pass.
This is not a clean full-repository regression result, native-video quality
approval, or evidence of faster production editing.

## What changed

The current source lists omitted transitive implementation dependencies.
Appending them to a frozen historical contract would silently change what an
old receipt means. New wire versions now capture the current implementation:

| Current receipt | Wire version | Policy | Unique source paths |
| --- | ---: | --- | ---: |
| Compositor build | 2 | `sniper-prebound-compositor-build-v2` | 83 |
| Render build | 3 | `sniper-headless-render-build-v4` | 110 |

The render policy number intentionally differs from its wire version, following
the existing numbering. Both catalogs pass complete static import-closure
checks, including their own validators: no missing local dependencies, duplicate
paths, or detected dynamic import calls. This check is not a proof about
arbitrary runtime behavior or optional external packages.

Current compositor hashing binds the entire canonical V2 manifest, including
full paths and sizes, under its own digest domain. Current render writers,
stores, admission writers and retained-admission readers use the closed V3
parser. Historical compositor V1 and render V1/V2 contracts, pure parsers and
frozen fixtures retain their original bytes and digest identities. Current
execution does not accept those historical versions as current builds.

The non-authorizing archive/binding APIs remain on their historical artifact
roles. This change does not add a new archive role or authorize a render from
old evidence. No SDK, media algorithm, codec setting, quality threshold,
production footage, existing finished video, or installed dependency changed
in this repair.

## Operational consequence

Changed source identities require freshly generated current build receipts and
admissions. Restart a stale long-lived writer before preparing new work; its
loaded-source drift protection must reject changed code. Do not relabel an old
receipt, overwrite historical evidence, or treat successful parsing as runtime
authorization. Existing historical artifacts remain readable by their matching
historical pure parser, not by the current execution store/loader.

## Verification

Commands ran from `PROJECT_SNIPER`, using local `.venv/bin/python`, no paid
services, and `PYTHONPATH=scripts/producer/tests:scripts/producer`.
Run each cohort with `./.venv/bin/python -B -m unittest -v` followed by its
module names below. Times are unittest-reported test runtimes, excluding Python
startup/import setup; they are not editing or rendering workflow timings.

1. **83 tests passed in 5.338 seconds**:
   `test_current_build_semantics`, `test_current_build_release`,
   `test_compositor_build_receipt_semantics`,
   `test_render_build_receipt_semantics`, `test_render_build_v2_semantics`,
   `test_render_build_receipt`, `test_render_admission_artifact`,
   `test_render_admission_artifact_authority`, `test_render_admission`,
   `test_admitted_render_lane`, `test_render_result`.
2. **60 tests passed in 2.229 seconds**:
   `test_build_receipt_binding`, `test_build_closure_reobservation`,
   `test_build_closure_reobservation_adversarial`,
   `test_graphic_render_receipt_binding`, `test_runtime_capability_binding`,
   `test_prebound_compositor_store_adversarial`,
   `test_admitted_graphic_receipt_controller`,
   `test_admitted_graphic_receipt_projection`.
3. **3 tests passed in 1.826 seconds**: `test_prebound_compositor`.
   This includes a tiny synthetic FFmpeg candidate: deterministic repeated
   output/receipt bytes, retained audio hashes, full decode, an expected pixel
   sample, and rejection of an empty-alpha overlay. It is not real-footage or
   native HyperFrames qualification.

Cases include mixed/unknown versions, noncanonical and oversized input,
duplicate keys, missing/extra/reordered paths, forged instances, hostile
equality, stale loaded sources, retained-evidence mutation, replay, and
historical source/fixture SHA-256 preservation. `git diff --check` passed.
The source-size/function-size/parameter-count audit found no new violations;
three pre-existing large test files were changed only at their fixture import.

## Remaining evidence outside this repair

The separate repository task owns the broader regression repairs and their
reruns. Its earlier 6,978-test Python baseline was not green; this focused pass
does not supersede that result. The isolated 67-second native real-footage
optimization test is separately held by resource admission and has not produced
a baseline or revised export. No speedup, human listening, visual acceptance,
or ten-minute-video/two-hour target is established here.
