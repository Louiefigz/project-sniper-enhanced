# Immutable Authority Enables Parallel Critics

## Finding

Independent read-only critics can run concurrently only when each critic is
bound to the exact same immutable candidate authority. The controller must run
the deterministic gates first, capture the authority digest, write a separate
hash-bound input packet for every critic, and reject the whole batch if that
authority changes before every critic finishes.

## Why this matters

In the July 13 C0679 run, one cut critic took about **1 minute 48 seconds**.
Two required clean cut reviews therefore occupied roughly 3 minutes 36 seconds
when run serially, even though neither critic depended on the other's answer.
Launching those two read-only reviews together makes the ideal critic portion
of the critical path about 1 minute 48 seconds plus controller overhead. The
next live run must measure the realized speedup; this estimate is not a claimed
production benchmark.

## Safe execution rule

1. Capture one plan/source/intent/doctrine/pipeline authority digest.
2. Run deterministic gates once against that authority.
3. Create distinct critic packets and evidence destinations for that authority.
4. Launch only the still-required clean critics concurrently.
5. Await every critic, then verify the authority again.
6. If every critic passes, commit their separately hashed evidence.
7. If any critic finds a material issue, merge and deduplicate all issue codes
   and send one combined brief to one revision writer.
8. Rerun gates and a fresh critic batch against the revised authority.

The implementation lives in `cut-review-batch.ts` and
`planning-review-batch.ts`; deterministic issue aggregation lives in
`review-batch.ts`.

## Why revisions stay serial

A revision writer mutates `edit_plan.json`. Two concurrent revision writers
would begin from the same old hash, race to replace the canonical plan, and
make at least one receipt stale or misleading. Revision is therefore a single
governed mutation followed by fresh gates and fresh critics. Parallelism is for
independent reads of one authority, never competing writes.

## When not to use this

- Do not batch critics whose prompts, lenses, or candidates depend on an earlier
  critic's result.
- Do not batch across different plan hashes or authority digests.
- Do not launch critics before deterministic gates pass.
- Do not approve a subset when another critic times out, fails, or observes an
  authority change.
- Do not parallelize revision writers or checkpoint publication.
