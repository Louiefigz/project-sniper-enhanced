# Request identity is not a source seal

## What failed

A canonical JSON request digest can prove which overlay entry the controller
selected. It cannot prove which template, asset, renderer source, or build bytes
will execute later.

The counterexample is simple:

1. store request A and admit its JSON digest;
2. change a referenced template, CSS file, asset, or renderer source;
3. prepare the overlay after the change; and
4. produce a perfectly self-consistent tar, build receipt, and render for the
   new bytes under the old admitted request digest.

Nothing is malformed. The authority mistake is temporal: admission approved a
request description, not the bytes that later realized it.

## The correction

Publish one closed, content-addressed artifact before admission. It contains
canonical request JSON, the exact build manifest, every selected overlay's
canonical source tar, and a manifest that binds all paths, sizes, and digests.
Admission stores the closed artifact digest and its build digest.

Later prepare, resume, and launch operations accept authority and attempt
identity, reload the admission, derive the artifact location, and use only its
retained bytes. They never accept caller-selected entries, source roots, build
digests, or seal paths.

## When the lighter digest is still useful

A JSON-only artifact is valuable for schema validation, idempotent request
identity, and rejecting request A plus entry B substitution. Use it for those
claims. Do not call it a preseal or count it as proof against
admission-to-execution source drift.
