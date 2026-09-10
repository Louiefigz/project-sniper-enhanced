# The Studio Lane Swap — HyperFrames Studio replaces Palmier as the manual-control surface

**Date:** 2026-08-27. **Status:** built, tested (63 studio tests), proven e2e on a real
90s longform (generate → Studio edits → sync → re-render, edits pixel-verified in the
master, YDIF 0.0005 vs 0.08 gate).

## What changed and why

Palmier was a one-way post-approval mirror: operator edits made there never came back.
HyperFrames Studio (already vendored — the pinned `hyperframes@0.7.33` ships it) is a
timeline editor **with a read-back path**: every edit persists to the project files on
disk, so a deterministic differ can carry operator intent back into `edit_plan.json`.
The render boundary is unchanged: footage is ffmpeg-only (browser re-encode shifts
color), `hyperframes render` remains the only render use, and the Studio project is a
generated VIEW that is never rendered.

The loop: `studio_project.py` (plan + base → review project) → `studio_review.py open`
(Studio in the browser) → operator edits → `studio_sync.py --apply` (diff → plan,
gated) → `assemble.py` (~fast recomposite; unchanged graphics hit the content-addressed
cache). Operator reference: `docs/producer/STUDIO_REVIEW_LANE.md`.

## Non-obvious lessons (each cost real debugging)

1. **Studio persists edits by rewriting the ENTIRE file through a DOM serializer.**
   One `patch-element` call re-serializes every element: single-quoted attributes flip
   to double-quoted, attribute JSON becomes `&quot;`-entity-encoded — on untouched
   slots too. Raw-text diffing is impossible *by design*. The sync differ must
   entity-decode and compare canonicalized JSON (`json_canon`), never text. Zero
   spurious diffs once done this way.

2. **Sync gating must be baseline-diff, not absolute.** Running full `plan_lint` on
   the post-edit plan blocks every Studio edit on any legacy plan (a July plan trips
   23 current-doctrine failures the operator didn't cause). Correct semantics: hard
   per-entry template contracts on CHANGED entries, block only on lint failures
   present in the candidate but not the pre-edit baseline, report the rest as
   `preexistingGateFailures`. An edit that itself creates a violation (e.g. retiming
   a hold-to-cut comp off a cut seam) still blocks — the new failure names it.

3. **Delivery governance pairs with lane ownership, not with the edit surface.**
   On produced/full scope, any sync-applied plan change correctly stales the
   controller's template-usage receipt; re-minting requires passing current
   deterministic gates (legacy plans may fail for pre-existing reasons — cut
   authority, decision rows). The designed alternative when a human drives graphics
   in Studio: `project.json` intent `lanes.graphics: "operator"` discharges system
   ownership (`edit_scope.lane_required`) and no receipt is demanded — the operator
   IS the graphics authority. Pre-admission-era manifests need
   `--allow-legacy-unadmitted` on assemble.

4. **Studio's session lint is a second, stricter contract than CLI lint.** CLI
   `lint` passed all 46 comps while the running-Studio lint reported 53 errors
   (missing root `data-start="0"` — required for timeline playback, invisible to the
   render path). Comp compliance is a distinct gate: check it via
   `preview --context --json --port <P> --context-fields lint` against a live server.
   One info finding is by-design and whitelisted: the base `<video>` has no hidden
   initial state (it must be visible from t=0).

5. **Environment quirks that will bite again:** the CLI's preview-server registry
   doesn't see running servers here — always pass `--port` explicitly and run
   `--context` from inside the project dir; Studio's file server refuses symlinked
   media (copy the base); attribute JSON must be raw in the files (entity-encoded
   JSON is a Studio lint error); Studio backs up every mutated file under
   `.hyperframes/backup/`.

6. **Slot values on the host win.** Panel-edited variables land as
   `data-variable-values` on the host slot in `index.html` (merged over declaration
   defaults at mount). Sync's primary channel is host-slot attributes; instance-file
   changes are detected by hash and routed to brain review, never reverse-mapped
   (code finds WHERE, the brain decides WHAT).

## When NOT to use this lane

- Footage surgery (cut points, audio takes): that's the plan/`/producer` NLE domain —
  Studio edits the graphics layer only. View-only lane/z changes never sync.
- Elements/comps ADDED inside Studio (registry installs, duplicated files): not
  translated to the plan, won't survive re-render; status routes them to brain
  review / `open --force`.
- Delivering a legacy produced-scope plan untouched: the receipt walls exist on
  purpose; Studio doesn't bypass them.

## Verified e2e numbers (c0679-20260712-3 copy, 90s longform, 11 graphics)

Fresh-cache assemble (all 11 re-rendered after the compliance pass flipped hashes):
completed clean, 2205/2205 frames, YDIF dup ratio 0.0005. Sync apply: 2 operator
edits (retime + copy change) → 0 new gate failures, 23 pre-existing reported,
backup written to `plan-history/`, planVersion bumped, second sync clean.
Re-assemble with edits: placements moved (4.06→3.5), text visible in the frame at
25.3s, YDIF 0.0005 again. Palmier code (150 modules) is untouched — demoted to
optional legacy mirror in doctrine only.
