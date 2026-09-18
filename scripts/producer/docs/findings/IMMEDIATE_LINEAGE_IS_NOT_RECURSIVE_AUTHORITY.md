# Immediate lineage is not recursive authority

## What failed

The first assembly-lineage binder authenticated the selected `CURRENT` ancestry,
then compared the current generation only with its immediate parent. That closes
one edge. It does not prove that every earlier generation preserved the same
base or that the tail was created by an authorized initialization.

A three-node chain exposes the difference:

```text
genesis:      base A
generation 2: base B  <- invalid historical switch
generation 3: base B  <- valid immediate continuity with generation 2
```

Generation 3 can match generation 2 perfectly while the chain is still invalid.
Canonical commits, exact parent references, and a walk to a null parent do not
repair the missing assembly and origin semantics.

## Correct contract

Report the strongest proof actually observed:

```text
assembly_edges_required = lineage_node_count - 1
assembly_edges_verified = 1
recursive_assembly_verified = false
genesis_origin_verified = false
```

The immediate-edge binder now also requires its supplied current card to be the
exact selected-lineage head. A separately constructed child can no longer borrow
a valid historical target.

Recursive authority needs the exact assembly receipt bytes for every non-genesis
edge and the R1 genesis card, origin receipt, initialize operation, snapshot
authority, initialization policy, and verification bytes at the tail.

## Result

The corrected focused campaign passed 39 tests and 57 subtests, including a
separate-valid-child attack. These tests establish the narrowed contract; they
do not establish recursive lineage or publication authority.

## When the immediate proof is useful

Use it for structural diagnostics and to locate the first unresolved edge. Do
not use it to authorize rendering, publish a generation, infer genesis
legitimacy, or claim that an entire selected ancestry preserved its base.
