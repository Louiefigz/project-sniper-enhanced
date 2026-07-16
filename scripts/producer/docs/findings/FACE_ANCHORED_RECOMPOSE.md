# Face-Anchored Recompose: a pan needs zoom, and the crop clamp gives you the glide for free

**Date:** 2026-07-10 · **Modules:** `motion/recompose.py`, `motion/punch_in.py`
(`releaseS`), `plan_lint_smooth.py` · **Trigger:** operator defect report §1
(rail windows never re-centered the subject — face 305px left of the
remaining-space center for 6.9s).

## The problem

When a 33%W rail slides in beside a talking head, the pro recomposes the
FOOTAGE simultaneously: face glides from fx≈0.50 to fx≈0.667 (the midpoint of
the non-panel space), eased over ~0.40s, starting ~3 frames BEFORE the rail is
visible — measured at 0.667±0.012 in all seven of the reference's rail
windows. Our renderer overlaid the rail on fixed framing.

## Finding 1 — a pure pan is impossible at scale 1.0

The footage fills the frame; the crop IS the frame. To move the subject you
need pan room, so the minimal zoom is a closed form:

```
z_min = max(target/fx, (1 - target)/(1 - fx))
```

(the two crop-feasibility bounds: crop x ≥ 0 and crop x ≤ scaled_w − w). For
the measured case (fx 0.55 → target 0.6651) that is z = 1.21 — comfortably
inside the 1.05–1.25 punch band. The reference reads "pan-dominant" because
his SOURCE is wider than his delivery; ours earns the pan with a ~21% zoom.
**When NOT to use:** if z_min exceeds the punch band (face far from the clear
region, e.g. face 0.2 → target 0.85 needs z=1.48+), the framing or the panel
side is wrong — `solve_recompose` fails loudly instead of rendering a lunge.

## Finding 2 — solve centerX against the clamp and the EXISTING push machinery renders the glide

`punch_in`'s animated windows crop at `x = clip(cx·z(t)·W − W/2, 0, (z(t)−1)·W)`.
Pick a CONSTANT `cx = fx − (target − 0.5)/z_hold` and let the eased attack
sweep `z(t): 1.0 → z_hold`:

- early in the attack `cx·z(t) < 0.5`, the clamp pins the crop at 0 (full
  frame) — the face drifts only with the zoom;
- once `cx·z(t) ≥ 0.5` the pan takes over and the face glides to the target,
  landing EXACTLY at `fo = fx·z − (cx·z − 0.5) = target`.

One constant-center push window = a two-phase, continuous, eased glide. Zero
new render machinery — the whole primitive is plan-side math emitting a
`role:"recompose"` punchIns window (`attackS`/`releaseS` = 0.4s, 0.12s lead).

Frame-verified on a marked synthetic (face box at fx 0.55, window 1.88–8.0):

| t | fx measured | expected |
|---|---|---|
| 1.83 | 0.5497 | pre (0.55) |
| 1.92–2.17 | 0.562 → 0.662 | eased bell increments |
| 2.33–7.50 | 0.6648 | target 0.6651 (±0.0003; ref ±0.012) |
| 7.96 | 0.5497 | released, no pop |

## Finding 3 — `releaseS`: a push that holds to its window end pops

The overlay disables at `outEnd`, snapping the scale to baseline in one frame
(defect §3's "punch releases also pop"). `releaseS` multiplies the attack
smoothstep by `(1 − smoothstep(release))` so `z(outEnd) = 1.0` exactly and the
disable is seamless. Longform lint now requires every discontinuous boundary
scale step (computed from `punch_in`'s own pure mirrors, so lint and renderer
cannot drift) to land ON a cut seam — pops are shorts grammar.
