import path from "node:path";
import { opendirSync } from "node:fs";
import { assertCutPreviewDirectory, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseRawTreatmentRevisionSubmissionV1, type RawTreatmentRequest } from "@/lib/producer/contracts/raw-treatment-revision-v1";
import { exactKeys, objectValue, sha256, uuid } from "@/lib/producer/contracts/validation";
import type { GuidedHandoffPointerV2 } from "@/lib/producer/contracts/guided-workflow-v2";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import { readGuidedExecution, readGuidedObject, strictGuidedTimestamp } from "./guided-cut-v2-store";
import { readRawTreatmentClock, type AcceptedGuidedCut } from "./guided-raw-treatment-store";
import { optionalLaunchRecord } from "./guided-opening-launch-store";
import { assertProposalDeadlineProof } from "./generation-deadline";

export const MAX_TREATMENT_ADMISSIONS = 32;
export const INVALIDATED_TREATMENT_KEYS = ["treatmentProposalHash", "proposalReadinessHash", "treatmentDraftRevisionHash"] as const;
const KEYS = ["schemaVersion", "kind", "scope", "requestObjectHash", "cutDecisionHash", "cutActivationHash", "parentRevisionHash",
  "clockHash", "beforeJournalHash", "executionId", "executionStartHash", "admittedAt"];
export type RawLineageAuthority = Pick<AcceptedGuidedCut, "job" | "fact" | "pointer" | "activation">;
export interface TreatmentAdmissionNode {
  hash: string; admission: Record<string, unknown>; submission: RawTreatmentRequest;
  before: ReturnType<typeof parseAutoEditJobRecord>;
}

export function invalidatedTreatment(pointer: GuidedHandoffPointerV2) {
  return Object.fromEntries(INVALIDATED_TREATMENT_KEYS.map((key) => [key, pointer[key] ?? null]));
}

/** No resource inference: even a failed/pre-activation launch needs its own revision owner. */
export function assertTreatmentRevisionIdle(cut: Pick<RawLineageAuthority, "job" | "pointer">): void {
  assertUnstartedPointer(cut.pointer);
  const directory = path.join(cut.job.ctx.dir, "guided-opening-launches");
  try { assertCutPreviewDirectory(directory); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return; throw error; }
  const entries = opendirSync(directory);
  try { if (entries.readSync()) throw new Error("Treatment revision is blocked by retained opening launch ownership; no automatic recovery"); }
  finally { entries.closeSync(); }
}

function assertUnstartedPointer(pointer: GuidedHandoffPointerV2): void {
  if (Object.keys(pointer).some((key) => key.startsWith("opening") || key.startsWith("body"))) {
    throw new Error("Treatment revision cannot invalidate opening/body ownership, selection, approval or a held master");
  }
}

export function treatmentRevisionReservation(dir: string, parent: string) {
  return path.join(dir, "guided-treatment-revisions", `${sha256(parent, "parentAdmissionHash")}.json`);
}

/** Presence is a pending mutation fence, not an approved or completed revision. */
export function readTreatmentRevisionReservation(dir: string, parent: string) {
  const held = optionalLaunchRecord(treatmentRevisionReservation(dir, parent));
  if (!held) return null;
  const row = held.value, keys = ["schemaVersion", "kind", "parentAdmissionHash", "requestObjectHash", "idempotencyKey"];
  exactKeys(row, keys, keys, "treatment revision reservation");
  if (row.schemaVersion !== 1 || row.kind !== "guided-treatment-revision-reservation" || row.parentAdmissionHash !== parent) {
    throw new Error("Treatment revision reservation belongs to another parent");
  }
  sha256(row.requestObjectHash, "revision request hash");
  uuid(row.idempotencyKey, "revision idempotency key");
  return held;
}

function revisedRequest(cut: RawLineageAuthority, admission: Record<string, unknown>) {
  const digest = sha256(admission.requestObjectHash, "revision request hash");
  const held = readCutPreviewObject(path.join(cut.job.ctx.dir, ".sniper-authority-v1", "objects", "requests", `${digest}.json`));
  const submission = parseRawTreatmentRevisionSubmissionV1(held.value);
  const reservation = readTreatmentRevisionReservation(cut.job.ctx.dir, submission.parentAdmissionHash);
  const expected = { schemaVersion: 1, kind: "guided-treatment-revision-reservation", parentAdmissionHash: submission.parentAdmissionHash,
    requestObjectHash: digest, idempotencyKey: submission.idempotencyKey };
  if (held.sha256 !== digest || canonicalJsonSha256(submission) !== digest || !reservation
      || canonicalJsonSha256(reservation.value) !== canonicalJsonSha256(expected)
      || admission.parentAdmissionHash !== submission.parentAdmissionHash || admission.supersedesRequestHash !== submission.supersedesRequestHash) {
    throw new Error("Treatment revision lost its exact immutable request/parent reservation");
  }
  return submission;
}

function admissionNode(input: { cut: RawLineageAuthority; hash: string; clock: ReturnType<typeof readRawTreatmentClock> }): TreatmentAdmissionNode {
  const { cut, hash, clock } = input, admission = readGuidedObject(cut.job.ctx.dir, hash);
  const extra = admission.schemaVersion === 2 ? ["parentAdmissionHash", "supersedesRequestHash", "invalidated",
    "budgetAdmissionHash", "budgetPrecommitHash"] : [];
  exactKeys(admission, [...KEYS, ...extra], [...KEYS, ...extra], "raw treatment admission");
  const submission = admission.schemaVersion === 2 ? revisedRequest(cut, admission) : clock.submission;
  if (![1, 2].includes(Number(admission.schemaVersion)) || typeof admission.schemaVersion !== "number"
      || admission.kind !== "guided-raw-treatment-admission" || admission.scope !== "raw-treatment-request-not-executed-or-approved"
      || admission.requestObjectHash !== canonicalJsonSha256(submission) || admission.clockHash !== clock.hash
      || admission.cutDecisionHash !== cut.pointer.cutDecisionHash || admission.cutActivationHash !== cut.pointer.cutActivationHash
      || admission.parentRevisionHash !== cut.pointer.pictureLockedRevisionHash || admission.beforeJournalHash !== submission.expectedJournalHash
      || strictGuidedTimestamp(admission.admittedAt) < String(clock.value.startedAt) || String(admission.admittedAt) > cut.job.updatedAt) {
    throw new Error("Raw treatment admission authority changed");
  }
  const start = readGuidedExecution({ dir: cut.job.ctx.dir, id: submission.idempotencyKey,
    executionId: admission.executionId, hash: admission.executionStartHash });
  const held = readCutPreviewObject(path.join(cut.job.ctx.dir, "human-cut-job-snapshots", `${sha256(admission.beforeJournalHash, "before journal")}.json`));
  const before = parseAutoEditJobRecord(held.value);
  if (held.sha256 !== admission.beforeJournalHash || before.token !== submission.expectedToken || before.token !== cut.job.token
      || canonicalJsonSha256(before.ctx) !== cut.fact.contextHash || before.guidedHandoffV2?.cutDecisionHash !== cut.pointer.cutDecisionHash
      || before.guidedHandoffV2?.cutActivationHash !== cut.pointer.cutActivationHash
      || before.guidedHandoffV2?.pictureLockedRevisionHash !== cut.pointer.pictureLockedRevisionHash
      || start.submissionHash !== admission.requestObjectHash || before.updatedAt > String(start.firstReceivedAt)
      || strictGuidedTimestamp(start.startedAt) > String(admission.admittedAt)) throw new Error("Raw admission execution/before-journal proof changed");
  assertNodeTransition({ admission, submission, before, start, clock });
  return { hash, admission, submission, before };
}

function assertNodeTransition(input: { admission: Record<string, unknown>; submission: RawTreatmentRequest;
  before: TreatmentAdmissionNode["before"]; start: Record<string, unknown>; clock: ReturnType<typeof readRawTreatmentClock> }): void {
  const { admission, before, start, clock } = input;
  if (admission.schemaVersion === 1) {
    if (before.status !== "awaiting_treatment_brief" || before.guidedHandoffV2?.treatmentAdmissionHash
        || start.firstReceivedAt !== clock.value.startedAt) throw new Error("Original raw admission lineage changed");
    return;
  }
  const pointer = before.guidedHandoffV2!, invalidated = objectValue(admission.invalidated, "invalidated treatment pointers");
  exactKeys(invalidated, [...INVALIDATED_TREATMENT_KEYS], [...INVALIDATED_TREATMENT_KEYS], "invalidated treatment pointers");
  assertUnstartedPointer(pointer);
  if (before.status !== "treatment_admitted" || pointer.treatmentAdmissionHash !== admission.parentAdmissionHash
      || canonicalJsonSha256(invalidated) !== canonicalJsonSha256(invalidatedTreatment(pointer))) {
    throw new Error("Treatment revision lost its exact parent/invalidation snapshot");
  }
  assertProposalDeadlineProof({ admission: readGuidedObject(before.ctx.dir, sha256(admission.budgetAdmissionHash, "revision budget")),
    precommit: readGuidedObject(before.ctx.dir, sha256(admission.budgetPrecommitHash, "revision precommit")) }, {
    origin: { clockHash: clock.hash, startedAt: String(clock.value.startedAt) },
    executionStartedAt: String(start.startedAt), createdAt: String(admission.admittedAt) });
}

/** Current or explicit historical admission chain; the immutable first clock is never replaced. */
export function readTreatmentAdmissionLineage(cut: RawLineageAuthority, activeHash: string) {
  const clock = readRawTreatmentClock(cut), nodes: TreatmentAdmissionNode[] = [], ids = new Set<string>();
  let hash = sha256(activeHash, "treatment admission");
  for (let count = 0; count < MAX_TREATMENT_ADMISSIONS; count++) {
    const node = admissionNode({ cut, hash, clock }), { admission, submission } = node;
    if (nodes.some((row) => row.hash === hash) || ids.has(submission.idempotencyKey) || ids.has(submission.requestId)) {
      throw new Error("Treatment revision lineage cycles or reuses request identifiers");
    }
    nodes.push(node); ids.add(submission.idempotencyKey); ids.add(submission.requestId);
    if (admission.schemaVersion === 1) return { clock, nodes };
    hash = sha256(admission.parentAdmissionHash, "parentAdmissionHash");
    const parent = readGuidedObject(cut.job.ctx.dir, hash);
    if (parent.requestObjectHash !== admission.supersedesRequestHash || String(parent.admittedAt) > node.before.updatedAt) {
      throw new Error("Treatment revision does not supersede the exact prior raw request");
    }
  }
  throw new Error("Treatment revision lineage exceeds 32 admissions; no automatic reset");
}
