# Caption display corrections should preserve the source word clock

The 38.64-second C0679 Short contained two ASR errors. After listening to isolated
excerpts, Aaron confirmed **“the pain level is this”** and **“sent”**, rather than
the stored `levels` and `set`. The first correction changes one ASR token into
two displayed words. Splitting its timing without acoustic evidence would invent
a word boundary; editing the source occurrence would also change speech authority.

The native route now stores occurrence-specific display corrections:

```json
{
  "occurrenceId": 60,
  "expectedSourceText": "levels",
  "displayText": "level is",
  "reason": "User confirmed this wording after listening to the excerpt"
}
```

Occurrence 60 retains source word index 832 and its `[474,486)` output-frame
window at 25 fps. Both displayed words share that original highlight window.
The existing next-phrase clamp still transfers visibility at frame 485.
Occurrence 86 similarly keeps source index 858 and `[717,723)`, displaying
`sent`. All 110 source occurrences, three source cuts, caption-group membership,
966 output frames and the source timing hash remain unchanged.

The correction is guarded by both occurrence ID and expected source text, so
another instance of the same word cannot be changed accidentally. Duplicate,
out-of-order, stale, oversized and control-containing entries fail. Caption text
limits reuse the existing Long caption predicate. HTML still escapes display text.
Corrections change the visual hash and project output; old projects without
corrections reproduce their original HTML and pacing reports. Source text remains
available beside corrected phrase text in the pacing report.

The change passed 26 native composition/pacing/project tests, the existing
caption-operation and schema-parity suites, type-check, focused ESLint and
independent semantic review. The actual revised picture also passed native text/fit checks, 527 encoded
comparisons, 284 reverse-seek comparisons, complete 966-frame decode and independent
inspection of ten final frames. Its fresh picture and qualified audio reuse
finished in 515.034 seconds. No additional AAC encode was necessary.

This mechanism does not rewrite the canonical transcript, manufacture human
approval, infer a new subword timestamp, or retokenize the accepted cut. Use the
separate source correction workflow when genuinely changing source authority;
its one-to-one text contract cannot be forced to perform a split. User-confirmed
display wording likewise does not approve every audio seam or the whole Short.

Evidence: [the actual confirmation](../../artifacts/shorts-workflow-completion-2026-09-13/confirmed-caption-wording.json),
[source/final auditions](../../artifacts/shorts-workflow-completion-2026-09-13/listening-excerpts-01/README.md),
and [the revised plan](../../artifacts/native-short-storytelling-2026-09-13/plan-v9.json).

Final evidence: [checked corrected export review](../../artifacts/shorts-workflow-completion-2026-09-13/confirmed-caption-final-review.json).
