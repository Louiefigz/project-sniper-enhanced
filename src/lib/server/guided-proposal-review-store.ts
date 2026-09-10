import path from "node:path";
import { exactKeys, objectValue, sha256, uuid } from "@/lib/producer/contracts/validation";
import { parseProposalReadinessSubmission, proposalReadinessChecks,
  PROPOSAL_GATE_BUNDLE_KIND, PROPOSAL_READINESS_SCOPE } from "@/lib/producer/contracts/proposal-readiness-v1";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { readGuidedTreatmentProposal } from "./guided-proposal-store";
import { readGuidedExecution, readGuidedObject, strictGuidedTimestamp } from "./guided-cut-v2-store";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import { buildProposalReadinessPacket, proposalReadinessAuthority, type ReviewedProposalInput } from "./guided-proposal-review-packet";
import { assertProposalCriticResult, type ProposalReadinessCriticResult } from "./guided-proposal-review-brain";
import { readGuidedTreatmentDraft } from "./guided-treatment-draft";
import { assertProposalReadinessDeadlineProof } from "./proposal-readiness-deadline";
import { assertCurrentReadinessGateExecution } from "./readiness-gate-execution";

function record(proposal: ReviewedProposalInput) {
  const hash = proposal.pointer.proposalReadinessHash;
  if (!hash) throw new Error("No independent proposal readiness review exists");
  const row = readGuidedObject(proposal.job.ctx.dir, hash);
  // Fail closed on every pre-gate receipt: schemaVersion 1/2 was written before readiness ran the
  // deterministic full-plan gate bundle, so it can neither prove nor be granted that evidence. A
  // historical readiness must be reviewed again rather than silently inherit today's admission.
  if (row.schemaVersion === 1 || row.schemaVersion === 2) throw new Error("Readiness receipt predates the deterministic full-plan gates; a new readiness review is required");
  const keys = ["schemaVersion", "kind", "scope", "submission", "beforeJournalHash",
    "proposalHash", "clockHash", "generationStartedAt", "executionId", "executionStartHash", "packetHash", "implementationHash",
    "reviewBundleHash", "treatmentDraftRevisionHash", "createdAt", "executable",
    "budgetAdmissionHash", "budgetPrecommitHash", "deterministicGates"];
  exactKeys(row, keys, keys, "proposal readiness receipt");
  const submission = parseProposalReadinessSubmission(row.submission); uuid(row.executionId, "executionId");
  for (const key of ["executionStartHash", "packetHash", "implementationHash", "reviewBundleHash"]) sha256(row[key], key);
  if (row.schemaVersion !== 3 || row.kind !== "guided-proposal-readiness" || row.scope !== PROPOSAL_READINESS_SCOPE
      || row.executable !== false || row.proposalHash !== proposal.proposalHash || submission.proposalHash !== proposal.proposalHash
      || submission.expectedToken !== proposal.job.token || submission.expectedJournalHash !== row.beforeJournalHash
      || row.clockHash !== proposal.clock.hash || row.generationStartedAt !== proposal.generationStartedAt
      || strictGuidedTimestamp(row.createdAt) < String(proposal.receipt.createdAt) || String(row.createdAt) > proposal.job.updatedAt
      || row.treatmentDraftRevisionHash !== (proposal.pointer.treatmentDraftRevisionHash ?? null)) throw new Error("Readiness receipt differs from current proposal/clock/draft");
  return { row, hash, submission };
}

function execution(proposal: ReviewedProposalInput, receipt: ReturnType<typeof record>) {
  const { row, submission } = receipt, dir = proposal.job.ctx.dir;
  const start = readGuidedExecution({ dir, id: submission.idempotencyKey, executionId: row.executionId, hash: row.executionStartHash });
  const before = readCutPreviewObject(path.join(dir, "human-cut-job-snapshots", `${sha256(row.beforeJournalHash, "beforeJournalHash")}.json`));
  const job = parseAutoEditJobRecord(before.value);
  if (before.sha256 !== row.beforeJournalHash || job.status !== "treatment_admitted" || job.guidedHandoffV2?.proposalReadinessHash
      || job.guidedHandoffV2?.treatmentProposalHash !== proposal.proposalHash || job.token !== proposal.job.token
      || canonicalJsonSha256(job.ctx) !== proposal.fact.contextHash || start.submissionHash !== canonicalJsonSha256(submission)
      || job.updatedAt > String(start.firstReceivedAt) || String(start.startedAt) > String(row.createdAt)) throw new Error("Readiness lost its exact before-journal/execution authority");
  return path.join(dir, "guided-v2-operations", submission.idempotencyKey, "executions", String(row.executionId));
}

function privateObject(proposal: ReviewedProposalInput, input: { execution: string; name: string; hash: unknown }) {
  const hash = sha256(input.hash, input.name), value = readGuidedObject(proposal.job.ctx.dir, hash);
  const file = readCutPreviewObject(path.join(input.execution, input.name));
  if (canonicalJsonSha256(file.value) !== hash) throw new Error(`Private readiness object changed: ${input.name}`);
  return value;
}

/** Every readable receipt is schemaVersion 3, so the original budget proof is always required. */
function readinessBudgetProof(proposal: ReviewedProposalInput, receipt: ReturnType<typeof record>, root: string) {
  const admission = privateObject(proposal, { execution: root, name: "budget-admission.json", hash: receipt.row.budgetAdmissionHash });
  const precommit = privateObject(proposal, { execution: root, name: "budget-precommit.json", hash: receipt.row.budgetPrecommitHash });
  const started = readCutPreviewObject(path.join(root, "start.json")).value;
  assertProposalReadinessDeadlineProof({ admission, precommit }, {
    origin: { clockHash: proposal.clock.hash, startedAt: proposal.generationStartedAt },
    executionStartedAt: String(started.startedAt), createdAt: String(receipt.row.createdAt),
  });
  return "proposal-phase-only-not-full-request-accounting" as const;
}

/** Re-read the retained bundle by hash and prove it graded THIS exact candidate plan and manifest.
 * The verdict itself is a subprocess observation and is never recomputed; only its binding is. */
function deterministicGateProof(proposal: ReviewedProposalInput, receipt: ReturnType<typeof record>, root: string) {
  const gates = objectValue(receipt.row.deterministicGates, "deterministic gate receipt");
  const keys = ["ok", "hash", "planHash", "executedChecks", "pendingChecks"];
  exactKeys(gates, keys, keys, "deterministic gate receipt");
  const ok = gates.ok; sha256(gates.hash, "deterministic gate bundle hash"); sha256(gates.planHash, "deterministic gate plan hash");
  if (typeof ok !== "boolean" || canonicalJsonSha256({ executedChecks: gates.executedChecks, pendingChecks: gates.pendingChecks })
      !== canonicalJsonSha256(proposalReadinessChecks(ok))) throw new Error("Readiness receipt misreports which deterministic checks actually ran");
  const bundle = privateObject(proposal, { execution: root, name: "gate-bundle.json", hash: gates.hash });
  const plan = privateObject(proposal, { execution: root, name: "gate-plan.json", hash: gates.planHash });
  const renderer = bundle.renderer as { verifiedAbsent?: unknown } | null | undefined;
  assertCurrentReadinessGateExecution(bundle);
  if (bundle.kind !== PROPOSAL_GATE_BUNDLE_KIND || bundle.scope !== PROPOSAL_READINESS_SCOPE
      || bundle.ok !== ok || bundle.planHash !== gates.planHash
      || (ok && renderer != null && renderer.verifiedAbsent !== true)
      || canonicalJsonSha256(plan) !== canonicalJsonSha256(proposal.result.candidate)) throw new Error("Deterministic gate bundle does not bind this exact candidate plan or verdict");
  const manifest = readCutPreviewObject(path.join(root, "gate-manifest.json"));
  if (canonicalJsonSha256(manifest.value) !== canonicalJsonSha256(readCutPreviewObject(proposal.job.ctx.manifestPath).value)) {
    throw new Error("Deterministic gates graded a different source manifest than the current accepted cut");
  }
  if (!ok && receipt.row.treatmentDraftRevisionHash !== null) throw new Error("Gate-blocked readiness cannot own a treatment draft");
  return { ok, hash: String(gates.hash), planHash: String(gates.planHash), bundle };
}

/** Reconstruct all critic inputs and independent results; no media/source-byte or final approval is inferred. */
export function readGuidedProposalReadiness(dir: string) {
  const proposal = readGuidedTreatmentProposal(dir), receipt = record(proposal), root = execution(proposal, receipt);
  const generationBudgetQualification = readinessBudgetProof(proposal, receipt, root);
  const deterministicGates = deterministicGateProof(proposal, receipt, root);
  const packet = buildProposalReadinessPacket(proposal), authority = proposalReadinessAuthority(proposal);
  for (const item of [{ name: "packet.json", hash: receipt.row.packetHash, expected: packet },
    { name: "implementation.json", hash: receipt.row.implementationHash, expected: authority }]) {
    const value = privateObject(proposal, { execution: root, name: item.name, hash: item.hash });
    if (canonicalJsonSha256(value) !== canonicalJsonSha256(item.expected)) throw new Error("Readiness packet or implementation changed");
  }
  const bundle = privateObject(proposal, { execution: root, name: "review-bundle.json", hash: receipt.row.reviewBundleHash });
  const expectedCritics = deterministicGates.ok ? 2 : 0;
  if (!Array.isArray(bundle.criticResultHashes) || bundle.criticResultHashes.length !== expectedCritics) {
    throw new Error(deterministicGates.ok ? "Two independent critic results are required"
      : "Gate-blocked readiness must retain zero paid critic results");
  }
  const results = bundle.criticResultHashes.map((hash, criticIndex) => {
    const result = privateObject(proposal, { execution: path.join(root, `critic-${criticIndex + 1}`), name: "result.json", hash }) as unknown as ProposalReadinessCriticResult;
    assertProposalCriticResult(result, { packet, criticIndex });
    const captured = readCutPreviewObject(path.join(root, `critic-${criticIndex + 1}`, "packet.json"));
    if (canonicalJsonSha256(captured.value) !== receipt.row.packetHash) throw new Error("Critic did not bind the same exact full packet");
    return result;
  });
  const expected = readinessBundle(String(receipt.row.packetHash), bundle.criticResultHashes.map((hash) => sha256(hash, "critic result")), results, deterministicGates.ok);
  if (canonicalJsonSha256(bundle) !== canonicalJsonSha256(expected)) throw new Error("Readiness bundle changed or combined incompatible critic verdicts");
  const draft = receipt.row.treatmentDraftRevisionHash;
  if ((expected.verdict === "clean") !== (typeof draft === "string")) throw new Error("Blocked proposal cannot own a treatment draft");
  const revision = typeof draft === "string" ? readGuidedTreatmentDraft(proposal, { hash: sha256(draft, "draft"), reviewBundleHash: String(receipt.row.reviewBundleHash) }) : null;
  if (observeHumanCutJob(dir).sha256 !== proposal.sha256) throw new Error("Readiness journal changed during observation");
  return { ...proposal, readinessHash: receipt.hash, readinessReceipt: receipt.row, readinessSubmission: receipt.submission,
    readiness: expected, draftRevision: revision, generationBudgetQualification, deterministicGates,
    scope: PROPOSAL_READINESS_SCOPE, available: false as const };
}

/** `deterministicGatesOk` moves the one check readiness actually ran out of pendingChecks;
 * a gate-blocked bundle carries zero critic results and keeps the whole historical list. */
export function readinessBundle(packetHash: string, criticResultHashes: string[],
  results: ProposalReadinessCriticResult[], deterministicGatesOk: boolean) {
  return { schemaVersion: 2, kind: "guided-proposal-independent-review-bundle", packetHash, criticResultHashes,
    verdict: results.length === 2 && results.every((result) => result.review.verdict === "pass") ? "clean" : "blocked",
    ...proposalReadinessChecks(deterministicGatesOk), executable: false };
}
