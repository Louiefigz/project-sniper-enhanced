# Visible bytes after a failed flush are not durable authority

## Finding

A restart can see the complete bytes from an operation whose `fdatasync()` or
directory `fsync()` returned an error. Visibility in the page cache does not
prove that the transition crossed its durability barrier.

This matters for the active-generation fence. If a complete `CANCEL` frame is
visible after a failed journal flush and recovery immediately materializes it,
recovery can clear the active attempt without first making the explicit cancel
durable. The corresponding projection problem occurs when `FENCE` was renamed
but the authority-directory flush failed.

## Safer protocol

Before accepting any visible journal prefix after startup or a prior error:

1. Hold the never-unlinked publisher mutex.
2. Validate the whole bounded hash-linked chain.
3. Flush the retained journal descriptor and authority directory.
4. Recheck the named journal inode and scan the exact same chain again.
5. Reconcile `FENCE` only to a state that appears in that chain.
6. Flush the named `FENCE` descriptor and authority directory, then re-read it
   through the retained inode.

Mutation APIs must also distrust a caller-supplied scan summary. Before either
truncating a torn tail or appending a transition, the journal now performs a
fresh scan of the held descriptor and compares it recursively with exact types.
This prevents a forged `valid_bytes`, hostile `__eq__`, or `False` masquerading
as integer zero from turning a live lock witness into truncation authority.

Capacity is preflighted before the first append byte. A frame that would exceed
the journal byte or transition bound is rejected with the journal unchanged;
writing it first and discovering the cap during rescan would create a complete,
newline-committed poison tail that normal torn-tail recovery cannot remove.

The implementation injects failures after a complete newline-delimited frame
and after `FENCE` rename. Both restart paths must re-flush and reobserve before
returning an idempotent replay. Torn frames without the newline commit marker
are truncated; a torn `CANCEL` therefore leaves the attempt active.

## Result in this slice

The focused fence suite covers 35 tests plus 12 subtests, including strict
prefix writes, complete visible frames after a failed data flush, projection
rename before failed root flush, named-inode replacement across recovery
barriers, forged scan summaries, capacity boundaries, malformed complete
frames, replay, and concurrent reservation.

## When not to use this pattern

This is not a substitute for storage-specific hardware durability guarantees,
a hostile same-user security boundary, or a distributed consensus log. It is
appropriate for the declared local process-crash/SIGKILL/restart contract on a
single private authority filesystem. Cross-host publication needs a different
authority and failure model.
