# Detached resources need prelaunch ledger entries

## What failed

The renderer used detached `docker run --rm`. Its outer worker deadline was 180
seconds while the inner render wait alone allowed 600 seconds. Terminating the
Python worker bypassed its cleanup `finally`, and the daemon-owned container was
outside the local process group. A random name generated only inside the worker
left the parent with nothing exact to reconcile after death.

The local process runner had a related edge case: a command could exit zero
after spawning a descendant that closed inherited stdio, causing the runner to
return while the descendant remained alive.

## The correction

The trusted parent now:

1. allocates the exact random container name;
2. durably writes a `REGISTERED` attempt ledger row before worker spawn;
3. passes that name through the closed child environment;
4. owns the local child process group on success, timeout, and interruption;
5. proves exact Docker absence before changing the row to `REMOVED`; and
6. retains uncleared `REGISTERED` rows for a future safe recovery protocol.

The outer deadline is now 1,200 seconds so it encloses the 600-second render,
120-second output stream, and bounded control-plane stages. Success latency is
unchanged; only the maximum failure horizon changes.

## What remains

A library hook is not startup recovery, and directly wiring the current hook is
unsafe. A prior delayed Docker creator can create the registered name after a
new controller's one-time absence proof. Temporary absence therefore cannot
clear the row or authorize name reuse.

Recovery remains quarantined until split create/start, durable creator
PID/start/boot identity, Docker engine identity, exact container ID/labels, and
a fence check before start prove prior-creator impossibility. The fault campaign
must then interrupt every boundary around registration, create, identity
commit, start, output, removal, and ledger replacement, including a same-boot
delayed create after the replacement controller starts.
