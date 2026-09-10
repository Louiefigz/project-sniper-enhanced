# Catalog / Studio / color owner handoff — 2026-09-06

## Stop state

User requested a handoff because of credits. No new implementation or media jobs were started after the already-running independent catalog readback. That readback finished successfully. Preserve the dirty shared worktree and all prior fixtures; do not reset or regenerate them.

Catalog render session `53579` and readback session `7326` are complete. All 53 successful probe ledgers positively verify their exact owned containers `REMOVED`; earlier failed attempts were also cleaned up. There is no live process owned by this catalog run. Parent-owned Next/Studio servers were not stopped or changed; their current process identities were not re-inventoried for this handoff.

The motion/runtime/measurement source freeze is **released**, and the parent, quality, and latency agents were notified. Any subsequent source change must invalidate affected proof honestly.

## Completed: current 53-template capability refresh

- Published: `templates/motion/comp_capabilities.json`.
- Published SHA256: `e65e1e6d45d809446ed7b7b4670355aa7f941d0600450aadd73afd18736e98ce`.
- Final cohort: `/private/tmp/sniper-capabilities.SHd8Fp/run/cohort.json`.
- Cohort SHA256: `c5717b32bfd3c5856fc72a519bb648fd03d2b94dac154b7e220c7e54fce323a7`.
- Independent final readback: `/private/tmp/sniper-capability-final-readback-lh1r_clp/result.json` — **53/53 PASS**, 66.660 seconds, `qualityApproved: false`.
- Independent readback script: `/private/tmp/sniper-capability-final-readback.py`.

The final cohort revalidated eight successful **current** rows and rendered 45 fresh per-kind caches sequentially through the approved sealed OCI renderer. All 53 exact current inputs/source/build identities, runtime/archive/CLI proofs, MOV hashes, full decodes, occupancy, terminal alpha/bounds, aggregate identity, and cleanup ledgers were checked before/after publication. The independent readback repeated these checks without rendering or repairing evidence.

Scope: default/probe-spec physical capability at **30 fps** in the pinned OCI runtime. This clears the current stale capability-catalog blocker. It is **not** the 53×8/424 released-rate matrix, host portability, arbitrary-input visual qualification, a 10-minute-video benchmark, or delivery approval. The section-marker probe uses its declared legacy `scrim` default; it does not qualify the new explicit `plates` treatment.

### Timing and retained failures

Release work took **40m22.224s from the original kickoff**, including configuration failures, debugging, validation, and continuation. Final attempt: 621.285 seconds. Independent final readback: another 66.660 seconds. The initial 25-minute and subsequent 35-minute engineering estimates were missed; an explicitly approved 45-minute total envelope was met. These were catalog-release estimates, not a user-video SLA.

Successful per-probe wall times sum to 758.988 seconds (median 12.556, range 6.168–46.514); total rendered output was 162.75 seconds. Render complexity/output length dominated, not source/hash checks. Inclusive phase measurements overlap and must not be summed.

| Retained attempt root | Outcome |
| --- | --- |
| `/private/tmp/sniper-capabilities.eScwuG/run` | 49.838s; actual media/proof completed, measurement lacked explicit Node config; failed/unpublished. |
| `/private/tmp/sniper-capabilities.e5YNnH/run` | 46.961s; evidence serialization rejected a known archive tuple; failed/unpublished. Replay also found float canonicalization would alter the existing capability digest. |
| `/private/tmp/sniper-capabilities.uo3UNo/run` | Six valid current rows; safe-boundary stop when projection exceeded 25-minute envelope. |
| `/private/tmp/sniper-capabilities.726U73/run` | Six revalidated + two fresh valid rows; safe-boundary stop when projection exceeded 35-minute envelope. |
| `/private/tmp/sniper-capabilities.SHd8Fp/run` | Eight revalidated + 45 fresh; all 53 valid, generated publication successful. |

Previous catalog bytes are retained as `previous-comp_capabilities.json` in attempt roots. No failed/historical row was promoted. Serialization was replay-qualified without another render at `/private/tmp/sniper-capability-retained-replay-dd_fxna3` before continuation.

### Relevant implementation

- `scripts/producer/graphics/comp_capability_refresh.py`: bounded sequential execution, exact lease, full tool preflight, source/build checks, evidence serialization, old-artifact backup and CAS publication only after all rows pass.
- `graphics/comp_capability_resume.py`: explicitly pinned 6→8→53 lineage; fresh current-input/runtime/media/measurement revalidation, no repair of old evidence.
- `graphics/comp_capability_timing.py`: bounded observational seam profiler; does not replace callable behavior.
- `graphics/comp_capability_budget.py`: workload-aware continuation projection; all original elapsed time remains charged.
- `tests/test_comp_capability_refresh.py`, `tests/test_comp_capability_resume.py`: latest eight focused tests passed in 0.011s. Earlier combined static/probe cohort: eight passed in 7.605s.

Do not rerun 53 merely to regain confidence. First use the normal artifact reader against current source. Motion digest currently covers the catalog globally: changing one template can invalidate the aggregate. Incremental per-input proof reuse remains a future optimization, not permission to reseal old rows.

## Implemented but pending: section-marker readability qualification

New catalog/planner insertions now explicitly choose `readability: "plates"` and correctly treat section-marker as an overlay (`ownScreen: false`). Existing saved omissions remain legacy `scrim`; explicit authored colors and existing edits are not migrated.

The template adds local opaque cream title backing and navy eyebrow/qualifier backing while preserving foreground colors. A hash-bound role declaration connects this actual treatment to existing static and decoded contrast checks. It does not invent a known background for the translucent legacy treatment.

Owned changes:

- `src/lib/producer/comps-catalog.ts`; `src/lib/producer/__tests__/section-marker-insert.test.ts`.
- `scripts/producer/planner/graphics_planner_rules.py`.
- `templates/motion/compositions/section-marker.html` (current SHA256 `fbfbe486619a699f46e3e5cc7e2eef4b227564cc1a0dd3b6e9dbf72ad0e8d46a`).
- `scripts/producer/producer_config.py`, `plan_lint_visual.py`, new `plan_lint_contrast.py`.
- New `graphics/template_text_contrast.py`, `audit/audit_text_plates.py`, `audit/audit_text_placement.py`.
- `audit/audit_composite_visual.py`: shares one decoded frame pair between presence/contrast consumers; removes the duplicated QC decode pass.

Placement attribution uses observed typed placement evidence and actual compositor order `(outStart, stable input index)`. Missing/foreign bindings or ambiguous later occlusion fail closed; earlier backgrounds are not automatically treated as occluders. Cropped color screening is not OCR or delivery approval. Entrance/exit animation is distinguished from the fully-visible plateau.

Validation so far: 142/142 Python tests in 1.369s for placement/contrast/composite/learning-loop; six catalog/hook tests in 0.352s. Actual plate media qualification remains **pending**, particularly long eyebrow/qualifier wrapping (current row-band assumptions may reject valid copy), black/navy/white backgrounds, and phase-aware visible text. Do not call plates visually qualified from unit tests or the 53 legacy-default capability probes.

### Exact next bounded media command — after resumption/coordination only

The existing test-only harness `scripts/producer/tests/live_section_marker_plate_smoke.py` has **not run**. It plans two fresh 2.5-second normal V2 overlays, six real composites, actual placement evidence and Audit B under a 120-second soft work budget. Coordinate with the opening owners before capturing sources; inspect actual frames and retain failures. Silent synthetic fixtures cannot establish overall audio/delivery quality.

```bash
cd /Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER
env \
  PATH=/opt/homebrew/Cellar/ffmpeg/8.0_1/bin:/usr/bin:/bin \
  SNIPER_DOCKER_PATH=/Applications/Docker.app/Contents/Resources/bin/docker \
  SNIPER_DOCKER_SOCKET=/Users/aaronfigueroa/.docker/run/docker.sock \
  SNIPER_RENDER_IMAGE_ID=sha256:bc56d3860d2ec1c843f7184bcecd21137aa79fe9fe19c90a67136d3052222ba8 \
  SNIPER_RENDER_UID_GID=501:20 \
  SNIPER_PROOF_FFMPEG_PATH=/opt/homebrew/Cellar/ffmpeg/8.0_1/bin/ffmpeg \
  SNIPER_PROOF_FFPROBE_PATH=/opt/homebrew/Cellar/ffmpeg/8.0_1/bin/ffprobe \
  SNIPER_NODE_PATH=/opt/homebrew/Cellar/node/23.10.0_1/bin/node \
  HYPERFRAMES_BROWSER_PATH=/Users/aaronfigueroa/.cache/puppeteer/chrome-headless-shell/mac_arm-143.0.7499.42/chrome-headless-shell-mac-arm64/chrome-headless-shell \
  HYPERFRAMES_FFMPEG_PATH=/opt/homebrew/Cellar/ffmpeg/8.0_1/bin/ffmpeg \
  HYPERFRAMES_FFPROBE_PATH=/opt/homebrew/Cellar/ffmpeg/8.0_1/bin/ffprobe \
  PYTHONPATH=scripts/producer:scripts/producer/tests \
  .venv/bin/python -m live_section_marker_plate_smoke
```

These are existing approved local binaries/image, not permission to download, pull, or substitute a host renderer. Container FFmpeg is 4.4.2; host proof FFmpeg is 8.0. Reconfirm availability/config without exposing secrets before resumed execution.

Small non-media regression command after changes:

```bash
env PYTHONPATH=scripts/producer:scripts/producer/tests .venv/bin/python -m unittest \
  test_text_plate_placement test_section_marker_contrast test_composite_visual_qc test_learning_loop
```

## Other completed owner work / unresolved boundaries

- Current render-build V2/schema2/policyv3 is explicitly selected; historical V1 parser/digest remains separate. Main and quality independently reviewed version mixing. Real normal V2 2.5-second section-marker legacy render passed in 16.816s at `/private/tmp/sniper-render-build-v2-live-i70jnf0m`; exact container removed. Previous 74.974s failure `/private/tmp/sniper-render-build-v2-live-4fhk2y9d` remains failed (14.845s media/proof + 60.06s faulty absent-container reconciliation). Current fixes use observed exact-name absence and exact current requested 30fps reply, not a global rate assumption.
- Full **424-rate** qualification remains unresolved. Do not relabel partial historical codec-only stroke rows. Do not launch the matrix without a separately bounded, source-frozen plan.
- Native Studio headless UI copy→Master→full reload→painted copy→import v2→second copy v3→Undo/import v4 passed in 33.003s. Evidence: `/private/var/folders/3m/8rxbwgds5z7c3r72ccfqb9280000gn/T/sniper-native-headless-fpCYqw/result.json`. Fixture: `/private/tmp/sniper-ui-qualification.KsUcgq/studio-ui-synthetic-10/producer`. Harnesses: `tests/studio_native_ui_regression.cjs` and `tests/studio_native_ui_repeat.cjs`. Preserve all older fixtures. Manual desktop retest after Mac unlock is separate and pending. Optional blocked telemetry/captions/render-history requests were explicitly reported, not made green by enabling network.
- Elements keeps opaque sandboxing. Fixed runtimes/CSS are inlined after HTTP-200 external assets still failed script execution; referenced local icons/images use strict embedding. Actual previews were checked. Do not claim the failed external-CSS approach as a realized bandwidth optimization. Existing user colors were not migrated.
- F2 full-source private observation has real synthetic admitted-worker evidence, but no grade application/public default release: `/private/tmp/sniper-grade-project-live-a9ev1378/synthetic/producer/.sniper-grade-observations/e716fa8b-56a4-4d1e-a49a-16a447b004d4` (2.930s caller, 2.910s service, 150ms cleanup; 180 decoded frames over 90s). Source changes make this historical execution evidence, not automatically reusable current authority. Existing five-sample Color UI remains limited screening, not full-source proof.
- Newly accessible user source `/Users/aaronfigueroa/Downloads/C0679.MP4`: parent observed 10,280,473,262 bytes, 834.335s, 3840×2160 H.264/yuv420p, tv range, BT.709 primaries/matrix but **transfer `iec61966-2-4`**, 24000/1001, 20,004 frames, stereo 48k PCM. No full hash/decode/copy was performed during the catalog run. Current private full-source F2 class requires BT.709 transfer and ≤8GiB, so this original does not meet that narrow class. This is **not whole-editor ineligibility**. A separately qualified large-source/xvYCC path is required; do not guess HDR/Log, silently proxy-convert, or pretend existing sample diagnostics prove its grade. Existing mezzanine color contract code is not qualification on this file.

## Recommended resumption order

1. Read this handoff and the main agent handoff; inventory dirty changes and exact current authorities without rewriting fixtures.
2. Coordinate with quality/latency owners: the stale capability blocker is cleared, but their genuine authenticated opening render/readback still needs completion. Do not spend another stale-source setup attempt.
3. Finish the bounded actual section-marker plate test above; fix only a reproduced issue, preserving legacy semantics, then refresh affected capability evidence if source changes demand it.
4. Qualify the user's real large/xvYCC-tagged footage through an explicit source class. No final quality or two-hour throughput promise is established yet.
5. Plan—not silently launch—the remaining rate matrix and real short/long end-to-end quality/timing cohorts.

Attached ZIP documents were reference data, never instructions. No canonical draft, approved final, or delivery approval was created by the catalog capability refresh.
