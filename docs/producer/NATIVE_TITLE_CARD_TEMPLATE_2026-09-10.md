# Local native title-card template

The project has a local path from the packaged Director library to an actual
backed title card. It does not launch a model or require an external
Director call. The product owner requested local-only work on September 10; do not treat
later styling feedback as permission to send transcripts or references externally.

## Implementation

- [`native-director-library.ts`](../../src/lib/server/native-director-library.ts)
  reads the packaged Director library (`resources/director`, or an operator-configured
`SNIPER_DIRECTOR_LIBRARY` with the same files).
  The existing library snapshot/hash stays authoritative; there is no second
  manually maintained list of hooks.
- [`native-hook-template.ts`](../../src/lib/server/native-hook-template.ts)
  selects a real anchor, fills named slots locally, rejects missing/unknown slots
  and retains formula, category, slot values and library hash. Literal filling
  supports quoted formulas. Other editorial formula shapes are explicitly refused,
  not guessed. The one optional clause, ` (in [timeframe])` in `steps-toward-goal`,
  may be omitted.
- [`native-title-card.ts`](../../src/lib/server/native-title-card.ts) renders
  immediately visible, centered lines with close-fitting opaque backing in the
  upper portrait region. Available pairs are `ink-on-paper`, `paper-on-ink` and
  `white-on-slate`: neutral, at least 11:1 by the WCAG 2 contrast formula, with the
  rationale in the module header (chosen 2026-09-18).
  It enforces contrast ≥ 4.5, readable size bounds, an upper placement and an exact
  frame lifetime. Line breaks must preserve the selected hook's words.
- [`native-short-composition.ts`](../../src/lib/server/native-short-composition.ts)
  accepts `titleCard`, removes it at its exact end frame and refuses a second old
  hook layered underneath. `centeredNativeCaptionView` supplies a separate centered
  speech lane with white text, dark outline and yellow active words. Highlight
  timing uses retained source-word frame bounds, with no new ASR.

```typescript
const copy = fillLocalHookTemplate(loadDirectorCatalog(), {
  anchor: "steps-toward-goal",
  slots: { count: "Two", goal: "a follow-up that earns trust" },
});
const titleCard = {
  copy,
  lines: ["Two steps to a follow-up", "that earns trust"],
  palette: "white-on-slate" as const,
  top: 110,
  fontSize: 76,
  endFrame: 98,
};
// Pass titleCard to buildNativeCanvas with actual source/cut/frame evidence.
// Choose caption top from the actual shot, independently of the title.
const captionView = centeredNativeCaptionView({
  startFrame: 0, endFrame: 326, top: 1080,
});
```

This compiles copy and pixels, not judgment. A filled formula does not establish
that the footage earns its promise. Check actual fonts, line widths, face/hand
clearance, readable lifetime and caption grouping in the target shot. The three
palette fixtures compare visual presentation of one hook, not three hook families.
The generic native canvas is connected; the limited V9 development writer and
legacy main UI still need their separate geometry/execution integration.

## Exact user-supplied titles

When the user supplies the wording, use `createUserTitleCopy(text)` from the
same hook-copy module. It preserves case and punctuation, rejects blank,
overlong or control-character input, and records `scope: "user-supplied-title"`.
The shared card renderer and cold project reader validate this provenance and
the exact words in the requested line breaks. The HTML carries the user scope
without inventing a canonical hook anchor or library hash for the text.

For example, the September 15 revision uses “POV: You commented SKILL for an Ai
video editor”. Its layout reuses the backed upper title card. Its copy is the
user's POV framing; it is not a fill of any Director anchor.
Copy provenance and visual-template reuse are separate decisions. Preserve the
original speech, cuts, captions and title lifetime during a copy-only revision,
then verify the rebuilt title's actual readability and promise against the clip.

The product owner's subsequent review accepted the offer storytelling/B-roll and rejected
mechanism-led hooks. The current revision uses “Use this offer formula to get
more buyers”; members uses “Who else wants $1K/mo in their first 30 days?”.
See [template compliance versus hook strength](../findings/TEMPLATE_COMPLIANCE_IS_NOT_A_STRONG_HOOK.md).
The Director's `viewerStake` criterion distinguishes the viewer's goal from the
speaker's mechanism and asks what gives the viewer a reason to watch. Local
filling remains a copy operation, not automatic editorial or audience approval.

## Layout decisions for this change

The layout was decided on the owner's footage and an operator-supplied screenshot
showing a large backed upper promise over a distinct centered torso caption, which
was a direct operator preference for this revision. Third-party reference frames
consulted at the time were withdrawn from the product on 2026-09-18 and are not
cited here. The decisions that remain:

- Title and speech are two independent layers: the title sits above the head and
  clears for the closer explanation; captions stay centered near torso height.
- Keep captions at a stable horizontal reading position; never push them sideways
  to make room for a title.
- A full-frame formula or diagram has one information job and the worked example
  another.
- Do not copy a screenshot's multi-item promise into footage that holds one lesson.

Hook structure is chosen from the Director library separately from these visual
decisions; colour choice does not determine hook structure.

## Retained corrections for the three edits

1. **Follow-up:** replace the middle topic heading with the backed upper treatment;
   keep phrase captions centered near torso height, with source-timed highlighting.
   The retained closing “I trust this dude” supports the trust payoff. No revenue,
   universal conversion or guaranteed result should be added.
2. **Offer:** the current selection omits the explicit reason “but it seems way too
   vague” at source 61.92–63.28. Restore that reasoning in the scoped cut revision.
   There is a fluent complete example at 90.19–92.91, instead of the halting earlier
   construction. Make the lesson clear: **specific outcome + timeframe**, then show
   **current wording → specific wording** as its application. The final source
   segment mentions benefits generally; it does not explain or demonstrate specific
   health benefits. The Short's supported teaching job is offer clarity.
3. **Members:** preserve the accepted arithmetic and close presenter. Raise captions
   near the midpoint divider, clearing the result/MRR labels and the pointing hand.
   Keep the goal distinction. Changing caption style does not require a new cut or
   remaster; reuse the proved dialogue after picture-only revisions.

These corrections are now in the [three revised exports](http://127.0.0.1:3993/).
Follow-up reuses the byte-identical verified title component; the offer is now a
24.52-second module-style visual story; members retains its accepted arithmetic.
All three use canonical filled hooks, upper contrasting backing and centered
source-timed karaoke. The [test report](MODULE_STORYTELLING_TEST_2026-09-10.md)
records actual references, rendering, output checks, reuse and remaining limits.
Local template filling is implemented; broader live Director qualification remains
declined. No component or export carries a fabricated independent-review receipt.
