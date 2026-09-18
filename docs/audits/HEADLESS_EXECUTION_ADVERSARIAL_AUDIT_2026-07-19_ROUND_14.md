# Headless execution adversarial audit — 2026-07-19, round 14

> **STATUS: CURRENT FROZEN AUDIT SNAPSHOT.** The living status remains in the
> [headless optimization dossier](../producer/HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md)
> and [empirical gate ledger](../producer/HEADLESS_EMPIRICAL_GATE_LEDGER.md).

## Scope

Claude Code/Codex Desktop to deterministic MP4 only. GUI, GUI-adjacent
execution, Palmier-native execution, and Palmier delivery are excluded from
this implementation round and its confidence assessment.

## Outcome

The local deterministic-overlay trust boundary materially improved, but no
release gate advanced and confidence has not crossed 95%. This is executable
mechanism evidence, not an integrated production controller, current-source OCI
qualification, complete quality-pass pilot, or field-reliability result.

## Counterexamples closed

- Descriptor-relative capture under one pinned source-root descriptor rejects
  intermediate-directory symlink swaps and source-root replacement.
- HTML/CSS closure discovery handles ordinary attributes, `srcset`, inline CSS,
  imports, and nested CSS. Remote, relative, base-rewritten, and noncanonical
  references fail closed.
- Canonical authority-scoped request JSON supplies exact overlay selection;
  request A plus a caller-forged entry B is rejected.
- Render intent, variables, assets, and caller-owned dictionaries are deeply
  frozen before per-overlay capture.
- Retained inputs are byte-exact canonical USTAR. Verification reconstructs the
  archive, so hidden PAX headers, alternate regular-file types, mode drift,
  ordering differences, malformed canonical JSON, and trailing bytes reject.
- The exact host build manifest is retained. Launch compares it with the loaded
  implementation before and after the isolated worker executes.
- Worker startup uses isolated, no-site, no-bytecode Python flags and ignores
  `PYTHONPATH`, user-site imports, and `sitecustomize`.
- Controller leases retain root and lock descriptors/inodes, bind PID and boot
  identity, revoke stale capabilities, and revoke authority in forked children.
- Warm result validation accepts runtime evidence only from exact containers
  durably proved `REMOVED` by the prior attempt-owned ledger.

## Newly disproved sequence

Direct startup resource reconciliation is unsafe. A delayed creator owned by a
prior controller can create its registered Docker name after a new controller
has observed temporary absence. A one-time absence proof does not establish
that the old creator can no longer act.

The existing reconciliation hook therefore remains quarantined. Safe startup
recovery requires split create/start, durable creator PID/start/boot identity,
durable Docker engine and container identity/labels, a fence check before
start, and a same-boot delayed-create fault test proving prior-creator
impossibility.

## Partial primitives, not admission authority

The new request artifact is canonical JSON and closes caller entry
substitution. The per-overlay source tar and build receipt are still created
after admission and are not one pre-admission artifact from which admission is
derived. A valid artifact B can also be paired with an attempt admitted for A,
because the render prepare/launch root does not yet reload the admission record.

The next trust boundary is one authority-scoped artifact published before
admission:

```text
request-artifacts/<artifactDigest>/
  request.json
  artifact-manifest.json
  render-build.json
  overlays/<selectionId>/render-input.tar
```

Admission must store the closed artifact digest and admitted build digest.
Prepare, resume, and launch must derive every locator and selection from the
admission record plus authority/attempt identity, never from loose caller
roots, paths, entries, or digests.

## Verification

- 234 focused non-GUI headless/render tests passed in 3.219 seconds; one
  environment-only host-loopback positive-control test was skipped.
- `ResourceWarning` was promoted to an error.
- A physical/AST audit covered 42 relevant production logic files and found
  zero violations of the 300-line file, 50-line function, four-parameter, and
  two-level logical-branch nesting limits.
- Python compilation and `git diff --check` passed.
- The test run first caught a missing `hashlib` import introduced during a
  line-count refactor. Restoring the import made all affected result-validation
  tests pass; the failed run was not hidden or counted.

Passing local tests do not promote G1 or G2b. The retained G2b specimen remains
explicitly nonqualifying and its frozen source closure is stale.

## Remaining blockers

- no production CLI/controller call site;
- no complete pre-admission request/source/build artifact;
- no admission-derived render prepare/resume/launch API;
- no admitted Docker daemon identity or safe startup replay;
- no trusted output/generation sealer;
- no `FENCE`, immutable generation commit, publisher, or `CURRENT`;
- no current-source independent OCI qualification;
- no full-minute fault campaign, six-project pilot, or qualifying field cohort.

## Go/no-go

**Go:** complete the pre-admission artifact and admission derivation, then
design and falsify the safe Docker creator/recovery protocol.

**No-go:** direct startup reconciliation, production publication, Palmier or
GUI work, and any claim that confidence has crossed 95%.
