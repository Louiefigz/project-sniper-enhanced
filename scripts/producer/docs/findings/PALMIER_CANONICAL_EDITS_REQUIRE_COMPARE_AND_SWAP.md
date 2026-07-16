# Palmier-canonical edits require compare-and-swap

## Finding

If the visible Palmier timeline is the user's source of truth, a Sniper plan
hash is not enough to authorize an AI edit. Palmier can change independently,
and an AI job based on yesterday's `edit_plan.json` would silently erase those
manual changes on its next mirror.

The safe unit is an immutable Palmier timeline revision:

1. Read `get_projects` and require the expected project to be active.
2. Read `get_timeline` with `captionDetail: true`.
3. Hash the entire returned JSON, including unknown fields. Defaults omitted by
   Palmier are deterministic; object key ordering is not, so keys are sorted.
4. Immediately before work, compare the active project, timeline id, and full
   hash to the saved baseline.
5. Fork with `create_timeline {from: <canonical timeline id>}`. Palmier documents
   this as a full copy whose clip and track ids are regenerated.
6. Re-read the fork. Compare a second semantic hash which normalizes only known
   structural ids. Effect/model fields such as `params.id` remain content.
7. Edit only the fork. The canonical timeline is never an in-place AI target.
8. Promote the candidate only after QC and a second unchanged-source check.

This is compare-and-swap (CAS): the candidate may replace the authority pointer
only if the exact source revision it copied is still current.

## Current implementation

`palmier/timeline_authority.py` writes two separate records:

- `palmier.timeline-authority.json` — the canonical Palmier revision;
- `palmier.timeline-candidate.json` — an unpromoted copy plus its base hash.

Creating a candidate cannot update canonical authority. `promote_candidate`
requires both an explicit QC verdict and an unchanged canonical source. New
Sniper draft/mirror timelines establish a baseline after readback.

Both Ask AI and Auto Edit run a read-only authority guard before invalidating
preview proof, snapshotting a plan, or launching a model. Manual drift is saved
as the new Palmier baseline and the current plan-only editor is blocked. That
is intentional: preservation is implemented; Palmier-native delta planning and
application are not connected yet.

## Readback boundary

Palmier's current `get_timeline` surface is rich: trims, transforms, opacity,
audio deviations, color, effects, keyframes, text, and caption summaries are
reported. Per-caption detail requires `captionDetail: true` and is capped at
200 rows per caption group. A group above that cap is marked incomplete and AI
forking fails closed; it must be paged before the claim can become complete.

This hash proves only the MCP-readable timeline. It does not claim to capture
an app property Palmier does not expose. Unknown exposed fields remain in the
hash so new MCP fields strengthen the guard automatically.

## Live contract evidence

An isolated Palmier Pro 0.6.3 project exposed a gap the mocks did not: after a
full-copy fork, `get_timeline` adds a root `timelines` inventory, and the
playhead appears as `currentFrame`. Neither is edit content. Both are now
excluded alongside `canGenerate`; unknown fields are still hashed.

After that correction, the live test proved all of these together:

- the fork had new timeline/track/clip ids but the same semantic edit;
- changing candidate opacity changed only the candidate fingerprint;
- switching back showed the canonical parent's full fingerprint unchanged;
- `inspect_timeline` returned composited-frame metadata;
- `export_project` with the candidate's explicit `timelineId` produced a
  valid 2.0-second, 21,865-byte video;
- the previously active user project was restored and every disposable test
  project was moved to Trash.

The repeatable live-only test is
`scripts/producer/tests/live_palmier_canonical_smoke.py`. It is deliberately
outside the offline suite because it launches/mutates Palmier.

## When not to use this approach

Do not copy the timeline and then immediately mark the copy canonical. That
loses the CAS source pointer before the edit or QC has happened. Do not strip
every field named `id` for copy equivalence: an effect model id may determine
the rendered look. Do not fall back to a stale Sniper plan when Palmier is
closed; under a Palmier-canonical product, inability to read the source is a
real blocker, not permission to guess.
