# Headless execution adversarial audit — 2026-07-18, round 12

> **STATUS: FROZEN AUDIT SNAPSHOT.** Later corrections belong in a later audit
> and the living
> [headless optimization dossier](../producer/HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md).

## Scope boundary

Only two non-GUI paths were reviewed:

1. Claude Code/Codex Desktop into one machine-facing Palmier protocol; and
2. Claude Code/Codex Desktop into a deterministic MP4.

No GUI, dashboard, Next.js, SSE, active-window, click, or desktop-view path was
reviewed or recommended.

## Verdict

The product remained **below 95% confidence**. Round 12 closed several exact
false accepts and one crash-recovery ordering bug, but did not produce a trusted
request constructor, final-generation sealer, publisher, `FENCE`, `CURRENT`, or
fresh current-source OCI qualification.

## Confirmed counterexamples and corrections

### Terminal intent had to precede ordinary torn-tail classification

A durable `terminal-intent.json` plus a torn terminal trace was classified as
`RECONCILIATION_REQUIRED/TORN_TRACE_TAIL` before terminal recovery ran. The
controller now invokes terminal recovery first, allowing the exact retained
intent to authorize repair of only its own torn terminal frame. The new
regression failed before the change and passed afterward. The G1-focused suite
reached 57 passing tests.

### Render proof accepted four self-consistent lies

Executable counterexamples showed that the parent could accept:

- impossible occupancy such as one sampled frame and 999 meaningful frames;
- a worker-chosen cache key when the worker made every dependent field agree;
- an unapproved image ID and empty before/after/runtime evidence; and
- asset proof for live source B after sealed snapshot A had actually rendered.

The corrected boundary now requires a parent-expected key, format, dimensions,
copy, approved image, exact occupancy arithmetic, deep runtime receipt, retained
archive revalidation, and exact asset bindings carried from the sealed snapshot.
Proof generation no longer rereads live asset paths.

### Hashing an inode did not keep it unchanged

A same-inode overwrite after hashing returned the old digest while the path held
11 bytes of different content. Validation now binds device, inode, type, link
count, owner, size, modification time, and change time before and after hashing,
then repeats the output binding after proof validation. This closes the observed
race window, not mutation after the final descriptor is closed; a trusted sealer
still must copy and rehash into fresh final-generation inodes.

### Cleanup scopes began too late

The host network decoy allocated a socket before entering its cleanup scope. A
denied bind leaked the descriptor. Allocation, bind, listen, and close now share
one `try/finally`, and the bind-failure regression runs with
`ResourceWarning` promoted to an error.

### Local timeout needed process-group ownership

Ordinary `subprocess.run(timeout=...)` killed the immediate child but left a
descendant alive. The launcher now starts a new session, owns the process group,
uses TERM/grace/KILL, waits for group absence, and applies the same cleanup on
timeout and interruption. This did not yet cover a daemon-owned detached Docker
container.

## Verification boundary

- 170 focused headless/render tests passed in 2.439 seconds; one environment
  capability test was skipped.
- The suite ran with `ResourceWarning` promoted to an error.
- Changed logic passed the repository limits: at most 300 physical lines per
  logic file, 50 lines per function, four parameters, and two control-flow
  nesting levels.
- The retained G2b proof remained compatible with the current strict validator.
  This was only compatibility evidence: the retained result says
  `qualifying:false`, and its frozen source hashes no longer match current code.

## Remaining blockers at this snapshot

- `requestDigest`, `buildDigest`, expected key, and expected asset facts were
  still supplied by the caller; no trusted request/preseal builder recomputed
  them from exact bytes and tool closure.
- The output descriptor closed before any trusted generation handoff.
- Detached Docker creation had no durable parent-owned resource ledger, and
  outer and inner deadlines were inconsistent.
- No production controller owned startup reconciliation, active attempt fence,
  sealer, publisher, `CURRENT`, or terminal publish recovery.
- Current source had no fresh independent OCI run, full-minute render cohort,
  quality-pass cohort, or fault campaign.

## Palmier disposition

Unchanged production no-go. The only defensible design remained one persistent
controller-owned arbiter between both planners and Palmier MCP. Existing exact
mutation, durable intent, request/response correlation, global fencing,
ambiguous-response reconciliation, and request-bound export QC were still
insufficient. No additional live mutation was justified.

