# Authority literal discovery is not persistence discovery

## Assertion

An inventory that finds every `.sniper*` filename can still miss most of the
system's persistence surface. Hidden-literal discovery and persistence-call
discovery answer different questions; a complete authority audit needs both.

## The incident

The P0 inventory initially scanned quoted `.sniper*`, `.palmier*`, and
`.render-graph-v1` literals. It found 44 literals: 31 were artifact-bound and
13 sat in a reasoned backlog.

After the 13 were audited into lifecycle rows, the hidden-literal backlog was
zero. That looked close to complete, but four blind spots remained:

- digest-derived filenames such as `<sha256>.json` and `<sha256>.media`;
- caller-supplied output roots;
- external stores;
- ordinary names such as `edit_plan.json`, `caption_authority.json`, and
  `palmier.timeline-authority.json`.

More importantly, literal discovery did not enumerate filesystem mutations at
all.

## Evidence

The 2026-07-29 bounded audit now scans 1,106 production Python/TypeScript
files.

- Direct authority-token audit: 312 declared dispositions across 57 artifact
  families.
- Hidden-literal audit: 47 detected, 47 artifact-bound, zero backlog.
- Retained dynamic/non-hidden evidence: 10 records across 29 source files.
- Filesystem persistence AST audit: 820 calls.
  - Python AST: 493.
  - TypeScript compiler AST: 327.
  - Bound to an inventoried artifact writer: 768.
  - Reviewed non-production/ephemeral exclusions: 52 calls across 17 files.
  - Blocking or unknown: zero.
- Process-boundary AST audit: 159 calls.
  - Bound to artifact or tool-execution families: 127.
  - Reviewed build/probe/cache exclusions: 32 calls across 22 files.
  - Blocking or unknown: zero.

The incident still matters: the hidden-literal result became green while only
333 of the then-detected 832 filesystem mutation calls had artifact-writer
ownership. The later family/launcher audit closed that gap without pretending
all outputs share one durability class.

The scanner intentionally uses each language's parser. Python's `ast` module
distinguishes read-only `open()` from write modes and tracks statically evident
`pathlib.Path` values. The TypeScript compiler resolves filesystem imports and
call expressions without confusing comments, strings, or regular expressions
for code.

## The principle

Use three separate controls:

1. literal discovery to catch hidden authority namespace drift;
2. retained boundary evidence for dynamic filenames, caller roots, external
   stores, and non-prefixed authorities;
3. AST persistence discovery to enumerate the declared filesystem mutation
   primitives and require writer ownership.

Do not promote an inventory from `partial` to `complete` because the literal
backlog reached zero. Require zero blocking or unknown persistence/process
sites; every raw remainder must be an exact reviewed exclusion.

The scanner must also publish its limits. This implementation recognizes
direct processes and selected wrappers, but does not infer arbitrary
project-specific wrapper call graphs or full argument-to-output dataflow
inside spawned programs. Explicit wrapper/launcher families inventory those
boundaries; deeper interprocedural analysis is still required before treating
the family rows as per-output lineage proof.

## When not to use this approach

Do not treat a filesystem-call scan as a data-lineage system or a security
sandbox. It does not prove what bytes an external process writes, whether a
database/API mutation occurred, or whether a caller-supplied root is safe.

For a small component with one sealed storage API, auditing that API and
forbidding direct filesystem calls may be simpler. For this mixed legacy
repository, the layered scan is useful because it turns a vague “dynamic paths
might exist” concern into an exact, reproducible unbound set.
