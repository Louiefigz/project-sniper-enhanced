# P3 exit audit — first-class captions

> Status: **PASS for the bounded P3 caption subsystem.**
>
> This is not a claim that the complete Project Sniper workflow, native
> Palmier caption editing, creator-footage cohort, or 90-minute long-form SLA
> has passed.

## Exit table

| # | P3 exit | Status | Executable evidence |
|---|---|---|---|
| 1 | Arbitrary range karaoke/style | **PASS** | `test_caption_compile.CaptionCompilationTests.test_arbitrary_phrase_range_can_enable_karaoke_only_there` resolves an exact stable-word phrase. `test_p3_caption_phase_demo` changes that phrase from line captions to karaoke in real alpha media. |
| 2 | Caption-only edit rebuilds only caption/preview nodes | **PASS** | The retained short/long traces reuse the caption-free base and unchanged shard, render only the changed shard, stream-copy identical audio, and match a forced-full decoded-frame oracle. `test_current_render_caption_graph` dirties the changed caption shard, composite, and final while reusing the base and other caption shard. |
| 3 | Repeated-name correction hits the right occurrence | **PASS** | Python stable-ID and occurrence tests target only the selected repeated word. The combined phase demo corrects the second `Jon` while retaining the first. The TypeScript word index resolves the requested timestamped occurrence before the model sees the plan. |
| 4 | SRT and burned output match | **PASS** | `test_caption_outputs` compares cue text and exact half-open frame ranges. `test_caption_legacy_integration` materializes SRT, ASS, Palmier alpha bindings, real burned media, and Audit B from one compilation. |
| 5 | Chapters bind the same timeline and survive non-ripple repair | **PASS** | `test_caption_outputs` binds chapters to stable word IDs. `test_caption_repair_revalidation` changes one local word timing, retains the chapter hash, and rejects a shifted downstream cue outside the declared dirty window. |
| 6 | No missing, duplicate, or ghost words after cut/speed changes | **PASS** | The compiler coverage gate rejects any missing/duplicate/ghost set. Stable-word, repeated-slice, cut/speed, legacy-ghost, and partial-correction tests pass. |
| 7 | Timeline/speed changes dirty every affected cue/placement node | **PASS** | Cue fingerprints bind exact frames, samples, relevant timeline-map slices, segment versions, destination, and compiler closure. Local-map tests retain unrelated cues; the downstream-shift repair test fails closed when the dirty window is incomplete. |
| 8 | Phase demo: one karaoke phrase, one repeated-name correction, all other caption/base nodes unchanged | **PASS** | `test_p3_caption_phase_demo` retains four initial shards, changes exactly two, reuses exactly two, preserves the base and mastered audio, and matches a forced-full decoded-frame oracle. The exact result is stored under `phaseDemo` in `p3-caption-shard-traces.json`. |

## Command-ingress correction found by this audit

The render subsystem passed, but the controller previously treated every
quoted string as source transcript text. A normal request such as:

```text
At 45 seconds, change "Jon" to "John" in the captions.
```

resolved `Jon`, then rejected the edit because replacement text `John` was not
already in the transcript. It also allowed a sole matching phrase at 45
seconds to be selected by a request that explicitly said 120 seconds.

`caption-word-index-v1.ts` now:

- removes the replacement side of source-to-target correction syntax from
  source anchors;
- applies a two-second timestamp tolerance even when only one occurrence
  exists;
- reports `timestamp-mismatch` instead of silently selecting distant text.

`caption-word-index-v1.test.ts` retains both regressions.

The caption text boundary is also runtime-neutral now. TypeScript
`caption-text-contract-v1.ts` and Python `caption_contract.py` use the same
explicit edge-whitespace set and count Unicode code points rather than
JavaScript UTF-16 units. The retained tests cover DEL (`U+007F`) as valid
interior text, `U+0085`/`U+FEFF` edge trimming, and the 500/501-code-point
boundary with astral characters for correction reasons, display tokens, and
chapter titles.

## Reproducible focused gate

```bash
PYTHONPATH=scripts/producer:scripts/producer/tests \
  .venv/bin/python3 -m unittest -v \
  tests.test_p3_caption_phase_demo \
  tests.test_caption_shards \
  tests.test_caption_compile \
  tests.test_caption_repair_revalidation

for f in \
  src/lib/producer/__tests__/caption-chapters-v1.test.ts \
  src/lib/producer/__tests__/caption-operations-v1.test.ts \
  src/lib/producer/__tests__/caption-schema-parity-v1.test.ts \
  src/lib/producer/__tests__/caption-word-index-v1.test.ts
do
  node --import tsx "$f" || exit 1
done
```

The 2026-07-30 caption discovery rerun passed **80/80 Python tests** in
9.745 seconds. All four caption TypeScript scripts and TypeScript
type-checking also passed. The final repository-wide regression run executed
**3,480 Python tests with no failures and one intentional skip**, then passed
both JavaScript harnesses and all **200 TypeScript test files** in
`npm test`.

## What P3 does not prove

- It does not qualify creator speech, multi-camera/VFR projects, or a real
  10–14 minute project.
- It does not qualify native Palmier captions. Exact review delivery remains a
  bound flattened master; caption alpha assets are baked but regenerable.
- It does not prove that a caption repair preserves a populated graphics,
  b-roll, transition, and music project together. That is the post-P5
  integration demo.
- It does not turn P2 word-safe cut repair or the P5 render graph/SLA into
  released capabilities.

Those boundaries keep the P3 **PASS** narrow and truthful.
