# Reference identities are not media probe records

## The real failure

On2026-09-07 a fresh synthetic opening-to-body CLI test ran for12m28.886s
before failing at body admission. Source admission, cut preview, opening
render, cleanup, selection and TEST-only approval had passed. The body command
then rejected its retained whole-program base reference, before launching any
body worker.

The two values named the same actual path and SHA:

```text
retained reference: { path, sha256 }
opening observation: { path, sha256, sizeBytes, frameRate, frames, ... }
```

The reader compared the complete objects. Eleven additional measured fields
made them unequal even though the identities matched. Pure fixtures had used
the same minimal shape on both sides, concealing the mismatch. Separate actual
media tests exercised assembly, not this admission-to-activation reader.

Retained evidence:
`/private/var/folders/3m/8rxbwgds5z7c3r72ccfqb9280000gn/T/sniper-body-live-DY4yOw/body-live-evidence`.
This is TEST data, not a creator-quality or throughput qualification.

## Keep the roles separate

A reference answers “which exact file?” A probe record answers “what was
measured about that file?” They have different schemas even when one contains
the other's fields.

Use one validated path/SHA projection in both the writer and reference reader.
Do not duplicate ad-hoc object construction across those boundaries. Compare
that projection with the stored reference, while separately preserving the
complete externally held observation's raw-byte SHA, required fields, original
approval binding, and current source/media verification.

This is not permission to ignore a codec/frame-count mismatch, trust a
self-reported file hash, accept changed observation bytes, or approve video
because a path exists. The outer held-evidence checks still establish those
facts; the projection simply compares like schemas.

## Test the boundary that actually failed

The regression must include a realistic rich probe record, not only
`{path, sha256}` on both sides. Require matching identity to pass and changed
path/SHA to reject. Check all other preparation references too. Then run the
read-only historical reader against the exact retained failed attempt, without
editing its files, resealing its evidence or activating its non-executable claim.

That read-only regression is still not a full fresh execution. A final
source-frozen CLI test must cross admission, activation, actual worker return,
cleanup and readback before claiming that the whole body path works.

## When not to project

Do not project away fields when the contract being compared is the complete
probe/approval/result object itself. Do not apply permissive partial equality
to arbitrary JSON. This approach is appropriate only for an explicitly smaller
reference contract whose complete source evidence is independently bound.
