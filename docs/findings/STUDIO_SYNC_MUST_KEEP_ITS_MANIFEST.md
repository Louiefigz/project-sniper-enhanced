# Studio sync must keep its selected manifest through the rebuild

Date: 2026-09-07. This is a command-wiring finding, not creator-quality approval.

## What failed

A normal workspace keeps `producer/edit_plan.json` beside a sibling
`source/asset_manifest.json`. The Studio review command found that manifest
and correctly passed it to its sync worker. Its subsequent assembly builder
only looked beside the plan, so it dropped the selected manifest. An explicit
override was also replaced by a beside-plan manifest during assembly.

That creates an avoidable late failure: the user edits and syncs successfully,
but rebuilding cannot use the same source authority. It can also select a
different manifest path if more than one copy exists.

Printed follow-up commands joined argv with spaces. A workspace containing
spaces, apostrophes or shell syntax no longer copied back into the same argv.
An operator path must remain data when pasted into a shell command.

## The bounded correction

`scripts/producer/studio/review_commands.py` owns existing project path
resolution and assembly argv. Sync resolves one manifest and passes it to
both commands; printed commands use `shlex.join`. Invalid explicit overrides
fail instead of silently falling back. Discovery precedence remains beside-
plan, then the established parent/source layout.

`sync --assemble` without `--apply` now fails before launching anything.
Previously it silently did a dry run, despite the explicit rebuild request.
Failed sync still never chains assembly.

The base-missing message recommends smart dispatch and no longer suggests
renaming a possibly existing final into the base. Review/receipt requirements
are stated before the printed rebuild; their actual enforcement remains in
the existing authority gates.

## Measured evidence

- Seven new pure regressions: six failed before the correction, all pass after.
- Independent review found no blocking issue in the three-file slice.
- A later focused Studio cohort passed85 tests in5.203 seconds.
- The broader cohort passed107 tests but could not start its live player:
  all default3990–3999 preview ports were occupied. No existing server was killed.
- Isolating the test range to41000–41100 and registering cleanup before setup
  failures let the actual pinned Studio player/fixture cohort pass12 tests in
 20.998 seconds. Unique screenshots were inspected, not merely generated.

The fixture contains synthetic color/tone footage. It verifies player scaling,
painting, playback and scoped edit mechanics; it does not establish speech
editing, skin tone, color matching or final-delivery quality.

## What not to infer

A manifest path handed through consistently is not a new cryptographic
snapshot across subprocesses. Existing admission/receipt verifiers still own
source identity. A successful sync is not permission to mint approval, change
graphics ownership, ignore inherited gate failures or export from Studio.

Likewise, a graphics edit may reuse a current base, but "graphics-only" is not
a universal promise that video never re-encodes. Measure the actual stage
decisions and their source/plan/tool dependencies. Do not quote a historical
86-second composite as a future service-level guarantee.
