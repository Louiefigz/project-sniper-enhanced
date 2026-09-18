/* PROJECT SNIPER — shared motion tokens (G4).
   Source: scripts/producer/docs/findings/JADEN_STYLE.md §5.3 (frame-verified
   across 6 reels): text pop-in <= 1-2 frames (<=83ms), NO fade, NO slide;
   EXIT — THE LAW: never animated out, hard-off <=1-2f (exactly ON the next cut
   or an instant pop at the semantic boundary). CSS twins live in tokens.css
   (--pop-in-dur / --pop-scale-from / --instant-out-dur).

   Usage (inside a comp's paused GSAP timeline build):
     <script src="/motion-tokens.js"></script>
     const M = window.__motionTokens;
     M.popIn(tl, el, 1.25);      // instant-visible at 1.25s + <=2f scale settle
     M.instantOut(tl, el, 3.0);  // 0-frame hard-off

   Contract: the target must START hidden (the comp sets autoAlpha 0 at t=0,
   or CSS opacity:0). popIn's alpha change is a SET (1 frame); only the tiny
   0.94->1 scale settle spans the 2-frame budget. The target must not carry
   its own CSS transform (GSAP owns transform on popped elements) — let a
   parent own any static centering translate. Deterministic + seek-safe:
   sets/fromTo only, no wall clocks, no randomness.

   NATEHERK pack (docs/studies/NATEHERK_STUDY.md §3 ranks 2-4 + §2 T-D) — a SEPARATE
   grammar lane from the jaden pop law above; nothing here changes
   popIn/instantOut. Tokens (CSS twins: --text-ramp-dur / --eyebrow-lead /
   --skeleton-gap / --exit-blur-dur in tokens.css):
     TEXT_RAMP_S    0.20  in-place opacity ramp; text NEVER travels more than
                          a few px (rank 4, measured ghost->ink 120-250ms)
     EYEBROW_LEAD_S 0.25  eyebrow precedes its headline (rank 3, band 0.08-0.5)
     SKELETON_GAP_S 0.35  containers/hairlines land BEFORE text (rank 2)
     EXIT_BLUR_S    0.15  graphics-layer blur+fade+recede exit (T-D
                          67.12->67.28 ~150ms ≈ 4f @30fps; python twin:
                          scripts/producer/graphics/exit_on_cut.py) */
(function () {
  "use strict";

  var FPS = 30;                    // producer delivery default (CANVAS.fps_default)
  var POP_IN_S = 2 / FPS;          // <=2 frames — the measured pop ceiling
  var POP_SCALE_FROM = 0.94;       // subtle settle; NEVER an alpha fade
  var INSTANT_OUT_S = 0;           // exits are hard-off, THE LAW

  // ---- NATEHERK pack tokens (NATEHERK_STUDY.md §3 ranks 2-4, §2 T-D) ----
  var TEXT_RAMP_S = 0.2;
  var EYEBROW_LEAD_S = 0.25;
  var SKELETON_GAP_S = 0.35;
  var EXIT_BLUR_S = 0.15;
  var EXIT_BLUR_PX = 12;           // blur radius: study gives dur/alpha/scale,
                                   // not px — 12px default, override per call

  /** Pop `target` in at `at` seconds: alpha snaps ON (1 frame), scale settles
      0.94 -> 1 inside the 2-frame budget. */
  function popIn(tl, target, at) {
    var t = Math.max(0, Number(at) || 0);
    tl.set(target, { autoAlpha: 1 }, t);
    tl.fromTo(target, { scale: POP_SCALE_FROM },
      { scale: 1, duration: POP_IN_S, ease: "power2.out",
        immediateRender: false }, t);
  }

  /** Hard-off `target` at `at` seconds — 0 frames, no fade (T7/§5.3 law). */
  function instantOut(tl, target, at) {
    tl.set(target, { autoAlpha: 0 }, Math.max(0, Number(at) || 0));
  }

  /** NATEHERK rank 4 — in-place opacity ramp: alpha 0 -> 1 over TEXT_RAMP_S
      at `at`. NO travel (the study's phase-correlation shows zero drift; all
      headlines are ghost->ink ramps). immediateRender stays DEFAULT (true):
      the from-state hides the target from t=0 until its ramp — one ramp per
      target (a second fromTo on the same target would steal the initial). */
  function textRamp(tl, target, at) {
    var t = Math.max(0, Number(at) || 0);
    tl.fromTo(target, { autoAlpha: 0 },
      { autoAlpha: 1, duration: TEXT_RAMP_S, ease: "power2.out" }, t);
  }

  /** NATEHERK rank 2 — skeleton-first build: the container/hairline shell
      ramps at `opts.at` (default 0), its content ramps at +`opts.gapS`
      (default SKELETON_GAP_S = 0.35 — MG-1: panel skeleton lands as one unit,
      holds, THEN fills). Both are in-place opacity ramps (rank 4). */
  function skeletonFirst(tl, containerEl, contentEl, opts) {
    var o = opts || {};
    var at = Math.max(0, Number(o.at) || 0);
    var gap = o.gapS == null ? SKELETON_GAP_S : Math.max(0, Number(o.gapS));
    textRamp(tl, containerEl, at);
    textRamp(tl, contentEl, at + gap);
  }

  /** NATEHERK T-D — graphics-layer-only exit: blur + fade + slight recede
      (scale -> 0.98) over EXIT_BLUR_S ending exactly at `at + EXIT_BLUR_S`.
      Comps schedule it at D - EXIT_BLUR_S so the exit completes on the seam
      (the exitOnCut clamp point). `blurPx` optional (default EXIT_BLUR_PX). */
  function blurRecede(tl, target, at, blurPx) {
    var t = Math.max(0, Number(at) || 0);
    var px = blurPx == null ? EXIT_BLUR_PX : Math.max(0, Number(blurPx));
    tl.fromTo(target, { filter: "blur(0px)" },
      { filter: "blur(" + px + "px)", autoAlpha: 0, scale: 0.98,
        duration: EXIT_BLUR_S, ease: "power2.in" }, t);
  }

  window.__motionTokens = {
    FPS: FPS,
    POP_IN_S: POP_IN_S,
    POP_SCALE_FROM: POP_SCALE_FROM,
    INSTANT_OUT_S: INSTANT_OUT_S,
    TEXT_RAMP_S: TEXT_RAMP_S,
    EYEBROW_LEAD_S: EYEBROW_LEAD_S,
    SKELETON_GAP_S: SKELETON_GAP_S,
    EXIT_BLUR_S: EXIT_BLUR_S,
    EXIT_BLUR_PX: EXIT_BLUR_PX,
    popIn: popIn,
    instantOut: instantOut,
    textRamp: textRamp,
    skeletonFirst: skeletonFirst,
    blurRecede: blurRecede,
  };
})();
