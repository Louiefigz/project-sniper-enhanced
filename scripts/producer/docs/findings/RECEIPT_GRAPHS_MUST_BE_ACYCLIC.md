# Receipt Graphs Must Be Acyclic

## The trap

An immutable artifact can name another artifact only after that artifact's
bytes, size, and digest are known. If two JSON records include each other's
digest, neither record can be serialized first:

```text
approved-parent.json -> generation-verification.json SHA-256
generation-verification.json -> approved-parent.json SHA-256
```

Retrying, reserving filenames, or writing placeholders does not solve this.
Changing either placeholder changes its file digest, which changes the other
record, which changes the first record again. This is a content-addressing
cycle, not an ordering inconvenience.

## The Project Sniper build order

The deterministic-MP4 generation uses this directed order:

```text
media/plans/evidence
  -> final-approval.json
  -> approved-parent.json
  -> generation-verification.json
  -> commit.json
  -> CURRENT
```

The boundaries matter:

- `approved-parent.json` references final approval but not generation
  verification, its own future commit digest, or publication sequence.
- `generation-verification.json` references the approved-parent artifact and a
  domain-separated digest of every commit payload row except the verification
  row itself.
- `commit.json` references the verification record and every other immutable
  generation file, but excludes itself.
- `CURRENT` is mutable publication state written only after the immutable
  commit digest exists.

The loader injects the unique generation-verification artifact into its
in-memory approved-parent object. That keeps the runtime object convenient
without making the wire graph circular.

## Why excluding only the verification row works

Assume an R0 commit has 40 payload rows. The verifier can freeze 39 rows,
compute:

```text
SHA256(
  "sniper-generation-payload-manifest-v1\0" ||
  canonical(rows sorted by normalized path)
)
```

and write that digest into the 40th verification record. The final commit then
binds all 40 rows. Any change to the first 39 invalidates both the verification
digest and commit. Any change to verification invalidates the commit.

## Validation rules

Reject a generation when:

- verification includes itself in the payload-set digest;
- any generation artifact embeds its own generation's future `commitDigest` or
  `publicationSeq`;
- final approval references an approved-parent card that already references
  final approval;
- the approved-parent descriptor directly names generation verification;
- the verifier omits identity or policy fields needed to compare it with the
  eventual commit; or
- payload rows are not in the one canonical ordering required by the profile.

## When not to use this pattern

Do not add a second receipt merely to duplicate the commit manifest. Use this
two-step card-plus-verification pattern when the card is a semantic projection
consumed by the application and the later verification proves that projection
was sealed after all other payload evidence. A simple immutable bundle with no
semantic projection needs only a canonical manifest and an external pointer.
