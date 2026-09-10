import path from "node:path";
import { parseTreatmentCompileSubmissionV1 } from "@/lib/producer/contracts/raw-treatment-v1";
import { exactKeys, objectValue, sha256, uuid } from "@/lib/producer/contracts/validation";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import { readGuidedExecution, readGuidedObject, strictGuidedTimestamp } from "./guided-cut-v2-store";
import { readRawTreatmentAdmission } from "./guided-raw-treatment-store";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { assertStoredProposalEvidence, type ProposalEvidence } from "./guided-proposal-evidence";
import { proposalCompilerAuthority, buildProposalPrompt } from "./guided-proposal-compiler";
import { readProposalInputs } from "./guided-proposal-inputs";
import { buildTreatmentCandidate } from "./guided-proposal-candidate";
import { assertProposalDeadlineProof } from "./generation-deadline";

export const PROPOSAL_SCOPE = "unapproved-full-program-treatment-proposal-not-render-or-delivery";
export type RawAdmission = ReturnType<typeof readRawTreatmentAdmission>;

function proposalRecord(cut: RawAdmission, hash: string) {
  const row = readGuidedObject(cut.job.ctx.dir, hash);
  const keys = ["schemaVersion", "kind", "scope", "treatmentAdmissionHash", "clockHash", "generationStartedAt", "cutDecisionHash",
    "parentRevisionHash", "submission", "beforeJournalHash", "executionId", "executionStartHash", "evidenceHash", "compilerAuthorityHash",
    "compilerResultHash", "candidateResultHash", "createdAt", "independentReview", "executable"];
  if (row.schemaVersion === 2) keys.push("budgetAdmissionHash", "budgetPrecommitHash");
  exactKeys(row, keys, keys, "guided proposal receipt");
  const submission = parseTreatmentCompileSubmissionV1(row.submission);
  for (const key of ["evidenceHash", "compilerAuthorityHash", "compilerResultHash", "candidateResultHash"]) sha256(row[key], key);
  uuid(row.executionId, "executionId");
  if (![1, 2].includes(Number(row.schemaVersion)) || typeof row.schemaVersion !== "number"
      || row.kind !== "guided-treatment-proposal" || row.scope !== PROPOSAL_SCOPE
      || row.treatmentAdmissionHash !== cut.pointer.treatmentAdmissionHash || row.clockHash !== cut.clock.hash
      || row.generationStartedAt !== cut.generationStartedAt || row.cutDecisionHash !== cut.pointer.cutDecisionHash
      || row.parentRevisionHash !== cut.pointer.pictureLockedRevisionHash || row.beforeJournalHash !== submission.expectedJournalHash
      || submission.treatmentAdmissionHash !== row.treatmentAdmissionHash || submission.expectedToken !== cut.job.token
      || row.independentReview !== "not-run" || row.executable !== false || strictGuidedTimestamp(row.createdAt) > cut.job.updatedAt
      || String(row.createdAt) < cut.generationStartedAt) throw new Error("Proposal receipt does not bind this unapproved cut/request/clock");
  return { row, submission };
}

function proposalExecution(cut: RawAdmission, parsed: ReturnType<typeof proposalRecord>) {
  const { row, submission } = parsed, dir = cut.job.ctx.dir;
  const started = readGuidedExecution({ dir, id: submission.idempotencyKey, executionId: row.executionId, hash: row.executionStartHash });
  const before = readCutPreviewObject(path.join(dir, "human-cut-job-snapshots", `${sha256(row.beforeJournalHash, "beforeJournalHash")}.json`));
  const job = parseAutoEditJobRecord(before.value);
  if (before.sha256 !== row.beforeJournalHash || job.status !== "treatment_admitted" || job.guidedHandoffV2?.treatmentProposalHash
      || job.guidedHandoffV2?.treatmentAdmissionHash !== row.treatmentAdmissionHash || job.token !== cut.job.token
      || canonicalJsonSha256(job.ctx) !== cut.fact.contextHash || job.updatedAt > String(started.firstReceivedAt)
      || started.submissionHash !== canonicalJsonSha256(submission) || String(started.startedAt) > String(row.createdAt)) {
    throw new Error("Proposal lost its original admitted journal or execution proof");
  }
  return path.join(dir, "guided-v2-operations", submission.idempotencyKey, "executions", String(row.executionId));
}

function privateObject(dir: string, execution: string, name: string, hash: unknown) {
  const value = readGuidedObject(dir, sha256(hash, name)), file = readCutPreviewObject(path.join(execution, name));
  if (canonicalJsonSha256(file.value) !== hash) throw new Error(`Private proposal object changed: ${name}`);
  return value;
}

/** Non-creating exact proposal observation. It grants no execution, semantic, render, source-byte or QC approval. */
export function readGuidedTreatmentProposal(dir: string) {
  const cut = readRawTreatmentAdmission(dir), hash = cut.pointer.treatmentProposalHash;
  if (!hash) throw new Error("No compiled treatment proposal exists");
  const parsed = proposalRecord(cut, hash), { row } = parsed, execution = proposalExecution(cut, parsed);
  if (row.schemaVersion === 2) {
    const admission = privateObject(dir, execution, "budget-admission.json", row.budgetAdmissionHash);
    const precommit = privateObject(dir, execution, "budget-precommit.json", row.budgetPrecommitHash);
    const started = readCutPreviewObject(path.join(execution, "start.json")).value;
    assertProposalDeadlineProof({ admission, precommit }, { origin: { clockHash: cut.clock.hash, startedAt: cut.generationStartedAt },
      executionStartedAt: String(started.startedAt), createdAt: String(row.createdAt) });
  }
  const evidence = privateObject(dir, execution, "evidence.json", row.evidenceHash) as unknown as ProposalEvidence;
  assertStoredProposalEvidence(cut, evidence, readProposalInputs(cut, execution));
  const authority = privateObject(dir, execution, "compiler-authority.json", row.compilerAuthorityHash);
  const version = evidence.schemaVersion;
  if (canonicalJsonSha256(authority) !== canonicalJsonSha256(proposalCompilerAuthority(cut, { version }))) throw new Error("Proposal compiler or schema authority changed");
  const compiler = privateObject(dir, execution, "compiler-result.json", row.compilerResultHash);
  const fields = ["output", "provider", "model", "effort", "elapsedMs", "promptHash"];
  exactKeys(compiler, fields, fields, "compiler result");
  if (!["codex", "legacy"].includes(String(compiler.provider)) || typeof compiler.model !== "string" || !compiler.model || compiler.model.length > 160
      || typeof compiler.effort !== "string" || compiler.effort.length > 20 || typeof compiler.elapsedMs !== "number" || !Number.isFinite(compiler.elapsedMs)
      || compiler.elapsedMs < 0 || compiler.elapsedMs > 600_000 || compiler.promptHash !== canonicalJsonSha256(buildProposalPrompt(cut.submission.rawIntent, evidence))) {
    throw new Error("Proposal compiler result metadata is invalid");
  }
  const candidate = privateObject(dir, execution, "candidate-result.json", row.candidateResultHash);
  const expected = buildTreatmentCandidate({ cut, rawIntent: cut.submission.rawIntent, evidence, output: compiler.output });
  if (canonicalJsonSha256(candidate) !== canonicalJsonSha256(expected)) throw new Error("Private proposal plan or clause/range result changed");
  if (expected.candidate) {
    const plan = readCutPreviewObject(path.join(execution, "candidate-plan.json"));
    if (canonicalJsonSha256(plan.value) !== canonicalJsonSha256(expected.candidate)) throw new Error("Private candidate plan bytes changed");
  }
  if (observeHumanCutJob(dir).sha256 !== cut.sha256) throw new Error("Proposal journal changed during observation");
  return { ...cut, cutReceipt: cut.receipt, proposalHash: hash, receipt: row, compileSubmission: parsed.submission, evidence,
    result: expected, compiler: objectValue(compiler, "compiler result"), available: false as const, scope: PROPOSAL_SCOPE };
}
