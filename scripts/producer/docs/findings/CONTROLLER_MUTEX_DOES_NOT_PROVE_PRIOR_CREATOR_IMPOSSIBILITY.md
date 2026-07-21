# A controller mutex does not prove prior creator impossibility

## What failed

An exclusive controller lock proves that two well-behaved controllers do not
hold authority at the same time. It does not revoke an already-started child or
daemon request from the prior controller.

After a parent dies, a new controller can acquire the lock, inspect a registered
container name, and observe that the name is absent. A delayed old worker or
Docker request can then create that name after the absence check. Clearing the
ledger row or reusing the name turns a temporary observation into false
recovery authority.

## The correction

Keep direct startup reconciliation disabled until the lifecycle proves that no
prior creator can still act. The minimum closure is:

1. split Docker create from start;
2. durably record creator PID/start/boot identity before create;
3. durably bind Docker engine identity, container ID, and required labels;
4. revalidate the current fence immediately before start;
5. reconcile only exact matching resources; and
6. pass a same-boot delayed-create fault campaign around every durable boundary.

Absence is evidence about the instant inspected. It is not a lease revocation,
creator cancellation, or proof of future absence.
