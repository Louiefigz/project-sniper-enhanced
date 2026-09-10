# Readiness timeout is not resource cleanup

Date: 2026-09-06. Scope: bounded readiness cancellation correction, not video-quality or whole-workflow qualification.

## The defect

The planning gate runner called `terminateProcessTree` and immediately returned a timeout. That helper scheduled escalation; it did not establish that the child group had stopped. The two gate waves also used `Promise.all`, so a thrown gate could return while a sibling was still running. Readiness then reconciled Docker names only after an ordinary return, not through a cleanup-finally boundary.

This creates an ordering error: a still-running gate can create a renderer resource after its caller believes cleanup has finished. A timeout or a rejected promise is an outcome, not proof of resource absence.

## Implemented boundary

- `planning-gate-runner.ts` now uses the existing bounded POSIX owned-group runner. TERM/KILL is followed by absence observation before settlement. Only ESRCH means absent; EPERM/unknown observation fails closed. Exit code, bounded output, live stderr and timing context remain available.
- The common runner adds opt-in AbortSignal cancellation and shutdown tracking. Existing cut-preview/opening timeout ceilings remain 900,000/1,500,000 ms. Its `forcedStop` caveat remains intact: outer-group absence does not cover a child-created independent session.
- `planning-gates.ts` waits every started sibling, cancels siblings after an infrastructure/unknown-stop failure, and spends one decreasing wall/monotonic remainder across both waves. Each real child retains its own five-minute ceiling. A late otherwise-successful verdict cannot renew the remainder.
- `readiness-gate-execution.ts` performs exact-name reconciliation in `finally` only after all launched groups are known stopped. Exceptions without complete stop evidence retain unknown cleanup instead of pretending no resources exist.
- Readiness retains the failed gate bundle before rejecting unknown cleanup. It does not pay critics or commit a readiness checkpoint in that case. Cleanup time is included in gate elapsed/overrun accounting, not new rendering credit.
- New deterministic gate bundles are schema 2. The current readiness reader rejects schema 1 rather than assigning new stop guarantees to historical bytes. Existing immutable objects and the separate historical proposal descriptor are not rewritten.

## Focused evidence

From the `PROJECT_SNIPER` directory:

```sh
/usr/bin/time -p node --import tsx --test src/lib/server/__tests__/planning-gate-cancellation.test.ts src/lib/server/__tests__/readiness-render-containers.test.ts src/lib/producer/__tests__/planning-gates.test.ts src/lib/server/__tests__/stage-timing-propagation.test.ts
```

14/14 passed, 2.44 seconds wall on the final focused source tree. Actual tiny Python parent/grandchild timeout and cancellation each completed in about 0.64 seconds and tested both PIDs absent. An actual two-sibling timeout tested absence before the configured reconciliation callback. Other cases cover EPERM, bounded output overflow, full 100 KB exit-7 JSON, all-settled failure, deadline consumption and stale schema rejection. Docker behavior here is a TEST adapter, not an actual Docker failure qualification.

```sh
/usr/bin/time -p node --import tsx --test --test-name-pattern='deadline terminates|only explicit guided-opening|zero-exit leader' src/lib/producer/__tests__/cut-preview.test.ts
```

4/4 passed, 1.91 seconds wall, including the unchanged legacy/opening ceilings and actual owned groups. Final focused ESLint passed in 2.05 seconds; whole TypeScript passed in 2.50 seconds. No test/model/render process from this task remained running after the cohort.

One test harness failure was retained in the tool record: the mock function uses `.mock.restore()`, not `.restore()`. The 13/14 failing cohort took 2.35 seconds; the corrected cohort passed. Earlier type-check also caught only an overly broad TEST renderer type; the helper now accepts only the reconciliation responsibility it uses.

## Explicit blockers and when not to rely on this

1. **Durable readiness ownership remains missing.** A crashed/unknown readiness attempt has no project-held resource-claim index equivalent to the opening lane. Retaining its failed operation is not sufficient to prevent a later different-id request from overlooking it. Do not claim crash-safe retry/recovery from this slice. A bounded durable ownership/reconciliation policy is required before enabling that behavior.
2. **Late Docker creation is not fenced.** Existing readiness cleanup is bounded exact-name `ps → rm → ps`; a remotely queued create may materialize later. The POSIX group fix prevents racing a known-live local producer but does not prove daemon-side future absence. No global container cleanup or guessed names were added.
3. **Independent nested sessions are outside outer-group proof.** Detached ffprobe/process sessions require their own exact ownership and reconciliation. `processesStopped` explicitly means the launched outer groups, not all OS resources or Docker.
4. **Cleanup can exceed the creative deadline.** Existing exact-name cleanup has its existing per-command bounds. Such time is reported as an overrun; no critic/render/retry credit is granted. This is not a two-hour performance claim.
5. The source-bound synthetic readiness integration fixture was not run during the parent’s unstable source window. A focused re-sealed schema1/cleanup mutation regression has been added to that suite for the next shared stable window. No production media or model job was launched for this correction.
