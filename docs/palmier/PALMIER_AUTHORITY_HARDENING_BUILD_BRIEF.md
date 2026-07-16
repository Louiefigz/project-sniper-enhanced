# Palmier authority hardening — sequenced build brief

> **STATUS: WORK PLAN (sequenced fixes), not current state.** Items marked "Not closed" in this brief are not wired. Do not read as delivered behavior.

**Verified:** 2026-07-12 against the current dirty `PROJECT_SNIPER` tree  
**Purpose:** land the remaining authority/refit/native-candidate fixes from a
frozen base, without another concurrent audit/fix loop.  
**Doctrine:** Palmier's valid managed timeline is the working source of truth;
manual edits advance that truth; automation edits a preserved-parent candidate;
only deterministic and rendered QC may approve a candidate. There is no
degraded fallback, stale-plan overwrite, or “Reclaim Sniper” product path.

## Freeze rule

Before phase 1:

1. Stop starting new Auto Edit or Palmier-native jobs.
2. Let current jobs finish or use **Stop & keep checkpoint**.
3. Record the current dirty-tree diff and create one frozen implementation
   branch/worktree. Do not run another agent against the same files while a
   phase below is in progress.
4. Land one phase per commit. Run its stop gate before beginning the next.
5. If a stop gate fails, fix that phase or revert its commit. Do not stack the
   next phase on an unproven authority boundary.

## Verified scorecard and corrections

| Finding | Verdict | Evidence / correction |
|---|---|---|
| TS/Python managed authority digest differs | **Confirmed blocker** | On `c0679-20260712-3`, every component matched except `pipelineDigest`. TS=`39bb59…f6b72`, Python=`8714d6…1e08b`; final digests also differed. TS appends doctrine after its sorted pipeline rows; Python includes live `SKILL.md` before the global sort. |
| Concurrent source edits fail a running Auto Edit | **Confirmed high** | `autoEditAuthoritySnapshot()` repeatedly walks and hashes the live repository. A size/mtime change changes the digest during review/QC. Only doctrine is pinned today. |
| Cross-language request key is stable for new pinned jobs | **Not closed** | TypeScript removes runtime `doctrine`; Python hashes the whole context. Adding a pipeline envelope without fixing both sides would create another mismatch. |
| Gate native routing on `ownership === "palmier"` | **Refuted** | `ownership` is a legacy mirror-writer lease, not product authority. Any valid managed Palmier workspace is canonical regardless of that field. Ownership-gating would send a valid managed mirror back through a stale `edit_plan.json`. |
| Native edits have no governance | **Overstated; partial gap** | They already load doctrine, use an independent critic, validate lane/tool envelopes, validate ids/frames/stale parent, and revalidate each operation. Missing: a pre-critic native deterministic bundle, content invariants where relevant, exported/rendered QC, bounded repair, and CAS promotion. Old `plan_lint` is not a valid substitute for a Palmier graph validator. |
| Surgical cut refit is exactly once | **Confirmed high; not closed** | Reproduced `[25,30] → [20,25] → [15,20]`. Surgical finalize refits once, saved-plan review compares against unchanged `base_plan.json`, and `assemble.py` refits again. |
| Failed Palmier-native candidate cannot become truth | **Confirmed blocker** | After a partial operation failure, the copied timeline remains active and `staged`; the next reconcile adopts it as `palmier-manual`. Existing tests checked that the parent record existed, not that the active timeline returned to it. |
| Staged candidate can be approved in the UI | **Not closed; do not wire yet** | The CLI has only reconcile/execute. Real candidates are `edited` with QC pending, while `promote_candidate()` accepts `staged`, trusts receipt-embedded timeline data, and has no production caller that obtains a fresh source CAS snapshot. |
| Hard-gate exhaustion needs a degraded override | **Refuted** | Exhaustion must fail closed. No “promote last clean” escape hatch. |
| Closed Palmier should fall back to plan AI | **Refuted** | For a managed workspace, Palmier readback is canonical. If it is unavailable, Ask AI must block rather than flattening back into a stale Sniper plan. |

## Phase 1 — one immutable, cross-language run authority

This phase fixes the current blocker and the concurrent-edit failure together.
Do not fix only the sort order: that would leave running jobs executing mutable
Python while claiming a pinned digest.

### 1.1 Add a versioned pipeline envelope

Add `AutoEditPipelineAuthority` to `AutoEditCtx` in
`src/app/api/producer/auto-edit/stream.ts`:

- `schemaVersion`
- canonical `digest`
- sorted POSIX-logical `{path, hash}` receipts
- immutable snapshot root and lock path
- capture/run id

Implement capture/restore beside the doctrine implementation, preferably in a
focused `src/lib/server/auto-edit-pipeline-authority.ts` module. Capture the
exact allowed renderer/gate/template bytes into the run directory before the
worker starts. Resume restores and verifies the saved envelope; it never
recaptures live repository state.

Files that must be coordinated:

- `src/app/api/producer/auto-edit/route.ts`
- `src/app/api/producer/auto-edit/stream.ts`
- `src/lib/server/auto-edit-job-types.ts`
- `src/lib/server/auto-edit-job-store.ts`
- `src/lib/server/auto-edit-quality-policy.ts`
- `src/lib/server/auto-edit-doctrine.ts` (shared capture/restore conventions)

### 1.2 Execute from the pinned tree

Route Python render, assemble, audit, plan-refit, and template/config reads to
the pinned snapshot. TypeScript worker modules are loaded by the detached
worker, but every later Python subprocess and prompt file path must resolve from
the run snapshot. A pinned digest with live execution is false evidence.

Likely seams:

- `src/app/api/_lib/spawn-python.ts`
- `src/app/api/producer/auto-edit/chain.ts`
- `src/app/api/producer/auto-edit/pipeline.ts`
- `src/app/api/producer/auto-edit/quality-loop.ts`
- `src/app/api/_lib/audit-gate.ts`
- author/reviewer prompt path builders
- `scripts/producer/**` and `templates/motion/**` resolution passed to children

Plan, manifest, stored/requested intent, transcripts, source hashes, reference
study, and operator decisions remain live authority inputs. Only pipeline and
doctrine are frozen for one run.

### 1.3 Canonicalize TS/Python identity

Use one contract on both sides:

1. Strip runtime `doctrine` and `pipeline` from the request key.
2. Verify the pinned envelopes independently.
3. Build the complete pipeline authority row list, including the one synthetic
   pinned-doctrine row.
4. Normalize logical paths to `/` and sort the complete list by logical path.
5. Hash the same stable JSON shape.
6. Keep an explicit, tested legacy reader for old markers; never silently
   classify corrupt/missing managed state as legacy.

Files:

- `src/lib/server/auto-edit-hash.ts`
- `src/lib/server/auto-edit-authority-snapshot.ts`
- `scripts/producer/palmier/quality_hash.py`
- `src/app/api/producer/palmier/_lib.ts`

### Phase 1 tests

Add a real cross-language golden test, not only “TS equals Python”:

- exact full snapshot and request key equal a checked-in golden fixture;
- pinned doctrine ordering and non-ASCII/canonical numeric values are covered;
- a live repo-script mutation does not change an already pinned run;
- plan, transcript, reference, and intent mutations still change authority;
- pipeline snapshot byte or lock tampering fails closed;
- Resume retains the original pipeline digest;
- a newly launched run sees the newly changed pipeline;
- managed Palmier approved-master/preflight accepts the matching approval.

Suggested test locations:

- `src/lib/producer/__tests__/auto-edit-authority-cross-language.test.ts`
- authority/doctrine/job-store tests
- Python `test_palmier_master.py`, `test_palmier_push.py`, and quality-hash tests

### Phase 1 stop gate

- Full TS/Python snapshot equality passes.
- A controlled live source edit cannot fail or alter a pinned test run.
- A pinned run demonstrably invokes Python from its snapshot tree.
- A real managed preflight no longer reports stale QC solely from language
  disagreement.
- No input freshness test is weakened.

## Phase 2 — exactly-once cut-timebase refit

> **Superseded correction (2026-07-13):** a `base_plan.json` cut mismatch is
> not proof that timed lanes are stale. Freshly authored plans, recovered
> authoring drafts, and full-plan revisions already express every lane in their
> own target cut timebase and must not be refitted. Only a mutation proven to be
> cut-only may use the previous plan as a refit source; unknown provenance fails
> closed.

`base_plan.json` must remain truthful provenance for the currently rendered
base. Do **not** advance it early merely to suppress the second refit; doing so
can make a stale base appear current.

### 2.1 Make the refit receipt a timebase authority

Upgrade `.sniper-plan-refit.json` to a versioned receipt containing:

- canonical source and target `cutTrack` values plus hashes;
- final plan hash for exact diagnostic display;
- source (`surgical-cut` or `saved-plan`), changes, drops, and creation time;
- enough crash-order evidence to distinguish “receipt staged, plan not yet
  promoted” from “current plan already carries this target timebase.”

The invariant is: downstream output-time lanes are expressed in exactly the
receipt's target cut timebase.

### 2.2 Share one refit decision

Teach all three callers the same decision:

- If current `cutTrack` equals the receipt target, emit
  `refit_already_applied` and do not remap again—even if non-cut plan fields
  changed.
- If the current cut changed again, remap from the last applied target
  timebase recorded by the receipt, not blindly from the older rendered base.
- If no valid receipt exists, never infer a refit from `base_plan.json`; require
  explicit cut-only provenance or treat a declared complete plan as current.
- Malformed/stale/conflicting receipt state fails loudly; it never guesses.

Apply this in:

- `src/app/api/_lib/plan-refit-transaction.ts`
- `src/app/api/producer/ai-edit/finalize.ts`
- `src/app/api/producer/auto-edit/saved-plan-request.ts`
- `scripts/producer/assemble.py`

`assemble.py` must still rebuild a stale base. It skips only the second window
remap, then advances `base_plan.json` and fingerprints only after the successful
base render.

### 2.3 Crash-safe ordering

Stage the candidate plan and matching receipt as one transaction. The receipt
may be written before the plan CAS promotion only when it is harmless on its
own: its target cut will not match the still-current authority plan. On a
failure, preserve the operator plan and discard/quarantine staged transaction
files. Project status should show drops/remaps only for the hash/timebase-current
receipt.

### Phase 2 tests

- surgical cut → saved-plan review → assemble maps `[25,30]` once to `[20,25]`;
- non-cut edit after receipt still skips refit;
- a second cut edit maps once from the first target timebase;
- stale/malformed receipts fail closed;
- failure between receipt staging and plan promotion is recoverable;
- failed base render neither advances `base_plan.json` nor loses the plan;
- successful rebuild advances base provenance and clears the need to refit.

### Phase 2 stop gate

- No chain of GUI cut, review, retry, or rebuild can apply the same timebase
  transform twice.
- All lint/gate calls see the already-refitted plan.
- `base_plan.json` always names the plan the base video actually used.

## Phase 3 — managed-workspace routing and candidate quarantine

### 3.1 Correct the routing boundary

Replace `stateExists()` in
`src/app/api/producer/ai-edit/palmier-native-stream.ts` with one parsed,
validated managed-workspace classifier:

- no Palmier state: plan-first surgical path;
- valid schema-v4 managed project/timeline: Palmier-native path, regardless of
  legacy `ownership`;
- present but corrupt/incomplete/unknown state: `409`, fail closed, no plan
  fallback.

Do not implement the audit's proposed `ownership === "palmier"` gate.

### 3.2 Quarantine every partial candidate

Immediately after `fork_candidate`, wrap identity remap and every native
operation in a failure boundary:

1. Capture the last readable partial candidate.
2. Atomically write a `quarantined` candidate receipt with base, failure,
   completed operation receipts, and last fingerprint.
3. Activate the preserved parent with `set_active_timeline`.
4. Re-read and require the exact parent project/timeline/fingerprint.
5. If restoration fails, retain quarantine evidence and report that the
   quarantined fork remains visible; never rewrite canonical authority.

Never use Palmier `undo` as transaction rollback.

Files:

- `scripts/producer/palmier/native_delta.py`
- `scripts/producer/palmier/timeline_authority.py`
- `scripts/producer/palmier/timeline_guard.py`
- `scripts/producer/palmier/native_delta_cli.py`
- TS native contract/runner/stream files

### 3.3 Make reconciliation candidate-aware

Before adopting active drift as `palmier-manual`:

- active candidate fingerprint exactly matches `staged`/`edited` receipt:
  candidate is still pending; do not adopt or promote it;
- candidate fingerprint changed by a human: adopt that visible manual revision
  as the new **unapproved** working head, explicitly supersede the automated
  candidate, and invalidate old approval;
- active quarantined candidate: block and offer parent recovery; never adopt;
- unrelated managed timeline drift: adopt it as manual working truth according
  to the normal doctrine.

After successful automated staging, restore the parent as active when possible.
The existing **Review Palmier candidate** action may intentionally activate the
candidate for inspection; merely viewing it is not approval.

Cancellation after fork must end in the same restore-or-quarantine invariant.
Use a graceful signal path where possible, with reconciliation's candidate
guard as the durable crash backstop.

### 3.4 Honest interim UI

Until phase 4 lands:

- keep **Review Palmier candidate**;
- say “review-only; automated rendered QC/promotion is not connected yet; the
  parent remains canonical”;
- add a quarantined-candidate recovery state/action;
- use candidate-specific opening copy: opening does not accept it; a deliberate
  manual edit makes that edited visible revision the new unapproved working
  truth;
- do not add **Approve**, **Continue anyway**, or **Reclaim Sniper**.

### Phase 3 tests

- absent sidecar → plan path;
- valid managed sidecar with either ownership value → native path;
- corrupt present sidecar → 409/no fallback;
- partial operation failure restores parent and quarantines candidate;
- restore failure leaves quarantine active and next reconcile conflicts;
- unchanged pending candidate is never silently adopted;
- manual modification of the visible candidate becomes explicit unapproved
  manual truth;
- abort after fork obeys the same invariant.

### Phase 3 stop gate

- No failed, canceled, staged, or merely viewed candidate can become canonical
  by accident.
- No valid managed workspace can fall back to stale-plan editing.
- The preserved parent is provably unchanged after every failed transaction.

## Phase 4 — native deterministic gate before mutation

Do this before promotion, but do not route the Palmier graph through old
`plan_lint` merely to reuse a checkbox.

1. After reconcile and model draft, run a native deterministic gate bundle
   before the critic and before fork: schema, allowed tools, lane ownership,
   ids, linked A/V, frame/range ordering, property bounds, destructive delta
   envelope, and relevant operator-intent/content invariants.
2. Run the independent doctrine-aware critic.
3. Re-run deterministic validation against the freshly copied/remapped ids
   before each operation, as today.
4. Add lane-specific rules equivalent to the applicable teachings (motion
   smoothness, caption safety, audio bounds, etc.) in native vocabulary.

Stop gate: corrupt or creatively invalid native plans fail before Palmier
mutation; per-operation stale/readback checks remain intact.

## Phase 5 — exported QC and compare-and-swap promotion

Only after phases 1–4 pass may the UI gain an approval action.

### Required transaction

1. Acquire the project/Palmier transaction leases.
2. Re-read the canonical parent by managed id and freeze its fingerprint.
3. Re-read the candidate fresh; do not trust receipt-embedded timeline JSON.
4. Export the exact candidate by explicit `timelineId`; wait for stable bytes.
5. Bind export hash, candidate fingerprint, pipeline/doctrine/input authority,
   and structural readback into a QC receipt.
6. Run deterministic Audit B, composition critic, and editorial critic.
7. If repairable, create a separately governed candidate delta and repeat the
   bounded QC loop. Exhaustion fails closed.
8. Re-read both candidate and parent. Any candidate drift reruns QC; any parent
   drift blocks promotion and preserves both.
9. Promote only a `qc-approved` candidate whose base still equals the canonical
   parent. Atomically record working head and approved head, clear/supersede the
   pending receipt, and activate the approved candidate.

Fix `promote_candidate()` so it accepts only freshly proven `qc-approved`
records—not current `staged` receipts—and derives the promoted snapshot from
fresh Palmier readback.

### UI after the backend is proven

- **Review Palmier candidate** — open only.
- **Run QC** — export and review; no implicit approval.
- **Use approved candidate** — appears only for a current QC receipt and
  performs the final CAS recheck.
- On parent drift: “Palmier changed while this candidate was under review;
  nothing was overwritten.”

### Phase 5 stop gate

- No UI caller can promote without current structural, export, deterministic,
  rendered-review, and parent-CAS evidence.
- Manual edits remain source of truth and never disappear.
- The last approved delivery remains separately identifiable while a newer
  working revision is unapproved.

## Deferred optimizations after correctness

1. Cache `final.palmier.mp4` hashing by a bounded
   `(dev, ino, size, mtime, ctime)` signature so editor preflight does not
   re-stream multi-GB bytes after every plan change. Invalidate on any signature
   change; never trust path alone.
2. Compute one authority snapshot per controller round and pass it through the
   round, rather than walking the tree at every assertion.
3. Keep the distinct semantics of the project writer lease, durable run
   journal, and Palmier global transaction lock. Remove redundant in-process
   maps only after crash/process tests prove the shared lease replaces them;
   do not collapse unlike locks merely to reduce file count.
4. Centralize project-card state → status → primary-action mapping after the
   authority schemas settle.

## Final release gate

Run, from the frozen implementation tree:

```bash
npm test
npm run lint
npm run type-check
npm run build
cd scripts/producer/tests
../../../.venv/bin/python -m unittest discover -s . -p 'test_*.py'
```

Then run an intentional Palmier sandbox project exercise:

1. bootstrap a managed workspace;
2. make a manual Palmier edit and verify the next AI request starts there;
3. stage a candidate and verify parent restoration;
4. inject a mid-operation failure and verify quarantine/recovery;
5. change repository code during a pinned Sniper run and verify the run uses
   its snapshot while a new run sees the change;
6. perform two successive cut edits and verify one refit per edit;
7. export/QC/promote a candidate, then repeat with parent drift and prove the
   promotion blocks without overwriting anything.

Release only when the state shown in Palmier, the saved working-head record,
the pending candidate record, and the approved delivery record are four honest,
explicitly distinguishable facts.
