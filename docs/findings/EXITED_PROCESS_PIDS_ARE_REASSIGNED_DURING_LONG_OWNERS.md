# Exited process PIDs are reassigned during long owners

A native owner records every process it has owned, including processes that have
already exited. On a busy Mac, the kernel reassigns those PIDs to unrelated
processes within minutes. The supervisor treated that as a lost identity and
stopped a healthy render. A second race, in how workers read their owner's receipt,
failed a healthy worker at startup.

## What happened

The final-segment spike ran one owner for ten render windows. At 423 s the
supervisor stopped it with `owned root start identity was not bound`. The owner had
recorded 198 identities. 189 had exited, 7 were live, and 2 recorded PIDs (31460 and
31462, started 18:16:49) now belonged to other processes with later start times.
The 1-minute load average was 22 when it stopped; the batch saw 17 to 157.

`_anchors` put any recorded PID whose start time had changed into `reused`, and
`reused` made the snapshot unverified. That rule was meant for a live process whose
identity changed. It cannot tell that case apart from an exited process whose PID
was later given to someone else. A process's start time cannot change while it runs,
so a different start at the same PID means the recorded process has exited.

## The rule now

| Recorded identity at its PID | Meaning | Result |
|---|---|---|
| Absent | Exited | `missing_registered_pids` |
| Same start and group | Live and owned | Anchor |
| Different start | Exited; the PID was reassigned | `recycled_registered_pids`; the holder is owned only if an owned process is its parent |
| Same start, other group | One live process changed identity | `reused_registered_pids`; unverified; stop |
| Owner root with a different start | Cannot happen while the supervisor holds the unreaped child | Unverified; stop (never retired, even when the root is also a remembered row) |

`OwnedRegistry.remember_measured` follows the same rule. A measured owned process
with a new start replaces the retired record at its PID. A group change is still
refused.

Children are found by listing a parent's child PIDs, so a parent that exits during
that listing could lend its PID, and a foreign process's children, to the owner.
The parent is read again after its children are listed. If that PID no longer holds
the process read into the table, the sample is retried
(`parent-changed-during-child-discovery`) and none of the listed children is owned.

## Other users' processes need a second reader

About a fifth of this Mac's processes (301 of 1,329 when checked) belong to root or
service accounts. For another user's process, `proc_pidinfo(PROC_PIDTBSDINFO)`
returns EPERM. Before this fix, a recorded PID reassigned to such a process made the
next sample fail as `measurement-unavailable`, which stopped the owner. `sysctl
{CTL_KERN, KERN_PROC, KERN_PROC_PID}` returns the `kinfo_proc` that `ps` reads for
any user. It is used only for a recorded PID that libproc refused:

- a different start marks the identity as reassigned;
- the same start means libproc refused the recorded process itself, which still fails;
- an unbound identity or the owner root still fails.

`clang offsetof` on the macOS SDK, for arm64 and x86_64, gave the layout: `kinfo_proc`
is 648 bytes, with start seconds at 0, state at 36, PID at 40, parent at 560 and
group at 564. The Python declaration reproduces those offsets; comparing them only
catches an edit to that declaration. The guards that run are: the kernel must return
exactly 648 bytes and the requested PID, and every binding first reads the helper's
own row both ways and refuses to continue unless the two rows are equal. On this host
a root-owned PID read through `kinfo_proc` also matched `ps`.

## Exited identities must also leave the registry and the lease

Retiring an identity from ownership decisions is not enough: an owner that keeps
every identity it ever saw eventually passes the fixed bound of 4,096 recorded
identities. At the F0 journal's 27 exits a minute that is about 150 minutes. The
owner then failed as a renderer failure, and because the lease could not record the
extra rows, a verified cleanup never completed the lease and the pool slot stayed
quarantined.

Now, after each verified sample, the owner forgets every non-root identity that
sample found absent or reassigned (`OwnedRegistry.retire`). Its lease drops the
matching rows, and rows replaced by a new process at the same PID, only after its own
`ps` read shows them absent (`retire_processes`). A row whose PID still matches stays
recorded. If that read fails, every row stays and the next verified sample retries.
The bound (`native_work_lease.MAX_RECORDED_IDENTITIES`) now limits the identities
recorded at one time, not an owner's lifetime churn. A synthetic three-hour owner
(1,080 samples, 6,480 exited identities, 216 PIDs given to unrelated processes, half
the steps reusing just-exited owned PIDs) never recorded more than 7 rows after a
sample. The same run on the first R1 commits stopped at sample 683 with an
unnamed `ValueError`.

More than 4,096 identities recorded at once still stops the owner, now as
`process-registry-overflow`. A cleanup that verified every registry identity absent
still completes the lease and frees the slot; an unverified cleanup still leaves the
slot quarantined.

## Owner receipts are replaced, not rewritten

`NativeRun.persist` writes each owner snapshot to a new file and renames it over the
receipt. A worker that opened the old receipt just before the rename then sees link
count 0, and `read_bytes` refused it as unsafe. This failed 1 of 25 worker starts in
the spike. `read_bytes` now raises `ArtifactReplaced` only when the opened regular
file has been unlinked and its path names another regular file.
`native_export.active_owner_snapshot` reopens on that error and nothing else, for at
most five reads, and never returns bytes from the replaced file. An in-place change,
a second hard link, a deleted receipt or malformed JSON is still refused on the
first read.

## When not to use this

- Do not retire an identity just because its PID is present. Only a different
  kernel start time shows that the PID was reassigned.
- Do not treat EPERM as proof that a process belongs to someone else. Read the start
  time through `kinfo_proc` first.
- Do not retry every changed read. Only a rename over the path is the owner's normal
  publication. Anything else would accept an edit that no owner published.
- This does not observe a process that starts and exits between samples, and it
  does not change how cleanup finds descendants.

Tests: `scripts/producer/tests/test_native_identity_retirement.py` (the three-hour
churn, overflow naming and slot release, lease retirement for both lease kinds),
`test_native_process_table.py` (a parent PID reassigned during child listing),
`scripts/producer/tests/test_native_pid_recycling.py` (the spike shape, a new
owned child at a retired PID, an unrelated holder's children, a live group change, a
changed root, the EPERM path and the owner loop through the real sampler parse) and
`scripts/producer/tests/test_native_owner_snapshot_race.py` (a real `persist`
between open and read, after the read, continuously, and the anomalies that still
refuse).
