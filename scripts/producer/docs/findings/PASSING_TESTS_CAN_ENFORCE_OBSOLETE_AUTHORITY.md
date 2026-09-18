# Passing tests can enforce obsolete authority

## Finding

A green regression suite proves that the implementation matches the assertions. It does not prove that the asserted behavior is still the right safety contract.

This matters most when an architecture changes from mutable files plus rollback to immutable candidate generations plus atomic publication. A behavior-lock test written for the old architecture can make the unsafe ordering look mandatory.

## The concrete Sniper example

Eight selected authority, surgical-edit, quality-loop, resume, concurrency, and Audit B contract tests passed during the seventh headless adversarial review:

```text
ai-edit-authority-invalidation.test.ts
surgical-edit.test.ts
auto-edit-quality-artifacts.test.ts
auto-edit-quality-loop.test.ts
auto-edit-pipeline-resume.test.ts
ask-edit-preview-invalidation.test.ts
auto-edit-review-concurrency.test.ts
audit-gate-contract.test.ts
```

Three passing assertions conflict with the proposed release contract:

- `ask-edit-preview-invalidation.test.ts` requires `invalidateAiEditAuthority(dir)` before `preparePlanForAi(planPath, plan)`. The implementation clears preview approval before a private replacement has been rendered, audited, reviewed, or published.
- `auto-edit-review-concurrency.test.ts` expects distinct defects sharing model code `SHARED` to merge, while the new controller identity requires rule/lane/time/evidence identity so same-code defects are not silently collapsed.
- `audit-gate-contract.test.ts` accepts an empty machine report and arbitrary report bytes as a passing summary, while generation QC must bind a checked report to exact MP4, plan, effect, base, and toolchain authority.

The first order is the opposite of the new generation invariant:

> A failed, rejected, cancelled, stale, or no-op candidate must leave the previously committed generation selected and recoverable.

The passing test is useful historical evidence, but it cannot remain a release requirement for the new design.

## Why this happens

Behavior-lock tests are often introduced after a production bug. “Hide the old preview immediately” may have prevented a stale result from being presented as the requested new edit. The test then encoded the implementation ordering—early invalidation—instead of the underlying product claim—never mislabel old output as the new edit.

Once immutable generations exist, the product claim has a safer implementation:

- keep the prior committed generation selected;
- label the private candidate as pending;
- never present the prior bytes as satisfying the new request;
- atomically move `CURRENT` only after the candidate passes every gate;
- discard or quarantine a failed candidate without restoring old files.

The user-visible rule survives while the destructive ordering disappears.

## Correct testing strategy

Before changing authority architecture, classify each existing test:

1. **Product claim:** behavior observable at the boundary, such as “a pending request is not reported as approved.” Preserve it.
2. **Safety invariant:** old valid generation or complete new generation, never a mixture. Strengthen it with state-machine and fault tests.
3. **Implementation lock:** call ordering, filename, or mutation sequence specific to the old design. Replace it when the design changes.
4. **Compatibility contract:** behavior intentionally retained for old readers. Keep it only on the compatibility projection, not as primary authority.

For the generation publisher, inject failure before and after every state write, `commit.json`, publish intent, pointer replacement, and compatibility copy. Assert that readers resolve either the exact old commit or the exact new commit. Also test stale-parent interleavings, duplicate requests, `ENOSPC`, cancellation, and process death.

For review/QC migration, add claim-level tests that preserve two defects with the same display code at different evidence windows; reject missing/unbound machine reports; fail when one critic rejects until its sibling is cancelled and reaped; and cover crashes before/after repair promotion, receipt persistence, invalidation, and every previous-approved-media projection step.

## When not to remove a behavior-lock test

Do not delete a test merely because it blocks a refactor. Keep it when the ordering is itself an externally required contract, when old readers still depend on it, or when no replacement claim-level test exists. First state the underlying guarantee, add the new test, then retire or narrow the obsolete assertion.

## General lesson

Tests are evidence about encoded behavior, not an oracle for architecture. When authority or recovery semantics change, audit the tests adversarially: a passing assertion can be the clearest proof that the old unsafe invariant is still active.
