# Default animation is not an empty schedule

Observed2026-09-07 during actual UI opening qualification. Status: deterministic
guard implemented and unit/actual-JavaScript schedule parity tested; corrected
full UI render and creative qualification still pending.

## What failed

The synthetic long-form proposal assigned a scoreboard45.9459–47.7477s:
1.8018s,54frames at30000/1001fps. It declared a heading, context chips, hero
number, three tiles, and a final caveat. Its `moduleLands` value was the measured
default empty string. Existing lint treated that as no explicit schedule and
the visible-completion registry did not cover this kind.

Actual rendered frames showed the heading/chips first and the hero number near
the end. The tiles and caveat never appeared before the cut. Valid decoding,
correct frame count, declared DOM copy and exact runtime provenance did not
prove that all intended content was displayed in the planned window.

This was diagnostic inspection of an UNSELECTED synthetic attempt. That attempt
also failed independently on a missing process ledger; it was not approved.
Evidence: `/private/tmp/sniper-unselected-opening-qc-20260907.CBaHfq/`
contains a nine-frame contact sheet and a6fps entry/exit diagnostic burst.
No real speaker, skin-tone qualification or human listening pass is implied.

## Why

Empty means “use defaults,” not “animate nothing.” The actual scoreboard places
present modules at0.2 + index×0.9s. In this case the final caveat begins at2.9s:
it could never be seen in1.8018s. The shared text ramp takes0.2s, and the existing
minimum readable-dwell policy is1.25s. Therefore the minimum complete hold is
2.9 +0.2 +1.25 =4.35s, or4.50s with the optional0.15s exit.

## Fix

`graphics/template_visual_contract.py` now derives scoreboard module presence,
actual default or explicit lands, context/tile/chip fan-out, text-ramp duration
and exit runway. It reads named timing constants from the current HTML/shared
motion source instead of copying those constants into a second registry.
Malformed schedules or missing source timing fail closed.

The shared `visible_timing` reader supplies lint, catalog probe duration and
TEST fixture hold calculation. Validation never changes the user's content,
retimes a card, or deletes its caveat to make a check pass. Catalog probe input
now explicitly names a hero, rather than relying on invisible preview defaults.

`test_scoreboard_visible_timing.py` executes the actual HTML module-build block
against recording GSAP stubs and compares its last completed text ramp with the
Python calculation. Cases cover default/custom timing, absent modules, tiles,
thirteen-chip fan-out, invalid timing, source drift and exit runway.
The focused timing/asset cohort passed18/18 in0.088s test-runner time.

## Fast pacing without losing content

A simple hero number plus label still fits1.8s: its sole module starts0.2s,
settles0.2s later, then has at least1.25s of dwell. A multi-module evidence card
needs more time, an explicitly justified faster schedule, or a simpler authored
graphic. Do not speed every template indiscriminately or remove planned copy.

## Limits

This patch covers scoreboard timing, not every catalog animation. The1.25s dwell
is a floor, not proof that dense copy can be comfortably read. Narration alignment,
actual motion/contrast/font geometry and the final composed video still need QC.
Do not use these unit tests as creator approval or a two-hour throughput result.
