# Authoring deadlines must recover fresh checkpoints, not discard them

## Finding

A model-process timeout and a failed edit are not the same state. If an
authoring attempt writes a new, parseable, hash-bound `edit_plan.json` before
its deadline, the controller may recover that file as `plan_authored`. It must
then run the normal deterministic gates and independent critics. It must never
promote the recovered plan directly to render or approval.

## The C0679 incident

The 30-minute authoring attempt had already run every required hard gate
successfully. The last recorded gate bundle was clean about 15 seconds before
the watchdog fired. The agent nevertheless kept refining advisory warnings,
did not return its completion message, and was killed at 1,800 seconds.

The old controller checked `timedOut` before inspecting the plan written by
that attempt. The UI therefore reported a failed edit even though a usable
draft existed on disk, and `Retry edit` started authoring over from the
beginning.

## Contract

Before authoring starts, capture the canonical plan-content hash (or absence).
After a timeout, recover only when all of these are true:

1. `edit_plan.json` now exists and parses as an object;
2. its content hash differs from the pre-attempt hash;
3. the raw-file and canonical hashes agree with controller-owned reads;
4. the recovery advances only to `plan_authored`;
5. the ordinary planning-review loop still runs from round one.

An absent, unchanged, malformed, or authority-changing file remains a failed
attempt. The hard deadline remains in place; increasing it merely makes the
same control-flow bug slower.

The authoring prompt also has a termination rule: gate warnings are advisory.
Once every required gate exits zero, the agent stops optional investigation,
prints the final completion line, and exits.

## Why this is safe

The recovery trusts no model claim. It trusts a fresh disk artifact and then
subjects that artifact to the same controller-owned gates, two clean
independent reviews for Produced/Full work, isolated rendering, and rendered
QC. Recovery saves completed work without weakening any approval boundary.

## When not to use this pattern

Do not recover a plan whose bytes predate the attempt, whose JSON is malformed,
or whose authority changed while the writer was running. Do not use checkpoint
recovery for a renderer that may have partially replaced delivery files; render
into isolated candidates and require fresh provenance instead.
