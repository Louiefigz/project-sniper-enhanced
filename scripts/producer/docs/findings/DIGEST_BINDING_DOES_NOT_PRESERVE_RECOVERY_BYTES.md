# Digest binding does not preserve recovery bytes

## What failed

The terminal trace stored a domain-separated SHA-256 of the result. That was
enough to reject different bytes, but not enough to recover after the process
died before the result was written anywhere. Recovery had only a 64-character
digest and no authoritative payload.

This distinction also applies to render requests, generation manifests, model
outputs, and remote-operation receipts: a digest is an integrity comparator,
not storage.

## The rule

When recovery must reproduce or return a value, durably retain the exact
canonical bytes before committing the event that depends on them:

```text
validate closed schema
write pending exact bytes
fsync file
replace authoritative intent
fsync directory
append digest-bound event
fsync event log
```

On replay, read the retained bytes, require exact canonical encoding, recompute
the digest, and compare every immutable identity field. Never ask a caller or a
model to resupply the payload after the fact.

## When a digest alone is enough

A digest alone is appropriate when the bytes are independently durable and
addressable—for example, an immutable CAS object whose existence, ownership,
size, and digest are revalidated. It is not enough when the referenced bytes
were transient, mutable, remote-only, or never committed.
