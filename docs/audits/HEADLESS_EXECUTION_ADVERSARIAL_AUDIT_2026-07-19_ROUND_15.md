# Headless execution adversarial audit — 2026-07-19, round 15

> **STATUS: CURRENT FROZEN AUDIT SNAPSHOT.** The living status remains in the
> [headless optimization dossier](../producer/HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md)
> and [empirical gate ledger](../producer/HEADLESS_EMPIRICAL_GATE_LEDGER.md).

## Scope

Claude Code/Codex Desktop to deterministic MP4 only. GUI, GUI-adjacent
execution, Palmier-native execution, Palmier delivery, publication, and
`CURRENT` mutation are excluded from this implementation round. Publication is
named below only to keep the non-authorizing boundary explicit.

## Verdict

The architecture is materially stronger at five isolated boundaries:
prospective denominator/order, durable replay, selected versioned history,
fresh-inode generation installation, and admitted graphic receipts. A
standalone active-fence state machine also exists. These are tested primitives,
not one executable product path. No gate advanced, the project is not at 95%,
and there are still zero qualifying independent product units.

## Counterexamples closed

### Visible rename is not durable success

An injected `fsync` failure can occur after a rename or append is already
visible. The old replay shape could observe exact bytes and return success
without completing their durability barrier.

Operation admission, unit enrollment, cross-ledger order, graphic-receipt, and
active-fence replay now pin the request-relevant named inode, re-flush exact
files and parent directories, then reread/reparse before returning success.
Same-byte file or record-directory substitution rejects. The cross-ledger
barrier is targeted; it does not add an O(n) `fsync` pass over unrelated rows.

Recovery remains deliberately narrow. A deterministic regular strict-prefix
pending file may be completed from exact expected bytes. A complete conflict,
non-prefix, oversize, unknown member, symlink, FIFO, hardlink, or identity-
ambiguous residue is preserved and fails closed.

A final hostile review found that the first repair still released its flushed
inode before the named reload. Operation, enrollment, and cross-ledger replay
now hold exact file, record, and store descriptors through that reload, bind
post-`fsync` metadata, compare named state, and return the pinned parsed
observation. Deterministic same-byte substitutions at the old gap reject.

The same review found that pending semantic checks and pathname unlink were
separate. Cleanup now validates bytes through the held descriptor, rechecks its
named identity immediately before unlink, and requires the held inode's link
count to reach zero. A malicious same-UID swap after the last pathname check is
not portably preventable; the proof remains scoped to cooperating writers under
the kernel lock and a private filesystem.

### Source-code order is not prospective order

Persisting enrollment and then calling admission does not prove that another
process did not admit first. The cross-ledger transaction now takes one shared
outer lock, reobserves the exact enrollment, makes PREPARED intent durable
before V3 admission, reobserves admission and enrollment, and finally retains a
COMMITTED receipt. PREPARED reserves idempotency, attempt, child, and bounded
capacity identities. A preexisting or stolen identity is rejected rather than
retroactively blessed.

This closes a denominator/order property only. Enrollment and order receipts
are not queue items, render-start capabilities, success evidence, or publication
authority.

### Immediate lineage is not recursive authority

The selected-history reader now authenticates a mixed R0/R1/V2 chain back to
genesis, including receipt kind, parent reference, plan/base binding, sequence,
and the full selected genesis R1 payload. It holds the cooperating publication
mutex while pinning and revalidating the selected bytes.

The result proves only the ancestry reachable from the selected pointer at that
observation. It does not prove global fork uniqueness, runtime identity,
execution, a future fence state, or continued immutability after descriptors
close.

### Read-only modes do not revoke escaped writers

The generation sealer creates a fresh final inode namespace from an exact,
bounded staging manifest. It rejects nonregular, multiply linked, undeclared,
unsafe, changed, or colliding input; writes and flushes `commit.json` last;
installs with no-replace semantics; and conservatively recovers identified
pending state.

The sealer does not prove writer-capable descendants are dead, reserve disk,
authorize execution, or publish. Its result is only generation identity,
commit identity, and replay disposition.

### A valid receipt can still name caller fiction

The admitted graphic controller now derives receipt identity from the retained
admission artifact, build/source closure, approved plan row, lane result, and
controller-owned request/quality policy. An attempt-bound set manifest prevents
copying a valid receipt set across attempts. The media file is reopened and
hashed after lane validation, after durable receipt persistence, and again on
replay/load.

The current R0 profile allows exactly one graphic and one receipt. Multiple
graphics require a new versioned profile. A receipt set does not append a
terminal success, seal a generation, or authorize execution/publication.

### Fence state is not a worker lifecycle

The standalone fence has a canonical append-only, length/CRC/hash-linked
journal plus materialized `FENCE`. Under the never-unlinked mutex it supports
idempotent `BOOTSTRAP`, `RESERVE`, and `CANCEL`, rejects resurrection and
conflicting holders, repairs only a torn final journal fragment, and re-syncs a
complete visible transition after an injected durability failure.

Repair and append also bind caller state to a fresh exact-type scan of the held
journal. Forged offsets, hostile nested equality, and bool/int aliases reject,
and byte/transition capacity is checked before any append byte is written.

It intentionally has no `RELEASE`, work launch, V3-admission composition,
terminal-result binding, final publication recheck, or `CURRENT` operation. A
missing materialized projection after later history is not inferred from
ambient state.

### Descendant metadata is not executable path identity

An executable pin originally retained every ancestor's link count. On APFS,
unrelated temporary-directory creation beneath a shared pinned ancestor can
change that count without replacing or weakening the executable path. This
produced a real concurrency-dependent false tamper rejection.

Directory pins now retain device, inode, mode, owner, and group. They still
reject path replacement and permission changes. Executable leaves retain the
stronger link-count, size, timestamp, inode, and digest checks. Deterministic
unrelated-child tests and ten repeated focused stress runs pass.

## Integration boundary

| Primitive | Implemented observation | Authority deliberately absent |
|---|---|---|
| Enrollment + ordered V3 admission | Prospective unit and exact admission order | Worker start, outcome, child seal |
| Versioned history | Complete selected chain and selected genesis payload | Runtime, live lease, global fork uniqueness |
| Admitted graphic receipt set | Exact one-graphic media/receipt evidence | Terminal success, generation authority |
| Fresh-inode sealer | Installed immutable generation bytes | Writer quiescence, capacity, publication |
| Standalone active fence | Bootstrap/reserve/cancel state | Release, worker integration, final commit check |

There is no composition root that consumes all five rows for one operation.
Passing each row independently cannot be multiplied into end-to-end confidence.

## Verification

Final independent reruns were grouped by concern. They overlap and must not be
summed:

- ordered admission/enrollment/cross-ledger/composition: 161 tests plus 104
  subtests;
- render/lane/graphic-receipt/build closure: 114 plus 100;
- generation/sealer/history: 97 plus 56;
- active fence plus the headless import boundary: 36 plus 12.

Focused handoffs separately reported cross-ledger recovery at 51 tests plus 17
subtests and graphic controller/store at 20 plus 6. They are subsets of the
concern suites, not additional independent evidence.

These are local mechanism tests. They are not natural product units, a complete
MP4 fault campaign, current-source OCI qualification, latency comparisons, or
blinded quality/reliability observations.

## Remaining blockers

- no production Claude Code/Codex Desktop CLI/status/cancel protocol;
- no single admission-to-terminal controller composition;
- no trusted runtime supervisor or proof that all writer descendants are dead;
- no safe delayed Docker creator/startup/reboot reconciliation;
- no CPU/memory/disk/provider resource-vector reservation or `ENOSPC` campaign;
- no final fence recheck integrated with operation admission and child success;
- no publisher, pointer recovery, or terminal-after-pointer reconciliation;
- no fully qualified current-source OCI closure or coherent R0 mechanism seed;
- no six-project paired pilot and no qualifying field cohort.

## Go/no-go

**Go:** keep composing the existing primitives behind work-disabled headless
authority. Add trusted execution/quiescence and capacity accounting, then
adversarially test the complete non-publishing lifecycle and freshly qualify the
current OCI closure.

**No-go:** infer end-to-end correctness from isolated suites, add production
publication before its gate, count synthetic tests as reliability units, or
claim 95% confidence.
