# Headless execution adversarial audit — 2026-07-18, round 13

> **STATUS: SUPERSEDED FROZEN AUDIT SNAPSHOT.** Round 14 disproved this
> round's direct-startup-reconciliation recommendation. See the
> [round-14 audit](HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-19_ROUND_14.md).
> The living status remains in the
> [headless optimization dossier](../producer/HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md)
> and [empirical gate ledger](../producer/HEADLESS_EMPIRICAL_GATE_LEDGER.md).

## Scope boundary

This round again reviewed only Claude Code/Codex Desktop to a machine-facing
Palmier protocol or deterministic MP4. GUI and GUI-adjacent execution were out
of scope.

## Outcome

Confidence improved, but the product is **still not at 95%**. Two additional
local lifecycle leaks were reproduced and fixed, and Docker resource identity
is now durably parent-owned before worker spawn. The startup hook, trusted
request constructor, generation sealer, publisher, and field evidence are still
missing.

## New executable falsifiers

### A successful command could leave a descendant alive

The process runner originally cleaned its process group only on timeout or
exception. A parent process spawned a descendant with closed inherited stdio,
exited zero, and caused `run_text()` to return while the descendant remained.
The success path now checks the group, applies TERM/grace/KILL when needed, and
requires group absence. The regression confirms that a zero-exit parent cannot
silently leave this descendant behind.

### Promotion leaked its source descriptor on an early destination failure

`promote_regular()` opened the staged source before opening the destination
directory, but its cleanup scope began after the directory open. A missing
destination directory leaked the source descriptor. Cleanup now begins before
that open and has an exact regression asserting the held source descriptor is
closed.

### Detached Docker had no recoverable exact name

The child previously generated a random container name after spawn. If the
parent died, startup had no durable exact target to remove. The headless launcher
now:

1. allocates the exact `sniper-render-{uuid}` name in the trusted parent;
2. writes a canonical mode-0600 `REGISTERED` row under an attempt-owned flock
   before spawning the worker;
3. passes the name through the closed child environment;
4. requires the runtime proof label to match that registered name;
5. proves exact absence before durably changing the row to `REMOVED`; and
6. exposes `reconcile_registered_containers()` for startup recovery.

The outer worker deadline increased from 180 to 1,200 seconds so it encloses the
600-second render wait, 120-second stream, and bounded control-plane stages.
This changes the failure ceiling, not successful render time.

The ledger has regressions for pre-yield durability, normal completion, worker
failure, cleanup failure retained for startup, recovery, control-plane mismatch,
noncanonical paths, and tampered encoding.

## Verification

- 178 focused headless/render tests passed in 2.127 seconds; one environment
  capability test was skipped.
- `ResourceWarning` was promoted to an error.
- An AST/physical-line audit covered 28 relevant Python logic files and found
  zero violations of the 300-line file, 50-line function, four-parameter, and
  two-level nesting limits.
- The retained G2b proof still passes the current validator when the new
  parent-owned container-name expectation is intentionally absent. That proves
  backward compatibility only. Eleven files in its frozen source manifest have
  changed, and new `render_result.py`, `process_runner.py`, and
  `resource_ledger.py` policy code was never in that qualification closure.

## What this does not prove

- The production durability controller does not yet call resource
  reconciliation after parent `SIGKILL`, daemon restart, or host reboot.
- Docker still uses combined detached `run`; split create, durable daemon ID,
  fence check, then start is stronger and remains required for the full fault
  claim.
- Expected request/build/key/asset facts still enter `OverlayLaunchRequest`
  from a caller. A self-consistent fabricated request can pass because no trusted
  builder recomputes the complete request and tool closure.
- Output validation releases its file descriptor. A later same-user mutation is
  possible until a trusted sealer copies and rehashes into fresh final inodes.
- There is no `FENCE`, immutable generation commit, flock publisher, `CURRENT`
  reader, production CLI, or publish/terminal recovery.
- No current-source OCI qualification, controller fault campaign, full-minute
  cohort, representative quality-pass pilot, or confirmatory field cohort has
  run.

## Optimization implication

The retained G2b timings showed a 0.666-second warm hit versus an 11.902-second
cold render in the second attempt. The safe optimization is not a mutable cache
shared by writers. It is a committed read-only cross-attempt CAS keyed by the
full sealed input/runtime/proof closure, imported into an attempt by digest and
revalidated before use. That optimization remains a plan item, not implemented
evidence.

## Go/no-go

**Go:** keep hardening the non-GUI MP4 controller boundary; wire startup resource
reconciliation; build the trusted request/preseal constructor and sealer; rerun
current source independently.

**Research go:** offline Palmier protocol/schema work behind one persistent
arbiter, with no planner-direct mutation.

**No-go:** production MP4 publication, live Palmier mutation canary, GUI work,
or a claim that confidence has crossed 95%.
