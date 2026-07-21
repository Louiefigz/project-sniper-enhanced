# Headless execution adversarial audit — 2026-07-18, round 11

> **STATUS: FROZEN AUDIT SNAPSHOT.** Later corrections belong in a later audit
> and the living
> [headless optimization dossier](../producer/HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md).

## Scope boundary

This round covers only:

1. Claude Code or Codex Desktop planning into one machine-facing Palmier
   protocol; and
2. Claude Code or Codex Desktop planning into a deterministic MP4.

It excludes GUI, Next.js, dashboard, SSE, active-window, click-automation, and
desktop-view work. Nothing below recommends or qualifies a GUI path.

## Verdict

The plan is materially stronger, but the overall product is **not at 95%**.
Round 11 converted the G1 durability pieces from disconnected helpers into a
small callable composition root and closed several result/proof schemas. It did
not create a production worker supervisor, resource ledger, trusted sealer,
publisher, or Palmier arbiter.

| Layer | Round-11 disposition | Evidence boundary |
|---|---|---|
| Durable admission/terminal recovery | INTEGRATED PRIMITIVE PASS | One non-GUI composition root admits, creates the first trace event, scans admissions, and recovers durable terminal intent. It does not decide worker liveness or publish generations. |
| Deterministic render result | STRICT PARENT VALIDATION ADDED | The parent now binds exact result shape, format, dimensions, copy, media facts, runtime receipt, sidecar, and output inode/hash during validation. It still trusts caller/worker assertions, releases the descriptor afterward, and lacks a trusted generation sealer. |
| G2 frozen evidence | HISTORICAL FROZEN PASS | Attempt 008 remains evidence for its exact old source closure only. Current source changed and needs requalification. |
| G2b parent preflight | NONQUALIFYING / STALE SOURCE | Its retained result remains `qualifying:false`; current validation accepts the specimen, but current source hashes differ. |
| Cancellation/restart | BLOCKED | No durable resource ledger, controller-owned process groups, startup cleanup, or split Docker create/start exists. |
| Palmier machine path | PRODUCTION NO-GO | Exact mutation, durable per-operation intent, MCP correlation, one global fence, and request-bound QC remain absent. |

## G1 integration that now exists

The new
[`durability_controller.py`](../../scripts/producer/headless/durability_controller.py)
is a bounded composition root for durability only. `admit_attempt()` now calls
the admission registry, derives or accepts a boot identity, builds an
authority-bound trace, creates exactly one `ADMITTED` frame, and finishes a
recoverable terminal boundary before returning. `recover_durable_boundaries()`
scans the durable admission denominator and classifies each attempt without
guessing whether an untracked worker is alive.

The integrated formats are deliberately fail-closed pre-release schemas:

- admission record version 2 persists authority, release, build, policy, and
  expected-parent identity;
- trace frame version 3 repeats `authorityId` in every frame and uses the
  `sniper-trace-event-v3` digest domain;
- terminal intent version 3 retains the exact canonical terminal-result bytes
  before the terminal trace append; and
- terminal manifest version 4 binds every immutable admission field, the exact
  result digest, terminal sequence, and terminal trace digest.

The startup scanner heals only unambiguous boundaries:

- admission record before attempt trace;
- a bounded newline-less first `ADMITTED` frame;
- durable terminal intent before terminal trace;
- terminal trace before terminal manifest; and
- a torn terminal tail when the exact terminal intent is already durable.

It returns `RECONCILIATION_REQUIRED` for host reboot or unknown process state,
and `BROKEN` for corrupt trace/terminal data, unsafe attempt paths, admission
identity conflict, or a terminal trace whose exact result bytes are unavailable.
One bad old attempt no longer hides healthy scan rows.

## Result availability was different from result integrity

Round 10 bound a digest of the terminal result into the trace. That prevented
substitution, but it did not preserve the bytes needed to recover after the
calling process died. A digest can answer “are these the same bytes?”; it cannot
reconstruct bytes that were never retained.

The corrected order is:

1. validate a closed terminal-result union;
2. durably write and directory-flush `terminal-intent.json` with the exact
   canonical result;
3. append and sync `TERMINAL_SEALED` with the domain-separated result digest;
4. derive and durably replace `terminal-manifest.json`; and
5. on replay, require byte-equivalent intent, trace, manifest, and admission
   identity.

Invalid early success is preflighted before intent creation, so a failed
lifecycle check cannot poison the attempt with an immutable unusable intent.

The terminal-result union is now exact rather than an arbitrary dictionary:

- failure-like dispositions require exactly schema version, typed error code,
  and evidence digest; and
- success requires the authority ID, publication sequence, canonical generation
  UUID, commit and generation-verification digests, normalized relative MP4
  path, MP4 digest, and typed media facts.

This is a schema and recovery guarantee, not publication authorization. A caller
can still assert plausible hashes and media facts. Only a future trusted sealer
and publisher can prove those facts against committed inodes and `CURRENT`.

## Authority roots now have identity

Previously, different logical authorities could write admissions under the same
mode-0700 directory because each record was internally consistent. The root
itself had no immutable identity.

[`authority_record.py`](../../scripts/producer/headless/authority_record.py)
now creates one canonical mode-0600 `authority.json` under the admission lock.
New admissions must match it, and denominator scans reject any record set that
crosses authority IDs. This closes accidental root reuse; it does not yet define
project lineage, copy/fork semantics, or a durable active fence.

## Render result closure added

The explicit render launcher previously accepted a child result when it was
mostly shape-correct. Empty proof dictionaries, the wrong kind/format/name, and
self-consistent proof for the wrong copy could pass the outer boundary.

The current launcher requires caller-supplied expected format, dimensions, and
copy fields intended to become controller-owned. No trusted request/preseal
constructor exists yet. It then verifies:

- an exact top-level worker-result schema;
- an attempt-cache direct child named exactly `{key}.{format}`;
- a user-owned, single-link, mode-0600, bounded, nonempty output inode;
- digest and size from the held output descriptor;
- exact kind, codec, pixel format, dimensions, duration, fps, and frame count;
- requested copy and render-input key;
- full fail-on-error decode and the MOV terminal-alpha oracle;
- runtime policy/image/snapshot/variables/output/network/removal bindings; and
- a mode-0600 retained sidecar byte-equivalent to the returned proof.

The retained G2b parent specimen passes this stricter validator. That is a
compatibility check, not a new qualification run.

At the round-11 boundary, one important closure remained open: `assetInputs`
could be derived by rereading
live source paths after the render snapshot was sealed. The proof rows are not
yet cross-bound to the exact corresponding snapshot-manifest rows. A changed
source could therefore describe newer bytes than those rendered. The controller
must derive asset proof from the sealed snapshot or precommit the exact asset
closure and compare both representations. Round 12 later implemented that
cross-binding; this frozen section records the counterexample that motivated it.

## Restrictive umask and cleanup findings

Requesting mode `0600` or `0400` at creation is insufficient under a restrictive
umask. The hardened authority/render creators now explicitly set and verify
modes for trace files, snapshots, promoted outputs, streamed outputs, cache
locks, owner receipts, and private temporary directories. Existing unsafe files
still fail closed instead of being adopted.

The host network-positive-control helper also allocated its socket before the
cleanup scope. A denied bind left that socket open. Resource allocation now
enters `try/finally` before bind/listen, and a regression requires close on bind
failure. This is local cleanup hygiene; it does not solve process or Docker
resource recovery.

## Cancellation remains the highest-risk MP4 blocker

The outer launcher deadline is shorter than the inner render allowance. Killing
the worker does not prove that its descendants or daemon-owned container died.
The exact adapter still performs one combined detached `docker run --rm`; a
controller death can bypass `finally`, and a short absence window cannot exclude
a late create.

The missing production contract is:

1. append and sync a resource intent before launch;
2. create the container without starting it;
3. record and sync the exact daemon/container identity;
4. start it only under a current attempt fence;
5. own local children in a new process group with stage deadlines and
   TERM/grace/KILL/reap;
6. record every verifier and streamed-output resource;
7. mark cleanup complete only after exact absence and daemon re-attestation; and
8. replay all cleanup-pending resources during controller startup.

The mandatory failure matrix includes cancellation or death before and after
intent, create, resource record, start, output, verification, promotion, pointer
commit, and terminal seal; verifier hang; Docker client death; daemon restart;
controller `SIGKILL`; and host reboot.

## Palmier machine path remains a no-go

The only defensible target topology remains:

```text
Claude Code/Codex planner -> one persistent controller-owned arbiter -> Palmier MCP
```

Neither planner should hold direct mutation authority. Executed fake-server and
parser counterexamples showed that the present machine path can:

- report `edited` when a requested opacity stays unchanged and an unrelated
  speed property changes;
- accept declared lanes that merely intersect, rather than exactly equal, the
  derived operation lanes;
- accept effectively untyped color/effect values;
- lose all local knowledge after a remote operation lands but before the final
  in-memory receipt is saved;
- correlate a Desktop Post only by tool name, not event/session/arguments/fence;
- treat unrelated fingerprint drift as proof that a pending operation landed;
- fail open on malformed hook JSON;
- parse a JSON-RPC response with the wrong ID; and
- approve an export relative to Palmier's own candidate rather than the
  controller-owned requested 9:16 product.

The arbiter needs a hash-chained per-operation journal with durable `OP_INTENT`
before dispatch, exact request/response/session correlation, a tool-specific
before/after comparator, state-generation CAS, one user-global fence across all
mutation families, and quarantine after any unattributable disconnect. QC must
bind the requested product, exported bytes, complete decode, reviewer
provenance, and evidence actually viewed.

## Round-11 go/no-go

**Go:** keep the durability composition root and strict render validator;
requalify them after the next independent review; build the process/resource
supervisor and trusted sealer before R0.

**Research go:** offline Palmier protocol/schema capture, exact typed-delta
comparators, persistent arbiter journaling, ambiguous-response reconciliation,
and request-bound QC negatives.

**No-go:** deterministic-MP4 publication, another live Palmier mutation canary,
direct planner mutation authority, GUI work, or any claim that the product has
reached 95% confidence.
