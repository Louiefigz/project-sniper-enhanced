# Profile Dispatch Is Not Disk Admission

## Finding

A pure schema/profile dispatcher can prove that an already-parsed commit belongs
to exactly one generation profile. It does not make that profile readable from
the published generation store.

This distinction matters for the R1 genesis and quality-pass bridge. The current
implementation can structurally validate these in memory:

- null parent plus `genesis-approved-card-v2` selects the genesis R1 profile;
- non-null parent plus `quality-pass-approved-card-v2` selects quality-pass V2;
- non-null parent plus `approved-parent-v1` selects frozen R0; and
- every other parent/card combination fails closed.

The dispatcher is `select_versioned_generation_profile()` in
`versioned_generation_profile_dispatch.py`. It reparses the commit and uses the
exact manifest class at `approvedParentPath`; it performs no disk reads and has
no fallback from an unrecognized R1 shape to R0.

## What The Green Tests Prove

The structural bridge authenticates the immediate parent kind without relabeling
the genesis origin receipt as an assembly receipt. A first quality-pass child can
bind exactly:

```text
genesis-origin + initialization-origin-receipt-v1
```

Later children can bind either:

```text
prior-assembly + assembly-receipt-v1
prior-assembly + assembly-receipt-v2
```

The child also binds the immediate parent's identity and immutable base. Runtime,
execution, recursive-lineage, and publication authority remain false.

## What The Green Tests Do Not Prove

As of this finding, a real selected R1 `CURRENT` cannot pass the production disk
path:

- `generation_reader.py` still calls `verify_r0_generation_profile()` before it
  materializes a generation;
- `approved_parent_loader.py` still selects only `approved-parent-v1`, parses only
  `ApprovedParentDescriptorV1`, and expects `generation-verification-v1`;
- `historical_generation_validation.py` still verifies R0 and parses only
  `ApprovedParentDescriptorV1`; and
- historical lineage records still store the V1 descriptor shape.

Therefore the R1 dispatcher and bridge are pure/in-memory structural contracts,
not a deployed reader, loader, or historical-admission path. Calling them
"integrated" before those disk boundaries are version-aware would overstate the
system.

## Required Integration Shape

Disk admission should dispatch only after exact commit parsing and inspection of
the manifest row selected by `approvedParentPath`. The selected branch must then
remain explicit through the full evidence lifecycle:

1. Genesis R1 loads `GenesisApprovedCardV2`, its origin receipt, genesis
   verification, and genesis policy bundle.
2. Quality-pass V2 loads `QualityPassApprovedCardV2`, `AssemblyReceiptV2`, its
   verification, and the immediate tagged parent authority.
3. Legacy non-null R0 continues through the frozen V1 loader unchanged.
4. Historical resolution dispatches every node independently and preserves
   `ParentAuthorityV2.kind` plus `artifactClass`; it never normalizes origin and
   assembly receipts into one untagged digest field.
5. Composition admission binds the selected operation's exact expected parent to
   the current card, receipt, and authenticated parent snapshot.

Until all five exist, execution and publication gates must remain closed.

## When This Pattern Helps

Use a pure dispatcher first when introducing a new immutable schema version. It
lets schema disjointness and downgrade resistance be tested without destabilizing
the trusted reader.

Do not treat that dispatcher as completion when authorization depends on sealed
bytes from disk, historical ancestry, runtime reobservation, or publication
fencing. Those are separate authority boundaries and need separate evidence.
