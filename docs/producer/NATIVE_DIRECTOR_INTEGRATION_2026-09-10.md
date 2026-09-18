# Native Script Director integration

Aaron requested the Script Director's actual template-selection workflow in
Sniper. The native backend now runs a Director stage before its scene-planning
worker. It reads the same canonical libraries rather than maintaining a second
hand-curated hook catalog.

## Implemented flow

`compileGuidedTreatmentProposal` with the native V9 route verifies its captured
implementation, prepares the retained source clock and references, then calls
`stageNativeDirector`. The Director author receives the actual source words and:

- The 11-entry Short Format Library.
- The unified hook library's 190 named anchors across 12 categories.
- All 121 R references and 205 T training examples, including the solution-aware
  examples absent from the older 234-entry formula index.
- The formula index's existing slots and disqualification conditions for its
  234 covered entries. Other training examples use the named anchor's slots.

The author records the viewer, problem, awareness, actual payoff, chosen format
and alternatives, one hook anchor/reference and rejected alternatives, grounded
slot mappings, and two or three fills of the same selected template. Every fill
had a literal-evidence audit against the condition set then in force, which was
withdrawn on 2026-09-18 with its library; current decisions use Director plan v2
and the six opening criteria in `resources/director/README.md`. The recorded spoken opening must start at retained occurrence zero.
Source selection and audio are preserved; typography cannot invent spoken words.

A separate, sessionless critic invocation reviews the decision before the scene
worker starts. Its verdict binds the exact plan hash. A failed selected condition,
missing/unknown ID, unfilled source slot, invalid quote, duplicate fill or rejected
critique blocks progression. The gates check concrete bindings and the returned
verdict; they do not establish that the critic's editorial judgment is correct.

The chosen plan includes first-picture, placement, contrast, reading-time and
exit requirements. Those remain proposed direction until inspected in pixels.
The existing limited V9 development renderer retains `DIRECTOR.json` and a
reviewable `BRIEF.md`; it does not yet realize arbitrary native hook typography
or crop plans. The separate native scene worker must retain unsupported requests
as blockers. This integration does not upgrade that renderer or change the main
UI's V5 default.

## Source and execution ownership

`SNIPER_RAG_ROOT` can configure the canonical RAG repository. In this monorepo the
default is the sibling `youtube-automation/rag-system`. An absent library fails;
there is no stock-hook fallback. Model output cannot choose filesystem paths.

Each attempt freezes the six exact library files, source input, author/critic
prompts and results, and the validated record under
`candidate-inputs/native-director/`. Cold reconstruction verifies the original
library bytes, revalidates the plan and critique, and regenerates their prompts.
Changed live RAG documents do not silently rewrite an existing decision.

Existing Codex subscription admission, configured model/effort, tool isolation,
output limits, original generation deadline and stage journal are reused. No paid
pipeline, ASR, media generation or second title bank was introduced. The author
sees the complete bounded retrieval packet. The critic receives the original
material, all formats, selected/rejected examples and relevant anchor siblings;
it does not resend all 326 examples. Both prompts have a 512 KiB bound with a
failure instead of silent truncation.

## Scope of verification

Tests use the real canonical library files and exact source clocks, with explicitly
marked TEST author/critic responses. They cover library completeness, source and
slot binding, rejected hooks, independent-critique ordering, tampering, cold
reconstruction, the stored native candidate, and its exported brief. A rejected
Director critique is tested to prevent the scene worker from being called.

These are executable integration checks. No real provider taste evaluation,
new visual-style comparison, changed three-Short preview, audience test or final
encoded audiovisual qualification is implied. The previous preview hooks remain
historical drafts; this change puts their missing prebuild process into code.

Verification on 2026-09-10: 35 tests passed across `native-director` (4),
`guided-native-proposal` (7), `guided-proposal` (7), `guided-proposal-speech` (7),
and `guided-proposal-history-snapshot` (10). Application type checking, targeted
ESLint and `git diff --check` passed. Tests use simulated model responses.
The application TypeScript configuration now excludes generated `artifacts/`;
its historical standalone preview scripts are not application entry points.
Their frozen bytes were preserved.

The Script Director's Shorts rule chooses a template first and compares fills of
that template. The separate YouTube title recomputation flow asks for three
different title packages. They serve related purposes and must not be conflated.
