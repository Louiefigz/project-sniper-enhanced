# Absence Windows Do Not Prove Asynchronous Cleanup

## Finding

Seeing no Docker container for a fixed interval is evidence of current absence, not
causal proof that an in-flight create request cannot register one later.

## The failed assumption

The hardened renderer kills and reaps an interrupted Docker client, repeatedly
removes the exact random name for up to 60 seconds, and requires three continuous
seconds of absence. That is a useful mitigation, but an adversarial review correctly
rejected it as cancellation/crash closure: a daemon create delayed beyond the stable
window can still finish after the controller returns. Nonzero transport results and
invalid detached IDs are ambiguous for the same reason.

Docker `run` performs container creation and start as separate daemon operations.
`--rm` protects a container that starts and exits; it does not prove cleanup of a
create that completes after its client disappears and never starts.

## Correct architecture

For integrated cancellation and crash safety:

1. split create from start;
2. run create under a cancellation-shielded supervisor;
3. durably persist and fsync the exact returned container ID;
4. treat an ambiguous create as `cleanup-pending`, never “absent”;
5. remove and reconcile by ID; and
6. recover the durable cleanup ledger after controller death or reboot.

The fault test must hold create beyond the former stable window, cancel the caller,
then allow creation to complete and prove removal by the returned ID before cleanup
is sealed.

## Scope consequence

The clean-success G2 overlay mechanism can be qualified without claiming asynchronous
cancellation. The late-create issue remains a P1 blocker for G1 and any integrated
headless release. Keeping those claims separate prevents a successful MOV from being
misreported as proof of lifecycle safety.

## When not to use this architecture

For a disposable local experiment where the operator accepts manual Docker cleanup,
a bounded name reconciler may be proportionate. It is not sufficient for an
unattended worker, a cancellation SLA, or any claim that SIGKILL/reboot cannot leave
resources behind.
