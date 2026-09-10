# Output path is not the authority root

## Assertion

An isolated candidate output directory is a destination, not the project
authority root. Delivery gates must resolve operator intent and approval
receipts from the canonical plan/controller directory.

## The incident

The auto-edit quality loop renders candidates under:

```text
<producer>/.sniper-qc/<run>/round-<n>/final.mp4
```

`assemble.py` passed `dirname(out)` to the template-history approval gate.
That happened to work for the ordinary `<producer>/final.mp4` route, but a real
candidate render searched the QC round for `project.json` and failed:

```text
delivery needs a valid stored operator intent in project.json
```

The unit pipeline missed this because its assemble dependency was stubbed.

## Evidence

The retained acceptance at
`artifacts/p1-auto-edit-qc-gated-graph-20260729-rerun2/` rendered an actual
three-second, 72-frame candidate through `assemble.py`.

- The first graph remained active while the changed candidate was staged.
- The candidate activated only after its exact SHA-256 was reverified and moved
  to canonical `final.mp4`.
- The activated incremental output and isolated forced-full output were
  byte-identical: SHA-256
  `dc3ef09b691cb17dec1f0ad51c080a57cc97605fbf51358ed8327e99827caea8`.
- Exact decoded picture, normalized PCM, and stream facts matched; oracle
  receipt hash:
  `91d72c45c2722f60fff2f0326de804d642ccd2d3c001e32012d90c6e2c4d6c7c`.

The fix derives the template-approval authority directory from
`dirname(plan_path)`. Candidate-local locks, diagnostics, and review artifacts
still derive from `dirname(out)`.

## Principle

Classify every path parameter by role:

| Role | Example | May locate authority? |
|---|---|---:|
| authority input | canonical `edit_plan.json` | yes |
| admitted input | source-set-bound manifest | only its own source authority |
| private output | QC candidate `final.mp4` | no |
| promoted output | canonical `final.mp4` | no; it must be bound by a receipt |

A consumer should never infer project identity from a path chosen merely to
hold output bytes.

## When not to use this rule

Do not replace all output-relative paths with the plan directory. Locks,
proxies, audit frames, placements, and candidate diagnostics intentionally
belong beside the output they describe. Only authority and approval lookups
must remain rooted in controller-owned inputs.
