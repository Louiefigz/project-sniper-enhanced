# P4 exit audit — governed custom motion and assets

> **Verdict: COMPLETE for the defined P4 exit — 13 of 13 exits pass.**
>
> **Evidence date:** 2026-07-30
>
> The direct Codex/Claude Code → `scene_package_cli.py` custom-scene lane is
> real. The formerly contract-only geometry, copy-repair, timing-reuse, and
> treatment-closure claims now have freshness-checked retained real-media
> evidence in `p4-live-exit-closure-v1.json`.

## Verdict rules

- **PASS** requires current executable enforcement plus a passing real-media
  acceptance or a freshness-checked retained artifact where the exit concerns
  rendered behavior.
- **BLOCKED** means at least one material part of the exit has only schema,
  invalidation, cache-key, mocked, or synthetic receipt evidence.
- A passing negative gate can prove that an unreleased capability remains
  unsupported; it does not release that capability.

## Exact exit table

| # | P4 exit | Verdict | Current evidence | Scope limit |
|---:|---|---|---|---|
| 1 | Twelve briefs cover required forms, risks, aspects, and FPS | **PASS** | `p4-scene-brief-matrix-v1.json` contains 12 unique briefs spanning overlay, takeover, presenter hole, masks, blends, particles, real-copy overflow, both aspects, and all eight rates. `test_scene_brief_matrix` passes. | This is explicitly a diversity/coverage artifact, not proof that 12 distinct scenes were rendered. The separate 46 × 8 retained rate matrix supplies the physical catalog render coverage. |
| 2 | Fire/sparkles two-card case passes | **PASS** | `live_scene_package_cli_acceptance` rendered and fully decoded both independently cacheable alpha units and read back their exact Palmier bindings. The fully pinned OCI replay also passed. | The acceptance proves the authored fixture, not arbitrary natural-language interpretation. |
| 3 | Exact delivery-pixel own-screen geometry and real-footage readability pass | **PASS** | The retained live cohort rendered a real 1920×1080 HyperFrames composition through `graphics_stage` onto a 3840×2160 master, decoded all 36 output frames, and retained exact `placedBBox=[0,0,3840,2160]` / delivery-canvas evidence. Fixture-green edge occupancy was `1.0` before the window and `0.0` inside it, so the physical delivery edge—not only metadata—was covered. `test_readability_gate` separately samples decoded footage and proves contrast/backing fail-closed behavior. | This proves the released same-aspect own-screen path and the current readability fixture, not arbitrary aspect conversion or subjective design quality. |
| 4 | Clean-process and randomized-seek renders match every decoded frame | **PASS** | `live_p4_scene_acceptance` rendered the full 180-frame scene twice, compared every decoded frame, and checked randomized seeks including first/last/middle frames. | This is one governed scene fixture, not a creator-project cohort. |
| 5 | Right-copy repair renders one unit | **PASS** | The retained fire/sparkles cohort rendered initial `[left miss,right miss]`, then changed only `rightTitle` and observed `[left hit,right miss]` with exactly one new cache medium. The left path/hash/size/mtime stayed exact, Palmier emitted one right-side `replace-media` and preserved the left binding, both fresh forced-cache unit hashes matched, and the independent full-scene oracle measured color SSIM `0.999925` and alpha SSIM `0.999999` against the `0.995` floor. | This proves independently addressable units in the governed fire/sparkles project fixture; universal one-unit repair belongs to P5 qualification. |
| 6 | Ordered units match the full-scene oracle | **PASS** | The live scene acceptance renders units with two workers and requires ordered composite color and alpha SSIM of at least `0.995` against the separately rendered full scene. | The proof covers the two-card fixture and its current blend/mask behavior. |
| 7 | Same-duration timing move reuses scene media | **PASS** | In the same retained cohort, typed `scene.move` returned `mediaReused=true`; both units were cache hits, the complete media-cache name/hash/size/mtime inventory was unchanged, and Palmier emitted exactly two `move-placement` operations. The moved incremental timeline and independently forced control matched exact FrameMD5, decoded PCM, and stream facts. | Absolute placement is excluded from scene-media identity only when duration, FPS, content, bundle, canvas, and render-mode authority remain unchanged. |
| 8 | Governed OCI proves OS-level network denial; local mode discloses unproved denial | **PASS** | The approved image `sha256:bc56d386…2222ba8` was present and the fully pinned OCI fire/sparkles CLI acceptance passed in 89.407 seconds. Each unit crossed image/container attestation, active host-loopback-decoy, external IPv4/IPv6, and DNS denial checks; runtime receipts were media/input-bound, and no `sniper-render-*` container remained. Local execution correctly omits this claim. | Sealed mode deliberately fails closed unless Docker, image, user/socket, browser, Node, ffmpeg, ffprobe, and proof-tool paths are all pinned. |
| 9 | One package passes TS/Python schema, lint, renderer, CLI, provenance, QC, and Palmier consumers | **PASS** | The TS package/schema/parity scripts pass; Python contract, bundle, authoring, asset, package, renderer, and CLI tests pass; the live package reobserves exact media and bundle bytes and reads back both real Palmier unit bindings. | QC here means structural lint, decode/asset proof, animation-map/filmstrip evidence, optional bound readability, and render oracle. It is not semantic aesthetic verification that the result matches an open-ended creative brief. |
| 10 | Malicious media, expired rights, missing attribution, and untrusted metadata fail closed | **PASS** | The freshness-checked `p0-adversarial-ingress-v1.json` retains six real hostile-byte rejections through the shared OCI admission boundary. `test_asset_governance` and `test_scene_package_assets` reject byte/MIME mismatch, active/remote SVG, expired rights, missing attribution, unknown consent, symlink/hardlink aliases, and instruction-like metadata. | The retained hostile cohort is the shared external-ingress boundary; project-authored source code is governed by the separate closed bundle/lint/runtime contract. |
| 11 | Thumbnail, cover, and loop-frame deliverables are hash-bound | **PASS** | `test_deliverables` uses real ffmpeg/ffprobe and PNGs, binds the exact source/receipt/frame, and rejects missing frames, source mutation, hash mismatch, existing targets, and wrong extensions. | These are baked deliverables, not native Palmier title/thumbnail objects. |
| 12 | Transition, SFX, and grade changes have correct local closures | **PASS** | A separate retained 320×180, 30 fps, four-second project with 48 kHz stereo audio exercises all three typed operations. Transition replacement changed 13 decoded frames, all 13 inside the declared old/new seam windows and zero outside, then matched an independent forced repetition exactly. SFX-only repair stream-copied the exact encoded picture (packet hash and decoded FrameMD5 unchanged), changed audio, and matched forced decoded PCM. Grade changed all 120 picture frames as its honest full-picture closure declares and matched its independent control exactly. | Transition and grade evidence is deterministic operation-versus-forced repetition plus decoded closure validation, not a production dirty-window splice. Universal fragment rendering remains P5. |
| 13 | Tracking/PIP stays unsupported until the complete fixture matrix passes | **PASS** | Plan lint rejects continuous tracking; the reserved `/presenter/**` plan root is rejected whether its nested value is true or false; incomplete tracking/PIP matrices remain unreleased. | Continuous subject tracking and animated PIP are **unsupported**, not released P4 capabilities. Static `graphicsTrack[*].spec.presenterFrame` remains a different, supported manual composition choice. |

## Replays performed

The focused P4 Python suite passed **116/116** cases:

```bash
PYTHONPATH=scripts/producer:scripts/producer/tests \
  .venv/bin/python -m unittest -v \
  scripts.producer.tests.test_scene_brief_matrix \
  scripts.producer.tests.test_scene_contract \
  scripts.producer.tests.test_parametric_scene \
  scripts.producer.tests.test_scene_authoring_stage \
  scripts.producer.tests.test_scene_package_assets \
  scripts.producer.tests.test_scene_package \
  scripts.producer.tests.test_scene_catalog \
  scripts.producer.tests.test_graphics_target_fps \
  scripts.producer.tests.test_graphics_runtime_closure \
  scripts.producer.tests.test_palmier_scene_bindings \
  scripts.producer.tests.test_treatment_operations \
  scripts.producer.tests.test_creative_proposer \
  scripts.producer.tests.test_advanced_motion_gate \
  scripts.producer.tests.test_asset_governance \
  scripts.producer.tests.test_deliverables \
  scripts.producer.tests.test_readability_gate \
  scripts.producer.tests.test_graphics_asset_occupancy \
  scripts.producer.tests.test_comp_capability_artifact \
  scripts.producer.tests.test_comp_rate_matrix \
  scripts.producer.tests.test_transition_sfx_repair \
  scripts.producer.tests.test_p4_exit_closure_artifact
```

The complete retained replay passed and wrote
`contracts/p4-live-exit-closure-v1.json`:

```bash
PYTHONPATH=scripts/producer:scripts/producer/tests \
  .venv/bin/python \
  scripts/producer/tests/live_p4_exit_closure_acceptance.py \
  --artifact \
  docs/producer/command-driven-editing/contracts/p4-live-exit-closure-v1.json
```

The freshly regenerated independently attributable cohort times were `8.171`
seconds for real 4K geometry, `204.270` seconds for copy repair plus timing
reuse, and `5.278` seconds for transition/SFX/grade, or `217.719` seconds
total. The artifact binds a 141-file source closure plus the exact browser,
Node, ffmpeg, and ffprobe binaries.
`test_p4_exit_closure_artifact` checks source freshness, case completeness,
every load-bearing threshold above, and the absence of temporary-path evidence.

The real local browser acceptances passed:

```bash
RUN_P4_SCENE_PACKAGE_TESTS=1 \
PYTHONPATH=scripts/producer:scripts/producer/tests \
  .venv/bin/python -m unittest -v \
  scripts.producer.tests.live_scene_package_cli_acceptance

RUN_P4_SCENE_TESTS=1 \
PYTHONPATH=scripts/producer:scripts/producer/tests \
  .venv/bin/python -m unittest -v \
  scripts.producer.tests.live_p4_scene_acceptance
```

The first passed in 53.243 seconds. The full-scene/seek/unit oracle passed in
207.513 seconds. The fully pinned governed OCI form of the first command passed
in 89.407 seconds. Missing sealed-mode pins failed before promotion, as
designed.

The additional reference/container/security group passed **48** cases with one
host-loopback positive-control skip caused by the calling sandbox. The real OCI
acceptance above supplied the active positive and denial controls. The retained
hostile-ingress, external-media, scene-asset, and rights group passed **26/26**.

These TypeScript scripts also passed:

```bash
for f in \
  src/lib/producer/__tests__/producer-contracts-v1.test.ts \
  src/lib/producer/__tests__/producer-schema-parity.test.ts \
  src/lib/producer/__tests__/scene-authoring-packet-v1.test.ts \
  src/lib/producer/__tests__/scene-package-contract-v1.test.ts \
  src/lib/producer/__tests__/reference-profile.test.ts \
  src/lib/producer/__tests__/reference-admission-verifier.test.ts \
  src/lib/producer/__tests__/reference-selection-flow.test.ts \
  src/lib/producer/__tests__/reference-provenance.test.ts
do
  node --import tsx "$f" || exit 1
done
```

## Truthful scope and non-claims

P4 proves that Codex or Claude Code can author a governed project bundle with
HTML/CSS/JavaScript/GSAP motion, bind declared variables and assets, render it
deterministically through HyperFrames, cache scene units independently, and
project proved baked-regenerable media into Palmier. The fire/sparkles request
is within that released direct-CLI substrate.

P4 does **not** prove:

- arbitrary keyframes, paths, and easing expressed directly in the closed
  `graphicsTrack` plan vocabulary;
- an Ask Editor or one-shot natural-language route that authors the custom
  bundle and integrates it into the whole project without an agent-driven
  staging step;
- objective reference-style replication. That is P6 and remains unqualified
  until three materially different packs, rights, adjudication, unseen footage,
  objective tolerances, and three-reviewer gates pass;
- native After Effects or native editable Palmier keyframe/layer parity;
- continuous subject tracking or animated PIP;
- universal one-unit short-form graphics repair, the complete P5 render graph,
  or a qualified 10–14 minute / 90-minute SLA.

## Closed formerly-blocked exits

1. Real 4K own-screen geometry is decoded, placement-audited, and
   delivery-edge pixel-measured.
2. Right-copy repair renders exactly one unit and matches fresh unit and
   independent full-scene controls.
3. Same-duration timing moves perform zero scene-media renders and match an
   independent moved-timeline control.
4. Transition, SFX-only, and grade operations have real decoded closure and
   forced-control evidence; SFX has a production picture-preserving mux path.

The defined P4 exit is complete. The broader user promise stays in its owning
phases: P5 for universal local repair and hybrid Palmier delivery, P6 for
verified style mimic, and P7/P8 for complete short/long creator-project and
latency qualification. P4 completion does not mean the whole editing system is
fully optimized.
