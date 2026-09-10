/** New-only admitted-source/existing-candidate launch through the ordinary qualified cut PAUSE. */
import path from "node:path";
import { lstatSync } from "node:fs";
import { writeProjectJson } from "@/app/api/_lib/workspace";
import { savePlanTransaction } from "@/app/api/producer/save-plan/transaction";
import { parseAutoEditIntent, type AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import type { EditPlan } from "@/lib/producer/edit-plan";
import { isoDate } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { acquireProjectMutationLease } from "./project-mutation-lease";
import { startAutoEditJob, autoEditJobPath } from "./auto-edit-job-store";
import { newProducerRunToken, beginProducerRunWithToken } from "./producer-run-registry";
import { prepareAutoEditRunContext } from "./auto-edit-pipeline-authority";
import { launchDetachedAutoEditWorker } from "./auto-edit-worker-launcher";
import { parseBootstrapRequest, parseAuthorCutRequest, type GuidedProjectRequest } from "./guided-project-bootstrap-contract";
import { atomicCreateFileSync } from "./atomic-file";
import { authoredPreparationRemainingMs } from "./guided-project-preparation-deadline";
import { readBootstrapInputs } from "./guided-project-bootstrap-inputs";
import { assertBootstrapSavedPlan } from "./guided-project-bootstrap-guard";
import { bootstrapProjectPath, bootstrapSeedPath, createBootstrapProject, readBootstrapIntake, retainBootstrapFailure } from "./guided-project-bootstrap-store";
import { readGuidedProjectBootstrapStatus } from "./guided-project-bootstrap-status";

/** Fixed production references. Tests mock these in-process; no caller/runtime override surface. */
export const bootstrapServices = { inputs: readBootstrapInputs, save: savePlanTransaction,
  pin: prepareAutoEditRunContext, start: startAutoEditJob, launch: launchDetachedAutoEditWorker,
  status: readGuidedProjectBootstrapStatus };

function existsExactly(file: string): boolean {
  try { lstatSync(file); return true; }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return false; throw error; }
}

function replay(request: GuidedProjectRequest, dir: string) {
  const held = readBootstrapIntake(dir);
  if (held.requestHash !== canonicalJsonSha256(request)) throw new Error("Bootstrap UUID conflicts with retained exact request");
  return { ...bootstrapServices.status(dir), replayed: true };
}

function assertOriginalInputs(request: GuidedProjectRequest, inputs: ReturnType<typeof readBootstrapInputs>): void {
  const current = bootstrapServices.inputs(request);
  if (request.operation === "author-cut" && current.transcriptDigest !== inputs.transcriptDigest) {
    throw new Error("Bootstrap original transcripts changed before launch");
  }
}

function policyContext(created: ReturnType<typeof createBootstrapProject>,
  inputs: ReturnType<typeof readBootstrapInputs>, saved: ReturnType<typeof readCutPreviewObject>): Pick<AutoEditCtx, "authoredCut" | "existingCutCandidate"> {
  const { request, requestHash, receivedAt } = created.record;
  if (request.operation === "bootstrap-existing-cut") return { existingCutCandidate: {
    schemaVersion: 1, policy: "previsual-review-only", requestHash,
    inputPlanSha256: request.candidate.sha256, savedPlanSha256: saved.sha256 } };
  if (!inputs.transcriptDigest) throw new Error("Authored-cut intake lacks original transcript digest");
  atomicCreateFileSync(bootstrapSeedPath(created.dir), saved.bytes);
  return { authoredCut: { schemaVersion: 1, policy: "source-brief-cut", requestHash,
    initialPlanSha256: saved.sha256, transcriptDigest: inputs.transcriptDigest, preparationStartedAt: receivedAt } };
}

async function saveContext(created: ReturnType<typeof createBootstrapProject>, inputs: ReturnType<typeof readBootstrapInputs>): Promise<AutoEditCtx> {
  const { request, token } = created.record;
  writeProjectJson(created.root, { origin: "raw", sourceMode: "referenced", history: [],
    requestedIntent: request.intent, resolvedIntent: request.intent, intent: request.intent, intentDecisions: [] });
  const planPath = path.join(created.dir, "edit_plan.json");
  await bootstrapServices.save({ filePath: planPath, plan: inputs.candidate.value as unknown as EditPlan, timebase: "full-plan" });
  const saved = readCutPreviewObject(planPath);
  assertBootstrapSavedPlan(inputs.candidate.value, saved.value);
  // Reobserve original inputs after save; their bytes are never replaced or normalized.
  assertOriginalInputs(request, inputs);
  const ctx: AutoEditCtx = { dir: created.dir, scope: request.intent.scope,
    intent: parseAutoEditIntent(request.intent as unknown as Record<string, unknown>),
    deliveryPolicy: "mp4-only", workflowPolicy: "cut-first",
    workflowV2: { schemaVersion: 2, mode: "guided", afterCut: "treatment-then-intro", approvalPolicy: "explicit-human" },
    planPath, manifestPath: request.manifest.path, transcriptsDir: path.dirname(request.manifest.path),
    ...policyContext(created, inputs, saved) };
  authoredPreparationRemainingMs(ctx);
  const pinned = bootstrapServices.pin({ ctx, runId: token, resume: false });
  authoredPreparationRemainingMs(pinned);
  assertOriginalInputs(request, inputs);
  if (readCutPreviewObject(planPath).sha256 !== saved.sha256
      || (ctx.authoredCut && readCutPreviewObject(bootstrapSeedPath(created.dir)).sha256 !== saved.sha256)) {
    throw new Error("Bootstrap saved initial plan or immutable seed changed before launch");
  }
  return pinned;
}

async function launchNew(created: ReturnType<typeof createBootstrapProject>, inputs: ReturnType<typeof readBootstrapInputs>) {
  const acquired = acquireProjectMutationLease(created.root, "bootstrap new guided cut preparation");
  if (!acquired.lease) throw new Error("New bootstrap project lease is unavailable; no launch occurred");
  let launchAttempted = false;
  let releaseLease = true;
  try {
    const ctx = await saveContext(created, inputs);
    authoredPreparationRemainingMs(ctx);
    bootstrapServices.start({ ctx, token: created.record.token, snapshots: 0 });
    beginProducerRunWithToken({ dir: created.dir, kind: "auto_edit", token: created.record.token,
      phase: "authoring", message: ctx.authoredCut
        ? "Authoring an unapproved source-bound cut; explicit human acceptance remains required."
        : "Validating the supplied cut; no writer or human acceptance is authorized." });
    authoredPreparationRemainingMs(ctx);
    launchAttempted = true;
    const workerPid = await bootstrapServices.launch(autoEditJobPath(created.dir));
    return { producerDir: created.dir, idempotencyKey: created.record.request.idempotencyKey, workerPid,
      requestHash: created.record.requestHash, state: "launched-not-yet-qualified", replayed: false,
      scope: "guided-project-bootstrap-not-cut-acceptance", cutAccepted: false, approvalGranted: false };
  } catch (error) {
    if (launchAttempted) releaseLease = false;
    retainBootstrapFailure(created.dir, error, { verified: !launchAttempted, forcedStop: false });
    throw error;
  } finally { if (releaseLease) acquired.lease.release(); }
}

/** Singleton project+intent fencing precedes every possible worker launch. */
async function bootstrapRequest(request: GuidedProjectRequest, receivedAt?: string) {
  const root = bootstrapProjectPath(request.idempotencyKey), dir = path.join(root, "producer");
  if (existsExactly(root)) return replay(request, dir);
  const inputs = bootstrapServices.inputs(request);
  let created: ReturnType<typeof createBootstrapProject>;
  try { created = createBootstrapProject(request, newProducerRunToken(), receivedAt); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") return replay(request, dir);
    throw error;
  }
  return launchNew(created, inputs);
}

/** Existing supplied candidates retain their exact review-only request contract. */
export async function bootstrapGuidedProject(value: unknown) {
  return bootstrapRequest(parseBootstrapRequest(structuredClone(value)));
}

/** Fixed preparation origin is captured before parsing; replay never launches or resets it. */
export async function authorGuidedProjectCut(value: unknown, receivedAt = new Date().toISOString()) {
  isoDate(receivedAt, "bootstrap receivedAt");
  if (Date.parse(receivedAt) > Date.now()) throw new Error("Bootstrap receivedAt cannot be future");
  return bootstrapRequest(parseAuthorCutRequest(structuredClone(value)), receivedAt);
}
