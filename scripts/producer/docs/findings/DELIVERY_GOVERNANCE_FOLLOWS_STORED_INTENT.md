# Delivery governance follows stored operator intent

## The defect

A plan is model-authored and mutable. If delivery decides whether governance
applies by reading `plan.target`, the plan can change its own scope or mark the
graphics lane `off` immediately before a direct render, assemble, or Palmier
push. The authoring loop may have been correct, yet the final entrypoint can
silently waive the contract it was meant to enforce.

## The invariant

The operator's persisted authority in `project.json` decides whether the
produced/full graphics contract applies. Use `resolvedIntent` when present and
the stored `intent` otherwise; never let mutable plan fields discharge it.

A passing review writes `.sniper-template-usage-approved.json`. The receipt is
tamper-evident and binds the exact:

- plan file and semantic plan content;
- manifest and transcript set;
- controller-captured template-history snapshot;
- stored operator-intent digest;
- template-usage and operator-intent gate implementations.

Saving another draft invalidates the receipt. Every HTTP and Python delivery
boundary verifies it again, including render, assemble, and Palmier push. A
missing, stale, malformed, moved, or digest-mismatched receipt fails closed.

## Why both intent and gate code are bound

Binding only plan bytes proves what was reviewed, not why it was subject to
review. Binding intent prevents a lane flip from changing authority. Binding
the gate implementations prevents an old receipt from authorizing output after
the contract itself changes. This makes the receipt evidence of the exact
decision procedure, not a generic approval flag.

## Verification

`template-usage-approval.test.ts` and `test_template_usage_approval.py` cover
fresh/stale receipts and the plan-lane-flip attack in both languages.
`auto-edit-authority-cross-language.test.ts` proves the TS and Python authorities
agree. Delivery-entrypoint tests assert that the shared verifier is called.

## When not to use it

Do not impose this produced/full system-owned graphics receipt on a stored
trim/light request or a lane the operator explicitly owns. That exception also
comes from stored intent, never from a later plan edit.
