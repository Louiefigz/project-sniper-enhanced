# Motion scenes, assets, and reference styles

> **Status:** Target architecture with the governed P4 direct agent/CLI scene
> lane implemented. Ask Editor/Auto Edit integration and P6 verified mimic
> remain unqualified.
>
> [Previous: cuts, captions, and audio](03_CUTS_CAPTIONS_AND_AUDIO.md) ·
> [Back to the plan index](../COMMAND_DRIVEN_EDITING_EXECUTION_PLAN.md) ·
> [Next: render, Palmier, and QC](05_RENDER_PALMIER_AND_QC.md)

## Motion realization lanes

Do not invent a universal JSON language for every animation. Keep HyperFrames
code as the open substrate and wrap it in a typed scene manifest:

```text
exact catalog comp exists
  → configure it
else a closed parametric grammar fits
  → build a typed SceneSpec
else
  → author a governed project-scoped HyperFrames bundle
```

Catalog reuse is correct only when information anatomy, layout, and motion
grammar match. A one-off bundle is not silently promoted into the global
catalog.

## Scene contract

```ts
interface SceneSpecV1 {
  schemaVersion: 1;
  sceneId: string;
  version: number;
  timing: ResolvedTimingV1;
  renderMode: "overlay-alpha" | "takeover-opaque" | "presenter-hole";
  composition:
    | { type: "catalog"; kind: string;
        variables: DeclaredSceneVariablesV1 }
    | { type: "project"; bundleId: string; bundleHash: string;
        entry: "composition.html";
        variables: DeclaredSceneVariablesV1 };
  elements: Array<{
    elementId: string;
    role: string;
    exposedProperties: string[];
    values: DeclaredSceneElementValuesV1;
  }>;
  renderUnits: Array<{
    unitId: string;
    elementIds: string[];
    zIndex: number;
    entry: string;
    sharedGroupId?: string;
    maskDependencyUnitIds?: string[];
    compositeMode: "normal" | "screen" | "multiply" | "declared";
    palmierGranularity: "scene" | "unit";
  }>;
  captionPolicy: "preserve" | "suppress-overlap";
  dependencies: Array<{ kind: string; id: string; sha256: string }>;
  provenance: {
    origin: "operator" | "autopilot" | "reference-style";
    requestId?: string;
    stylePackHash?: string;
  };
}
```

Variable and element-value types are generated closed unions from the selected
composition manifest, not open JSON maps.

The manifest declares an authoring interface; it is not physical capability
evidence. Release decisions use a fresh measured/proved capability record from
the catalog probe and asset proof:

- measured canvas pixels and aspect;
- delivered bounding box and pixel occupancy;
- alpha/opacity and fade class;
- exact rational FPS and decoded frame duration;
- render/decode/terminal-state result.

Missing, stale, unmeasured, or `renderError` evidence fails closed. Measured
values win over declared metadata. “Same aspect” is not “full screen”: a
1920×1080 own-screen comp on a 3840×2160 delivery must be scaled to the exact
delivery canvas and prove its final bounding box.

A render unit is independently cacheable only when:

1. it renders in isolation from a clean process;
2. shared masks/interactions are in the same unit or declared group;
3. ordered units are frame/alpha-equivalent to a clean full-scene oracle;
4. randomized seek order produces the same complete decoded frame sequence.

Otherwise the shared group or whole scene is the smallest honest unit.

The fire/sparkles request becomes:

```text
scene-045
├── unit-left
│   ├── left-blue-card
│   └── seeded-fire
└── unit-right
    ├── right-copy
    └── seeded-sparkles
```

Changing right copy rerenders `unit-right` only when no cross-mask/shared
interaction exists.

## Creative/delight proposer

Explicit creative requests do not depend on the current number/entity/contrast
trigger detector. Autopilot needs a bounded proposer for:

- visual metaphor;
- comic/delight beat;
- emotional emphasis;
- product/world visualization;
- purposeful texture/transition;
- showable referents beyond stat/list cards.

Each proposal records the content reason, viewer effect, style/format fit,
density cost, and informational/decorative role. Deterministic code still owns
placement, collision, and budget gates. Decorative density is capped.

## Reframe and presenter-motion boundary

Static/manual reframing and the proved static presenter-hole layout are
separate from:

- `reframe.continuousTracking`;
- `presenter.animatedPip`.

Those stay `unsupported` until no-face, multiple-face, face-exit, occlusion,
screen-share, shot-boundary, fast-motion, safe-zone, canvas/FPS, and manual
override fixtures pass. A full or verified-reference request that critically
depends on them blocks or downgrades before render.

## Governed HyperFrames authoring

The useful pattern from the supplied ZIP is project-scoped code, independently
renderable parts, animation-map diagnostics, local rerender, and stable
placement. It is not a magic open plan vocabulary.

Authoring flow:

1. Create an attempt-owned staging directory.
2. Give the coding agent only the brief, canvas/FPS/duration, brand tokens,
   approved asset registry, scene contract, and examples.
3. Permit writes only inside that bundle.
4. Require declared variables, paused seekable timeline, root duration, and
   deterministic PRNG seed.
5. Require pinned local runtime assets; no CDN/render-time network.
6. Reject traversal, symlinks, undeclared assets, wall-clock time, unseeded
   randomness, infinite repeats, dynamic imports, unsafe evaluation, secrets,
   and unsupported native modules.
7. Run source lint and animation-map diagnostics.
8. Use the sealed non-root networkless OCI renderer when its approved image is
   configured. Direct local mode must record `osSandboxProved: false` and may
   not claim OS-level network denial.
9. Prove canvas, rational FPS, frame duration, alpha/opacity class, decode,
   terminal state, and seek safety.
10. Render twice from clean processes and compare every decoded frame plus
    alpha/audio metadata. Sampled hashes are diagnostic only.
11. Review entrance, early land, middle, exit, after-window, extrema, clipping,
    visibility, overflow, collision, and intent.
12. Promote the content-addressed bundle/proof before plan binding.

All 46 current production comps now use the vendored GSAP/runtime closure and
pass the retained eight-rate matrix. A future comp or bundle must join that
closure before release.

Text exposed over footage also receives a real-background readability gate.
Sample the actual underlying footage across the visible interval and prove
contrast or a backing treatment; a critic/lint pass or missing measurement is
not a verdict.

## Asset governance

`Full` may source or generate missing material only through `AssetRecordV1`.
Each record binds:

- immutable content hash/snapshot;
- origin and acquisition/generation time;
- license, consent, allowed uses/platforms, attribution, and expiry;
- generated model/version and prompt/request provenance;
- MIME, geometry, duration, rates, color/alpha, and publication disposition.

Every external media byte—raw footage, references, local uploads, downloads,
archives, fonts, images, audio, and video—first enters an immutable snapshot
and then a non-root, networkless, resource-limited probe/decode sandbox. Bound
limits include bytes, MIME/codec, dimensions, frame count, duration, archive
expansion, process count, time, and output.

Archives/symlinks cannot escape staging. Expired rights, missing attribution,
unknown consent, or byte mismatch blocks publication. Transcript, OCR,
metadata, filenames, and embedded text are untrusted evidence, never agent
instructions.

## Reference-style modes

Offer two promises:

1. **Reference-inspired:** quick measured cadence, density, caption behavior,
   and layout tendencies.
2. **Verified mimic:** complete versioned style pack, independent review,
   adjudication, realization proof, and matched-window QC.

Current implementation status: only the first promise is released. The legacy
stored strategy value `mimic` maps to `reference-inspired` in visible UI and
authoring instructions. The production route consumes `style_profile.json` and
`reference_profile_lint.py`; the offline V1 pack compiler/linter is not wired
into planning, render, or QC. See the
[exact P6 exit audit](18_P6_EXIT_AUDIT.md).

```text
reference bytes + source hash
  → deterministic deep study
  → chronological mechanics review
  → independent reverse editorial review
  → disagreement adjudication
  → ReferenceStylePackV2
  → scene/template realization proof
  → grammar/event plan bindings
  → matched-window comparison
```

The pack covers:

- canvas/safe zones;
- cut cadence by region;
- hook/body/outro production envelope;
- caption grouping, typography, placement, emphasis, karaoke;
- information forms and graphic anatomy;
- motion paths/easing/entrances/exits/camera grammar;
- transitions and visual-state changes;
- b-roll/cutaway behavior;
- audio/music/SFX relationships;
- confidence, unobservable mechanics, supported realization, and gaps;
- reference, review, template, asset, and toolchain hashes.

## Coverage and downgrade rules

The denominator is every detected edit event/change boundary, every persistent
visual state at a frozen cadence, and every observable visual, caption, motion,
cut, b-roll, and audio lane. Every item is:

- bound to a supported grammar/mechanic;
- marked unobservable; or
- given a named noncritical waiver.

Cuts/timing, visible captions, dominant layout/motion, defining transitions,
and audible music/SFX relationships are non-waivable critical dimensions. An
unsupported, unobservable, or unrealized critical mechanic downgrades the
result to `reference-inspired`/`partial`.

Each reference-derived operation stores the style-pack hash and grammar/event
ID. Re-study creates a new candidate; it never destroys the approved pack.

V1 packs remain readable under their original hashes. V1→V2 migration creates
a new unapproved candidate.

A finished reference shows visible outcomes, not rejected raw takes. Without a
raw+edited pair, edit-selection policy is inferred/unobservable.

Transfer structure, not identity. Without rights, do not copy logos, creator
identity, faces, footage, claims, screenshots, proprietary UI, exact
fonts/colors, thumbnails, or music.

Verified release applies packs to unseen target footage and measures frozen
cadence/caption/motion/layout tolerances plus blinded editorial review.
Reference onboarding time is reported separately from editing with an
already-approved pack.
