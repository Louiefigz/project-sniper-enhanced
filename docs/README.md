# docs/ — reading order

## Start here (in this order)

1. [`PIPELINE.md`](PIPELINE.md) — the canonical doctrine: footage in → in-house render → **optional** Palmier mirror out. Wins every contradiction.
2. [`PRODUCER_README.md`](producer/PRODUCER_README.md) — the operator's manual: what to ask for and what you get back.
3. [`HANDOFF.md`](HANDOFF.md) — current state: the verified `/producer` loop, test invocation, known gaps.

New to the whole app? Start at the repo root [`README.md`](../README.md) (setup + the easy **Claude Code desktop** path) and [`CLAUDE.md`](../CLAUDE.md) (architecture + read-order).

## Architecture / design records

- [`PRODUCER_PLAN.md`](producer/PRODUCER_PLAN.md) — full architecture design record.
- [`AUTO_EDIT_LANE.md`](producer/AUTO_EDIT_LANE.md) — the one-click Auto-edit lane: the detached worker + bounded plan-review/QC controller (how the GUI actually drives the CLI brain).
- [`LOCAL_CODEX_AUDIT.md`](audits/LOCAL_CODEX_AUDIT.md) — local Codex/Sol capability + data-egress matrix.
- [`PRODUCER_EDGE_CASES.md`](producer/PRODUCER_EDGE_CASES.md) — error-handling scenarios.
- [`PRODUCER_MOTION_GRAPHICS_PLAN.md`](producer/PRODUCER_MOTION_GRAPHICS_PLAN.md) — MG-track design record (**historical**: header still says DRAFT, but the MG system shipped — the live map is `scripts/producer/CLAUDE.md`).
- GUI performance: [`GUI_UX_AUDIT.md`](audits/GUI_UX_AUDIT.md) · [`GUI_LATENCY_TEARDOWN.md`](audits/GUI_LATENCY_TEARDOWN.md) · [`PRODUCER_LATENCY_OPTIMIZATION_PUNCHLIST.md`](producer/PRODUCER_LATENCY_OPTIMIZATION_PUNCHLIST.md).
- Defect ledger + QC brief: `scripts/producer/docs/findings/` (`FAILURE_LEDGER.md`, `QC_CHECKLIST.md`).

## Palmier Pro — the optional NLE mirror (read in this order)

Each Palmier doc carries a **STATUS banner** at its top saying which bucket it's in.

1. [`PALMIER_MCP_SETUP.md`](palmier/PALMIER_MCP_SETUP.md) — connect Palmier (open the app → local MCP at `127.0.0.1:19789`; Claude Desktop bridge).
2. **What's wired today:** [`PALMIER_MIRROR_HANDOFF.md`](palmier/PALMIER_MIRROR_HANDOFF.md) (impl map) + [`PALMIER_PARITY_CONTRACT.md`](palmier/PALMIER_PARITY_CONTRACT.md) (the one-way exact-master mirror contract).
3. **Live status:** [`PALMIER_CANONICAL_IMPLEMENTATION_STATE.md`](palmier/PALMIER_CANONICAL_IMPLEMENTATION_STATE.md) + [`PALMIER_LIVE_CHECKPOINTS.md`](palmier/PALMIER_LIVE_CHECKPOINTS.md).
4. **Target direction (aspirational — not all wired):** [`PALMIER_CANONICAL_WORKFLOW.md`](palmier/PALMIER_CANONICAL_WORKFLOW.md).
5. **Proposed / work plans:** [`PALMIER_LIVE_BUILD_SPEC.md`](palmier/PALMIER_LIVE_BUILD_SPEC.md) · [`PALMIER_AUTHORITY_HARDENING_BUILD_BRIEF.md`](palmier/PALMIER_AUTHORITY_HARDENING_BUILD_BRIEF.md) · [`PALMIER_SKILLED_AGENT_ORCHESTRATION_HANDOFF.md`](palmier/PALMIER_SKILLED_AGENT_ORCHESTRATION_HANDOFF.md).
6. **Historical:** [`PALMIER_PHASE2_SPEC.md`](palmier/PALMIER_PHASE2_SPEC.md) — superseded by the parity + mirror-handoff contracts.

## Reference studies (read on demand — cited by gates/configs)

Styles: [`CALEB_STYLE.md`](studies/CALEB_STYLE.md) · `JADEN_STYLE.md` (the copy the **code loads** is `scripts/producer/docs/findings/JADEN_STYLE.md`; the one here is a shorter duplicate) · [`ANGELA_STYLE.md`](studies/ANGELA_STYLE.md) · [`NATEHERK_STUDY.md`](studies/NATEHERK_STUDY.md) + [`NATEHERK_CARDS.md`](studies/NATEHERK_CARDS.md) · [`REFERENCE_STYLE_STUDY.md`](studies/REFERENCE_STYLE_STUDY.md)
Grammar/pacing: [`MEASURED_EDIT_GRAMMAR.md`](studies/MEASURED_EDIT_GRAMMAR.md) · [`MOTION_GRAMMAR_STUDY.md`](studies/MOTION_GRAMMAR_STUDY.md) · [`PACING_RHYTHM_STUDY.md`](studies/PACING_RHYTHM_STUDY.md) · [`PRODUCTION_ENVELOPE_STUDY.md`](studies/PRODUCTION_ENVELOPE_STUDY.md) · [`LONGFORM_VISUAL_STUDY.md`](studies/LONGFORM_VISUAL_STUDY.md)
Edit decisions/lessons: [`EDIT_DECISION_STUDY.md`](studies/EDIT_DECISION_STUDY.md) · [`EDITCRAFT_LESSONS.md`](studies/EDITCRAFT_LESSONS.md) · [`SHORTFORM_LESSONS.md`](studies/SHORTFORM_LESSONS.md) · [`INTRO_MACHINE_VS_PRO_AUDIT.md`](audits/INTRO_MACHINE_VS_PRO_AUDIT.md)
