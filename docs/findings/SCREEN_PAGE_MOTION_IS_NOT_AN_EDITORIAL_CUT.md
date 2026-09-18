# Screen-page motion and editorial cuts need different reuse decisions

The LF01 long-form reference is 927.359 seconds at 60 fps. The deterministic
scan sampled 1,855 frames at 2 fps, yielding 222 visual states, while scene-change
detection reported 29 candidates. Those counts describe different things.

Reviewing all 222 states and 101 selected native frames showed why: the creator
keeps a browser and presenter inset stable while changing tabs, scrolling pages,
and operating animated sites. The opening's dramatic beam is inside a local
presentation page. Around 341.6 seconds, a deck crossfades within the screen while
the surrounding browser/presenter remain. Near 913 seconds, the whole composition
changes to full presenter with a hard cut.

A generic rule to animate every changed state would add unnecessary transitions,
and rebuilding every visible website graphic would throw away useful recordings.
The better decision is to identify which layer changed:

```text
captured page/app motion → retain our real screen recording
editorial framing       → native media layout/crop, only when useful
new explanatory graphic → inspect saved catalog match, then configure/compose
missing behavior        → bounded experimental addition with separate review
```

The full catalog also contains near matches with important limits.
`browser-device-stage` supplies device chrome and screen slots, but its default
16:10 shape and 0.9-second entrance differ from a fixed reference browser.
`ui-focus-zoom` supplies a tested camera mechanism for screenshots, not a live
screen-recording slot. `aurora-drift` supplies ambient color, not the reference's
beam; its source uses an onUpdate driver that needs suppressed-seek review.
Saving the source hash **and** these limitations prevents a name match from
becoming an unsupported production choice.

Use this distinction for software demonstrations and screen-led explainers. Do
not assume it fits a vlog, montage, documentary or a reference with extensive
editorial overlays. Re-study the source and classify where its visible motion
originates. These observations do not prove that a particular pacing improves
retention, or that the proposed catalog adaptations render correctly.

Evidence: [LF01 study](../studies/longform-visual-playbook/README.md) and the
[source-frame manifest](../../artifacts/longform-reference-study-2026-09-16/native-frame-evidence.json).

The full extractor also attempts up to 90 OCR frames per detected graphic event.
On this screen-heavy source that repeats substantial page text. The explicit
`--text-scope states --skip-captions` research route keeps the native motion/event
sequence and transcript alignment, reads every state representative, and marks
per-event text timing and caption OCR as unmeasured. The default full analysis is
unchanged. Do not use this research shortcut to claim measured caption animation
or exact word-by-word graphics timing.
