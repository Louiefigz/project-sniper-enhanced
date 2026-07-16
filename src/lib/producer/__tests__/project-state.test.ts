import assert from "node:assert/strict";
import {
  canResumeAutoEdit,
  canOpenProject,
  elapsedRunLabel,
  nextProjectAction,
  projectPhase,
  projectPhaseCopy,
  projectCardSummary,
  projectPrimaryActionLabel,
  requestedEditLabel,
  runPhaseRemainingLabel,
  streamProgressMessage,
  type StageFlags,
} from "../project-state";

function stages(bits: string): StageFlags {
  const values = bits.split("").map((value) => value === "1");
  return {
    ingested: values[0],
    transcribed: values[1],
    plan: values[2],
    base: values[3],
    final: values[4],
  };
}

assert.equal(projectPhase(stages("00000")), "needs_ingest");
assert.equal(projectPhase(stages("10000")), "needs_transcript");
assert.equal(projectPhase(stages("11000")), "ready_to_generate");
assert.equal(projectPhase(stages("11100")), "plan_ready");
assert.equal(projectPhase(stages("11110")), "final_pending");
assert.equal(projectPhase(stages("11111")), "complete");
assert.equal(projectPhase(stages("01000")), "inconsistent");
assert.equal(projectPhase(stages("11010")), "inconsistent");

assert.equal(nextProjectAction(stages("11000")), "generate");
assert.equal(nextProjectAction(stages("11100")), "render_plan");
assert.equal(nextProjectAction(stages("11110")), "assemble");
assert.equal(nextProjectAction(stages("11111")), "open");
assert.equal(canOpenProject(stages("11100")), true);
assert.equal(canOpenProject(stages("11110")), true);
assert.equal(canOpenProject(stages("11111")), true);
assert.equal(projectPrimaryActionLabel(stages("00000")), "Prepare media");
assert.equal(projectPrimaryActionLabel(stages("10000")), "Analyze speech");
assert.equal(projectPrimaryActionLabel(stages("11000")), "Create first edit");
assert.equal(projectPrimaryActionLabel(stages("11100")), "Start render & QC");
assert.equal(projectPrimaryActionLabel(stages("11110")), "Resume review & QC");
assert.equal(projectPrimaryActionLabel(stages("11111")), "Open editor");
assert.match(projectCardSummary(stages("11110")).available, /saved edit timeline and base preview/);
assert.equal(projectCardSummary(stages("11110")).working, "Nothing is running in the background.");
assert.match(projectCardSummary(stages("11110")).next, /Resume review & QC/);

assert.equal(
  requestedEditLabel({ mode: "longform", scope: "produced", lanes: {} }),
  "Long (16:9) · Produced edit",
);

const running = projectPhaseCopy(stages("11000"), {
  kind: "auto_edit",
  status: "running",
  phase: "authoring",
  startedAt: "2026-07-12T10:00:00.000Z",
  updatedAt: "2026-07-12T10:01:00.000Z",
  message: "Codex is authoring the edit plan.",
  events: [],
});
assert.equal(running.label, "Generating edit plan");
assert.equal(running.tone, "running");
const runningSummary = projectCardSummary(stages("11100"), {
  kind: "auto_edit",
  status: "running",
  phase: "quality_check",
  startedAt: "2026-07-12T10:00:00.000Z",
  updatedAt: "2026-07-12T10:01:00.000Z",
  message: "Audit B round 1.",
  events: [],
});
assert.match(runningSummary.working, /reviewing the rendered video/);
assert.match(runningSummary.next, /approved|corrects it/);
assert.match(runningSummary.safe, /start another project/);
assert.match(runningSummary.safe, /Stop and keep the checkpoint/);
assert.equal(elapsedRunLabel("2026-07-12T10:00:00.000Z", Date.parse("2026-07-12T10:02:03.000Z")), "2m 3s elapsed");
assert.equal(
  streamProgressMessage({ event: "heartbeat", message: "Plan critic still reviewing · 6m elapsed" }),
  "Plan critic still reviewing · 6m elapsed",
);
assert.equal(
  streamProgressMessage({ event: "authoring_done", stage: "cut" }),
  "Transcript cut authored · independent cut review is next",
);
assert.equal(
  streamProgressMessage({ event: "authoring_done", stage: "visual" }),
  "Visual edit plan authored · deterministic gates and planning review are next",
);
assert.equal(
  streamProgressMessage({
    event: "authoring_started", stage: "visual", provider: "legacy", model: "sonnet",
  }),
  "Claude Code · sonnet is authoring the governed visual plan",
);
assert.equal(
  streamProgressMessage({ event: "plan_refit_receipt", remapped: 3, dropped: 1 }),
  "Cut-timebase receipt · 3 timed elements remapped; 1 element was removed because the new cut removed their content.",
);
assert.equal(
  streamProgressMessage({
    event: "plan_refit_receipt", remapped: 3, dropped: 1, alreadyApplied: true,
  }),
  "Existing cut-timebase receipt · no second remap was applied · 3 timed elements remapped; 1 element was removed when that cut was applied.",
);
assert.equal(
  streamProgressMessage({ event: "intent_capability", message: "B-roll is off for this Produced edit." }),
  "B-roll is off for this Produced edit.",
);
assert.equal(streamProgressMessage({ event: "phase", phase: "assemble" }), "Rendering base and final video");
assert.equal(streamProgressMessage({ event: "authoring_item.completed" }), null);
assert.equal(
  streamProgressMessage({
    event: "palmier_primary_selected",
    limitations: [{ lane: "graphics" }, { lane: "transitions" }],
  }),
  "Palmier-native build selected · editable timeline · declared limits: graphics, transitions",
);
assert.equal(
  streamProgressMessage({
    event: "palmier_native_progress", status: "operation_applied",
    tool: "add_texts", index: 2, total: 6,
  }),
  "Palmier applied add_texts · 2 of 6",
);
assert.equal(
  streamProgressMessage({
    event: "candidate_qc_progress", message: "Reviewing the exact editable candidate.",
  }),
  "Reviewing the exact editable candidate.",
);
assert.equal(
  streamProgressMessage({
    event: "outputs", approved: true, mode: "palmier-native-initial",
  }),
  "Approved editable Palmier timeline is ready",
);
assert.match(runPhaseRemainingLabel("planning_review"), /render a candidate/);
assert.match(runPhaseRemainingLabel("quality_check"), /approve and promote/);

assert.equal(
  streamProgressMessage({
    event: "cut_review_started", round: 1, maxRounds: 6,
    requiredCleanReviews: 2,
  }),
  "Transcript cut review 1 of 6 started · 2 clean independent reviews of the same cut are required.",
);
assert.equal(
  streamProgressMessage({
    event: "cut_review_completed", round: 1, maxRounds: 6,
    requiredCleanReviews: 2, verdict: "pass", materialIssues: 0,
    ms: 108_000,
  }),
  "Transcript cut review 1 of 6 found no material issues · 1m 48s elapsed · checking cut approval.",
);

assert.equal(
  streamProgressMessage({
    event: "planning_review_started",
    planningRound: 1,
    planningRoundsRequired: 2,
  }),
  "Planning review 1 of 2 started · fresh editor review is running; revision or render follows.",
);
assert.equal(
  streamProgressMessage({ event: "planning_gate_bundle", ok: true }),
  "Deterministic planning gates passed · fresh editor review remains.",
);
assert.equal(
  streamProgressMessage({ event: "planning_gate_bundle", ok: false, errors: [{ gate: "claims_contract" }] }),
  "Deterministic planning gates failed with 1 issue · revision and a full gate rerun remain.",
);
assert.equal(
  streamProgressMessage({
    event: "planning_review_completed",
    planningRound: 1,
    planningRoundsRequired: 2,
    review: { verdict: "revise", materialIssues: [{ code: "PACING" }] },
  }),
  "Planning review 1 of 2 found 1 issue · revision and another full review remain.",
);
assert.equal(
  streamProgressMessage({ event: "candidate_ready", qcRound: 1, qcRoundsMax: 3 }),
  "Candidate 1 of 3 rendered · Audit B, composition review, and editorial review remain.",
);
assert.equal(
  streamProgressMessage({
    event: "rendered_review_started",
    lens: "composition",
    qcRound: 1,
    qcRoundsMax: 3,
  }),
  "Candidate 1 of 3 · composition review started; approval waits for both visual reviews.",
);
assert.equal(
  streamProgressMessage({
    event: "rendered_review_completed",
    lens: "composition",
    qcRound: 1,
    qcRoundsMax: 3,
    verdict: "pass",
  }),
  "Candidate 1 of 3 · composition review passed; aggregate QC waits for both visual reviews.",
);
assert.equal(
  streamProgressMessage({
    event: "rendered_review_completed",
    lens: "editorial",
    qcRound: 1,
    qcRoundsMax: 3,
    verdict: "revise",
    materialIssues: [{ code: "CARD_SCALE" }, { code: "TIMING" }],
  }),
  "Candidate 1 of 3 · editorial review found 2 issues; repair or a stop decision follows.",
);
assert.equal(
  streamProgressMessage({ event: "repair_started", qcRound: 1, qcRoundsMax: 3, findingCount: 2 }),
  "Candidate 1 of 3 repair started for 2 findings · plan review, gates, re-render, and QC remain.",
);
assert.equal(
  streamProgressMessage({ event: "repair_completed", qcRound: 1, qcRoundsMax: 3 }),
  "Candidate 1 of 3 repair complete · re-reviewing the plan before a fresh candidate render.",
);
assert.equal(
  streamProgressMessage({ event: "candidate_approved", qcRound: 2, qcRoundsMax: 3 }),
  "Candidate 2 of 3 passed all QC · approval is recorded; final-file promotion remains.",
);
assert.equal(
  streamProgressMessage({ event: "candidate_promoted", qcRound: 2, qcRoundsMax: 3 }),
  "Candidate 2 of 3 promoted · the approved final video is ready.",
);
assert.equal(
  streamProgressMessage({ event: "max_rounds_exhausted", stage: "qc", findingCount: 3 }),
  "Maximum QC attempts reached with 3 unresolved findings · no unapproved candidate was promoted.",
);
assert.equal(
  streamProgressMessage({ event: "outputs", approved: true }),
  "Approved final video is ready",
);

const failedRun = {
  kind: "render" as const,
  status: "failed" as const,
  phase: "rendering" as const,
  startedAt: "2026-07-12T10:00:00.000Z",
  updatedAt: "2026-07-12T10:02:00.000Z",
  message: "FFmpeg stopped.",
  events: [],
};
assert.equal(projectPhaseCopy(stages("11100"), failedRun).label, "Render failed");
assert.equal(projectPhaseCopy(stages("11111"), failedRun).label, "Finished · QC needs attention");
const failedAutoEditRun = { ...failedRun, kind: "auto_edit" as const };
assert.equal(canResumeAutoEdit(failedAutoEditRun), true);
assert.equal(projectPrimaryActionLabel(stages("11000"), failedAutoEditRun), "Resume edit");
assert.match(projectPhaseCopy(stages("11000"), failedAutoEditRun).detail, /last safe checkpoint/);

const interruptedRun = {
  ...failedRun,
  kind: "auto_edit" as const,
  status: "interrupted" as const,
  phase: "authoring" as const,
  message: "The local server stopped before the edit completed.",
};
const interruptedCopy = projectPhaseCopy(stages("11000"), interruptedRun);
assert.equal(interruptedCopy.label, "Edit interrupted");
assert.equal(interruptedCopy.tone, "error");
assert.match(interruptedCopy.detail, /Resume Edit/);
assert.equal(canResumeAutoEdit(interruptedRun), true);
assert.equal(canResumeAutoEdit(failedRun), false);

console.log("project-state.test.ts: all assertions passed");
