# Durable cleanup completion is not a replay token

## The interruption we need to distinguish

A cleanup worker can finish correctly while its controller stops before saving
the project checkpoint. Repeating native cleanup is not the right default:
the old attempt may have finished, or an older worker may still be unresolved.

Project Sniper now separates three facts:

1. The actual worker returned, its owned output and process ledger agree, and
   the independent attempt reader accepts that evidence.
2. The controller published a new-only `prepared.json` inside that attempt.
3. The project journal committed the prepared cleanup checkpoint.

These facts are related but not interchangeable. Publishing preparation does
not authorize a journal mutation, reservation retirement, lease release or
media approval.

## Recover data instead of rerunning work

The normal writer creates `prepared.json` only after step1 succeeds. It retains
the original raw bytes, SHA, size, file identity and parent identities through
the first journal CAS. A preexisting entry refuses native replay.

Recovery uses a different private capability from a live completion. It needs
the actual current precleanup journal, actual project and global leases, the
full current execution claim, and the exact cold reservation. A copied JSON
object or a cast to the live TypeScript interface cannot create that capability.

Every prior attempt is inspected, not just the selected UUID. The reader holds
six exact files per attempt plus five shared media records, with limits of32
attempts and64MiB of aggregate actual metadata. Cleanup intent/spawn/reap must
balance. A fresh UUID cannot hide an unresolved old attempt.

## Callbacks must not move the baseline

Capture the journal, active reservation, claim and input before the first
original callback. Capture all attempts and shared media before sampling the
original clock or calling namespace/claim readers. After each callback, compare
the original identities again. Equal bytes on a replacement inode are still a
change, not a reason to accept a new baseline.

After the intended CAS, only the obsolete current-journal check is excluded.
Original historical evidence remains held. No post-CAS callback should demand
that the current journal still be the pre-CAS file.

## Measured evidence and limitations

The initial adoption suite passed21 cases in43.86s wall. Eight added callback
and actual-lease cases passed in27.97s, with one overlapping original test:
28 distinct cases, not29. An independent six-case review passed in20.46s.
The broader preparation/first-CAS/live-workflow/final-CAS suite passed96 cases
in92.48s concurrent wall. Those times include fixture setup and fault tests;
they do not measure native cleanup or video generation throughput.

All fixtures use actual private TEMP files, leases and journal CAS, with
explicit TEST native/claim admission leaves. They do not qualify real footage.

Do not use this approach to settle a missing output, torn ledger, unmatched
spawn, forced/uncertain worker or crash before durable preparation exists.
Those need separately authenticated interruption recovery. Fresh leases and
PID absence alone do not prove an old wrapper has stopped. The existing native
singleton and public V2 execution fences remain in place.
