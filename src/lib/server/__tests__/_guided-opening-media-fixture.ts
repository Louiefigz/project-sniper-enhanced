import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createGuidedProposalFixture, passingReadinessResult, readinessRequest } from "./_guided-proposal-fixture";
import { passingGateBundle } from "./_readiness-gate-stub";
import { appendTestCaptionProposal, longformProposal, TEST_CAPTION_INTENT } from "./_guided-longform-proposal";
import type { GuidedCaptionPreset } from "@/lib/producer/contracts/treatment-proposal-v5";
import type { SyntheticProgram } from "./_human-cut-fixture";
import { reviewGuidedTreatmentProposal } from "../guided-proposal-review";
import { readGuidedProposalReadiness } from "../guided-proposal-review-store";
import { parsePrepareGuidedOpening } from "@/lib/producer/contracts/guided-opening-v1";
import { acquireGuidedMutation, guidedOperation, finishGuidedOperation, writeGuidedObject } from "../guided-cut-v2-store";
import { writeGuidedOpeningMediaInput } from "../guided-opening-media-input";
import { captureOpeningAttemptStart } from "../opening-deadline";
import { guardGenerationAttempt } from "../generation-clock-watermark";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { createHumanCutIndex } from "../human-cut-acceptance-store";
import type { ProposalBrainInput } from "../guided-proposal-compiler";
import { claimGuidedOpeningExecution } from "../guided-opening-claim";
import { runClaimedOpeningMedia } from "../guided-opening-process";
import { reconcileClaimedOpeningUnderLease } from "../guided-opening-cleanup";
import { runOpeningCleanupCasFaults } from "./_guided-opening-cleanup-faults";
import { executeGuidedOpeningUnderLease } from "../guided-opening-execution";
import { readGuidedOpeningStatus } from "../guided-opening-status";
import { approveGuidedOpening } from "../guided-opening-approval";
import { requiredSemanticBeats } from "../guided-proposal-longform";

const RAW = "Show one own-screen catalog bar chart comparing the exact TEST transcript values 12 and 28.";
const RAW_LONGFORM = "Dress every strong transcript beat with one own-screen catalog cutaway; keep the cut, audio and color exactly as accepted.";

function numericChartProposal(input: ProposalBrainInput) {
  const evidence = JSON.parse(input.prompt.split("INPUT_DATA_JSON\n")[1]).evidence;
  if (![4, 5].includes(evidence.schemaVersion)) throw new Error("TEST numeric chart fixture requires explicit V4/V5 evidence");
  const catalog = evidence.catalog.find((row: { kind: string }) => row.kind === "chart-story");
  if (!catalog || catalog.canvas.join(",") !== "1920,1080") throw new Error("Actual measured landscape chart-story catalog is unavailable");
  const last = evidence.anchors.length - 1;
  if (last < 3) throw new Error("Synthetic numeric chart needs actual interior frame anchors");
  const spec = { type: "bars", data: "12,28", labels: ",", emphasize: 1, unit: "", accent: "#054BC9", exit: "hold" };
  const required = requiredSemanticBeats(evidence);
  if (required.length !== 1 || required[0].shape !== "comparison" || !required[0].compatibleKinds.includes("chart-story")) {
    throw new Error("TEST numeric comparison must derive exactly one chart-compatible comparison obligation");
  }
  const seams: Array<{ seamIndex: number }> = evidence.introSeams ?? [];
  return { schemaVersion: evidence.schemaVersion, summary: "TEST ONLY transcript-grounded chart timing/input fixture, not creative approval.",
    graphicsStyle: "catalog-first", graphicsStyleRationale: "TEST ONLY: the landscape catalog bar chart compares 12 and 28 from the explicit numeric transcript variant.",
    clauses: [{ start: 0, end: RAW.length, quote: RAW, disposition: "supported", rationale: "TEST transcript values, locked picture retained.", operationIndices: [0] }],
    beats: [{ startAnchor: 0, endAnchorExclusive: last, purpose: "opening", summary: "TEST whole short program", supportsBeatIndices: [] }],
    operations: [{ type: "catalog-graphic", clauseIndex: 0, beatIndex: 0, catalogKind: "chart-story",
      variables: Object.entries(spec).map(([name, value]) => ({ name, value })), grade: null, startAnchor: 1, endAnchorExclusive: last - 1,
      presentation: { schemaVersion: 1, anchor: "own-screen", placement: "full-canvas", compositeMode: "normal", baseTreatment: "preserve", rationale: "TEST full-canvas chart with source visible before/after." },
      reason: "TEST ONLY: compares the exact numeric transcript values through the private own-screen opening mechanics.",
      ...(evidence.schemaVersion === 5 ? { captions: null } : {}) }],
    beatDecisions: [{ beatId: required[0].beatId, decision: "graphic", kind: "chart-story", operationIndex: 0,
      alternativesConsidered: required[0].compatibleKinds.filter((kind) => kind !== "chart-story"),
      reason: "TEST ONLY: the explicit 12 versus 28 comparison needs a single side-by-side numeric chart.",
      selectionReason: "The catalog bar chart displays exactly the two values in this synthetic comparison." }],
    hookSeamDecisions: seams.map((seam) => ({ seamIndex: seam.seamIndex, decision: "clean-hook",
      reason: "TEST ONLY: a hard cut keeps the synthetic seam clean; no transition lane is exercised.", evidence: "TEST synthetic seam evidence" })),
    openingEndAnchor: last, continuityEndAnchor: last, audioPolicy: "preserve-full-program", colorPolicy: "preserve" };
}

/** Actual synthetic source+authority records; every editorial/transcript/human assertion is TEST ONLY. */
/** A blocked or non-executable readiness must stop the fixture with the retained gate findings, never a pointer parse error. */
function assertReadinessExecutable(dir: string, proposal: ReturnType<typeof readGuidedProposalReadiness>): void {
  if (proposal.pointer.treatmentDraftRevisionHash) return;
  const result = path.join(dir, "guided-v2-operations", String(proposal.readinessSubmission.idempotencyKey), "executions",
    String(proposal.readinessReceipt.executionId), "result.json");
  let detail = "no retained operation result";
  try {
    const row = JSON.parse(readFileSync(result, "utf8")) as { state?: unknown; error?: unknown; deterministicGates?: { findings?: unknown } };
    const findings = Array.isArray(row.deterministicGates?.findings) ? row.deterministicGates.findings.map(String) : [];
    detail = `${String(row.state)}${row.error ? `: ${String(row.error)}` : ""}${findings.length ? ` — ${findings.join(" | ")}` : ""}`;
  } catch (error) { detail += ` (${String(error).slice(0, 200)})`; }
  throw new Error(`TEST fixture: readiness produced no executable treatment draft (${detail}); see ${result}`);
}

interface OpeningFixtureOptions { workspace?: string; runWorker?: boolean; cleanupCasFaults?: boolean;
  sourceCanvas?: "160x90" | "1920x1080"; approveTestOnly?: boolean; program?: SyntheticProgram; realGates?: boolean;
  captionPreset?: GuidedCaptionPreset }

/** TEST source/readiness only, leaving the actual launch unstarted for UI integration.
 * This contains explicit TEST editorial attestations; never use with creator footage. */
export async function createOpeningReadyFixture(options: OpeningFixtureOptions = {}) {
  const graphicsIntent = options.program ? RAW_LONGFORM : RAW;
  const rawIntent = graphicsIntent + (options.captionPreset ? TEST_CAPTION_INTENT : "");
  const fixture = await createGuidedProposalFixture({ workspace: options.workspace, rawIntent,
    output: (input) => {
      const proposal = options.program ? longformProposal(input, graphicsIntent) : numericChartProposal(input);
      return options.captionPreset ? appendTestCaptionProposal(proposal, graphicsIntent, options.captionPreset) : proposal;
    },
    sourceCanvas: options.sourceCanvas ?? "1920x1080", retainFailure: true, program: options.program,
    ...(options.program ? {} : { transcriptVariant: "numeric-comparison" as const }),
    ...(options.program && options.captionPreset ? { captionIntent: "auto" as const } : {}) });
  // The default 3-second program can never pass the real deterministic bundle; unit tests stub it. A synthetic
  // long-form program runs the REAL gates so the opening worker only ever receives a lintable draft.
  const realGates = options.realGates ?? options.program !== undefined;
  await reviewGuidedTreatmentProposal({ dir: fixture.ctx.dir, submission: readinessRequest(fixture.ctx.dir) },
    { critic: async (input) => passingReadinessResult(input), ...(realGates ? {} : { gates: passingGateBundle() }) });
  const proposal = readGuidedProposalReadiness(fixture.ctx.dir);
  assertReadinessExecutable(fixture.ctx.dir, proposal);
  return { fixture, proposal };
}

export async function createOpeningMediaFixture(options: OpeningFixtureOptions = {}) {
  if (options.cleanupCasFaults && !options.runWorker) throw new Error("TEST cleanup faults require the actual owned worker");
  const { fixture, proposal } = await createOpeningReadyFixture(options);
  const submission = parsePrepareGuidedOpening({ schemaVersion: 1, operation: "prepare-guided-opening", idempotencyKey: randomUUID(),
    expectedToken: proposal.job.token, expectedJournalHash: proposal.sha256, proposalReadinessHash: proposal.readinessHash,
    treatmentDraftRevisionHash: proposal.pointer.treatmentDraftRevisionHash });
  const captured = captureOpeningAttemptStart();
  const lease = await acquireGuidedMutation(fixture.ctx.dir, { workflowVersion: 2, action: "prepare-guided-opening", expectedStatus: "treatment_admitted",
    expectedToken: proposal.job.token, expectedJournalHash: proposal.sha256 });
  let result: Awaited<ReturnType<typeof fixtureInputPhase>>;
  try { result = await fixtureInputPhase({ fixture, proposal, submission, captured, lease }, options); }
  finally { lease.release(); }
  // TEST-only approval acquires its own guided lease AFTER the opening lease is released, exactly like a browser POST would.
  if (options.runWorker && options.approveTestOnly) await testOnlyApproval(fixture.ctx.dir, result.operation.execution);
  return result;
}

async function fixtureInputPhase(input: { fixture: Awaited<ReturnType<typeof createGuidedProposalFixture>>;
  proposal: ReturnType<typeof readGuidedProposalReadiness>; submission: ReturnType<typeof parsePrepareGuidedOpening>;
  captured: ReturnType<typeof captureOpeningAttemptStart>; lease: Awaited<ReturnType<typeof acquireGuidedMutation>> },
  options: { runWorker?: boolean; cleanupCasFaults?: boolean }) {
  const { fixture, proposal, submission, captured, lease } = input;
  const runWorker = options.runWorker ?? false;
  const operation = guidedOperation({ dir: fixture.ctx.dir, id: submission.idempotencyKey, submission, receivedAt: captured.receivedAt });
  const guard = cutPreviewLeaseGuard(fixture.ctx.dir, lease), origin = { clockHash: proposal.clock.hash, startedAt: proposal.generationStartedAt };
  const budget = guardGenerationAttempt({ dir: fixture.ctx.dir, origin, executionId: operation.executionId, guard }, captured.start(origin));
  try {
    createHumanCutIndex(path.join(operation.execution, "budget-admission.json"), budget.admission);
    const invocation = writeGuidedOpeningMediaInput({ proposal, operation, lease, remainingMs: budget.remainingMs });
    const descriptor = { scope: "TEST-ONLY-input-and-media-worker-not-opening-approval", root: fixture.root, dir: fixture.ctx.dir,
      inputPath: invocation.inputPath, inputSha256: invocation.inputSha256, executionInputHash: invocation.input.executionInputHash,
      outputDirectory: path.join(operation.execution, "media-output"), sourceKind: "actual-testsrc2-and-tone-impulses",
      transcriptKind: "TEST-only-text-not-spoken-audio", models: "TEST-only-stubs", genuineHumanAcceptance: false,
      openingApproved: false, deliveryApproved: false };
    createHumanCutIndex(path.join(fixture.root, "OPENING-TEST-ONLY.json"), descriptor);
    if (runWorker) await actualWorker({ proposal, operation, invocation, lease, remainingMs: budget.remainingMs,
      budgetAdmissionHash: writeGuidedObject(fixture.ctx.dir, budget.admission) }, options.cleanupCasFaults ?? false);
    guard(); budget.remainingMs();
    finishGuidedOperation(operation, { state: runWorker ? "test-worker-exited-not-promoted" : "test-input-only-not-rendered",
      generationStartedAt: proposal.generationStartedAt, budget: budget.observe(), openingApproved: false, deliveryApproved: false });
    return { fixture, descriptor, invocation, operation };
  } catch (error) {
    createHumanCutIndex(path.join(operation.execution, "controller-failure.json"), { error: String(error),
      ...(error instanceof CutPreviewProcessError ? error.details : {}), fixtureRoot: fixture.root, openingApproved: false, deliveryApproved: false });
    throw error;
  }
}

type OwnedInput = Parameters<typeof claimGuidedOpeningExecution>[0];

/** TEST ONLY: a synthetic attestation exercises the exact approval transaction; it is NOT genuine human acceptance. */
async function testOnlyApproval(dir: string, execution: string) {
  const before = readGuidedOpeningStatus(dir);
  if (before.state !== "ready-for-review") throw new Error(`TEST approval needs ready-for-review, got ${before.state}`);
  const started = performance.now();
  const result = await approveGuidedOpening({ dir, submission: { schemaVersion: 1, operation: "approve-guided-opening", idempotencyKey: randomUUID(),
    expectedToken: before.journal.token, expectedJournalHash: before.journal.sha256, selectionHash: before.selectionHash,
    coreMediaSha256: before.media.core.mediaSha256, reviewMediaSha256: before.media.review.mediaSha256,
    attestation: { watchedOpening: true, watchedBodyTransition: true, listened: true, approvesOpening: true, understandsBodyPending: true } } });
  const after = readGuidedOpeningStatus(dir);
  if (after.state !== "ready-for-review" || !after.openingApproved || after.approval?.approvalHash !== result.approvalHash) throw new Error("TEST approval did not verify as the current approved selection");
  createHumanCutIndex(path.join(execution, "test-approval-result.json"), { scope: "TEST-ONLY-synthetic-attestation-not-genuine-human-acceptance",
    genuineHumanAcceptance: false, approvalHash: result.approvalHash, approvedAt: result.approvedAt, approvalElapsedMs: performance.now() - started,
    statusState: after.state, openingApproved: after.openingApproved, bodyGenerated: false, deliveryApproved: false });
}

async function actualWorker(input: OwnedInput, cleanupCasFaults: boolean) {
  let completed = false;
  const { process, cleanup, verified, selection, status, selectionElapsedMs } = await executeGuidedOpeningUnderLease(input, cleanupCasFaults ? {
    run: async (request) => { const result = await runClaimedOpeningMedia(request); completed = result.receipt.status === "complete"; return result; },
    cleanup: (request) => completed ? runOpeningCleanupCasFaults(request) : reconcileClaimedOpeningUnderLease(request),
  } : {});
  createHumanCutIndex(path.join(input.operation.execution, "test-production-worker-result.json"), {
    scope: "actual-production-process-and-cleanup-not-media-selection-or-approval", processReceiptSha256: process.receiptSha256,
    cleanupHash: cleanup.cleanupHash, openingApproved: false, deliveryApproved: false });
  createHumanCutIndex(path.join(input.operation.execution, "test-production-readback-result.json"), {
    scope: "actual-production-owned-current-media-readback-not-playback-selection-or-approval", receiptSha256: verified.receipt.sha256,
    outputSha256: verified.output.sha256, mediaResultSha256: verified.selected.completion.receiptSha256,
    cleanupHash: cleanup.cleanupHash, openingApproved: false, deliveryApproved: false });
  createHumanCutIndex(path.join(input.operation.execution, "test-production-selection-result.json"), {
    scope: "actual-production-mechanical-playback-selection-not-human-review-or-approval", selectionHash: selection.selectionHash,
    selectionQualifiedAt: selection.fact.selectionQualifiedAt, selectionElapsedMs,
    media: { core: { mediaSha256: status.media.core.mediaSha256, sizeBytes: status.media.core.sizeBytes, videoFrames: status.media.core.videoFrames, audioSamples: status.media.core.audioSamples },
      review: { mediaSha256: status.media.review.mediaSha256, sizeBytes: status.media.review.sizeBytes, videoFrames: status.media.review.videoFrames, audioSamples: status.media.review.audioSamples } },
    statusState: status.state, sourceFreshness: status.sourceFreshness, openingApproved: false, deliveryApproved: false });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const workspace = process.argv.slice(2).find((value) => !value.startsWith("--"));
  const programArg = process.argv.find((value) => value.startsWith("--program="));
  createOpeningMediaFixture({ workspace, runWorker: process.argv.includes("--run-worker"), cleanupCasFaults: process.argv.includes("--cleanup-cas-faults"),
    approveTestOnly: process.argv.includes("--approve-test-only"), ...(programArg ? { program: programArg.slice("--program=".length) as SyntheticProgram } : {}) })
    .then(({ descriptor }) => process.stdout.write(`${JSON.stringify(descriptor)}\n`))
    .catch((error) => { process.stderr.write(`${JSON.stringify({ error: String(error),
      ...(error instanceof CutPreviewProcessError ? { ...error.details,
        stdout: error.details.stdout.slice(0, 262144), stderr: error.details.stderr.slice(0, 262144) } : {}) })}\n`); process.exitCode = 1; });
}
