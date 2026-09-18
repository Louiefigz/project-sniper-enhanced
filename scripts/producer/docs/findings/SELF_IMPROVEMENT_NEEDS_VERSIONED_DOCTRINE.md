# Self-improvement needs versioned doctrine

## The defect in the obvious learning loop

The original Producer loop has useful memory: QC/operator defects append to
`FAILURE_LEDGER.md`, deterministic rules and regression tests encode the hard
parts, and every future writer/critic reads the Brain lessons.  But the ledger
is also a live file.  There was no per-run doctrine version and no mechanical
boundary between an observation, a proposed lesson, and an active lesson.

That creates four failure modes:

1. A long-running edit can read one ledger version during authoring and a newer
   one during revision or criticism.
2. A critic finding or operator correction can be mistaken for a universal
   rule before it is tested against other edits.
3. A manual Palmier revision becomes the timeline source of truth, but its
   before/after evidence is not retained as a learning input.
4. A bad lesson has no exact, mechanical rollback target.

The surprising part is that a doctrine hash alone does not fix this.  A hash
can detect drift, but it cannot reconstruct the text after a process restart.
The run must pin both the hash and the exact doctrine bytes it will read.

## The invariant

Every edit run gets one immutable doctrine lock before its first writer or
critic starts.  All agents in that run read the pinned text in the lock, never
the mutable repository files.  Learning may happen while the run executes,
but it can only produce evidence and inert proposals.  A different doctrine
hash can become active only for a different run id after all three gates pass:

- explicit operator approval for the exact proposal ids;
- at least one deterministic regression-test receipt, all passing;
- at least one representative edit-eval receipt, all passing, with zero known
  regressions and the exact candidate doctrine hash.

The activation records the prior doctrine hash and exact prior snapshot as the
rollback target.  Rollback is also next-run-only; it never changes a running
edit's rules.

## Deterministic foundation

`learning/doctrine_lifecycle.py` implements the state boundary as frozen value
objects and pure functions:

| Artifact | State | Authority |
|---|---|---|
| `DoctrineLock` | `pinned` | Active for exactly one `runId`; contains exact UTF-8 text |
| `LearningObservation` | `observed` | Evidence only; cannot edit doctrine |
| `LessonProposal` | `proposed` | Draft only; an agent may draft it but cannot approve it |
| `DoctrineCandidate` | `candidate` | Exact proposed bytes; still inactive |
| promoted `DoctrineLock` | `pinned` in a new run | Active only after operator + tests + evals |

The Producer-specific capture requires the shared Codex adapter, canonical
Producer skill, canonical pipeline, failure ledger, and QC checklist.  The
controller must add every resolved lane document it tells an agent to read
(for example transition, motion, graphics, audio, or style doctrine).  This is
important: the hash is only honest when its source map contains the complete
effective doctrine for that run.

The resumable snapshot contains exact text plus a hash-only receipt.  Every
file hash, the aggregate doctrine hash, and the lock receipt hash are verified
on restore.  Changing content, run id, activation kind, rollback authority, or
proposal ids fails closed.  `source_drift()` reports repository movement but
does not alter what the current run reads.

## Auto Edit runtime integration

The detached Auto Edit controller now captures this lock before launching a
new writer, including the shared core, every doctrine document referenced by
the Producer skill, and the selected closed-style grammar. It atomically
commits the lock and exact readable copies under
`producer/.sniper-learning/runs/<runId>/doctrine/`, then stores the run id,
doctrine hash, lock path, and copy map in the durable job context. Resume
restores and verifies that same snapshot; it never reconstructs the run's
doctrine from current repository files.

Initial authoring, plan critics, revision writers, and rendered-QC critics all
receive the pinned copy paths. The render/QC authority binds the pinned
doctrine hash and excludes mutable live doctrine files, so a legitimate live
promotion cannot invalidate an edit already in flight. Tampering with a pinned
copy still fails closed because authority checks re-verify the snapshot bytes.

Material independent-critic findings and every deterministic QC warning or
failure are written as immutable observations under that run's
`observations/` directory. Each record is bound to the exact critic/QC artifact
hash, `runId`, and `doctrineHash`. This runtime writes no proposal, candidate,
or doctrine file; promotion remains the explicit next-run operator/test/eval
boundary implemented by the pure lifecycle.

## What the system is allowed to learn from

`learning/observations.py` records three evidence classes:

- A scoped critic issue retains its issue code, lane, severity, concrete frame
  or timestamp evidence, critic artifact hash, run id, and doctrine hash.
- A deterministic QC warning/failure retains its check code, measurement,
  artifact hash, run id, and doctrine hash. Passing checks are not findings.
- A manual Palmier revision retains verified before/after timeline ids and
  fingerprints plus a deterministic JSON-pointer diff. Leaf values are stored
  as hashes, not copied into a prose lesson. Palmier runtime state
  (`canGenerate`, playhead `currentFrame`, and the root timeline inventory) is
  excluded from the content diff, matching timeline authority behavior.

The manual-diff record deliberately says `"interpretation": "none"`.  A trim,
graphic move, or transition replacement made in Palmier is immediately the
truth for that project, but it may be a one-off preference, an experiment, or
even a mistake.  The system may cite the diff in a proposal; it may not infer
and activate a global rule from the diff by itself.

## Promotion and rollback receipts

A promotion call must bind all of these values together:

```json
{
  "nextRunId": "run-2026-07-13-001",
  "operatorApproval": {
    "actor": "operator",
    "decision": "approve",
    "proposalIds": ["proposal-042"],
    "candidateDoctrineHash": "<sha256>"
  },
  "verification": {
    "candidateDoctrineHash": "<sha256>",
    "regressionCount": 0,
    "tests": [{"id": "transition-lint", "status": "pass", "artifactHash": "<sha256>"}],
    "evals": [{"id": "longform-golden-3", "status": "pass", "artifactHash": "<sha256>"}]
  }
}
```

Any missing receipt, failed row, stale candidate hash, different proposal set,
model self-approval, or attempt to reuse the current `runId` raises
`DoctrineLifecycleError`.  The returned next-run lock records
`rollbackDoctrineHash` as the exact current hash.  A rollback requires a new
run id, an operator reason, and the exact recorded prior lock; arbitrary older
or hand-reconstructed text is rejected. The lock also binds an
`activation.evidenceHash` to the exact approval/verification gate; persist that
gate artifact beside the lock so the promotion remains auditable.

`"actor": "operator"` is a controller trust boundary, not proof of identity by
itself. Never parse that field out of a model response. The GUI/controller must
construct it only from an explicit operator action and pass the already-trusted
receipt into `promote_for_next_run()`.

## Verification

`tests/test_doctrine_lifecycle.py` has 18 stdlib-only tests.  They cover stable
hashing, content sensitivity, live-source drift, resumable snapshot tampering,
the mandatory Producer core, critic/QC evidence, verified Palmier timeline
diffs, proposal inactivity, model self-approval refusal, test and eval gates,
stale verification, next-run-only activation, and exact rollback.

Run them with:

```bash
python3 -m unittest scripts/producer/tests/test_doctrine_lifecycle.py -v
```

## When not to promote a lesson

Do not promote after one ambiguous manual edit, when the observation lacks a
hash-bound critic/QC receipt, when an eval merely confirms the edit that
inspired the proposal, or when the candidate improves one editing style by
flattening another.  Keep the item proposed, add representative evals from the
affected modes/lanes, and preserve the current doctrine until the evidence is
strong enough.  Continued self-improvement means accumulating and testing
knowledge; it does not mean changing policy continuously inside active work.
