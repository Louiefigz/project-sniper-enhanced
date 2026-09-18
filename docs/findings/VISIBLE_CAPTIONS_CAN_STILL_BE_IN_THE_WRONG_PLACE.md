# Visible captions can still be in the wrong place

Date: 2026-09-06. Scope: measured synthetic1080p caption assembly, not creator
visual quality or whole-video listening approval.

## What the output exposed

An actual NTSC multi-source/J-cut video with music and explicit captions passed
full AuditB and the early/late caption-pixel checks. Its full master had exactly
192192 presented audio samples. Those checks established useful facts, but the
captions were visibly near the middle instead of their requested lower position.

The compiler copied a portrait safety box into a1920×1080 destination. In
particular, a520px portrait bottom exclusion limited the available baseline to
1080−520=560. The plan's existing bottom-center ratio was70%, which requested
756px. A later safety clamp overrode it. The retained early caption glyph top was
510px: it was present and legible enough for a presence test, but misplaced.

This is not evidence that the underlying caption renderer cannot support
widescreen. The error was in destination-aware layout preparation.

## The bounded correction

`scripts/producer/captions/caption_plan_pipeline.py` now selects landscape
insets from the existing aspect layout authority instead of transferring the
portrait exclusion unchanged. The declared placement ratios and portrait
behavior remain unchanged. No user-plan position, font or style is silently
rewritten. The compiler's existing source identity invalidates old compiled
caption/cache evidence.

The corrected actual output has these decoded glyph boxes:

| Sample | Glyph y interval | Declared baseline |
|---|---:|---:|
| Early words |706–749|756|
| Later words |711–744|756|

The three-case actual media cohort passed in34.99s wall. The47-case
compatibility cohort passed in13.37s wall. A regression against the retained
old output fails its placement assertion without rerendering it.

## What to test next time

Presence and position answer different questions. Retain both assertions:

```text
caption pixels exist at the required words
AND their decoded box agrees with the requested destination placement
AND their visible interval and style remain correct
```

Use a high-contrast synthetic source to measure renderer/layout behavior, plus
real footage to assess faces, contrast, composition and readability. Check
multiple times: entry, settled text, changed words and exit may have different
bounds. An ASS/config coordinate alone is not proof of rendered placement.

Do not use this fixture's numbers as a universal safe area or infer that every
caption must use70% height. Other destinations, explicit user placements and
platform overlays need their own policy and observations. Pixel location alone
does not establish reading speed, taste, accessibility, factual correctness or
whether a moving presenter is obscured.

Retained evidence: `/private/tmp/sniper-f1-caption-final-m7h5l5cr`, with the
corrected decoded screenshot and measured boxes. The preceding failed setup
attempt and original misplaced output remain in the implementation log.
