/** Leased local guided assembly. This entry creates no editorial or publication approval. */
import path from "node:path";
import { randomUUID } from "node:crypto";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { exactKeys, objectValue, sha256 } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { acquireGuidedMutation } from "./guided-cut-v2-store";
import { createHumanCutIndex, humanCutDirectory, observeHumanCutJob } from "./human-cut-acceptance-store";
import { readGuidedTreatmentProposal } from "./guided-proposal-store";
import { writeGuidedNativeProject } from "./guided-native-project-store";
import type { GuidedNativeVisualPlan } from "./guided-native-project";
import { guardGenerationAttempt } from "./generation-clock-watermark";
import { GENERATION_DEADLINE_POLICY } from "./generation-deadline";
import { deadlineTimestamp, finiteDeadlineClock, startGenerationAttempt, SYSTEM_DEADLINE_CLOCKS,
  type DeadlineClocks, type GenerationClockOrigin } from "./generation-attempt-clock";

const BUILD_MS = 120_000;
interface Dependencies {
  canonicalDir: typeof canonicalProducerDir; proposal: typeof readGuidedTreatmentProposal;
  observeJob: typeof observeHumanCutJob; acquire: typeof acquireGuidedMutation;
  leaseGuard: typeof cutPreviewLeaseGuard; write: typeof writeGuidedNativeProject; clocks: DeadlineClocks;
}
const DEFAULTS: Dependencies = { canonicalDir: canonicalProducerDir, proposal: readGuidedTreatmentProposal,
  observeJob: observeHumanCutJob, acquire: acquireGuidedMutation, leaseGuard: cutPreviewLeaseGuard,
  write: writeGuidedNativeProject, clocks: SYSTEM_DEADLINE_CLOCKS };

/** Request transport cannot select providers, dependencies, budgets, destinations or approvals. */
export function parseGuidedNativeVisualPlan(value: unknown): GuidedNativeVisualPlan {
  const row = objectValue(value, "guided visual plan");
  exactKeys(row, ["candidateHash", "project", "assetResolutions"], ["candidateHash", "project"], "guided visual plan");
  sha256(row.candidateHash, "guided candidate hash"); objectValue(row.project, "guided native project");
  if (row.assetResolutions !== undefined && (!Array.isArray(row.assetResolutions) || row.assetResolutions.length > 128)) throw new Error("Guided asset resolutions need a bounded list");
  return row as unknown as GuidedNativeVisualPlan;
}

function admission(origin: GenerationClockOrigin, wall: number) {
  const began = deadlineTimestamp(origin.startedAt), received = finiteDeadlineClock(wall);
  const deadline = began + GENERATION_DEADLINE_POLICY.requestMs;
  if (!Number.isSafeInteger(received) || received < began) throw new Error("Guided native build clock precedes its original request");
  return { schemaVersion: 1, kind: "guided-native-build-deadline-admission", clockHash: sha256(origin.clockHash, "clock hash"),
    generationStartedAt: origin.startedAt, observedAt: new Date(received).toISOString(),
    requestDeadlineAt: new Date(deadline).toISOString(), attemptMs: BUILD_MS,
    admitted: deadline - received >= BUILD_MS, excludedUserWaitMs: null };
}

function capturedStart(clocks: DeadlineClocks) {
  const wall = finiteDeadlineClock(clocks.wall()), mono = finiteDeadlineClock(clocks.monotonic());
  let firstWall = true, firstMono = true;
  return { receivedAt: new Date(wall).toISOString(), start: (origin: GenerationClockOrigin) => startGenerationAttempt({
    origin, admit: admission, attemptMs: BUILD_MS, kind: "guided-native-build-deadline-observation" }, {
    wall: () => { if (firstWall) { firstWall = false; return wall; } return clocks.wall(); },
    monotonic: () => { if (firstMono) { firstMono = false; return mono; } return clocks.monotonic(); },
  }) };
}

/** The only overrides are internal unit seams; CLI dispatch never receives them. */
export async function buildGuidedNativeProject(input: { dir: unknown; visual: unknown }, overrides: Partial<Dependencies> = {}) {
  const visual = parseGuidedNativeVisualPlan(structuredClone(input.visual)), deps = { ...DEFAULTS, ...overrides };
  const started = capturedStart(deps.clocks), dir = deps.canonicalDir(input.dir), proposal = deps.proposal(dir);
  if (visual.candidateHash !== canonicalJsonSha256(proposal.result.candidate)) throw new Error("Guided visual plan belongs to another current candidate");
  const lease = await deps.acquire(dir, { workflowVersion: 2, action: "compile-post-cut-proposal",
    expectedStatus: "treatment_admitted", expectedToken: proposal.job.token, expectedJournalHash: proposal.sha256 });
  try {
    const leaseGuard = deps.leaseGuard(dir, lease), guard = () => {
      leaseGuard();
      if (deps.observeJob(dir).sha256 !== proposal.sha256) throw new Error("Guided native build journal changed under its lease");
    };
    guard();
    const id = randomUUID(), parent = humanCutDirectory(dir, "native-build-attempts"), execution = humanCutDirectory(parent, id);
    const origin = { clockHash: proposal.clock.hash, startedAt: proposal.generationStartedAt };
    const budget = guardGenerationAttempt({ dir, origin, executionId: id, guard }, started.start(origin));
    createHumanCutIndex(path.join(execution, "start.json"), { schemaVersion: 1, kind: "guided-native-build-attempt",
      proposalHash: proposal.proposalHash, visualHash: canonicalJsonSha256(visual), beforeJournalHash: proposal.sha256,
      receivedAt: started.receivedAt, budget: budget.admission, scope: "local-project-assembly-not-approval" });
    return await finishBuild({ dir, visual, execution, guard }, budget, deps.write);
  } finally { lease.release(); }
}

async function finishBuild(input: { dir: string; visual: GuidedNativeVisualPlan; execution: string; guard: () => void },
  budget: ReturnType<ReturnType<typeof capturedStart>["start"]>, write: typeof writeGuidedNativeProject) {
  const remaining = () => { input.guard(); return budget.remainingMs(); };
  try {
    remaining(); const result = await write(input.dir, remaining, input.visual); remaining();
    const observation = budget.observe();
    if (observation.state !== "within-deadline" || !Number.isSafeInteger(observation.remainingMs) || observation.remainingMs < 1) {
      throw new Error(`Guided native build ${observation.state} before its success receipt`);
    }
    const status = { status: "ready-for-native-qc", scope: "local-guided-native-project-not-editorial-or-delivery-approval",
      ...result, budget: observation, providerCalls: 0, renderStarted: false, publicationApproved: false };
    createHumanCutIndex(path.join(input.execution, "result.json"), status); return status;
  } catch (error) {
    createHumanCutIndex(path.join(input.execution, "result.json"), { status: "failed-or-incomplete",
      error: String(error).slice(0, 2048), projectMayExist: true, publicationApproved: false });
    throw error;
  }
}
