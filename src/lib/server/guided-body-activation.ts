import path from "node:path";
import { mkdirSync } from "node:fs";
import { readCutPreviewObject, assertCutPreviewDirectory } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { assertBodyActivationInput, parseGuidedBodyExecutionActivation,
  type GuidedBodyExecutionActivationV1 } from "@/lib/producer/contracts/guided-body-activation-v1";
import { canonicalJsonSha256 as hash } from "./auto-edit-hash";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import { readGuidedBodyClaim, readHistoricalBodyAdmission } from "./guided-body-lineage";
import { writeGuidedBodyMediaInput, observeGuidedBodyMediaInput, assertBodyInputReferences } from "./guided-body-input";
import { createOpeningRecord, assertOpeningRecord } from "./guided-opening-process-activation";
import { writeGuidedObject, readGuidedObject } from "./guided-cut-v2-store";
import { commitGuidedJob } from "./guided-cut-v2";
import { consumeFreshBodyAdmission, type FreshBodyAdmission } from "./guided-body-claim";
import { assertBodyControllerInvocation, checkBodyControllerInvocation, retainBodyControllerActivation,
  checkBodyControllerActivation, assertBodyControllerActivationMetadata } from "./guided-body-controller-handoff";

type Journal = ReturnType<typeof observeHumanCutJob>;

/** Only this exact edge follows admission. Extra changes cannot masquerade as body activation. */
export function bodyActivationJournal(before: Journal, activation: GuidedBodyExecutionActivationV1, activationHash: string) {
  const job = before.job, pointer = job.guidedHandoffV2;
  if (before.sha256 !== activation.beforeJournalHash || pointer?.bodyExecutionClaimHash !== activation.admissionClaimHash
      || pointer.bodyActivationHash || job.status !== "treatment_admitted" || job.updatedAt > activation.createdAt) {
    throw new Error("Body activation lost its exact single admission edge");
  }
  return { ...job, updatedAt: activation.createdAt, guidedHandoffV2: { ...pointer, bodyActivationHash: activationHash },
    message: "Private body execution owns a resource claim; this is not body completion or delivery approval.",
    nextEventId: job.nextEventId + 1, events: [...job.events, { id: job.nextEventId, at: activation.createdAt,
      payload: { event: "body_execution_activated", activationHash, executionId: activation.executionId,
        bodyApproved: false, deliveryApproved: false } }].slice(-256) };
}

/** Fresh SAME-CALL handoff only. New-only input/activation files block replay after ambiguous pre-spawn failure. */
export function activateFreshGuidedBody(context: FreshBodyAdmission) {
  consumeFreshBodyAdmission(context);
  if (context.admission.replayed) throw new Error("A retained body admission cannot activate another worker");
  const { dir, lease, budget } = context, before = observeHumanCutJob(dir), leaseGuard = cutPreviewLeaseGuard(dir, lease);
  const guard = () => {
    leaseGuard(); budget.remainingMs();
    if (observeHumanCutJob(dir).sha256 !== before.sha256) throw new Error("Body journal changed before activation");
  };
  guard(); const held = readGuidedBodyClaim(dir);
  if (held.claimHash !== context.admission.claimHash || held.claim.executionId !== context.operation.executionId
      || held.execution !== context.operation.execution || held.current.sha256 !== context.admission.journalHash) {
    throw new Error("Body activation lost its actual fresh admission return");
  }
  const invocation = writeGuidedBodyMediaInput(held, guard, budget.remainingMs), outputRoot = path.join(held.execution, "body-media-output");
  assertCutPreviewDirectory(held.execution); mkdirSync(outputRoot, { mode: 0o700 });
  const activation = parseGuidedBodyExecutionActivation({ schemaVersion: 1, kind: "guided-body-execution-activation",
    scope: "private-body-owned-execution-not-approval", requestId: held.claim.requestId, executionId: held.claim.executionId,
    admissionClaimHash: held.claimHash, beforeJournalHash: before.sha256, inputPath: invocation.record.path,
    inputSha256: invocation.record.sha256, outputRoot, clockHash: held.claim.clockHash, generationStartedAt: held.claim.generationStartedAt,
    budgetAdmissionHash: held.claim.budgetAdmissionHash, budgetPrecommitHash: held.claim.budgetPrecommitHash,
    selectedGraphicOrders: invocation.input.selectedGraphicOrders, runtime: invocation.input.runtime, createdAt: new Date().toISOString() });
  const record = createOpeningRecord(path.join(held.execution, "body-execution-activation.json"), { ...activation });
  const activationHash = writeGuidedObject(dir, activation); saveHumanCutJobSnapshot(dir, before);
  const commitGuard = () => {
    assertBodyControllerInvocation(invocation); guard(); assertOpeningRecord(record); assertOpeningRecord(invocation.record);
    observeGuidedBodyMediaInput(invocation.record.path, invocation.record.sha256);
    if (new Date().toISOString() < activation.createdAt) throw new Error("Body clock moved backwards before activation");
    guard(); checkBodyControllerInvocation(invocation);
  };
  commitGuidedJob({ beforeHash: before.sha256, guard: commitGuard, job: bodyActivationJournal(before, activation, activationHash) });
  const activated = readGuidedBodyActivation(dir);
  retainBodyControllerActivation(invocation, activated);
  budget.remainingMs(); checkBodyControllerActivation(activated); leaseGuard();
  if (observeHumanCutJob(dir).sha256 !== activated.current.sha256) throw new Error("Body activation journal changed after its actual CAS");
  assertBodyControllerActivationMetadata(activated);
  return activated;
}

function activationFromJournal(dir: string, current: Journal) {
  const activationHash = current.job.guidedHandoffV2?.bodyActivationHash;
  if (!activationHash) throw new Error("No durable body execution activation exists");
  const activation = parseGuidedBodyExecutionActivation(readGuidedObject(dir, activationHash));
  const snapshot = path.join(dir, "human-cut-job-snapshots", `${activation.beforeJournalHash}.json`);
  const raw = readCutPreviewObject(snapshot), before = { ...raw, job: parseAutoEditJobRecord(raw.value) };
  if (raw.sha256 !== activation.beforeJournalHash || before.job.ctx.dir !== dir
      || hash(current.job) !== hash(bodyActivationJournal(before, activation, activationHash))) {
    throw new Error("Body activation differs from its exact retained admission transition");
  }
  const admission = readHistoricalBodyAdmission(dir, before.sha256), root = admission.execution;
  const activationPath = path.join(root, "body-execution-activation.json"), record = readCutPreviewObject(activationPath);
  const invocation = observeGuidedBodyMediaInput(activation.inputPath, activation.inputSha256);
  assertBodyInputReferences(admission, invocation.input);
  assertBodyActivationInput(activation, invocation.input, { path: activation.inputPath, sha256: activation.inputSha256 });
  if (record.sha256 !== activationHash || hash(record.value) !== activationHash
      || activation.requestId !== admission.claim.requestId || activation.executionId !== admission.claim.executionId
      || activation.admissionClaimHash !== admission.claimHash || activation.clockHash !== admission.claim.clockHash
      || activation.generationStartedAt !== admission.claim.generationStartedAt
      || activation.inputPath !== path.join(root, "body-media-input.json") || activation.outputRoot !== path.join(root, "body-media-output")) {
    throw new Error("Body activation has changed or transplanted input/runtime/original-clock references");
  }
  if (readCutPreviewObject(snapshot).sha256 !== before.sha256) throw new Error("Body admission snapshot changed during activation read");
  return { current, activation, activationHash, activationPath, activationSha256: record.sha256, admission, invocation,
    controlJob: admission.before.job,
    observationScope: "exact-owned-activation-not-current-source-media-or-absence-proof" as const };
}

/** Current activated phase only, never an arbitrary later body journal descendant. */
export function readGuidedBodyActivation(dir: string) {
  const current = observeHumanCutJob(dir), held = activationFromJournal(dir, current);
  if (observeHumanCutJob(dir).sha256 !== current.sha256) throw new Error("Body activation changed during observation");
  return held;
}

/** Actual snapshot selected by a separately verified known process edge, not a caller-supplied synthetic journal. */
export function readHistoricalBodyActivation(dir: string, journalHash: string) {
  if (!/^[a-f0-9]{64}$/u.test(journalHash)) throw new Error("Historical body activation hash is malformed");
  const file = path.join(dir, "human-cut-job-snapshots", `${journalHash}.json`), raw = readCutPreviewObject(file);
  if (raw.sha256 !== journalHash) throw new Error("Historical body activation snapshot changed");
  const held = activationFromJournal(dir, { ...raw, job: parseAutoEditJobRecord(raw.value) });
  if (readCutPreviewObject(file).sha256 !== journalHash) throw new Error("Historical body activation changed during observation");
  return held;
}
