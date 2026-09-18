# Approve the resolved plan, not the input plan

## Finding

An executor that deterministically refits, measures, or recomposes a plan is also a plan transformer. Linting or approving the input file does not approve the bytes that actually controlled the render.

Project Sniper currently has three concrete examples:

1. [`render.py`](../../render.py) runs its gate before `recompose_stage`, but recompose mutates the in-memory plan. `apply_recompose()` replaces `plan.punchIns`, and face measurement stamps `faceBBoxNorm` plus `faceBBoxSource` into graphics entries.
2. The renderer copies the original input file to `edit_plan.json` before execution, while `base_plan.json`, fingerprints, and provenance are generated from the later in-memory plan. One run can therefore retain two different apparent plan authorities.
3. [`assemble.py`](../../assemble.py) verifies template usage before `ensure_base()`, but base recovery can refit a cut-timebase plan and replace the plan file afterward. The subsequent write of `base_plan.json` can also use the stale parent-process `plan` object instead of the refitted bytes.

There is a separate receipt-order problem: `render_report.json` is flushed before Audit B runs. The returned Python object may contain `audit`, but the on-disk report does not prove terminal audit success.

## Safer contract

Introduce a deterministic `ResolvedPlanV1` stage:

```text
operator/candidate plan
  -> normalize IDs and schema
  -> refit cut timebase
  -> measure/stamp face geometry
  -> apply recompose and other deterministic expansions
  -> canonicalize
  -> lint + template approval + critics
  -> freeze ResolvedPlanV1 digest
  -> render/assemble with no semantic mutation permitted
```

The renderer and assembler must compare the plan digest before and after execution. A changed digest is not a warning and cannot inherit the old approval: it is a new candidate that returns through governance.

The final generation should bind a terminal audit receipt produced after full decode and Audit B. Treat the current pre-audit `render_report.json` as diagnostic until its write is moved after Audit B and flushed.

## Why this matters

Without this boundary, all of the following can be true at once:

- the input plan passed lint;
- the template-history approval matched that input;
- the renderer used different in-memory geometry or timing;
- `edit_plan.json` shows the old bytes;
- `base_plan.json` or provenance reflects some of the new bytes;
- the final report on disk omits the audit result.

That is not merely stale metadata. It breaks cache validity, request-effect proof, exact parent comparison, restart safety, and any claim that two experiment arms rendered the same approved candidate.

## When not to add a resolved-plan stage

Do not add it for a genuinely pure executor whose input is already canonical and whose before/after digest test proves no mutation across every supported path. In that case, keep the executor pure and retain the digest assertion. Do not create another schema layer solely to rename unchanged bytes.

## Tests that make the rule executable

- A cut change requiring refit produces one `ResolvedPlanV1`; approval and render bind its exact digest.
- A rail missing measured face geometry resolves before approval, not during render.
- Any downstream recompose/refit attempt fails before media publication.
- `edit_plan.json`, `base_plan.json`, fingerprints, provenance, approval, and render receipt all bind the same resolved-plan digest.
- The terminal audit receipt is absent on an Audit B crash and present only after checked full decode plus Audit B success.
