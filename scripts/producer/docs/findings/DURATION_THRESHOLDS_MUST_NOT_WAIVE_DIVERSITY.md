# Duration thresholds must not waive diversity

## Finding

The first-minute variety policy activated at 40.0 seconds, while the C0679 cut
landed at 39.92 seconds. The semantic intro contract still required four
graphics, but the variety gate did not require four different forms. A plan
could therefore alternate two templates across four valid semantic beats and
pass the structural check.

That is a policy-boundary bug: trimming 80 milliseconds must not turn four
distinct required treatments into permission to repeat the same anatomy.

## Deterministic rule

The local variety gate now activates below its duration threshold whenever the
plan already contains the rule's minimum number of semantic graphic windows.
For the first-minute rule:

- fewer than four windows on a genuinely shorter edit are not forced upward by
  the variety gate; the semantic-density contract owns whether more are due;
- once four windows exist, they must satisfy the four-form and ratio floors;
- `A-B-A-B` and four-windows/three-kinds both fail;
- four compatible, semantically bound, distinct forms pass.

Duration remains useful for deciding when density is automatically owed. It is
never a waiver for diversity already promised by the plan or operator intent.
