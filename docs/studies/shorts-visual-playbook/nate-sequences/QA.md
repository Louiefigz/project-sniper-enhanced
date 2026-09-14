# Evidence scope and delivery checks

The library contains 12 complete cases from the existing 30-Short Nate corpus.
This is a purposeful selection for differing story mechanisms, not a ranking of
performance or an assertion that 12 cases cover every future editing need.

## Visual review

Three parallel reviewers revisited N01–N09; the root reviewer revisited N10,
N26 and N27. Review included complete chronological half-second context sheets,
timed machine-caption references and finer inspection of selected movements.
The case JSON records the actual evidence paths and limits for each review.

For delivery, all case overview pages and selected beat sequences/full frames
were inspected against the notes. This checks the representative images and
important interpretations; it is not a claim that all 991 selected full frames
were individually opened at native resolution or that audio was auditioned.

- [N01–N03 delivery receipt](../../../../artifacts/shorts-visual-playbook-2026-09-10/expansion/inspection/nate_corpus-final-qa.json).
- [N04–N06 delivery receipt](../../../../artifacts/shorts-visual-playbook-2026-09-10/expansion/inspection/nate_catalog-final-qa.json).
- [N07–N09 delivery receipt](../../../../artifacts/shorts-visual-playbook-2026-09-10/expansion/inspection/three_cuts-final-qa.json).
- [Root delivery receipt](../../../../artifacts/shorts-visual-playbook-2026-09-10/expansion/inspection/root-final-qa.json).
- [Integrity and coverage validation](validation.json).

## Corrections incorporated

- N03-B09 labels its first image as the previous setting, before the changed
  background is present. The sampled handoff is retained rather than claiming
  the new background existed throughout the approximate interval.
- N08-B33 overview uses the final sampled state showing all three priority labels.
- N09-B15 is a lateral sheet movement at broadly stable scale; the earlier
  face-zoom interpretation was removed, and the catalog guidance changed with it.
- N10-B19 acknowledges the request's brief loading state before the earlier,
  different deck returns. The case does not portray that deck as its output.
- N26's carriage-to-presenter cut was refined with native frames 435 and 436;
  the first presenter frame is at 14.560 seconds.
- N27's supposed weekly/annual unit conflict was retracted after two reviewers
  inspected individual 1080 frames. The verified source issue is edge clipping.
  Earlier mechanics and reconciliation notes were corrected as well.

## Integrity checks

Validation covers contiguous case intervals, unique case/beat IDs, samples inside
their intervals, source video hashes, exact referenced frame/sequence hashes,
1080 × 1920 source-image dimensions, existing inspected evidence and catalog files,
local Markdown links and the edited planning skills' frontmatter.

The selected frames were decoded by source frame index. Requested sample times
and actual presentation timestamps are stored separately. Exact frame timestamps
do not make approximate editorial or machine-caption boundaries exact.

## Limits that remain explicit

Source audio exists in the original study but was not auditioned in this work.
No music, sound-effect, phonetic alignment, exact easing or voice-quality finding
is claimed. A chronological frame study can establish visible story structure;
it cannot stand in for listening to the final edit.

The 22 catalog mechanisms are inspected implementation candidates. Their sources
are hashed, and the case describes the content and adaptations still needed.
They have not been adapted, rendered or qualified by this research step.

The saved guide and producer instructions require opening references during
planning and reusing them for Studio QA. Automatic image retrieval and template
selection are not implemented by these documentation changes.
