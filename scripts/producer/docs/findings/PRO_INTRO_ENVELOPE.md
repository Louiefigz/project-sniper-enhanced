# PRO_INTRO_ENVELOPE — what a pro longform intro actually measures

**Source:** frame-by-frame study (1fps classification + scene-score analysis) of the
pro-edited reference *"Replaced 5 Content Tools With 1 Production Workflow"* (16 min,
same speaker/set as our C0666 footage — a direct A/B), first 180s, 2026-07-10.
Compared against our v3 edit of C0666, then used to rebuild it (v4).

## The measured envelope (first 180s)

| Metric | PRO | our v3 | our v4 (rebuilt) |
|---|---|---|---|
| Perceived cuts/min (scene ≥ 0.12) | **25.3** | 12.2 | **28.2** |
| Non-head visual share of intro seconds | **32%** (≈50% in first 60s) | 22% | ~45% |
| Framing shifts/min | **12.3** | 6.9 | ~14 |
| On-head overlay seconds | 10 | **0** | ~15 |
| Receipt/b-roll seconds | 23 | 3 | ~8 |
| Longest plain-head run | 36s (body breath) | **37s (in a 79s cut!)** | ~10s |
| Soft internal-motion events/min | 48 | 16 | 21 |

## The pro intro grammar (what the numbers are made of)

1. **The hook is NEVER a bare head.** Kinetic styled text builds word-by-word ON
   the live talking head from ~1s (red/white, heavy weight), plus an animated
   arc+icon diagram in the headroom. → `kinetic-quote-wide` with
   `bg: "transparent"` (added 2026-07-10), composited over the footage.
2. **Full-frame takeovers carry 2–6 internal build states** — a dark glass
   statement pair with a whip-pan between cards, a whiteboard mind-map growing
   node-by-node ON the spoken names. Never a static card. → staged `at*` specs.
3. **Credibility is an animated sequence**, not a card: circle headshot + name +
   employer landing as drawn strokes. → `avatar-bio-card`.
4. **Receipts run as MONTAGES**: 3–4 different screenshots at ~1s each,
   back-to-back (channel page, actual content, site scrolls). A lone 1.5s receipt
   is not the pattern. → brollTrack chains, 0.8–1.5s per state.
5. **Dim-under lists**: mid-intro enumerations build over the DARKENED head
   (55% black matte), chips landing to speech, placed BESIDE the face. →
   `list-build` (transparent) over a matte; kinetic quotes get the same
   treatment on thesis beats.
6. **Punch-cut alternation**: the head framing changes on (nearly) every cut —
   tight/wide alternation ~1.05–1.06, hard snap ON the seam. This is what makes
   cuts *perceived*; invisible micro-trims read as dead air. → `punchIns` with
   `role: "recompose"` landing on cutTrack seams (cadence-exempt in lint).
7. **Duotone/light-leak flashes** cover section seams (~2 in 3 min). → `transitions`.
8. The **body breathes** (a 36s plain run at 60–90s is on-style) — density is
   front-loaded, not uniform.

## What this is wired into (all shipped 2026-07-10)

- `producer_config.MODES.longform.pacing`: `intro_window_s: 180`,
  `intro_min_nonhead_share: 0.28`, `hook60_min_nonhead_share: 0.40`,
  `hook_overlay_by_s: 4.0`, `receipt_montage_state_s: (0.8, 1.5)`.
- `planner/pacing.py`: `nonhead_share()` (merged graphics+broll coverage),
  `_staged_land_times()` (spec `atN` lands count as discrete changes — an
  entry-start-only model reads a building comp as dead air), region-aware
  `suggest_fills` (hook 4s / body 20s ceilings).
- `plan_lint_motion.py`: `_warn_intro_envelope` (share floors, WARN),
  `_semantic_zooms` (on-seam `role:"recompose"` punches exempt from the zoom
  cadence budget; floating recomposes count + warn).
- `hook_contract.py`: `_check_hook_density` (hook still-gap WALL) +
  `_check_hook_opens_dressed` (first graphic must open by 4s — WALL).
- `kinetic-quote-wide.html`: `bg` variable (`dark` takeover default |
  `transparent` on-head overlay, ProRes4444 alpha).

## When NOT to apply

- **clean-cut / trim scopes** — the envelope is a produced-longform doctrine;
  the treatment gate skips it entirely.
- **The front-load RATIO stays a WARN, not a wall**: a hard ratio deadlocks
  against the zoom-cadence cap and demands fabricated cuts on genuinely
  back-loaded content; on an all-intro excerpt (like the 79s C0666 cut) the
  body zone is legitimately as dense as the hook.
- Don't flatten the body to intro density — the pro's 60–90s breath is real.
  The envelope governs the INTRO window only.

## Reproduce the measurement

```bash
# perceived cuts + soft events
ffmpeg -t 185 -i pro.mp4 -vf "select='gte(scene,0.04)',metadata=print:file=scene.txt" -f null -
# classify content types: 1fps frames -> per-second head/overlay/graphic/receipt map
ffmpeg -t 180 -i pro.mp4 -vf "fps=1,scale=640:-2" frames/p%03d.jpg
```
