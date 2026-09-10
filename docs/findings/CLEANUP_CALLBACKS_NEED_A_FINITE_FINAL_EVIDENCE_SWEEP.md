# Cleanup callbacks need a finite final evidence sweep

## What failed

Three independent fault checks in the September 8 source-color cleanup work
showed why checking an owner at the end is insufficient on its own:

- A final remaining-time callback released the actual temporary resource lease.
  Recovery's `assertCurrent`, its returned reservation hold, and its copied
  reservation still reported success; an immediate lease check then failed.
- A final cleanup guard appended a newline to the original reservation after
  it had been checked. The process helper returned successful parsed cleanup,
  but its original reservation hold immediately rejected the changed file.
- That guard could instead change the cleanup process ledger after settlement
  checking. The helper returned a ledger SHA that no longer matched the file.

These were actual writes to exact fixture-owned files and an actual temporary
lease release. Source admission, journal settlement and native cleanup were
explicit test boundaries; none of these tests qualifies a real Docker cleanup.

## The correction

Keep the original owner, deadline, result, raw hashes and file identities.
After the last arbitrary owner/clock callbacks, perform a finite verification
of the original evidence with no further arbitrary callbacks:

1. Check the actual resource lease after the original remaining-time callback.
2. Check the original reservation/claim/input metadata through the private
   authenticated hold, without calling the owner or clock again.
3. Compare the original cleanup ledger inode/stat identity and raw SHA, plus
   the original invocation record and captured tool evidence.
4. Charge that final filesystem work to the same captured remainder using
   elapsed monotonic time. Do not create a replacement cleanup allowance.

The callback-free reservation helper authenticates its key with a private
WeakMap. A spread/JSON copy cannot become an original hold. It is deliberately
only a metadata check: it cannot prove a lease is held, time remains, a process
stopped, resources were removed or a result is approved.

Adding another general `assertCurrent()` at the end would merely move the
last-callback gap. The final sweep needs narrowly defined read-only behavior.

## Measured evidence

The corrected cold reservation/process cohort passed 33 tests in 8.39 seconds
wall, including the two permanent final-guard negatives. Independent review
passed the 12 process cases in 4.92 seconds and the 53 recovery/hold cases in
12.23 seconds. The new callback-free core helper passed 21 tests independently
in 7.005 seconds; a separate check armed both callbacks to throw and confirmed
the helper called neither. Later invocation-history additions have their own
test cohorts in the active implementation log; do not combine these counts.

## The same rule applies at both ends of a composed reader

The later final-cleanup reader initially captured its outer journal and then
called the caller's guard before constructing its child attempt reader. Three
tests replaced the original media outcome, cleanup output or reservation
archive in that first callback. The child captured the replacement inode as its
baseline, so a final sweep alone could not detect the substitution. The repair
captures the complete child evidence first, then admits the original callback
exactly once, with explicit reentry/failure handling. Six admission regressions
and the full256-case reader/commit union pass (56.660s suite). This is actual
TEMP metadata/CAS evidence with explicit native/claim leaves, not real video QC.

A separate outer-workflow gap appeared after an otherwise valid final CAS:
the last clock callback could replace the committed journal or acknowledgement
before workflow return. Both negatives first failed in2.90s wall. The actual
final-commit result now retains a private finite metadata check; the workflow
awaits timing bookkeeping, samples its original remainder, checks that original
evidence and charges the sweep before returning. All12 workflow cases pass
in9.81s wall; the positive TEST workflow took680.308ms after fixture setup.

Keep intentional phase changes explicit. After the second journal CAS, the
old current-pending guard must fail; use separately captured retained history
for the final evidence. After verified lease release, historical proof must
not require the old live resource lock or current active marker. This is not
permission to skip a check: each later phase needs its own narrowly scoped,
authenticated evidence captured before any callback that could change it.

## When this is not enough

This pattern does not make filesystem observations atomic against arbitrary
external processes. Real ownership locks, canonical paths, new-only writes,
exact original process settlement and crash-consistent journal edges remain
necessary. An expired allowance still fails; metadata-only checks must not
replace execution guards or be presented as a hard filesystem timeout.

A new lease or new cleanup-attempt UUID also does not prove an earlier cleanup
child stopped. Until all earlier attempts have actual journal-bound settlement,
the initial source-color cleanup route explicitly refuses a sibling attempt.
Missing child ledgers never prove that no child was launched.

## Readback must preserve both its first caller and its final evidence

The separate schema2 media readback service exposed the same failure family:

- Its first actual cleanup-store reader could replace the request's remaining-
  time callback before the service captured it. The service accepted that new
  allowance. The permanent regression first failed in4.08s wall.
- A final metadata stat could consume the last remaining millisecond yet return
  verified. Adding another clock callback would reopen the mutation gap.
- A rejected held-claim mutation could redirect failure-clock publication if
  logging read the already-mutated claim instead of its original snapshot.

The service now captures request fields and the lease release method before
the initial reader, retains the original failure lineage, and charges finite
callback-free final checks to the same sampled remainder. It retains original
read-worker/interpreter/runner/config identities and ancestry through return,
so a late tool replacement cannot follow an earlier successful byte check.
These tool checks use stat metadata after capture rather than repeatedly
hashing installed executables. Installed tools are not required to have the
private permissions of execution metadata files.

All22 permanent service cases plus23 transport/integration and17 legacy cases
passed together:62/62 in68.25s wall. Two initial deadline/failure-lineage faults
were reproduced before repair; the tool-replacement case was verified only
after repair and is not claimed as an old-source reproduction. These tests use
actual TEMP leases, records, readers and both cleanup CASes, with explicit
upstream/native TEST leaves. They do not prove audiovisual quality, native
render compatibility, delivery approval or the two-hour editing target.

## Release and test fixtures must keep the original parent

A live controller now records an opaque phase before claim publication. A
failed claim call cannot be interpreted as "nothing launched"; that phase
retains the original lease until exact terminal cleanup is authenticated.
Once cleanup is proved, a later readback failure need not keep an already
settled renderer claim alive. The final release sweep still retains the
original cleanup ledger and absence of a cleanup failure marker.

The test setup initially preserved the claim hash but rebuilt its parent job
from another template. An adversarial diagnostic showed that the token and
plan context changed while the release test could still pass. A genuine
claim-admission reader would reject that lineage, but the explicit test
admission stub did not. Matching a child identifier is not proof of preserving
the complete request. The corrected fixture constructs the actual parent
before staging, declares its eventual inert tool metadata up front, performs
the real parent CAS and asserts the complete original context, token,
submission and pointer at the end. No captured claim is rebound or repaired.

Borrowed test leases also must not register a second owning teardown after
the temporary-root destructor. That separate defect caused four teardown
failures in each of two runs (12.59 and12.68seconds wall). The corrected four
terminal tests pass in12.98seconds; independent continuity and teardown pass
in3.70seconds. Original creative/claim admission, OS identity and native work
remain explicit TEST leaves. These fixtures qualify live protocol composition,
not cold crash recovery, actual container absence or real video quality.

## A body continuation must preserve time and version across the handoff

The body-input integration reproduced two more concrete faults. An original
source2 admission copied into a DTO with both version tags changed to1 could
publish a V1 worker input (RED15.93seconds). Its stored held-input bytes still
said version2. The writer now compares that independently hash-bound original
document before its first caller callback; parsing it does not recreate the
private source2 capability. Version dispatch also checks membership of genuine
source2 handles before trusting mutable tags. A cast or a well-formed hash is
not a cross-version migration.

Separately, a final source-color archive stat inside body-input retention could
consume the last original budget yet return a valid-looking held input
(confirmed RED14.17seconds using a virtual clock, no file writes). The existing
body verifier subdeadline now exposes a private callback-free tail assertion.
It checks the same original cutoff and every smaller parent sample after the
final metadata sweep, without calling the arbitrary parent again. A first
callback could also edit the original submission object in place while keeping
its reference unchanged (RED10.59seconds). Both the original reference and a
closed, detached value snapshot must be retained before that callback.

For Python source replay, do not call a base-class clock method when borrowing
a body clock: that loses the body's wall-clock deadline and rollback check.
The narrow adapter accepts only the exact existing opening clock or an already
wall-bound body clock, creates no allowance, and keeps the body's original wall
watermark. Save each actual clock sample before subsequent filesystem work;
saving it only at the end of the check allowed an intermediate rollback
(RED0.33seconds). Two exact rollback regressions plus the existing/new clock
cases passed together:44/44 in3.05seconds. These tests qualify bookkeeping and
original metadata continuity, not a successful render or the two-hour target.

## Replaying the original source does not retain the new body result

The source reader correctly retained the original opening result, but the body
reader also needed an independent lifetime for its NEW result and worker entry.
In two real fault tests, a later callback either appended whitespace to the body
result and changed its externally supplied raw SHA, or rewrote the worker entry
with identical bytes. The final semantic read accepted both replacements
(two REDs in5.64seconds). Separately, creating a failure marker just after that
final raw read still allowed success (RED2.83seconds).

The fix retains the original request/invocation before clock callbacks and both
current output file identities plus ALL canonical ancestors before the first
remaining/phase callback. Final checks include the original failure-marker
absence and original time AFTER metadata work. Construct the response—including
elapsed time—before that last check. A final digest is work too: an expired
semantic comparison once returned success (RED1.25seconds); class-dispatched
original work validation now follows it. This adds finite metadata checks, not
another source decode, replay pass or timeout. The combined85-case Python suite
passes in33.48seconds; it does not establish real video quality or native speed.

Test failures also need provenance. An initial elapsed-time hook was attached
through Mock's extra stack frame and never armed. Its missing-exception failure
was a TEST defect, not a reproduced production bug. The corrected direct hook
asserts it actually fired and passes after the fix. Keep that distinction in
timing reports; do not turn a broken fault injector into evidence of coverage.

The TypeScript result binder had the same early/late capture pattern in three
additional reproduced cases. A phase Buffer could change during the first input
read before the binder saved its original phase. A result parent could change
after the binder's only directory sweep. Finally, the actual raw parser's
returned media object could change during later metadata IO before the result
object was privately retained—even though disk and raw Buffer bytes remained
unchanged. Save original inputs before the first read, and each actual reader's
return immediately before the next callback. A final sweep must cover both the
original files and their original ancestors. These three permanent regressions
pass in62.86seconds; the last was independently verified in25.00seconds. The
tests do not substitute a real audiovisual or process-ownership qualification.

## A successful journal save is not the end of the attempt

Two actual body-transition tests reproduced late deadline failures. Activation
saved its real journal, the original wall budget narrowed to100ms, and a final
metadata read consumed101ms. Activation still returned success (RED32.64s).
Separately, candidate qualification returned success after its actual final CAS
advanced the original wall by60minutes (RED89.28s). Neither test replaced the
budget method, the CAS, or the saved lineage with a stub.

Retain the original controller-code inventory and already-spent parent remainder
through the handoff. A smaller parent observation must shorten the saved deadline;
checking the parent separately while retaining the old cutoff is insufficient.
After the last original budget callback, recheck the original lease and the NEW
expected journal, then the original result and finite metadata tail. Reusing the
old current-journal guard after a legitimate CAS would reject valid progress.
Do not roll back a completed CAS when the tail fails: retain the facts and report
failure so retry/recovery cannot mistake a completed transition for no work.

The exact activation fault now passes in38.63s. The actual candidate protocol
positive and exact expired-return fault pass together in185.13s. These are full
metadata/history/ledger/CAS tests with explicit native/readiness/tool leaves,
not real video renders, listening approval, or two-hour performance evidence.

A further actual callback replaced the final attempt's `verified.json` after
candidate CAS with identical bytes but a different inode (RED95.81s). The
candidate's reference hashes and current journal still matched. Retaining the
input/source proof did not retain these newly created readback records. Capture
start, output and verified records immediately on creation, their detached
returned values before following IO, and the worker ledger before its actual
settlement reader. Keep all ancestors and the exact original four-role set.
After the last budget callback, sweep those original publications as well as
the selected result, then charge the same deadline. No repeated raw hashes or
new source replay is necessary for this retained metadata check. The unchanged
replacement regression passes in105.74s; genuine candidate success and original
expiry refusal still pass together in188.59s. These remain native-free protocol
tests with explicit tool/readiness/native leaves, not audiovisual qualification.
