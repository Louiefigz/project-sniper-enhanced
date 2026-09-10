import path from "node:path";
import { observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseGuidedBodyExecutionActivation, assertBodyActivationInput } from "@/lib/producer/contracts/guided-body-activation-v1";
import { parseCurrentBodyMediaInput as parseGuidedBodyMediaInput } from "@/lib/producer/contracts/guided-body-media-v1";
import { parseGuidedBodyExecutionClaim } from "@/lib/producer/contracts/guided-body-claim-v1";
import { canonicalJsonSha256 as hash } from "./auto-edit-hash";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { readGuidedObject } from "./guided-cut-v2-store";
import { bodyClaimJournal } from "./guided-body-lineage";
import { bodyActivationJournal } from "./guided-body-activation";
import { bodyPhaseJournal, parseBodyPhaseFact, retainedBodyJournal, assertBodyPhaseReferences } from "./guided-body-phase";
import { assertOpeningRuntimeControl } from "./guided-opening-runtime-control";
import type { BodyExecutionControl } from "./guided-body-process-tools";

function controlActivation(dir: string, current: ReturnType<typeof observeHumanCutJob>): BodyExecutionControl {
  const activationHash = current.job.guidedHandoffV2?.bodyActivationHash;
  if (!activationHash) throw new Error("Body cleanup lacks durable activation authority");
  const activation = parseGuidedBodyExecutionActivation(readGuidedObject(dir, activationHash));
  const admitted = retainedBodyJournal(dir, activation.beforeJournalHash);
  if (hash(current.job) !== hash(bodyActivationJournal(admitted, activation, activationHash))) throw new Error("Body cleanup activation edge changed");
  const claim = parseGuidedBodyExecutionClaim(readGuidedObject(dir, activation.admissionClaimHash));
  const approved = retainedBodyJournal(dir, claim.beforeJournalHash);
  if (hash(admitted.job) !== hash(bodyClaimJournal(approved, claim, activation.admissionClaimHash))
      || claim.requestId !== activation.requestId || claim.executionId !== activation.executionId
      || claim.clockHash !== activation.clockHash || claim.generationStartedAt !== activation.generationStartedAt
      || claim.budgetAdmissionHash !== activation.budgetAdmissionHash || claim.budgetPrecommitHash !== activation.budgetPrecommitHash) {
    throw new Error("Body cleanup lost exact approved admission ancestry or original clock");
  }
  const root = path.join(dir, "guided-v2-operations", activation.requestId, "executions", activation.executionId);
  const activationPath = path.join(root, "body-execution-activation.json"), record = readCutPreviewObject(activationPath);
  if (record.sha256 !== activationHash || hash(record.value) !== activationHash
      || activation.inputPath !== path.join(root, "body-media-input.json") || activation.outputRoot !== path.join(root, "body-media-output")) {
    throw new Error("Body cleanup activation bytes or derived paths changed");
  }
  const input = observeCutPreviewFile(activation.inputPath, 128 * 1024, true);
  if (input.sha256 !== activation.inputSha256) throw new Error("Body cleanup top input changed");
  const value = parseGuidedBodyMediaInput(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(input.bytes)));
  assertBodyActivationInput(activation, value, { path: activation.inputPath, sha256: input.sha256 });
  assertOpeningRuntimeControl(activation.runtime);
  retainedBodyJournal(dir, admitted.sha256); retainedBodyJournal(dir, approved.sha256);
  return { current, activation, activationHash, activationPath, activationSha256: record.sha256, controlJob: approved.job };
}

/** Known-resource recovery only. No source, result, historical approval receipt or media freshness is inferred. */
export function readBodyCleanupControl(dir: string) {
  const current = observeHumanCutJob(dir), factHash = current.job.guidedHandoffV2?.bodyProcessOutcomeHash;
  if (!factHash) throw new Error("Body cleanup requires a separately held actual process outcome");
  const fact = parseBodyPhaseFact(readGuidedObject(dir, factHash), "process"), activated = retainedBodyJournal(dir, fact.beforeJournalHash);
  if (hash(current.job) !== hash(bodyPhaseJournal(activated, fact, factHash))) throw new Error("Body cleanup process journal edge changed");
  const held = controlActivation(dir, activated), a = held.activation;
  if (fact.activationHash !== held.activationHash || fact.executionId !== a.executionId || fact.requestId !== a.requestId
      || fact.clockHash !== a.clockHash || fact.generationStartedAt !== a.generationStartedAt) throw new Error("Body cleanup process moved to another invocation");
  const file = path.join(path.dirname(held.activationPath), `body-process-${factHash}.json`);
  if (readCutPreviewObject(file).sha256 !== factHash) throw new Error("Body cleanup private process fact changed");
  assertBodyPhaseReferences(fact, held); retainedBodyJournal(dir, activated.sha256);
  if (observeHumanCutJob(dir).sha256 !== current.sha256) throw new Error("Body cleanup journal changed during observation");
  return { current, held, fact, factHash, observationScope: "known-resource-control-not-selection-source-or-media-proof" as const };
}
