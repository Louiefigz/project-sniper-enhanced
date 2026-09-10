# A QC receipt hash is not QC proof

## The assertion

A syntactically valid hash proves nothing unless the controller either reopens
the content-addressed object named by that hash or receives the complete
receipt and recomputes the hash itself. Promotion gates must validate measured
claims, candidate-media identity, and operator approval from actual receipt
objects.

## The incident

The P2 revision bridge originally required five post-render evidence rows:
alignment, VAD, re-transcription, seam, and audition. Each row contained only:

```json
{
  "status": "bounded-pass",
  "receiptHash": "<64 lowercase hex characters>",
  "candidateCompositeSha256": "<candidate hash>"
}
```

The bridge validated the spelling of `receiptHash`, but no receipt object was
stored or reopened. Five invented 64-character strings could therefore satisfy
the same structural check as five real QC executions. The terminal compositor
proof was real; the acoustic and human-review claims were not yet grounded.

## Evidence with real numbers

The promotion envelope still has five lanes, but each lane now embeds its
closed receipt. Python reopens those receipts from the controller-owned repair
attempt and re-hashes the actual candidate `.mov`; TypeScript independently
recomputes each canonical receipt hash and candidate binding before revision
CAS and again during recovery.

The released checks include:

- alignment: exact target word IDs, one occurrence, boundary match, and pinned
  runtime/model/cache hashes;
- VAD: pinned runtime, continuous intended speech, and zero unintended gaps;
- re-transcription: pinned runtime/model, target phrase hash, one occurrence,
  and preserved word order;
- seam: pinned runtime plus click, duplicate, room-tone, and lip-sync
  disposition;
- audition: explicit operator receipt, approval policy, timestamp, approved
  decision, and confirmation that the reported damage is resolved.

`test_p2_cut_repair_promotion_gate.py` has four executable cases: complete
receipt set, missing audition, semantically false VAD, and changed composite
bytes. `p2-cut-repair-revision.test.ts` recomputes the hash of a deliberately
false alignment receipt and still rejects it, proving that a fresh hash cannot
launder a false measurement. The complete focused P2 suite passes 75 tests.

## The principle

Separate three questions:

1. Is the digest well formed?
2. Does that digest name bytes the controller can reopen?
3. Do those bytes prove the exact candidate and required semantic result?

Only the third answer can authorize promotion. Content addressing provides
identity and immutability; it does not provide truth by itself.

## When not to embed the receipt

Do not duplicate a large receipt when it is already in immutable
content-addressed authority and the gate reopens that exact object before every
decision. A hash reference is sufficient in that case.

Do embed or store the receipt before CAS when no independently reopenable
object exists. This pattern also does not manufacture measurements: until the
real aligner, VAD, re-transcription, seam-analysis, and operator-audition
producers run, promotion must remain blocked.
