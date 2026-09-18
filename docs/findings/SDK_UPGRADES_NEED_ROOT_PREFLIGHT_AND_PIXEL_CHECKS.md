# SDK upgrades need root preflight and pixel checks

## What happened

On 2026-09-08, Project Sniper upgraded HyperFrames from 0.7.33 to 0.8.31.
The packages installed successfully and the sealed runtime's version/hash
probe passed. That did not mean our existing rendering adapter was compatible.

The first real catalog attempt stopped after 7.541 seconds. HyperFrames now
requires at least 1024 MiB free in the output directory. Our existing 1 GiB
temporary filesystem already contained a log, so it was just below that floor.
The user's disk was not full. We retained the guard and introduced an explicit
version-to-quota mapping: 0.8.31 uses 2 GiB; retained 0.7.33/1g receipts keep
their original allowance. Unknown versions reject. Accepted media still has
the separate 512 MiB output limit. Codec, quality, memory and network settings
did not change.

The next attempt rendered 32 templates, then stopped on template 33 after
515.671 seconds. The actual animation registered its timeline in an external
script. The new HTML-only strict lint could not see that registration.
Initializing the real registry before the script, and checking the actual
paused/seekable timeline afterward, fixed the compatibility issue. Merely
inserting a comment containing the expected text would not have fixed it.

## Why a directory lint was not enough

The upstream directory scan treats HTML under `compositions/` as subcompositions.
Some root-only rules are exempt there. Rendering that file as the root runs a
different rule context. We therefore checked all 53 files as roots before the
next expensive render cohort: zero errors in 25.198 seconds, with 26 warnings
retained. Pipeline had zero errors or warnings.

The installed official `@hyperframes/lint@0.8.31` also exposes the exact root
entry API that the render path uses:

```js
import { lintProject } from "@hyperframes/lint";

const result = await lintProject(motionRoot, absoluteCompositionPath);
```

This avoids writing a shadow validator. The CLI's `lint` command does not
expose that entry argument. A batch can share one Node process; do not assume
the SDK's higher-level session API reexports the linter. Before adopting this
as a production preflight, preserve exact version/dependency provenance,
original source identities, a bounded total deadline and retained findings.
The full project linter can probe local video metadata; "lint" is not by itself
a guarantee of no child processes or network activity.

The integrated official-root preflight subsequently passed all53 entries in
1.47 seconds wall, with the same26 warnings. Its bounded Node child refuses
network and child-process attempts, including errors swallowed upstream. The
retained source/dependency checks bind the direct linter/parser implementation,
not every transitive installed module. This is intentionally not a second
renderer or a complete dependency-attestation framework.

## What preflight cannot tell you

Real rendering still matters. Both upgraded native frame observers subsequently
passed: 75 agenda frames and 104 pipeline frames, with exact cleanup, in 20.652
seconds including preflight. That proves those observation paths, not final
caption legibility or creator approval.

Pixels can also change despite unchanged animation source. At staircase frame
54, the new runtime restored an intended kicker missing from the old output.
The main title stayed unchanged. Two reviewers checked the actual images and
the source intent; this was a specific improvement, not a blanket claim that
every render is better. Seven comparable renders totaled 109.353 seconds versus
129.650 previously, but uncontrolled host load and changed quota make this an
observation, not a controlled speed benchmark.

A separate real SDK revision illustrates the useful reuse boundary. Re-proving
two existing six-second units took2.714 seconds; changing one title and rendering
only its unit took44.463 seconds, with47.973 seconds total including setup and
readback. Original left bytes and high-quality ProRes4444 alpha were unchanged.
That warm-cache result does not clear an earlier120-second cold-run failure.
Measure proposal, cold render, warm reproof and changed-unit render separately;
a0.287-second text proposal is not a finished video edit.

## Measure validation overhead separately, too

A Node CPU profile of one real cleanup TEST attributed about1.969seconds
inclusive to staging code-pin capture. A separate actual-class count probe
explained why:303 one-byte TEST pins incurred184224 pin stats plus2424 original
claim/input stats. Each pin invokes four checks of a growing held-file set:
the pin term is `2*N*(N+1)`, not linear. The original guard, expectation and
resource callbacks each ran1212times. The count probe itself took1.06seconds
for five sizes; it is not production timing or a before/after improvement.

This identifies work to optimize, not checks to delete. A private prepublication
batch could hold original identities, hash under the original control callbacks,
then validate the whole set before any reservation/result becomes available.
Live prelaunch hooks also re-enter full metadata checks, so removing just one
direct scan would not solve the problem. That change requires focused mutation,
reentry and cancellation qualification; it has not been implemented or counted
as a speedup. Keep all original quality and publication checks until equivalent
failure detection is demonstrated. Detailed counts and the runnable probe are
under `/private/tmp/sniper-staging-count-review-20260908.nHrDnJ/`.

Subsequent implementation supersedes that pending status: the reviewed private
batch is now integrated. At303pins its direct count is2424(8N), or3636(12N)with
genuine live-owner hooks; each original direct work/expectation/resource callback
still runs1213times versus1212before. Original claim/input checks increase, not
disappear. One matched pair of metadata TEST commands measured9.00→5.06seconds,
not a render benchmark. The agent's158tests passed; independent root36batch tests
and17live staging tests passed as separate overlapping checks.

The explicit tradeoff is that mutations among unpublished prospective pins may
be detected at the final batch boundary rather than the next unrelated pin.
Every original identity/parent is captured first, completed output cannot escape
before validation, and original held inputs keep their immediate checks. Caught
reentry poisons publication. Failed-batch phase-only cancellation keeps leases
and cannot manufacture a complete cancellation inventory or cleanup proof.
Details: `/private/tmp/sniper-staging-batch-20260908.nTn2tC/review.md`.

## When not to apply this approach

Do not rerender the entire catalog for every editorial revision. This was
one-time runtime qualification. Normal editing should reuse only artifacts
whose actual source, runtime and request identities still match. Do not treat
all-template lint or default-spec renders as approval for arbitrary long copy,
different frame rates, composited captions, sound, color or a full master.

Detailed evidence and retained failures:
`docs/producer/HYPERFRAMES_0_8_31_UPGRADE_2026-09-08.md`.
