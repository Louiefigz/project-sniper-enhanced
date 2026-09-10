import path from "node:path";
import { exactKeys, objectValue, sha256, uuid } from "@/lib/producer/contracts/validation";
import { parseGuidedOpeningApprovalSubmission } from "@/lib/producer/contracts/guided-opening-approval-v1";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { readGuidedObject, strictGuidedTimestamp } from "./guided-cut-v2-store";
import { readGuidedOpeningApproval, OPENING_APPROVAL_MESSAGE } from "./guided-opening-approval";
import { assertOpeningFailureAbsent } from "./guided-opening-process-activation";
import { assertOpeningReadbackIdentity, type HeldOpeningResult } from "./guided-opening-result";
import type { readSelectedOpeningMedia } from "./guided-opening-selection";
import type { observeHumanCutJob } from "./human-cut-acceptance-store";
import { readSourceColorOpeningApproval } from "./guided-source-color-approval-read";
import { assertOpeningSelectionMetadata, openingSelectionVersion } from "./guided-opening-selection";
import { assertSourceColorOpeningResultMetadata, type HeldSourceColorOpeningResult } from "./guided-source-color-opening-result";
import type { BodyOpeningResult } from "./guided-body-opening-version";

export const bodyApprovalReads = { file: readCutPreviewObject, object: readGuidedObject,
  approval: readGuidedOpeningApproval, absent: assertOpeningFailureAbsent };
interface ApprovalInput { dir: string; current: ReturnType<typeof observeHumanCutJob>;
  selected: ReturnType<typeof readSelectedOpeningMedia>; result: BodyOpeningResult; guard?: () => void }

function same(actual: unknown, expected: unknown, label: string): void {
  if (canonicalJsonSha256(actual) !== canonicalJsonSha256(expected)) throw new Error(`Body opening ${label} differs from held authority`);
}

function approvalFact(input: ApprovalInput, reads: typeof bodyApprovalReads) {
  const { dir, current, selected } = input, summary = reads.approval(dir, selected.selectionHash);
  if (!summary || summary.approvalHash !== current.job.guidedHandoffV2?.openingApprovalHash) throw new Error("Body requires current explicit opening approval");
  const fact = reads.object(dir, summary.approvalHash), decision = parseGuidedOpeningApprovalSubmission(fact.decision);
  if (canonicalJsonSha256(fact) !== summary.approvalHash) throw new Error("Body opening approval object hash changed");
  const held = selected.held;
  const expected = { selectionHash: selected.selectionHash, claimHash: held.claimHash, executionId: held.claim.executionId,
    cleanupHash: selected.fact.cleanupHash, mediaResultSha256: input.result.record.sha256,
    receiptHash: input.result.completion.receiptHash, coreMediaSha256: selected.rows.core.mediaSha256,
    reviewMediaSha256: selected.rows.review.mediaSha256, clockHash: held.claim.clockHash,
    generationStartedAt: held.claim.generationStartedAt };
  for (const [key, value] of Object.entries(expected)) same(fact[key], value, key);
  if (decision.expectedToken !== current.job.token || decision.expectedJournalHash !== fact.beforeJournalHash
      || decision.coreMediaSha256 !== fact.coreMediaSha256 || decision.reviewMediaSha256 !== fact.reviewMediaSha256
      || canonicalJsonSha256(decision) !== fact.decisionHash) throw new Error("Body opening approval decision differs from its fact");
  const stamps = [held.claim.generationStartedAt, selected.selectionQualifiedAt, fact.approvedAt].map(strictGuidedTimestamp);
  if (stamps.some((at, index) => index > 0 && at < stamps[index - 1])) throw new Error("Body approval predates its exact opening");
  return { fact, summary, decision };
}

function approvalJournal(input: ApprovalInput, approval: ReturnType<typeof approvalFact>, reads: typeof bodyApprovalReads) {
  const { fact, summary } = approval, hash = sha256(fact.beforeJournalHash, "approval before journal");
  const before = reads.file(path.join(input.dir, "human-cut-job-snapshots", `${hash}.json`));
  const job = before.value, pointer = objectValue(job.guidedHandoffV2, "approval prior pointer");
  if (before.sha256 !== hash || pointer.openingApprovalHash
      || pointer.openingExecutionClaimHash || pointer.openingMediaSelectionHash !== fact.selectionHash
      || job.status !== "treatment_admitted" || !Number.isSafeInteger(job.nextEventId) || Number(job.nextEventId) < 0
      || !Array.isArray(job.events) || job.events.length > 256 || strictGuidedTimestamp(job.updatedAt) > String(fact.approvedAt)) {
    throw new Error("Body approval lost its exact pre-approval journal");
  }
  const event = { id: job.nextEventId, at: fact.approvedAt, payload: { event: "opening_approved_by_operator",
    approvalHash: summary.approvalHash, selectionHash: fact.selectionHash, executionId: fact.executionId,
    bodyGenerated: false, deliveryApproved: false } };
  same(input.current.job, { ...job, updatedAt: fact.approvedAt, guidedHandoffV2: { ...pointer, openingApprovalHash: summary.approvalHash },
    message: OPENING_APPROVAL_MESSAGE, nextEventId: Number(job.nextEventId) + 1, events: [...job.events, event].slice(-256) }, "approval journal transition");
  return before;
}

function readbackFiles(input: ApprovalInput, fact: Record<string, unknown>, reads: typeof bodyApprovalReads) {
  const row = objectValue(fact.requalification, "opening approval requalification");
  const keys = ["readbackReceiptSha256", "readbackOutputSha256", "readbackDirectory", "elapsedMs"];
  exactKeys(row, keys, keys, "opening approval requalification");
  const name = uuid(row.readbackDirectory, "approval readback directory");
  const root = path.join(path.dirname(input.selected.held.claimPath), "readback-attempts", name);
  reads.absent(path.join(root, "failure.json"));
  const start = reads.file(path.join(root, "start.json")), output = reads.file(path.join(root, "output.json"));
  const receipt = reads.file(path.join(root, "verified.json")), published = reads.file(path.join(root, "approval.json"));
  if (receipt.sha256 !== sha256(row.readbackReceiptSha256, "approval readback receipt")
      || output.sha256 !== sha256(row.readbackOutputSha256, "approval readback output")
      || typeof row.elapsedMs !== "number" || !Number.isFinite(row.elapsedMs) || row.elapsedMs < 0
      || row.elapsedMs !== output.value.elapsedMs) throw new Error("Body approval requalification bytes/timing changed");
  same(published.value, { ...fact, approvalHash: canonicalJsonSha256(fact) }, "private approval publication");
  return { root, row, start, output, receipt, published };
}

function checkReadback(input: ApprovalInput, fact: Record<string, unknown>, files: ReturnType<typeof readbackFiles>) {
  const start = files.start.value, output = files.output.value, receipt = files.receipt.value, held = input.selected.held;
  const stamps = [start.startedAt, output.observedAt, receipt.createdAt, fact.approvedAt].map(strictGuidedTimestamp);
  const result = assertOpeningReadbackIdentity(String(output.stdout), { held, selected: input.result as HeldOpeningResult });
  const startKeys = ["schemaVersion", "kind", "beforeJournalHash", "cleanupHash", "claimHash", "executionId", "receiptSha256", "tools", "clockHash", "generationStartedAt", "startedAt"];
  exactKeys(start, startKeys, startKeys, "approval readback start");
  const outputKeys = ["schemaVersion", "kind", "stdout", "stderr", "processGroupStopped", "observedAt", "elapsedMs"];
  exactKeys(output, outputKeys, outputKeys, "approval readback output");
  if (start.schemaVersion !== 1 || start.kind !== "guided-opening-readback-start" || start.executionId !== held.claim.executionId
      || start.receiptSha256 !== input.result.completion.receiptSha256 || output.schemaVersion !== 1
      || output.kind !== "guided-opening-readback-owned-output" || output.processGroupStopped !== true
      || typeof output.stdout !== "string" || typeof output.stderr !== "string" || Buffer.byteLength(output.stderr) > 2 * 1024 * 1024
      || Number(output.elapsedMs) > 600_000 || result.elapsedMs > Number(output.elapsedMs) + 1
      || stamps.some((at, index) => index > 0 && at < stamps[index - 1])) throw new Error("Body approval readback execution/clock differs");
  for (const key of ["beforeJournalHash", "cleanupHash", "claimHash", "clockHash", "generationStartedAt"]) same(start[key], fact[key], `readback ${key}`);
  same(receipt, { schemaVersion: 1, kind: "guided-opening-owned-readback", scope: "actual-current-readback-not-selected-or-approved",
    beforeJournalHash: fact.beforeJournalHash, cleanupHash: fact.cleanupHash, claimHash: fact.claimHash,
    startSha256: files.start.sha256, outputSha256: files.output.sha256, result, clockHash: fact.clockHash,
    generationStartedAt: fact.generationStartedAt, createdAt: receipt.createdAt, mediaSelected: false, openingApproved: false, deliveryApproved: false }, "readback receipt");
}

/** Validate retained HUMAN approval plus its exact transition and actual readback lineage. No freshness or body approval inferred. */
export function readBodyOpeningApproval(input: ApprovalInput, reads = bodyApprovalReads) {
  if (openingSelectionVersion(input.selected) === 2) {
    if (!input.guard) throw new Error("Source-color body approval needs the original caller guard");
    assertOpeningSelectionMetadata(input.selected);
    assertSourceColorOpeningResultMetadata(input.result as HeldSourceColorOpeningResult, input.selected.held);
    const approval = readSourceColorOpeningApproval({ dir: input.dir, current: input.current, selected: input.selected, guard: input.guard });
    if (approval.fact.mediaResultSha256 !== input.result.record.sha256 || approval.fact.receiptHash !== input.result.completion.receiptHash) {
      throw new Error("Source-color body approval result differs from its exact selected result");
    }
    assertOpeningSelectionMetadata(input.selected);
    assertSourceColorOpeningResultMetadata(input.result as HeldSourceColorOpeningResult, input.selected.held); return approval;
  }
  if (input.selected.fact.schemaVersion !== 1) throw new Error("Body opening approval version is unsupported");
  const approval = approvalFact(input, reads), before = approvalJournal(input, approval, reads);
  const files = readbackFiles(input, approval.fact, reads); checkReadback(input, approval.fact, files);
  if (strictGuidedTimestamp(files.start.value.startedAt) < strictGuidedTimestamp(before.value.updatedAt)) throw new Error("Approval verification predates its selected journal");
  reads.absent(path.join(files.root, "failure.json"));
  return { ...approval, before, files };
}
