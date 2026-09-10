import path from "node:path";
import { mkdtempSync, realpathSync, writeFileSync, rmSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { guidedFixture } from "@/lib/producer/__tests__/_guided-cut-fixture";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { bodyAuthorityFixture, bodyTestDocument, BODY_TEST_DIR, BODY_TEST_HASH as H } from "./_guided-body-fixture";
import { canonicalJsonSha256 as hash } from "../auto-edit-hash";
import { autoEditRequestKey } from "../auto-edit-hash";
import { parseAutoEditJobRecord } from "../auto-edit-job-persistence";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { readBodyOpeningApproval } from "../guided-body-approval";
import { OPENING_APPROVAL_MESSAGE } from "../guided-opening-approval";
import { bodyClaimServices } from "../guided-body-claim";
import { readGuidedBodyClaim, bodyClaimLineageReads } from "../guided-body-lineage";
import { clearProducerRun } from "../producer-run-registry";
import { projectBodyProgramReferences } from "@/lib/producer/contracts/guided-body-media-v1";

type Row = Record<string, unknown>;
function remap(value: unknown, dir: string, offset: number): unknown {
  if (typeof value === "string") {
    if (/^2026-09-06T12:/u.test(value)) return new Date(Date.parse(value) + offset).toISOString();
    return value.replaceAll(BODY_TEST_DIR, dir);
  }
  if (Array.isArray(value)) return value.map((item) => remap(item, dir, offset));
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, remap(item, dir, offset)]));
  return value;
}

function durableBefore(root: string, template: ReturnType<typeof bodyAuthorityFixture>, at: string) {
  const base = guidedFixture(root), job = structuredClone(base.run.job), fake = template.before.value;
  job.ctx.workflowV2 = { schemaVersion: 2, mode: "guided", afterCut: "treatment-then-intro", approvalPolicy: "explicit-human" };
  job.requestKey = autoEditRequestKey(job.ctx);
  const request = { schemaVersion: 1 as const, requestKey: job.requestKey, planHash: H, authorityDigest: H,
    cutAuthorityDigest: H, cutApprovalReceiptHash: H, cutReviewApprovalReceiptHash: H, pictureLockHash: H,
    timelineMapHash: H, projectionReceiptHash: H, createdAt: at };
  Object.assign(job, { token: "TEST-guided", status: "treatment_admitted", checkpoint: "cut_reviewed", workerPid: undefined, workerIdentity: undefined,
    updatedAt: at, nextEventId: 2, events: [], message: fake.message, cutApprovalWaitStartedAt: at,
    cutApprovalRequest: { ...request, requestHash: hash(request) }, cutPreview: { executionKey: H, receiptHash: H },
    guidedHandoffV2: { ...fake.guidedHandoffV2 as Row, cutActivationHash: H, treatmentAdmissionHash: H, treatmentProposalHash: H } });
  return { base, before: bodyTestDocument({ ...parseAutoEditJobRecord(job) }) };
}

function proofObjects(input: { template: ReturnType<typeof bodyAuthorityFixture>; dir: string; offset: number; before: ReturnType<typeof bodyTestDocument> }) {
  const { template: f, dir, offset, before } = input;
  const selected = remap(f.selected, dir, offset) as Row, record = bodyTestDocument(remap((f.result.record as Row).value, dir, offset) as Row);
  ((selected.held as Row).claim as Row).inputPath = `${dir}/TEST-execution/media-input/input.json`;
  const resultValue = remap(f.resultValue, dir, offset) as Row; resultValue.receiptSha256 = record.sha256;
  const start = bodyTestDocument({ ...remap(f.records.start.value, dir, offset) as Row, beforeJournalHash: before.sha256, receiptSha256: record.sha256 });
  const output = bodyTestDocument({ ...remap(f.records.output.value, dir, offset) as Row, stdout: JSON.stringify(resultValue) });
  const receipt = bodyTestDocument({ ...remap(f.records.receipt.value, dir, offset) as Row,
    beforeJournalHash: before.sha256, startSha256: start.sha256, outputSha256: output.sha256, result: resultValue });
  const fact = remap(f.fact, dir, offset) as Row, decision = fact.decision as Row;
  decision.expectedJournalHash = before.sha256; fact.decisionHash = hash(decision); fact.beforeJournalHash = before.sha256;
  fact.mediaResultSha256 = record.sha256;
  Object.assign(fact.requalification as Row, { readbackReceiptSha256: receipt.sha256, readbackOutputSha256: output.sha256 });
  const result = { ...f.result, record, completion: { ...resultValue, executionClaimSha256: H } };
  const root = String(remap(f.approvalRoot, dir, offset)), files = new Map<string, ReturnType<typeof bodyTestDocument>>();
  for (const [name, value] of Object.entries({ "start.json": start, "output.json": output, "verified.json": receipt,
    "approval.json": bodyTestDocument({ ...fact, approvalHash: hash(fact) }) })) files.set(path.join(root, name), value);
  files.set(path.join(dir, "human-cut-job-snapshots", `${before.sha256}.json`), before);
  return { selected, result, fact, files };
}

/** Real checkpoint files/lease/CAS; source/media/approval evidence is expressly TEST-only protocol data. */
export function bodyClaimFixture() {
  const root = realpathSync(mkdtempSync("/private/tmp/sniper-body-claim-")), dir = path.join(root, "producer");
  const template = bodyAuthorityFixture(), began = Date.now() - 5 * 60_000;
  const offset = began - Date.parse("2026-09-06T12:00:00.000Z");
  const { base, before } = durableBefore(root, template, new Date(began + 60_000).toISOString());
  const proof = proofObjects({ template, dir, offset, before }), approvalHash = hash(proof.fact), prior = before.value;
  const event = { id: 2, at: proof.fact.approvedAt, payload: { event: "opening_approved_by_operator", approvalHash,
    selectionHash: H, executionId: proof.fact.executionId, bodyGenerated: false, deliveryApproved: false } };
  const job = parseAutoEditJobRecord({ ...prior, updatedAt: proof.fact.approvedAt, message: OPENING_APPROVAL_MESSAGE,
    guidedHandoffV2: { ...prior.guidedHandoffV2 as Row, openingApprovalHash: approvalHash }, nextEventId: 3, events: [event] });
  writeFileSync(base.jobPath, JSON.stringify(job));
  const current = observeHumanCutJob(dir), submission = { schemaVersion: 1 as const, operation: "continue-approved-opening" as const,
    idempotencyKey: randomUUID(), expectedToken: job.token, expectedJournalHash: current.sha256, openingApprovalHash: approvalHash,
    selectionHash: H, proposalReadinessHash: H, treatmentDraftRevisionHash: H };
  Object.assign(proof.selected, { observed: { ...current }, receiptSha256: (proof.result.record as ReturnType<typeof bodyTestDocument>).sha256 });
  const origin = { clockHash: H, startedAt: new Date(began).toISOString() };
  const reads = lineageReads(proof, current);
  const services = serviceReads({ dir, current, submission, origin, proof, reads });
  return { root, dir, base, current, submission, origin, proof, reads, services, cleanup() { clearProducerRun(dir); rmSync(root, { recursive: true, force: true }); } };
}

function lineageReads(proof: ReturnType<typeof proofObjects>, current: ReturnType<typeof observeHumanCutJob>) {
  const approval = { approval: () => ({ approvalHash: hash(proof.fact), approvedAt: String(proof.fact.approvedAt), decisionHash: String(proof.fact.decisionHash) }),
    object: () => proof.fact, file: (file: string) => {
      const value = proof.files.get(file); if (!value) throw new Error(`TEST missing approval ${file}`); return value;
    }, absent: () => {} };
  return { selection: (_dir: string, snapshot: string) => {
    if (snapshot !== current.sha256) throw new Error("TEST wrong historical snapshot"); return proof.selected;
  }, result: () => proof.result, approval } as unknown as typeof bodyClaimLineageReads;
}

function serviceReads(input: { dir: string; current: ReturnType<typeof observeHumanCutJob>; submission: Row;
  origin: { clockHash: string; startedAt: string }; proof: ReturnType<typeof proofObjects>; reads: typeof bodyClaimLineageReads }) {
  const { dir, current, origin, proof, reads } = input;
  const record = proof.result.record.value;
  const counts = { holds: 0, histories: 0 }, services = { ...bodyClaimServices,
    canonicalDir: (value: unknown) => { if (value !== dir || realpathSync(dir) !== dir) throw new Error("TEST invalid project"); return dir; },
    readiness: () => ({ sha256: current.sha256, clock: { hash: origin.clockHash }, generationStartedAt: origin.startedAt }),
    selection: () => proof.selected,
    read: (directory: string) => { counts.histories += 1; return readGuidedBodyClaim(directory, reads); },
    hold: async (request: Parameters<typeof bodyClaimServices.hold>[0]) => {
      counts.holds += 1; const guard = cutPreviewLeaseGuard(dir, request.lease); guard(); request.remainingMs();
      readBodyOpeningApproval({ dir, current, selected: reads.selection(dir, current.sha256), result: reads.result({} as never) }, reads.approval);
      return { schemaVersion: 1, scope: "held-body-input-not-launch-body-readiness-or-delivery-approval", submission: request.submission,
        journalHash: current.sha256, approvalHash: hash(proof.fact), selectionHash: H, readinessHash: H, draftRevisionHash: H,
        authority: record.authority, bindings: { graphics: [] }, origin, references: projectBodyProgramReferences(record),
        verification: { receiptPath: `${dir}/TEST-only-verifier.json`, receiptSha256: H, outputSha256: H },
        executable: false, bodyReadiness: "not-qualified", bodyGenerated: false, deliveryApproved: false,
        assertUnchanged: () => { guard(); if (observeHumanCutJob(dir).sha256 !== current.sha256) throw new Error("TEST approved journal changed"); } };
    } } as unknown as typeof bodyClaimServices;
  return Object.assign(services, { counts });
}
