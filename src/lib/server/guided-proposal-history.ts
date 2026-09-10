import path from "node:path";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseTreatmentCompileSubmissionV1 } from "@/lib/producer/contracts/raw-treatment-v1";
import { parseCurrentTreatmentProposal as parseTreatmentProposal } from "@/lib/producer/contracts/treatment-proposal-v8";
import { assertProposalClauseCoverage } from "@/lib/producer/contracts/treatment-proposal-v2";
import { exactKeys, objectValue, sha256 } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import { parseGuidedCutDecision, readGuidedExecution, readGuidedObject, strictGuidedTimestamp } from "./guided-cut-v2-store";
import { observeHistoricalProposalSnapshot } from "./guided-proposal-history-snapshot";
import { readRawTreatmentAdmission } from "./guided-raw-treatment-store";
import { readTreatmentAdmissionLineage } from "./guided-treatment-revision-store";

/** An older proposal is read from its exact retained before-revision journal, never a substituted current pointer. */
function historicalJournal(dir: string, admissionHash?: string) {
  const current = observeHumanCutJob(dir);
  if (!admissionHash || admissionHash === current.job.guidedHandoffV2?.treatmentAdmissionHash) return { ...current, currentJournalHash: current.sha256 };
  const held = readRawTreatmentAdmission(dir, { pendingRevisionObservation: true }), index = held.lineage.findIndex((row) => row.hash === sha256(admissionHash, "historical admission"));
  if (index < 1 || held.sha256 !== current.sha256) throw new Error("Historical admission is not an ancestor of the current brief");
  const hash = sha256(held.lineage[index - 1].admission.beforeJournalHash, "revision before journal");
  const prior = readCutPreviewObject(path.join(dir, "human-cut-job-snapshots", `${hash}.json`));
  if (prior.sha256 !== hash) throw new Error("Historical revision journal changed");
  return { job: parseAutoEditJobRecord(prior.value), sha256: prior.sha256, currentJournalHash: current.sha256 };
}

function historyRecord(dir: string, admissionHash?: string) {
  const observed = historicalJournal(dir, admissionHash), { job } = observed, pointer = job.guidedHandoffV2;
  if (!pointer?.treatmentProposalHash || !job.ctx.pipeline) throw new Error("No stored guided proposal history exists");
  const fact = parseGuidedCutDecision(readGuidedObject(dir, pointer.cutDecisionHash)), row = readGuidedObject(dir, pointer.treatmentProposalHash);
  const keys = ["schemaVersion", "kind", "scope", "treatmentAdmissionHash", "clockHash", "generationStartedAt", "cutDecisionHash",
    "parentRevisionHash", "submission", "beforeJournalHash", "executionId", "executionStartHash", "evidenceHash", "compilerAuthorityHash",
    "compilerResultHash", "candidateResultHash", "createdAt", "independentReview", "executable"];
  if (row.schemaVersion === 2) keys.push("budgetAdmissionHash", "budgetPrecommitHash");
  exactKeys(row, keys, keys, "historical proposal receipt");
  const submission = parseTreatmentCompileSubmissionV1(row.submission);
  if (fact.producerDir !== dir || fact.contextHash !== canonicalJsonSha256(job.ctx) || (row.schemaVersion !== 1 && row.schemaVersion !== 2)
      || row.kind !== "guided-treatment-proposal" || row.scope !== "unapproved-full-program-treatment-proposal-not-render-or-delivery"
      || row.executable !== false || row.independentReview !== "not-run" || row.treatmentAdmissionHash !== pointer.treatmentAdmissionHash
      || row.cutDecisionHash !== pointer.cutDecisionHash || row.parentRevisionHash !== pointer.pictureLockedRevisionHash
      || row.beforeJournalHash !== submission.expectedJournalHash || submission.treatmentAdmissionHash !== row.treatmentAdmissionHash
      || submission.expectedToken !== fact.nextToken) throw new Error("Historical proposal lost its stored cut/request/context bindings");
  const started = readGuidedExecution({ dir, id: submission.idempotencyKey, executionId: row.executionId, hash: row.executionStartHash });
  const before = readCutPreviewObject(path.join(dir, "human-cut-job-snapshots", `${sha256(row.beforeJournalHash, "before journal")}.json`));
  const prior = parseAutoEditJobRecord(before.value);
  if (before.sha256 !== row.beforeJournalHash || prior.status !== "treatment_admitted" || prior.guidedHandoffV2?.treatmentProposalHash
      || prior.guidedHandoffV2?.treatmentAdmissionHash !== row.treatmentAdmissionHash || prior.token !== submission.expectedToken
      || canonicalJsonSha256(prior.ctx) !== fact.contextHash || started.submissionHash !== canonicalJsonSha256(submission)
      || prior.updatedAt > String(started.firstReceivedAt) || strictGuidedTimestamp(row.createdAt) < String(started.startedAt)) throw new Error("Historical proposal execution bindings changed");
  return { ...observed, pointer, fact, row, submission, root: path.join(dir, "guided-v2-operations", submission.idempotencyKey, "executions", String(row.executionId)) };
}

function historyObject(history: ReturnType<typeof historyRecord>, name: string, hash: unknown) {
  const digest = sha256(hash, name), value = readGuidedObject(history.job.ctx.dir, digest);
  const privateValue = readCutPreviewObject(path.join(history.root, name));
  if (canonicalJsonSha256(privateValue.value) !== digest) throw new Error(`Historical private object differs: ${name}`);
  return value;
}

function historyOrigin(history: ReturnType<typeof historyRecord>) {
  const activation = readGuidedObject(history.job.ctx.dir, history.pointer.cutActivationHash);
  const held = readTreatmentAdmissionLineage({ job: history.job, fact: history.fact, pointer: history.pointer, activation },
    sha256(history.row.treatmentAdmissionHash, "historical raw admission"));
  if (held.clock.hash !== history.row.clockHash || held.clock.value.startedAt !== history.row.generationStartedAt
      || strictGuidedTimestamp(held.nodes[0].admission.admittedAt) > String(history.row.createdAt)) throw new Error("Historical raw admission clock changed");
  return held.nodes[0].submission;
}

/** Explicit historical descriptor only. NEVER feeds current readiness, replay, opening, source or approval checks. */
export function readHistoricalGuidedProposal(value: unknown, admissionHash?: string) {
  const dir = canonicalProducerDir(value), history = historyRecord(dir, admissionHash), raw = historyOrigin(history), { row } = history;
  const evidence = historyObject(history, "evidence.json", row.evidenceHash), authority = historyObject(history, "compiler-authority.json", row.compilerAuthorityHash);
  const compiler = historyObject(history, "compiler-result.json", row.compilerResultHash), result = historyObject(history, "candidate-result.json", row.candidateResultHash);
  const compilerKeys = ["output", "provider", "model", "effort", "elapsedMs", "promptHash"];
  exactKeys(compiler, compilerKeys, compilerKeys, "historical compiler result"); sha256(compiler.promptHash, "historical prompt hash");
  if (!["codex", "legacy"].includes(String(compiler.provider)) || typeof compiler.model !== "string" || !compiler.model
      || typeof compiler.effort !== "string" || !compiler.effort || typeof compiler.elapsedMs !== "number"
      || !Number.isFinite(compiler.elapsedMs) || compiler.elapsedMs < 0 || compiler.elapsedMs > 600_000) throw new Error("Historical compiler metadata is malformed");
  const proposal = parseTreatmentProposal(compiler.output); assertProposalClauseCoverage(proposal, raw.rawIntent);
  if (evidence.schemaVersion !== proposal.schemaVersion || evidence.pipelineHash !== canonicalJsonSha256(history.job.ctx.pipeline)
      || evidence.cutDecisionHash !== history.pointer.cutDecisionHash || evidence.parentRevisionHash !== history.pointer.pictureLockedRevisionHash
      || canonicalJsonSha256(result.proposal) !== canonicalJsonSha256(proposal) || !Array.isArray(result.blockers)) throw new Error("Historical proposal/evidence object relationships changed");
  if (result.candidate !== null) {
    const candidate = objectValue(result.candidate, "historical candidate"), file = readCutPreviewObject(path.join(history.root, "candidate-plan.json"));
    if (canonicalJsonSha256(file.value) !== canonicalJsonSha256(candidate)) throw new Error("Historical candidate plan bytes changed");
  }
  if (row.schemaVersion === 2) {
    historyObject(history, "budget-admission.json", row.budgetAdmissionHash);
    historyObject(history, "budget-precommit.json", row.budgetPrecommitHash);
  }
  const snapshot = observeHistoricalProposalSnapshot(history.job.ctx.pipeline!, authority);
  if (observeHumanCutJob(dir).sha256 !== history.currentJournalHash) throw new Error("Historical journal changed during observation");
  return { schemaVersion: 1, scope: "historical-proposal-record-not-current-reproduction-or-approval", available: false as const,
    currentExecutionAuthority: false as const, sourceCurrentness: "not-observed", readinessCurrentness: "not-revalidated",
    proposalHash: history.pointer.treatmentProposalHash, proposalVersion: proposal.schemaVersion, summary: proposal.summary,
    rawIntent: raw.rawIntent, clauses: proposal.clauses, storedBlockers: result.blockers, createdAt: row.createdAt,
    generationStartedAt: row.generationStartedAt, snapshotIntegrity: snapshot };
}
