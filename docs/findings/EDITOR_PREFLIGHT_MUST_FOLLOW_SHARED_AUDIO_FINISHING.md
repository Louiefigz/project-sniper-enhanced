# Editor preflight must follow shared audio finishing

On September 10, 2026, the JavaScript regression continuation stopped at
`guided-caption-profile.test.ts`. The TypeScript opening preflight refused
`audioEnhance: {preset: "voice"}`, while the actual Python opening profile
accepted it through the existing source-float-v2 program master.

That mismatch prevented supported audio cleanup from reaching the editor. The
negative fixture was also outdated: `voice` is an installed filter preset,
whereas `separate` still requires a different, unsupported runtime for this
execution path.

## One execution owner, matching early checks

The TypeScript preflight now checks the existing enhancement menu, excludes the
separate runtime, and validates numeric gain windows and overlap. It preserves
the submitted plan. Python still owns full plan validation, exact program
bounds, actual filter/model availability, audio mastering and output proof.

Enhancement and gain belong to the shared program master before the opening
excerpt is sliced. This change does not admit visual transitions, SFX, new
presenter profiles or downloaded runtimes. Historical unavailable-only
authority records retain their original contract.

A single cross-runtime test sends **140 cases** through the actual Python
profile and both TypeScript opening/body metadata checks. It covers long and
short plans, with and without captions, supported presets, valid gain windows,
invalid presets, malformed fields and overlap. Separate checks reject
nonfinite JavaScript values without coercing them into numbers.

## Direct Python callers need the same numeric boundary

Review found that `audio.audio_gain.parse_windows` called `float()` before
checking input types. As a result, a boolean start or a string dB value could
become a number, and NaN endpoints could survive the ordering comparison.
The frontend's rejection did not protect direct Python/skill callers.

The shared parser now requires actual `int`/`float` fields and finite converted
values. Overflow follows the existing `ValueError` contract. Valid numeric
windows keep their ordering, gain limits, overlap checks and filter output.
An isolated candidate compared valid filter output with the prior parser;
the applied repair then passed **129 tests in 3.577 seconds**, including
direct finishing-call rejection of malformed values in all three fields.

These are contract and regression results, not listening approval or a new
video-render timing measurement. Reuse this approach when an early UI check
drifts from an existing execution owner; do not use a preflight change to
claim an unimplemented media capability.
