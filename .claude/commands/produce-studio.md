---
description: Review and hand-adjust a render's graphics layer in HyperFrames Studio
argument-hint: <producer-dir> [what to review or change]
---

Invoke the `producer` skill and use its **Studio review lane** — the default
manual-control path after render/assemble. Full reference:
`docs/producer/STUDIO_REVIEW_LANE.md`.

The operator's request is: $ARGUMENTS

The loop: `scripts/producer/studio/studio_review.py open <producer_dir>`
generates the review project from `edit_plan.json` + `base_final.mp4` and
serves it in Studio (the browser opens); the operator edits graphic
panels/timing on the timeline; `studio_review.py sync <producer_dir> --apply`
folds those edits back into `edit_plan.json` (baseline-diff gated: only NEW
gate failures the edit introduces block; backup written);
then rerun applicable current-plan gates and independent reviews and renew any
required stale receipt. Run the shell-quoted assembly command printed by sync
using that same resolved manifest (or explicit `--manifest` override).
Use combined `sync --apply --assemble` only when no intervening review is
required, never to bypass the newly changed auto-graphics plan's review wall.
Base reuse requires current
source/plan/tool fingerprints; report measured timing, not a fixed duration.
`status` prints the lane state
plus the next action; `context` exposes the agent bridge for agent-driven
edits; `stop` shuts the preview server down.

This direct skill/CLI path does not require the custom Sniper web UI. Sync is
not delivery approval: any stale graphics receipt requires applicable gates
and reviews again. Never switch graphics ownership to bypass them. Use local
processing and subscription-backed agent tools only unless the user explicitly
authorizes paid services. Do not discard unsynced work with `--force` unless
the user explicitly requests it.

Studio is a review surface ONLY: never `hyperframes render` the studio dir —
the deliverable path is unchanged (footage = ffmpeg; graphics =
`graphics_render.py` + `assemble.py`). For a pro-NLE footage-level pass, the
optional legacy Palmier exact-master mirror remains `/produce-palmier`.
