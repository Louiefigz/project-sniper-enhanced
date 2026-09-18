# docs/ — reading order

## Start here (in this order)

1. [`PIPELINE.md`](PIPELINE.md) — the canonical doctrine: footage in → in-house render → **optional** Palmier mirror out. Wins every contradiction.
2. [`PRODUCER_README.md`](producer/PRODUCER_README.md) — the operator's manual: what to ask for and what you get back.
3. [`12_SHORT_LONG_EXECUTABLE_MATRIX.md`](producer/command-driven-editing/12_SHORT_LONG_EXECUTABLE_MATRIX.md) — current route/workflow behavior, incremental boundaries, and explicit blockers.
4. [`HANDOFF.md`](HANDOFF.md) — historical 2026-07-10 implementation snapshot; not current release evidence.

New to the whole app? Start at the repo root [`README.md`](../README.md) (setup + the easy **Claude Code desktop** path) and [`CLAUDE.md`](../CLAUDE.md) (architecture + read-order).

## Architecture / design records

- [`COMMAND_DRIVEN_EDITING_EXECUTION_PLAN.md`](producer/COMMAND_DRIVEN_EDITING_EXECUTION_PLAN.md) — modular next-step plan beginning with the audited reuse/extend/replace map, then cut-first/autopilot workflows, typed incremental edits, custom HyperFrames scenes, range captions, Palmier hybrid review, legacy regression gates, and bounded performance qualification.
- [`PRODUCER_PLAN.md`](producer/PRODUCER_PLAN.md) — full architecture design record.
- [`AUTO_EDIT_LANE.md`](producer/AUTO_EDIT_LANE.md) — the one-click Auto-edit lane: the detached worker + bounded plan-review/QC controller (how the GUI actually drives the CLI brain).
- [`HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md`](producer/HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md) — living decision record and confidence gates for the active Claude Code/Codex Desktop → deterministic-MP4 optimization; GUI and Palmier execution are excluded.
- [`HEADLESS_MP4_95_CONFIDENCE_EXECUTION_PLAN.md`](producer/HEADLESS_MP4_95_CONFIDENCE_EXECUTION_PLAN.md) — ordered, stop-gated implementation and evidence plan for the separate headless deterministic-MP4 lane; a durability composition root, strict render boundary, process-group runner, and resource ledger exist, but the production controller/publisher does not.
- [`HEADLESS_EMPIRICAL_GATE_LEDGER.md`](producer/HEADLESS_EMPIRICAL_GATE_LEDGER.md) — live record of executed G0–G11 evidence, blockers, and the independent-project census; unlike the plan, this file records only what has actually run.
- [`HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18.md`](audits/HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18.md) — frozen evidence snapshot behind the current headless go/no-go decisions.
- [`HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_3.md`](audits/HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_3.md) — third-wave architecture/QC/migration attack that corrected the implementation order and scoped-repair boundary.
- [`HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_4.md`](audits/HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_4.md) — fourth-wave economics/state/operations attack that paused live Palmier mutation and moved MP4 scoped repair first.
- [`HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_5.md`](audits/HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_5.md) — fifth-wave dependency/sequence/protocol attack that moved the hour-long target from renderer reuse to a bounded quality-pass loop and defined the no-promotion experiments.
- [`HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_6.md`](audits/HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_6.md) — sixth-wave context/typed-repair/renderer/experiment attack that put typed patches and critic-context measurement first and hardened the falsification controls.
- [`HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_7.md`](audits/HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_7.md) — seventh-wave minimal-path/authority/confidence attack that exposed non-private candidates, replaced subjective confidence weights with 95/95 gates, and pulled immutable generation publication ahead of any user-facing fast path.
- [`HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_8.md`](audits/HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_8.md) — eighth-wave implementation/toolchain/statistics attack that selected a separate headless API, removed initial GUI migration, and made the release-evidence contract executable.
- [`HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_9.md`](audits/HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_9.md) — ninth-wave code/contract/statistics attack that added resolved-plan authority, trusted sealing, recoverable async publication, comparator symmetry, and block-aware evidence rules.
- [`HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_10.md`](audits/HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_10.md) — tenth-wave integration/cancellation/Palmier attack that kept G2 narrow, falsified terminal-result recovery, exposed absent controller call sites, and selected one exact-delta Palmier arbiter.
- [`HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_11.md`](audits/HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_11.md) — eleventh-wave durability/result-closure audit that integrated admission and terminal recovery while preserving the no-publication boundary.
- [`HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_12.md`](audits/HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_12.md) — twelfth-wave recovery-order/render-proof/process-group audit that closed four concrete false accepts and retained current-source requalification as mandatory.
- [`HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_13.md`](audits/HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-18_ROUND_13.md) — thirteenth-wave lifecycle/resource audit that closed success-descendant and descriptor leaks and added a durable parent-owned Docker resource ledger.
- [`HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-19_ROUND_14.md`](audits/HEADLESS_EXECUTION_ADVERSARIAL_AUDIT_2026-07-19_ROUND_14.md) — current MP4-only implementation audit; closes request-entry, source-capture, archive, build, worker, and controller-lease attacks while disproving direct startup reconciliation.
- [`LOCAL_CODEX_AUDIT.md`](audits/LOCAL_CODEX_AUDIT.md) — local Codex/Sol capability + data-egress matrix.
- [`PRODUCER_EDGE_CASES.md`](producer/PRODUCER_EDGE_CASES.md) — error-handling scenarios.
- [`PRODUCER_MOTION_GRAPHICS_PLAN.md`](producer/PRODUCER_MOTION_GRAPHICS_PLAN.md) — MG-track design record (**historical**: the registered composition system shipped; this is not a claim that Ask Editor can author arbitrary one-off motion — the live map is `scripts/producer/CLAUDE.md`).
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
Creator doctrine (taught, not measured): [`adrian-per/`](studies/adrian-per/README.md) — Adrian Per's story spine, three-element hook, music-first tempo, paper edit, safe zones, post workflow, production system; study + 7 SOPs; every encoding proposal is NOT BUILT (2026-09-15)
