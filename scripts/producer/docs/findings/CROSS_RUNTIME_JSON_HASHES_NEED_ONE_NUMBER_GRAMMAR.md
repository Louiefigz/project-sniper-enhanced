# Cross-runtime JSON hashes need one number grammar

## Assertion

Sorting object keys is not enough to make a Python JSON hash equal a
TypeScript JSON hash. Every writer and every verifier at a shared authority
boundary must use the same serializer, including its number, Unicode, key
ordering, omission, and invalid-value rules.

## The incident

Several Producer receipts were described as canonical but were independently
implemented with `json.dumps(...)` in Python and
`JSON.stringify(stableValue(...))` in TypeScript.

That worked for ordinary fixtures and failed for valid edge values:

```text
value       Python json.dumps     JavaScript JSON.stringify
0.000001    1e-06                 0.000001
```

Numeric-looking object keys exposed a second difference. Rebuilding a sorted
JavaScript object does not preserve lexical insertion order for array-index
keys, while Python `sort_keys=True` sorts the strings themselves. A valid
object containing keys `"2"` and `"10"` could therefore hash differently.

A separate, domain-prefixed caption-ledger serializer had one more edge:
TypeScript left U+007F DEL literal while Python `ensure_ascii=True` escaped it.
Both validators allowed the character, so a TypeScript-bound correction ledger
could later be rejected by Python.

These were authority failures, not cosmetic hash differences. They could make
an approved compatibility picture lock undiscoverable, reject a cut-repair
context minted by the materializer, or reject a caption correction at compile
time.

## Evidence

The shared compact serializer now has retained TypeScript-to-Python coverage
for:

- 10,011 finite JavaScript numbers, including `-0`, `1e-7`, `1e-6`, and the
  minimum subnormal;
- Unicode code-point key order, astral characters, and lone surrogates;
- numeric-looking keys including `"2"`, `"10"`, `4294967294`, and
  `4294967295`;
- sparse arrays, whose missing elements must become `null`;
- fail-closed rejection of non-finite numbers, unsafe integral values, and
  `bigint`;
- transcript cut-track and cut-decision hashes across Python and TypeScript;
- doctrine, pipeline-lock, learning-observation, plan-refit, Palmier-plan, and
  template-usage authority boundaries;
- the existing ASCII/domain-separated caption-ledger format, including DEL.

The materializer-to-analyzer cut-repair regression also carries `1e-6`,
`1e-7`, and numeric-looking keys through the real writer and reader rather than
testing two isolated helper functions.

## The principle

Treat canonical serialization as protocol code:

1. Name the exact domain. Producer currently has a general compact authority
   domain, a historical spaced plan-content domain, and a legacy
   ASCII/domain-prefixed caption-ledger domain.
2. Implement one serializer per domain and import it on both sides of every
   writer/reader boundary.
3. Serialize tokens directly. Do not sort entries, rebuild an object, and then
   assume `JSON.stringify` will retain that order.
4. Reject values whose identity cannot survive both runtimes. Silent coercion
   is not canonicalization.
5. Test the artifact seam—writer output through the real verifier—not only
   helper-versus-helper examples.
6. Bind the serializer source into retained tool/source closures so a change
   makes old evidence stale.

## When not to use this approach

- Do not replace byte SHA-256 for files, media, executables, or exact JSON text
  with an object hash.
- Do not silently migrate a released domain-prefixed protocol. Preserve its
  prefix and encoding, add parity tests, and version a deliberate migration.
- Do not force Python-only cache keys or receipts into a cross-runtime domain
  when no other runtime recomputes them; migrate only with an explicit cache or
  receipt compatibility plan.
- Do not present this serializer as a universal standards-level canonical JSON
  format. It is the closed Producer contract for the admitted JSON domain.
