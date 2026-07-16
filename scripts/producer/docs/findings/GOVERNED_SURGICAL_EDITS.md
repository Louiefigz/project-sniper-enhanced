# Surgical in scope, full-doctrine in rigor

## Finding

An edit request such as “add one transition at 0:42” should be cheap to render,
but it is not exempt from the editorial system. Render scope and review rigor are
different controls:

- **Render scope** comes from plan fingerprints. A graphics-only change reuses
  the base, an audio-bus change uses the audio-only path, and a structural cut
  change rebuilds the base.
- **Mutation scope** is a deterministic allowlist chosen before the writer runs.
  The model may modify only fields belonging to the requested lanes.
- **Review rigor** remains complete. The writer reads the canonical Producer
  skill, Failure Ledger, and lane-specific doctrine. Then `plan_lint.py` and a
  fresh read-only critic independently approve the resulting plan.

These controls prevent two common failures: asking for a title card and getting
an opportunistic pacing rewrite, or receiving a mechanically valid transition
that violates the long-form motion grammar.

## Enforced sequence

1. Classify the operator request into explicit lanes without an LLM.
2. Snapshot the current plan and write a pending review marker.
3. Give either writer provider the same doctrine and field allowlist.
4. Diff top-level plan fields; rollback if anything outside the scope moved.
5. Run `plan_lint.py` before any render can start.
6. Launch a new read-only critic process for soft craft review.
7. Stamp the exact reviewed plan hash. The render route rejects pending or stale
   review evidence.

If the writer, lint, or critic fails, the original plan is restored. A process
crash leaves a pending marker, so a half-reviewed plan cannot render.

## When not to use this path

Do not route broad requests such as “make the whole video better” through the
surgical editor. They do not establish a bounded lane. Send them through the
full author → deterministic gates → independent critic → revision → render/QC
pipeline instead.
