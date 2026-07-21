# Network-Denial Proofs Need Positive Controls

## Finding

“Every connection failed” does not prove isolation. The probe itself may be broken.
A credible offline-render proof needs one operation that must succeed, plus denied
operations that distinguish the container namespace from the host and the internet.

## G2 proof shape

The exact render container now performs the active probe after live-policy
attestation and before output is trusted:

1. It binds and connects to its own loopback socket. The preflight succeeded on
   container port `46373`, proving Node and loopback networking worked.
2. The host starts a nonce-returning loopback decoy and connects successfully. The
   preflight used host port `58220`.
3. The same render container tries that same host port through its own `127.0.0.1`
   and gets `ECONNREFUSED`, proving loopback namespace separation.
4. Connections to external IPv4 and IPv6 addresses both fail with
   `ENETUNREACH`.
5. DNS resolution fails with `EAI_AGAIN`.

This active evidence is retained with the exact media hash. It complements, rather
than replaces, the daemon-resolved `NetworkMode=none`, empty addresses/ports, one
read-only input mount, and pre/post container inspections.

## General rule

Every negative capability test needs a nearby positive control using the same tool
and execution context. For filesystem isolation, prove a declared file is readable
before proving a secret sentinel is not. For tool isolation, prove an allowed tool
works before interpreting denied calls. For network isolation, prove local probe
mechanics before trusting egress failures.

## When not to use this approach

Do not add a live decoy to a renderer that cannot tolerate any extra local socket or
subprocess. In that case, qualify a dedicated immutable probe image with the exact
same runtime policy and retain daemon-level namespace evidence, while clearly stating
that it is a policy-equivalence proof rather than an observation inside the render
container.
