import path from "node:path";
import { mkdirSync, writeFileSync, lstatSync } from "node:fs";
import { createServer } from "node:net";
import { observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseGuidedBodyMediaInput } from "@/lib/producer/contracts/guided-body-media-v1";
import { parseGuidedBodyExecutionActivation } from "@/lib/producer/contracts/guided-body-activation-v1";
import { bodyClaimFixture } from "./_guided-body-claim-fixture";
import { admitGuidedBodyClaim } from "../guided-body-claim";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "../human-cut-acceptance-store";
import { writeGuidedObject } from "../guided-cut-v2-store";
import { createOpeningRecord } from "../guided-opening-process-activation";
import { bodyActivationJournal } from "../guided-body-activation";
import { bodyPhaseJournal, parseBodyPhaseFact } from "../guided-body-phase";

const H = "a".repeat(64);
async function localRuntime(root: string) {
  const server = createServer(), dockerSocketPath = path.join(root, "test.sock");
  const close = () => new Promise<void>((resolve) => server.close(() => resolve()));
  try {
    await new Promise<void>((resolve, reject) => { server.once("error", reject); server.listen(dockerSocketPath, resolve); });
    return { runtime: socketRuntime(root, dockerSocketPath), close };
  } catch (error) { await close(); throw error; }
}

function socketRuntime(root: string, dockerSocketPath: string) {
  const dockerPath = path.join(root, "TEST-never-invoked-docker"), imageApprovalPath = path.join(root, "image.json");
  writeFileSync(dockerPath, "#!/bin/sh\nexit 99\n", { mode: 0o700 });
  writeFileSync(imageApprovalPath, JSON.stringify({ schemaVersion: 1, imageId: `sha256:${H}` }));
  const stat = lstatSync(dockerSocketPath, { bigint: true });
  const runtime = { dockerPath, dockerSha256: observeCutPreviewFile(dockerPath, 1024).sha256, dockerSocketPath,
    dockerSocketDevice: String(stat.dev), dockerSocketInode: String(stat.ino), imageId: `sha256:${H}`, userId: "501:20",
    imageApprovalPath, imageApprovalSha256: readCutPreviewObject(imageApprovalPath).sha256, runtimeRepoRoot: root };
  return runtime;
}

function activationRecords(f: ReturnType<typeof bodyClaimFixture>, admitted: Awaited<ReturnType<typeof admitGuidedBodyClaim>>,
  runtime: Awaited<ReturnType<typeof localRuntime>>["runtime"]) {
  const current = observeHumanCutJob(f.dir), root = path.join(f.dir, "guided-v2-operations", admitted.requestId, "executions", admitted.executionId);
  const claim = readCutPreviewObject(path.join(root, "claim.json")).value;
  const openingInput = createOpeningRecord(path.join(root, "TEST-original-input.json"), { TEST: "metadata, not media authority" });
  const openingResult = createOpeningRecord(path.join(root, "TEST-original-result.json"), { TEST: "no media generated" });
  const reference = (name: string) => ({ path: path.join(root, name), sha256: readCutPreviewObject(path.join(root, name)).sha256 });
  const input = parseGuidedBodyMediaInput({ schemaVersion: 1, kind: "guided-body-media-input", scope: "private-body-candidate-not-approval",
    profile: "held-source-float-own-screen-body-v1", requestId: admitted.requestId, executionId: admitted.executionId, runtime, selectedGraphicOrders: [0],
    references: { admissionClaim: reference("claim.json"), heldInput: reference("held-input.json"), budgetAdmission: reference("budget-admission.json"),
      budgetPrecommit: reference("budget-precommit.json"), approvedSnapshot: { path: path.join(f.dir, "human-cut-job-snapshots", `${claim.beforeJournalHash}.json`), sha256: claim.beforeJournalHash },
      openingInput: { path: openingInput.path, sha256: openingInput.sha256 }, openingResult: { path: openingResult.path, sha256: openingResult.sha256 } } });
  const inputRecord = createOpeningRecord(path.join(root, "body-media-input.json"), { ...input });
  const activation = parseGuidedBodyExecutionActivation({ schemaVersion: 1, kind: "guided-body-execution-activation", scope: "private-body-owned-execution-not-approval",
    requestId: admitted.requestId, executionId: admitted.executionId, admissionClaimHash: admitted.claimHash, beforeJournalHash: current.sha256,
    inputPath: inputRecord.path, inputSha256: inputRecord.sha256, outputRoot: path.join(root, "body-media-output"), clockHash: claim.clockHash,
    generationStartedAt: claim.generationStartedAt, budgetAdmissionHash: claim.budgetAdmissionHash, budgetPrecommitHash: claim.budgetPrecommitHash,
    selectedGraphicOrders: [0], runtime, createdAt: new Date().toISOString() });
  const activationRecord = createOpeningRecord(path.join(root, "body-execution-activation.json"), { ...activation });
  const activationHash = writeGuidedObject(f.dir, activation); saveHumanCutJobSnapshot(f.dir, current);
  mkdirSync(activation.outputRoot, { mode: 0o700 });
  writeFileSync(f.base.jobPath, JSON.stringify(bodyActivationJournal(current, activation, activationHash)));
  return { root, input, inputRecord, activation, activationRecord, activationHash };
}

function processRecords(f: ReturnType<typeof bodyClaimFixture>, activated: ReturnType<typeof activationRecords>) {
  const current = observeHumanCutJob(f.dir), intent = createOpeningRecord(path.join(activated.root, "body-media-process-intent.json"), { TEST: "intent" });
  const outcome = createOpeningRecord(path.join(activated.root, "body-media-process-result.json"), { TEST: "not an actual process outcome" });
  const fact = parseBodyPhaseFact({ schemaVersion: 1, kind: "guided-body-process-fact", scope: "owned-private-body-phase-not-approval", phase: "process",
    requestId: activated.activation.requestId, executionId: activated.activation.executionId, activationHash: activated.activationHash,
    beforeJournalHash: current.sha256, clockHash: activated.activation.clockHash, generationStartedAt: activated.activation.generationStartedAt,
    createdAt: new Date().toISOString(), references: { intent: { path: intent.path, sha256: intent.sha256 }, outcome: { path: outcome.path, sha256: outcome.sha256 } } }, "process");
  const factHash = writeGuidedObject(f.dir, fact); createOpeningRecord(path.join(activated.root, `body-process-${factHash}.json`), { ...fact });
  saveHumanCutJobSnapshot(f.dir, current); writeFileSync(f.base.jobPath, JSON.stringify(bodyPhaseJournal(current, fact, factHash)));
  return { fact, factHash, outcome, activatedJournalHash: current.sha256 };
}

/** Durable admission/CAS and exact control edges; all activation/process/media data below is explicitly TEST-only. */
export async function bodyCleanupFixture() {
  const f = bodyClaimFixture(); let local: Awaited<ReturnType<typeof localRuntime>> | undefined;
  try {
    local = await localRuntime(f.root); const active = local;
    const admitted = await admitGuidedBodyClaim({ dir: f.dir, submission: f.submission }, f.services);
    const activated = activationRecords(f, admitted, local.runtime), process = processRecords(f, activated);
    return { ...f, ...activated, ...process, runtime: local.runtime,
      async dispose() { await active.close(); f.cleanup(); } };
  } catch (error) { await local?.close(); f.cleanup(); throw error; }
}
